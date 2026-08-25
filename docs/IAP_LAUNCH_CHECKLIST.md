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

- [ ] **`BETA_DEFAULT_PREMIUM` OFF + 베타 테스터 tier 정리** (2026-07-27 등재) —
  베타 신규 가입 자동 premium 플래그(fly secrets)를 제거·재배포하고, 승급된 베타
  테스터를 `scripts/grant_beta_premium.py --revoke --apply`로 리셋(IAP 구매자는
  subscriptions 행으로 자동 보호). 일괄 승급 이력: `db/2026-07-27_beta_testers_premium.sql`
- [ ] 배포 환경 변수 `ENVIRONMENT=production` 설정
- [ ] production에서 `IAP_MODE=mock`이면 **부팅 자체가 거부**되는지 확인 (main.py 가드)
- [ ] `iap_notifications_raw` 테이블 용량 모니터링 (처리 구현 후 정리 정책)

## 6. 보안 감사 미비 (2026-08-24 출시 전 보안 감사 20항목 파생 — 심각도·수정범위)

- [ ] **#2 git 히스토리 시크릿 스크럽** — [선택·위생] 노출 service_role은 2026-07-08
  회전 완료로 **무효**(긴급 아님). 잔존 텍스트 제거는 방어심화. **수정범위**: 문서
  절차(`docs/SECRET_SCRUB.md`) 실행 — filter-repo + Ivan 재클론 공지 + GitHub 캐시
  purge. **오너 승인 필수**(히스토리 재작성).
- [ ] **#5 PII/민감 컬럼 암호화 검토** — [권장] 신체정보 4종(birth_year·weight·
  height·gender)·GPS 트랙·이메일 저장. 앱레벨 암호화 없음(Supabase 저장시 암호화+TLS
  의존). **수정범위**: App Privacy 신고와 정합성 검토 후 필요시 컬럼 암호화(마이그레이션+
  read/write 경로) — 러닝앱 표준상 미적용도 수용 가능, 판단 필요.
- [ ] **#11 로그인/엔드포인트 rate limit** — [권장] 앱레벨 rate limit 없음(로그인
  브루트포스는 Supabase Auth 방어, 자사 엔드포인트는 JWT 게이트+생성쿼터만). **수정범위**:
  slowapi 미들웨어 or Fly 엣지 룰(main.py 1곳).
- [ ] **#18 보안 헤더 + `/docs` 프로덕션 차단** — [권장] HSTS·CSP·X-Frame 미들웨어
  전무, CORS `allow_origins=["*"]`, Swagger `/docs` 브라우저 도달. **수정범위**: HSTS
  미들웨어 추가 + 프로덕션 `/docs` 비활성 + 출시 시 CORS 도메인 화이트리스트(main.py).
- [ ] **#20 의존성 취약점 스캔** — [권장] `requirements.txt` `>=` 하한만(핀·lockfile·
  자동스캔 없음). **수정범위**: pip-audit/dependabot 도입 + 버전 핀(CI 설정+requirements).

## 참고 (방식 선택 근거, 2026-07 조사)

- verifyReceipt(구식 영수증)는 deprecated — 신규 구현 금지
- 채택: StoreKit 2 signedTransaction(JWS)을 서버가 Apple 공식 `app-store-server-library`로 로컬 검증 (API 호출·rate limit 없음), 갱신/환불은 Server Notifications V2
- 문서: developer.apple.com/documentation/appstoreserverapi (Simplifying your implementation by using the App Store Server Library)
