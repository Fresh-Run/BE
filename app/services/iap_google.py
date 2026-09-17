"""Google Play Billing Verifier — 인터페이스 스텁(2026-09-17).

서비스계정 크리덴셜 도착 전 단계: verify() **시그니처만 확정**. 실제 Play Developer API
(purchases.subscriptionsv2.get) 호출은 크리덴셜 후 채운다.

- google_iap_mode=='mock': payload.mock으로 정규화(개발/테스트, production 부팅거부).
- google_iap_mode=='google': 실검증 미구현 → IapNotConfigured(503, Apple app_apple_id
  미구성 패턴과 동일). 크리덴셜 도착 후 아래 TODO를 채운다.
"""
from __future__ import annotations

from datetime import datetime

from app.core.config import settings
from app.models.schemas import IapVerifyRequest
from app.services.iap_common import (
    InvalidTransaction,
    IapNotConfigured,
    VerifiedTransaction,
)


def _mock_allowed() -> bool:
    """production+mock 조합 거부(Apple _mock_allowed 미러)."""
    return settings.google_iap_mode == "mock" and settings.environment != "production"


def verify(payload: IapVerifyRequest) -> VerifiedTransaction:
    """Google 구매 검증 → VerifiedTransaction(store='google').

    현재: mock만 동작. 실검증(subscriptionsv2.get)은 서비스계정 후.

    필요 크리덴셜(config, 이반 서비스계정 후 fly secret 주입):
      · google_service_account_json — 서비스계정 JSON 전문(androidpublisher API auth).
      · google_package_name — Play packageName(API 호출 인자).
    실검증 흐름(TODO):
      creds = service_account.Credentials.from_service_account_info(
          json.loads(settings.google_service_account_json),
          scopes=["https://www.googleapis.com/auth/androidpublisher"])
      client = build("androidpublisher", "v3", credentials=creds)
      res = client.purchases().subscriptionsv2().get(
          packageName=settings.google_package_name, token=payload.purchase_token).execute()
      → subscriptionState / lineItems[].expiryTime / latestOrderId / linkedPurchaseToken
        을 VerifiedTransaction(store='google', original_transaction_id=<앵커 토큰>,
        purchase_token=<현재 토큰>, order_id=latestOrderId, expires_at=expiryTime)로 정규화.
      + 구매 acknowledge(3일 내 미승인=자동환불) 처리.  ⚠️ Apple엔 없는 필수 단계.
    온라인 API라 서버 구조 영향: 명시 timeout(~10s)·전송성 5xx 짧은 재시도·4xx는 재시도
    금지(InvalidTransaction). 동기 클라이언트는 asyncio.to_thread로 감쌀 것.
    """
    if settings.google_iap_mode == "mock":
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
            store="google",
            purchase_token=payload.purchase_token,
        )

    # 실검증 미구현(크리덴셜 대기) — 503 safe. 위 TODO를 서비스계정 후 채운다.
    raise IapNotConfigured()
