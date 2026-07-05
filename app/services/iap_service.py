"""Apple 인앱 구독(IAP) 검증 + tier 전환.

구조 (2026-07 설계 확정):
- 앱(StoreKit 2)이 구매 직후 받은 signedTransaction(JWS)을 POST /iap/verify로
  전송 → 서버가 검증·디코드 → subscriptions insert/갱신 + profiles.tier 전환.
  (subscriptions PK는 original_transaction_id — 유저당 여러 행 = 구독 이력.)
- 만료 강등은 quota_service.get_tier의 lazy 훅 (별도 잡 없음).
- 갱신/환불 웹훅(App Store Server Notifications V2)은 현재 수신+raw 저장만.

검증 백엔드 2종 (IAP_MODE):
- apple: 실검증 — [출시기 TODO] app-store-server-library의 SignedDataVerifier
  로 JWS 서명 체인 검증 + 디코드. 크리덴셜(.p8/Issuer ID/Key ID/Bundle ID)
  발급 전까지는 IapNotConfigured(→ 503).
- mock: 개발/테스트 전용 — 서명 검증만 스킵하고 페이로드 구조 검증은 동일.
  프로덕션 사고 방지 3중 장치: ① main.py 부팅 거부 ② 기본값이 apple이라
  명시적 opt-in 필요 ③ 아래 _mock_allowed의 요청 시점 재확인.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.core.config import settings
from app.core.supabase_client import get_supabase_admin
from app.models.schemas import IapVerifyRequest, IapVerifyResponse

logger = logging.getLogger(__name__)

_UNIQUE_VIOLATION = "23505"


class IapNotConfigured(Exception):
    """apple 모드인데 크리덴셜/구현이 아직 없음 (출시기 작업)."""


class InvalidTransaction(Exception):
    """페이로드 구조/서명이 유효하지 않음."""


class TransactionExpired(Exception):
    """이미 만료 시각이 지난 거래 (재구독은 새 거래로 와야 함)."""


class TransactionAlreadyUsed(Exception):
    """다른 유저가 이미 등록한 original_transaction_id (재사용 공격 방어)."""


@dataclass
class VerifiedTransaction:
    original_transaction_id: str
    product_id: str
    expires_at: datetime
    environment: str  # sandbox | production | mock


def _mock_allowed() -> bool:
    """안전장치 ③: 요청 시점에도 production+mock 조합을 거부."""
    return settings.iap_mode == "mock" and settings.environment != "production"


def _verify(payload: IapVerifyRequest) -> VerifiedTransaction:
    """검증 백엔드 분기 — 반환은 정규화된 거래 정보."""
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

    # ── apple 모드 ────────────────────────────────────────────────────────
    # [출시기 TODO — docs/IAP_LAUNCH_CHECKLIST.md]
    #   1) `app-store-server-library` 의존성 추가
    #   2) SignedDataVerifier(Apple Root CA, environment, bundle_id)로
    #      payload.jws를 verify_and_decode_signed_transaction()
    #   3) 디코드 결과의 originalTransactionId/productId/expiresDate/
    #      environment를 VerifiedTransaction으로 매핑
    if not payload.jws:
        raise InvalidTransaction("jws가 필요합니다.")
    raise IapNotConfigured()


async def verify_purchase(user_id: str, payload: IapVerifyRequest) -> IapVerifyResponse:
    """거래 검증 → 구독 upsert → tier 전환. 같은 거래 재전송은 멱등."""
    tx = _verify(payload)

    if tx.expires_at <= datetime.now(timezone.utc):
        raise TransactionExpired()

    supabase = get_supabase_admin()
    record = {
        "user_id": user_id,
        "original_transaction_id": tx.original_transaction_id,
        "product_id": tx.product_id,
        "status": "active",
        "expires_at": tx.expires_at.isoformat(),
        "environment": tx.environment,
        "latest_transaction_id": tx.original_transaction_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # 실제 테이블의 PK는 original_transaction_id (거래가 곧 정체성).
    # upsert는 PK 충돌 시 남의 행을 덮어써 구독 탈취가 되므로 쓰지 않는다 —
    # insert-first, PK 충돌이면 기존 행의 소유자를 확인해 분기 (레이스 안전:
    # insert가 원자적이라 먼저 넣은 쪽이 소유자로 확정된다).
    try:
        await asyncio.to_thread(
            lambda: supabase.table("subscriptions").insert(record).execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:
            raise
        owner_res = await asyncio.to_thread(
            lambda: supabase.table("subscriptions")
            .select("user_id")
            .eq("original_transaction_id", tx.original_transaction_id)
            .limit(1)
            .execute()
        )
        if not owner_res.data or owner_res.data[0]["user_id"] != user_id:
            raise TransactionAlreadyUsed() from exc
        # 본인 거래 재검증/갱신 — 멱등 (만료 연장 등 반영)
        update = {k: v for k, v in record.items() if k != "original_transaction_id"}
        await asyncio.to_thread(
            lambda: supabase.table("subscriptions")
            .update(update)
            .eq("original_transaction_id", tx.original_transaction_id)
            .execute()
        )

    await asyncio.to_thread(
        lambda: supabase.table("profiles")
        .update({"tier": "premium"})
        .eq("user_id", user_id)
        .execute()
    )
    logger.info("IAP 구독 활성화 (user=%s, product=%s, env=%s)",
                user_id, tx.product_id, tx.environment)
    return IapVerifyResponse(
        tier="premium",
        product_id=tx.product_id,
        expires_at=tx.expires_at.isoformat(),
        environment=tx.environment,
    )


async def store_notification(signed_payload: str) -> None:
    """App Store Server Notification V2 수신 — 현재는 raw 저장만.

    [출시기 TODO — docs/IAP_LAUNCH_CHECKLIST.md]
      1) SignedDataVerifier.verify_and_decode_notification()으로 서명 검증
      2) notificationType별 처리: DID_RENEW → expires_at 연장,
         EXPIRED → status='expired' + tier 강등,
         REFUND/REVOKE → status='revoked' + 즉시 강등
      3) processed=false로 쌓인 기존 raw 재처리
    Apple은 200 아닌 응답에 재시도하므로 저장 실패도 호출부에서 삼킨다.
    """
    if not isinstance(signed_payload, str) or signed_payload.count(".") != 2:
        # JWS 형태(3세그먼트)가 아니면 저장할 가치도 없음 — 로그만.
        logger.warning("IAP notification: JWS 형태가 아닌 페이로드 수신 (무시)")
        return
    supabase = get_supabase_admin()
    # 실제 테이블 컬럼: payload(jsonb) + notification_type(출시기 디코드 후 채움)
    await asyncio.to_thread(
        lambda: supabase.table("iap_notifications_raw")
        .insert({"payload": {"signedPayload": signed_payload}})
        .execute()
    )
    logger.info("IAP notification raw 저장 (미처리 — 출시기 처리 예정)")
