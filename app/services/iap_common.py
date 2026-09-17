"""IAP 공통 코어 — store-agnostic(정규화 거래·예외·구독 upsert+tier 전환).

Apple(iap_apple)·Google(iap_google) Verifier가 원본을 VerifiedTransaction으로 정규화하면
이 모듈의 persist_verified가 store 무관하게 subscriptions upsert + profiles.tier 전환을
수행한다.

리팩터(2026-09-17): 기존 iap_service.verify_purchase의 **DB층을 로직 변경 없이 이관**.
애플 동작 100% 보존 — persist_verified는 store=='apple'이면 신규 컬럼 키를 미전송해
기존 insert와 바이트 동일(스키마 마이그레이션 타이밍과 무관).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import IapVerifyResponse

logger = logging.getLogger(__name__)

_UNIQUE_VIOLATION = "23505"


class IapNotConfigured(Exception):
    """검증 크리덴셜/구현이 아직 없음 (출시기 작업)."""


class InvalidTransaction(Exception):
    """페이로드 구조/서명이 유효하지 않음."""


class TransactionExpired(Exception):
    """이미 만료 시각이 지난 거래 (재구독은 새 거래로 와야 함)."""


class TransactionAlreadyUsed(Exception):
    """다른 유저가 이미 등록한 거래 정체성 (재사용 공격 방어)."""


@dataclass
class VerifiedTransaction:
    """스토어 무관 정규화 거래. original_transaction_id = 스토어 공통 구매 정체성 PK
    (Apple=originalTransactionId, Google=linkedPurchaseToken 앵커 토큰)."""
    original_transaction_id: str
    product_id: str
    expires_at: datetime
    environment: str  # sandbox | production | mock
    # additive(2026-09-17) — 기본 apple=하위호환. 구글만 신규 필드를 채운다.
    store: str = "apple"
    purchase_token: str | None = None   # 구글 현재 토큰(Play API 호출용). 애플=None
    order_id: str | None = None         # 구글 latestOrderId. 애플=None


def _epoch_ms_to_dt(ms: int) -> datetime:
    """Store epoch millis → tz-aware UTC datetime (Apple·Google 공용)."""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


async def persist_verified(user_id: str, tx: VerifiedTransaction) -> IapVerifyResponse:
    """정규화 거래 → subscriptions upsert + profiles.tier='premium'. 같은 거래 재전송 멱등.

    (기존 verify_purchase의 DB층 — 로직 불변 이관.) 실제 테이블 PK는
    original_transaction_id(거래가 곧 정체성). upsert는 PK 충돌 시 남의 행을 덮어써
    구독 탈취가 되므로 쓰지 않는다 — insert-first, PK 충돌이면 기존 행 소유자 확인 후 분기
    (레이스 안전: insert가 원자적이라 먼저 넣은 쪽이 소유자로 확정).

    ⚠️ 애플 하위호환: store=='apple'이면 record에 store/purchase_token/order_id 키를
    넣지 않는다 → 기존 insert와 **바이트 동일**(마이그레이션 타이밍 무관·회귀 0).
    """
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
    if tx.store != "apple":  # 애플 경로는 기존과 동일(신규 키 미전송). 구글만 채움.
        record["store"] = tx.store
        if tx.purchase_token is not None:
            record["purchase_token"] = tx.purchase_token
        if tx.order_id is not None:
            record["order_id"] = tx.order_id

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
    logger.info("IAP 구독 활성화 (user=%s, product=%s, env=%s, store=%s)",
                user_id, tx.product_id, tx.environment, tx.store)
    return IapVerifyResponse(
        tier="premium",
        product_id=tx.product_id,
        expires_at=tx.expires_at.isoformat(),
        environment=tx.environment,
    )
