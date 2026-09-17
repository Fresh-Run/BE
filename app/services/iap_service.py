"""IAP 오케스트레이터(facade) — store 분기 진입점 + 하위호환 re-export.

리팩터(2026-09-17): 로직을 iap_common(공유)·iap_apple(애플)·iap_google(구글)로 분리하고
이 모듈은 ① store별 Verifier 디스패치(_verify) ② 공유 persist 위임(verify_purchase)
③ 기존 공개 API를 그대로 re-export한다(routes·tests 무변경 — 애플 동작 100% 보존).

구조: verify_purchase(user_id, payload) → _verify(store)로 정규화 → iap_common.persist_verified.
  · store 미지정/'apple' → iap_apple.verify(apple/mock, IAP_MODE)
  · store == 'google'    → iap_google.verify(google/mock, GOOGLE_IAP_MODE — 실검증 스텁)
애플 웹훅(store_notification·reprocess_unprocessed)은 iap_apple에서 re-export.
"""

from __future__ import annotations

from app.models.schemas import IapVerifyRequest, IapVerifyResponse
from app.services import iap_apple, iap_google
from app.services.iap_common import (  # noqa: F401 — 하위호환 re-export(routes/tests가 iap_service.X 접근)
    IapNotConfigured,
    InvalidTransaction,
    TransactionAlreadyUsed,
    TransactionExpired,
    VerifiedTransaction,
    persist_verified,
)

# 애플 웹훅 공개 API re-export — routes.py(iap_service.store_notification)·기존 테스트 보존.
store_notification = iap_apple.store_notification
reprocess_unprocessed = iap_apple.reprocess_unprocessed


def _verify(payload: IapVerifyRequest) -> VerifiedTransaction:
    """store별 Verifier 디스패치. 기본 store='apple'(하위호환 — 기존 클라 {jws}는 애플로)."""
    store = getattr(payload, "store", "apple") or "apple"
    if store == "google":
        return iap_google.verify(payload)
    return iap_apple.verify(payload)  # apple/mock (IAP_MODE)


async def verify_purchase(user_id: str, payload: IapVerifyRequest) -> IapVerifyResponse:
    """거래 검증(store 분기) → 공유 persist(subscriptions upsert + tier). 재전송 멱등.

    애플 경로는 리팩터 전과 동일: _verify가 iap_apple.verify를 호출(JWS/mock),
    persist_verified가 기존 DB층(신규 store 키 미전송)을 수행 → 동작·와이어 불변.
    """
    tx = _verify(payload)
    return await persist_verified(user_id, tx)
