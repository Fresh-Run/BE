# 출시 전 IAP 실연동 체크리스트 (노션 이관용)

서버 구조는 완성 상태 (`POST /api/iap/verify`, `POST /api/iap/notifications`,
mock 모드, lazy 만료 강등). 아래는 **출시 준비기(12월 전)에 남은 실연동 작업**.
코드상 구현 지점은 `app/services/iap_service.py`의 `[출시기 TODO]` 주석 2곳.

## 1. App Store Connect 설정

- [ ] 구독 그룹 생성 + 구독 상품 등록 — `product_id` 확정 (예: `freshrun.premium.monthly`, `freshrun.premium.yearly`), 가격, 심사용 메타데이터
- [ ] **In-App Purchase용 App Store Connect API 키 발급**: Issuer ID + Key ID + `.p8` 개인키
- [ ] App Store **Server Notifications V2 URL 등록** (sandbox / production 각각) — 공개 HTTPS 배포 도메인 필요: `https://<배포도메인>/api/iap/notifications`

## 2. 서버 구현 (iap_service.py TODO 2곳)

- [ ] 의존성 추가: `app-store-server-library` (Apple 공식 Python 라이브러리)
- [ ] `.env` 추가: `APPSTORE_ISSUER_ID`, `APPSTORE_KEY_ID`, `APPSTORE_PRIVATE_KEY_PATH`, `APPSTORE_BUNDLE_ID`, `IAP_MODE=apple`
- [ ] `_verify()` apple 분기 구현: `SignedDataVerifier`(Apple Root CA 동봉분, environment, bundle_id)로 `verify_and_decode_signed_transaction(jws)` → `VerifiedTransaction` 매핑 (originalTransactionId / productId / expiresDate / environment)
- [ ] `store_notification()` 처리 구현: `verify_and_decode_notification()` 서명 검증 + 타입별 처리 — `DID_RENEW`→만료 연장, `EXPIRED`→status='expired'+강등, `REFUND`/`REVOKE`→status='revoked'+**즉시** 강등. 이후 `iap_notifications_raw`의 `processed=false` 잔여분 재처리 스크립트 1회 실행

## 3. Sandbox 실검증 (테스터 계정)

- [ ] 구매 → `POST /iap/verify` → tier premium + 만료일 확인
- [ ] 자동 갱신(sandbox 가속 주기) → `DID_RENEW` 웹훅 수신·연장 확인
- [ ] 만료 방치 → lazy 강등 확인 (`/me/quota` tier free)
- [ ] 재구독 → 복귀 확인
- [ ] 환불(Apple 지원 페이지) → `REFUND` 웹훅 → 즉시 강등 확인
- [ ] 기기 2대/계정 2개로 **같은 거래 재사용 → 409** 확인

## 4. 정책 결정

- [ ] **Billing Grace Period / Billing Retry** 기간을 premium 유지로 볼지 확정 (Apple 권장: grace 동안 유지 — `GRACE_PERIOD_EXPIRES` 알림 처리 필요)
- [ ] 가족 공유(Family Sharing) 허용 여부
- [ ] 구독 복원(restore purchases) UX — 앱이 현재 entitlement의 JWS를 다시 verify로 보내면 서버는 멱등 처리(이미 구현됨)

## 5. 배포 가드 확인

- [ ] 배포 환경 변수 `ENVIRONMENT=production` 설정
- [ ] production에서 `IAP_MODE=mock`이면 **부팅 자체가 거부**되는지 확인 (main.py 가드)
- [ ] `iap_notifications_raw` 테이블 용량 모니터링 (처리 구현 후 정리 정책)

## 참고 (방식 선택 근거, 2026-07 조사)

- verifyReceipt(구식 영수증)는 deprecated — 신규 구현 금지
- 채택: StoreKit 2 signedTransaction(JWS)을 서버가 Apple 공식 `app-store-server-library`로 로컬 검증 (API 호출·rate limit 없음), 갱신/환불은 Server Notifications V2
- 문서: developer.apple.com/documentation/appstoreserverapi (Simplifying your implementation by using the App Store Server Library)
