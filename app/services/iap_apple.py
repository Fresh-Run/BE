"""Apple IAP — StoreKit 2 JWS 오프라인 검증 + App Store Server Notifications V2 웹훅.

리팩터(2026-09-17): 기존 iap_service.py의 **애플 전용 로직을 로직 변경 없이 이관**.
공유 코어(예외·VerifiedTransaction·persist·_epoch_ms_to_dt)는 iap_common에서 import.
동작 100% 보존 — 코드 이동일 뿐 검증/디코드/웹훅/재처리 로직 불변.

검증 백엔드 2종 (IAP_MODE):
- apple: SignedDataVerifier로 JWS 서명 체인을 **순수 오프라인 검증**(번들 Apple Root CA,
  API 콜 0). prod→sandbox 환경 폴백.
- mock: 개발/테스트 전용 — 서명 검증만 스킵하고 페이로드 구조 검증은 동일.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache

from app.core.config import settings
from app.core.supabase_client import get_supabase_admin
from app.models.schemas import IapVerifyRequest
from app.services.iap_common import (
    InvalidTransaction,
    IapNotConfigured,
    VerifiedTransaction,
    _epoch_ms_to_dt,
)

logger = logging.getLogger(__name__)

# 번들된 Apple Root CA(오프라인 JWS 체인 검증용 — G3가 StoreKit2 루트). app/data에
# 커밋(공개 인증서). 라이브러리는 root CA를 동봉하지 않아 호출자가 공급해야 한다.
_ROOT_CA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "apple_root_ca")


@lru_cache(maxsize=1)
def _apple_root_cas() -> list[bytes]:
    """번들 Apple Root CA(DER bytes) 로드 — 부재 시 빈 리스트(→ IapNotConfigured)."""
    certs = []
    for path in sorted(glob.glob(os.path.join(_ROOT_CA_DIR, "*.cer"))):
        with open(path, "rb") as fh:
            certs.append(fh.read())
    return certs


@lru_cache(maxsize=2)
def _verifier(environment: str):
    """SignedDataVerifier(오프라인·enable_online_checks=False) — 환경별 캐시.

    production은 app_apple_id 필수(라이브러리 강제) → 미설정(Track A 전)이면
    IapNotConfigured. sandbox는 bundle_id만으로 가능(출시 전 Sandbox 1사이클).
    root CA 번들 부재도 IapNotConfigured. import는 지연(라이브러리 미설치 환경 방어).
    """
    from appstoreserverlibrary.models.Environment import Environment
    from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier

    root_cas = _apple_root_cas()
    if not root_cas:
        raise IapNotConfigured()
    env = Environment.PRODUCTION if environment == "production" else Environment.SANDBOX
    app_apple_id = settings.appstore_app_apple_id
    if env == Environment.PRODUCTION and not app_apple_id:
        raise IapNotConfigured()  # prod 검증엔 app_apple_id 필수(Track A)
    return SignedDataVerifier(
        root_certificates=root_cas,
        enable_online_checks=False,   # 순수 오프라인(OCSP 콜 0)
        environment=env,
        bundle_id=settings.appstore_bundle_id,
        app_apple_id=app_apple_id,
    )


def _mock_allowed() -> bool:
    """안전장치 ③: 요청 시점에도 production+mock 조합을 거부."""
    return settings.iap_mode == "mock" and settings.environment != "production"


def verify(payload: IapVerifyRequest) -> VerifiedTransaction:
    """애플 검증 백엔드 분기(apple/mock) — 반환은 정규화된 거래 정보(store='apple')."""
    if settings.iap_mode == "mock":
        if not _mock_allowed():
            raise IapNotConfigured()
        if payload.mock is None:
            raise InvalidTransaction("mock 모드에서는 mock 페이로드가 필요합니다.")
        try:
            expires = datetime.fromisoformat(payload.mock.expires_at)
        except ValueError as exc:
            raise InvalidTransaction("expires_at이 ISO 8601이 아닙니다.") from exc
        if expires.tzinfo is None:
            raise InvalidTransaction("expires_at에 타임존이 필요합니다.")
        return VerifiedTransaction(
            original_transaction_id=payload.mock.original_transaction_id,
            product_id=payload.mock.product_id,
            expires_at=expires,
            environment="mock",
        )

    # ── apple 모드 — SignedDataVerifier 오프라인 JWS 검증(API 콜 0) ──────────
    if not payload.jws:
        raise InvalidTransaction("jws가 필요합니다.")
    decoded = _verify_signed_transaction(payload.jws)
    if not decoded.originalTransactionId or not decoded.productId:
        raise InvalidTransaction("거래에 필수 필드(originalTransactionId/productId) 없음.")
    if decoded.expiresDate is None:
        raise InvalidTransaction("구독이 아닌 거래(expiresDate 없음) — 지원 안 함.")
    return VerifiedTransaction(
        original_transaction_id=decoded.originalTransactionId,
        product_id=decoded.productId,
        expires_at=_epoch_ms_to_dt(decoded.expiresDate),
        environment=_env_str(decoded),
    )


def _env_str(decoded) -> str:
    """디코드 payload의 environment(enum/raw) → 'sandbox'/'production' 문자열."""
    raw = (getattr(decoded, "rawEnvironment", None)
           or getattr(getattr(decoded, "environment", None), "value", None) or "")
    return "sandbox" if str(raw).lower().startswith("sandbox") else "production"


def _verify_signed_transaction(jws: str):
    """JWS 트랜잭션을 prod→sandbox 순으로 오프라인 검증. 서명 무효면 InvalidTransaction.

    JWS는 자신의 환경(sandbox/prod)을 담고 있어 잘못된 환경 verifier는
    VerificationException을 낸다 → prod 시도 후 sandbox 폴백. 두 환경 모두
    미구성(예: Track A 전 prod)은 건너뛰고 sandbox만 시도. 둘 다 설정 불가면
    IapNotConfigured(503 safe)."""
    from appstoreserverlibrary.signed_data_verifier import VerificationException

    last_verif_exc: Exception | None = None
    configured = False
    for env in ("production", "sandbox"):
        try:
            verifier = _verifier(env)
        except IapNotConfigured:
            continue  # 이 환경은 미구성(prod app_apple_id 부재 등) — 다음 환경
        configured = True
        try:
            return verifier.verify_and_decode_signed_transaction(jws)
        except VerificationException as exc:
            last_verif_exc = exc  # 환경 불일치·서명 무효 — 다음 환경 시도
    if not configured:
        raise IapNotConfigured()
    raise InvalidTransaction(f"JWS 서명 검증 실패: {last_verif_exc}")


# 처리 대상 알림 타입(최소 스코프). 나머지 타입(SUBSCRIBED·DID_CHANGE_* 등)은
# raw만 보관하고 processed=true(엔타이틀먼트 무영향) — 확장은 후속.
_RENEW_TYPES = {"DID_RENEW", "SUBSCRIBED", "RESUBSCRIBE"}       # 만료 연장·활성
_EXPIRE_TYPES = {"EXPIRED", "GRACE_PERIOD_EXPIRED"}            # lazy 강등(status=expired)
_REVOKE_TYPES = {"REFUND", "REVOKE"}                          # 즉시 강등(status=revoked)


def _verify_notification(signed_payload: str):
    """알림 JWS를 prod→sandbox 오프라인 검증 → ResponseBodyV2DecodedPayload."""
    from appstoreserverlibrary.signed_data_verifier import VerificationException

    last_exc: Exception | None = None
    configured = False
    for env in ("production", "sandbox"):
        try:
            verifier = _verifier(env)
        except IapNotConfigured:
            continue
        configured = True
        try:
            return verifier.verify_and_decode_notification(signed_payload)
        except VerificationException as exc:
            last_exc = exc
    if not configured:
        raise IapNotConfigured()
    raise InvalidTransaction(f"알림 서명 검증 실패: {last_exc}")


async def _apply_notification(notification_type: str, tx) -> None:
    """검증된 알림의 타입별 엔타이틀먼트 반영. tx=디코드된 트랜잭션(originalTransactionId·
    expiresDate 등). 멱등(같은 상태 재적용 무해) — 재처리 안전."""
    otid = tx.originalTransactionId
    if not otid:
        return
    supabase = get_supabase_admin()
    now = datetime.now(timezone.utc).isoformat()

    if notification_type in _RENEW_TYPES and tx.expiresDate is not None:
        # 구독 연장 — 소유 행이 있으면 만료·상태 갱신(멱등). 없으면 무동작(verify로
        # 이미 활성화된 구독만 존재; 웹훅 선행 케이스는 다음 /iap/verify가 생성).
        await asyncio.to_thread(
            lambda: supabase.table("subscriptions")
            .update({"status": "active",
                     "expires_at": _epoch_ms_to_dt(tx.expiresDate).isoformat(),
                     "latest_transaction_id": tx.transactionId or otid,
                     "updated_at": now})
            .eq("original_transaction_id", otid)
            .execute()
        )
        logger.info("IAP 웹훅 %s — 구독 연장 (otid=%s)", notification_type, otid)
    elif notification_type in _EXPIRE_TYPES:
        # 만료 — status=expired만. tier 강등은 quota_service.get_tier lazy 훅이 수행.
        await asyncio.to_thread(
            lambda: supabase.table("subscriptions")
            .update({"status": "expired", "updated_at": now})
            .eq("original_transaction_id", otid)
            .execute()
        )
        logger.info("IAP 웹훅 %s — status=expired (lazy 강등, otid=%s)", notification_type, otid)
    elif notification_type in _REVOKE_TYPES:
        # 환불/취소 — status=revoked + **즉시** tier 강등(lazy 대기 없이).
        await asyncio.to_thread(
            lambda: supabase.table("subscriptions")
            .update({"status": "revoked", "updated_at": now})
            .eq("original_transaction_id", otid)
            .execute()
        )
        owner = await asyncio.to_thread(
            lambda: supabase.table("subscriptions")
            .select("user_id").eq("original_transaction_id", otid).limit(1).execute()
        )
        if owner.data and owner.data[0].get("user_id"):
            await asyncio.to_thread(
                lambda: supabase.table("profiles")
                .update({"tier": "free"})
                .eq("user_id", owner.data[0]["user_id"])
                .execute()
            )
        logger.info("IAP 웹훅 %s — status=revoked + 즉시 강등 (otid=%s)", notification_type, otid)
    # 그 외 타입: 엔타이틀먼트 무영향(raw만 보관·processed).


async def store_notification(signed_payload: str) -> None:
    """App Store Server Notification V2 수신 — 서명 검증 + 타입별 처리 + raw 보관.

    흐름: ① raw insert(processed=false — 검증 실패해도 유실 방지·재처리 대상) ②
    verify_and_decode_notification 서명 검증 ③ 타입별 엔타이틀먼트 반영(DID_RENEW 연장·
    EXPIRED lazy 강등·REFUND/REVOKE 즉시 강등) ④ 성공 시 그 행을 processed=true +
    notification_type로 갱신. 검증 실패분은 processed=false로 남아 reprocess_unprocessed
    가 재시도. Apple은 200 아닌 응답에 재시도하므로 라우터가 항상 200을 반환한다."""
    if not isinstance(signed_payload, str) or signed_payload.count(".") != 2:
        logger.warning("IAP notification: JWS 형태가 아닌 페이로드 수신 (무시)")
        return
    if len(signed_payload) > 50 * 1024:
        logger.warning("IAP notification: 페이로드 과대 (%d bytes) — 미저장", len(signed_payload))
        return
    supabase = get_supabase_admin()
    ins = await asyncio.to_thread(
        lambda: supabase.table("iap_notifications_raw")
        .insert({"payload": {"signedPayload": signed_payload}})
        .execute()
    )
    row_id = ins.data[0]["id"] if ins.data else None
    try:
        await _process_notification_payload(signed_payload, row_id)
    except IapNotConfigured:
        logger.info("IAP notification raw 저장 — 검증 미구성(processed=false, 재처리 대기)")
    except Exception:  # noqa: BLE001 — 처리 실패도 raw는 보존, 재처리로 회복
        logger.warning("IAP notification 처리 실패 (processed=false 유지, 재처리 대기)",
                       exc_info=True)


async def _process_notification_payload(signed_payload: str, row_id: str | None) -> str:
    """검증→타입별 반영→raw 행 processed=true+type 갱신. 반환은 notification_type."""
    decoded = _verify_notification(signed_payload)
    ntype = str(getattr(decoded, "rawNotificationType", None)
                or getattr(getattr(decoded, "notificationType", None), "value", "") or "")
    data = getattr(decoded, "data", None)
    if data is not None and getattr(data, "signedTransactionInfo", None):
        tx = _verify_signed_transaction(data.signedTransactionInfo)
        await _apply_notification(ntype, tx)
    if row_id is not None:
        supabase = get_supabase_admin()
        await asyncio.to_thread(
            lambda: supabase.table("iap_notifications_raw")
            .update({"processed": True, "notification_type": ntype})
            .eq("id", row_id)
            .execute()
        )
    return ntype


async def reprocess_unprocessed(limit: int = 200) -> int:
    """processed=false 잔여 알림 재처리(멱등) — 반환은 성공 처리 건수. 검증 미구성
    (IapNotConfigured)이나 개별 실패는 건너뛰고 계속(그 행은 processed=false 유지)."""
    supabase = get_supabase_admin()
    rows = await asyncio.to_thread(
        lambda: supabase.table("iap_notifications_raw")
        .select("id, payload")
        .eq("processed", False)
        .order("received_at", desc=False)
        .limit(limit)
        .execute()
    )
    done = 0
    for row in rows.data or []:
        sp = (row.get("payload") or {}).get("signedPayload")
        if not sp:
            continue
        try:
            await _process_notification_payload(sp, row["id"])
            done += 1
        except Exception:  # noqa: BLE001 — 건별 격리, 나머지 계속
            logger.warning("재처리 실패 (id=%s, processed=false 유지)", row.get("id"), exc_info=True)
    logger.info("IAP 알림 재처리 — %d/%d 성공", done, len(rows.data or []))
    return done
