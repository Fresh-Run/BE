# 출시 전 IAP 실연동 체크리스트 (노션 이관용)

서버 구조는 완성 상태 (`POST /api/iap/verify`, `POST /api/iap/notifications`,
mock 모드, lazy 만료 강등). 아래는 **출시 준비기(12월 전)에 남은 실연동 작업**.
코드상 구현 지점은 `app/services/iap_service.py`의 `[출시기 TODO]` 주석 2곳.

## 착수 계획 (2026-08-26 조사) — 배틀·소셜 구현의 선행(출시 필수)

**핵심 진단**: 엔타이틀먼트 **배선은 완성**(verify_purchase→`subscriptions` upsert[PK
original_transaction_id]→`profiles.tier='premium'`, 만료는 `quota_service.get_tier`
lazy 강등). **비어 있는 건 JWS "검증"뿐** — `iap_service._verify`(apple)가
`IapNotConfigured`(→503 safe-closed), `store_notification`이 raw만 저장.

**Track A(오너 · App Store Connect) — 리드타임 순서**:
1. **유료 앱 계약·세금·뱅킹**(Paid Apps Agreement) — 승인 리드타임 최대, **최우선**.
2. 구독 상품 등록(product_id·가격·심사 메타) — 심사 리드타임.
3. App Store Server API 키(Issuer ID+Key ID+`.p8`) — 로컬 검증엔 불요(오프라인)이나
   상태 재조회·notification 재처리엔 유용(MVP 선택).
4. Server Notifications V2 URL 등록(sandbox/production 각각):
   `https://freshrun.run/api/iap/notifications`(AASA 도메인 배포 선행).
5. Sandbox 테스터 계정. → `.env`: `APPSTORE_ISSUER_ID·KEY_ID·PRIVATE_KEY_PATH·BUNDLE_ID`.

**Track B(서버 구현 · Track A와 병렬)** — ✅ **구현 완료(2026-08-27)**:
1. ✅ `app-store-server-library` 의존성(requirements.txt). Apple Root CA(G3/G2/Inc)
   `app/data/apple_root_ca/` 번들(라이브러리 미동봉이라 호출자 공급).
2. ✅ `_verify` apple: `SignedDataVerifier`(번들 root CA·env·`appstore_bundle_id`·
   `appstore_app_apple_id`[prod]) → `verify_and_decode_signed_transaction` → 매핑.
   **순수 오프라인(API 콜 0)**·prod→sandbox 폴백. sandbox는 bundle_id만으로 동작.
3. ✅ `store_notification`: `verify_and_decode_notification` + 타입별(DID_RENEW/EXPIRED/
   REFUND/REVOKE) 처리 + raw processed 갱신.
4. ✅ `iap_service.reprocess_unprocessed()`(processed=false 재처리, 멱등).
5. ✅ 테스트 `tests/test_iap_apple_verify.py`(fake decode 주입 12 assert — 매핑·웹훅
   4타입·재처리 멱등·구성 가드). **실 Sandbox JWS 검증은 Track A(app_apple_id·테스터) 후.**
   config: `.env` `APPSTORE_BUNDLE_ID`(기본 com.freshrun.app)·`APPSTORE_APP_APPLE_ID`(Track A).

**최소 스코프(출시 필수)**: ① `_verify` apple(구매→premium) ② 웹훅 4타입 —
DID_RENEW(연장)·EXPIRED(lazy 강등)·REFUND/REVOKE(즉시 강등) ③ Sandbox 1사이클
(구매·갱신·만료·환불·재구독·409) ④ **BETA_DEFAULT_PREMIUM OFF**(출시 직전, IAP 실동작
검증 후 — fly secret 제거+재배포 + `grant_beta_premium.py --revoke --apply`, IAP
구매자는 subscriptions 행으로 자동 보호) ⑤ production `IAP_MODE=mock` 부팅거부 확인.
**나중(post-launch)**: GRACE_PERIOD/Billing Retry 정교화 · Server API 주기 재조회 ·
가족 공유 · restore UX.

**정책 미확정 3건(오너 결정 — 발명 금지)**: ① product_id·가격·구독 주기 ② GRACE_PERIOD
동안 프리미엄 유지 여부(Apple 권장=유지, `GRACE_PERIOD_EXPIRED` 알림 처리) ③ 가족 공유 허용.

**리스크**: ① **환경 미스매치**(sandbox JWS를 prod verifier로 실패 → prod 시도→sandbox
폴백 분기 필요) ② **웹훅 유실 → 상태 동기화**(DID_RENEW 유실 시 오만료 — **백스탑 = lazy
강등 `get_tier` + restore 멱등 재검증**[구현됨], post는 Server API 주기 재조회) ③ 환불/
만료(REFUND/REVOKE 즉시·EXPIRED lazy). 웹 근거: apple/app-store-server-library-python.

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
  - **✅ 사전 점검 완료(2026-08-28, 읽기전용 dry-run)**: revoke 가드 실확인 —
    ① 강등 대상 = `profiles.tier=premium` **AND** `subscriptions` 행 부재(스크립트
    line 96). ② **IAP 구매자 보호 가드 있음**(line 79 `iap_uids`←subscriptions,
    line 98-99 `🔒 IAP 구매자 보호` 로그). ③ 시드(test1·test2·demo1~5)·운영진
    (freshrun0609) 이중 제외. ④ **dry-run이 기본**(변경엔 `--apply` 필수). 현
    dry-run: **강등 대상 71명·IAP 보호 0명**(pre-IAP = subscriptions 0행이라 지금은
    전원 강등이 정상). **출시 후엔 구매자가 subscriptions 행을 가져 자동 제외**되므로
    가드 추가 불요. ⚠️ **전환 순서**: BETA off는 IAP Sandbox 검증 후 — 그래야
    구매자 subscriptions 행이 존재해 revoke가 보호. ⚠️ dry-run에 `te***@freshrun.com`
    (nick=지연) 등 비-시드 `@freshrun.com` 계정 포함 — 오너가 유지 원하면 SEED_EMAILS
    추가 또는 수동 재승급(개인 계정 강등 방지 확인 필요).
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
- [x] **#11 엔드포인트 rate limit** — ✅ 처리(2026-08-26, main.py). 우리 API엔 login/
  signup 엔드포인트 없음(Supabase Auth 측)이라 **전역 per-IP 베이스라인**(프록시 IP
  인지 — fly-client-ip/X-Forwarded-For)으로 적용. 기본 240/분(`RATE_LIMIT_PER_MIN`,
  0=끔), 초과 429 `rate_limited`+Retry-After. /health·/.well-known exempt. 단일 머신
  in-memory(예산 1대). ⚠️ 다중 머신 확장 시 공유 저장(redis) 필요.
- [x] **#18 보안 헤더 + `/docs` 프로덕션 차단** — ✅ 처리(2026-08-26, main.py). HSTS·
  X-Content-Type-Options:nosniff·X-Frame-Options:DENY 미들웨어(순수 JSON API라 CSP
  생략). production에서 `/docs`·`/redoc`·`/openapi.json` 404(docs_url=None 조건부),
  스테이징·로컬 유지. **CORS 도메인 화이트리스트는 웹 클라 생길 때 별도**(현 네이티브만).
- [x] **#20 의존성 취약점 스캔** — ✅ 처리(2026-08-26, pip-audit).
  - **실스캔 결과(3건, 전부 전이 의존)**: cryptography 49.0.0(PYSEC-2026-3552, PKCS#7
    Bleichenbacher/타이밍 오라클) · h2 4.3.0(PYSEC-2026-3628, HTTP/2 서버 요청 스머글링) ·
    pip 26.1.2(PYSEC-2026-3721, 악성 인덱스 경로탈출). **레포지토리 즉시 조치 불요** —
    ① **컨텍스트상 미해당**: PKCS#7/S-MIME 복호 안 함 · 우리는 h2 **서버** 아님(h2는
    httpx **클라** 경유, supabase 클라는 HTTP/1.1 강제) · pip는 빌드 툴(신뢰 인덱스만).
    ② **fresh 빌드가 자동 수정**: `>=` 범위가 최신 해석 → h2 **4.4.1**·cryptography
    **50.0.1**(둘 다 fixed)를 받음(취약분은 로컬 .venv 잔재뿐). **재배포(fly deploy
    rebuild)로 반영.** pip는 빌드 이미지 `pip install --upgrade pip`로(백로그).
  - **자동화**: `.github/workflows/dep-audit.yml` — pip-audit 주 1회(화 03:00 KST) +
    requirements 변경 PR + 수동. requirements.txt는 `--strict`(CVE 시 실패), factory는
    관찰만. **dependabot 대비 GH Actions 선택**: 이미 백업 워크플로 있어 정합·설정 단순·
    PR 노이즈 적음(주1회 요약). ⚠️ GH Actions 60일 무활동 비활성(§C).
  - **핀/lockfile 권고(미채택·백로그)**: 현 `>=`는 재현성 약점(배포 버전=빌드 시점
    최신). **전면 핀은 지금 지양**(테스트 커버 안 된 버전 고정 리스크) — 권고 =
    출시 안정화 후 `pip-compile`(pip-tools)로 `requirements.lock` 생성(정확 버전 +
    해시), Dockerfile이 lock 설치. 그때까지 pip-audit CI가 신규 CVE 감시.

## 참고 (방식 선택 근거, 2026-07 조사)

- verifyReceipt(구식 영수증)는 deprecated — 신규 구현 금지
- 채택: StoreKit 2 signedTransaction(JWS)을 서버가 Apple 공식 `app-store-server-library`로 로컬 검증 (API 호출·rate limit 없음), 갱신/환불은 Server Notifications V2
- 문서: developer.apple.com/documentation/appstoreserverapi (Simplifying your implementation by using the App Store Server Library)
