# 배포 실행 체크리스트 (노션 이관용)

결정 사항 (2026-07-06 설계): **Fly.io 도쿄(nrt) · 머신 1대(shared-cpu-1x 512MB, 상시 실행) · uvicorn workers=1 · 베타→출시 동일 유지.**
근거·비교표는 배포 설계 문서 참고. 예산: 월 $3~5 (+출시 전 Supabase Pro $25).

## A. 사전 준비 (코드) — ✅ 완료 (2026-07-06 커밋)

- [x] CORS `allow_credentials=False` 정리 (`app/main.py`)
- [x] `Dockerfile` (python:3.13-slim, `$PORT` 바인드, workers 1) + `.dockerignore`
- [x] `fly.toml` (nrt, 상시 실행, `/health` 체크, ENVIRONMENT=production)
- [x] Sentry SDK 연동 — `SENTRY_DSN` 미설정 시 no-op (DSN만 채우면 켜짐)
- [x] 3.13 컨테이너 검증: 빌드 → 기동 → `/health` production 응답 → prod+mock 부팅 거부까지 확인됨

## B. 계정·프로젝트 생성

- [ ] Fly.io 가입 + 결제 수단 등록 → `brew install flyctl` → `fly auth login`
- [ ] Supabase 대시보드 → Settings > General에서 **리전 확인** (서울이면 그대로 진행 — 도쿄행 +30ms/쿼리 허용 판단 완료. 만약 미국/유럽이면 설계 재검토!)
- [ ] Sentry 가입(무료) → FastAPI 프로젝트 → DSN 확보

## C. 첫 배포

- [ ] `fly launch --no-deploy` (앱 이름: freshrun-api, 리전: **nrt**)
- [ ] `fly.toml` 확인: `min_machines_running = 1` (콜드 스타트 방지), `auto_stop_machines = "off"`, http 헬스체크 → `GET /health`
- [ ] **secrets 등록** (`fly secrets set KEY=...` — .env의 실값, 단 아래 3개 규칙 주의):
  - [ ] `ENVIRONMENT=production` ← IAP mock 부팅 거부 가드의 스위치
  - [ ] `IAP_MODE`는 **설정하지 않음** (기본 apple = 닫힘)
  - [ ] `OPENWEATHER_BASE_URL`은 **설정하지 않음** (실서버 기본값)
  - [ ] `OPENAI_BASE_URL` = Gemini 릴레이 주소 **필수** (누락 시 코스 생성 전멸)
  - [ ] 나머지: SUPABASE_URL / SUPABASE_KEY / SUPABASE_SERVICE_ROLE_KEY / OPENAI_API_KEY / OPENAI_MODEL / KAKAO_REST_API_KEY / TMAP_APP_KEY / MAP_PROVIDER / OPENWEATHER_API_KEY (+ SENTRY_DSN)
- [ ] `fly deploy` → `fly logs`로 기동 확인

## D. 배포 검증 (스모크)

- [ ] `GET https://<app>.fly.dev/health` → `{"status":"ok","environment":"production"}`
- [ ] 데모 계정(test1)으로 로그인 토큰 발급 → `GET /api/me/quota` 200
- [ ] `GET /api/weather?lat=37.5445&lng=127.0374` 200 (OpenWeather 실키 동작)
- [ ] `POST /api/routes/generate` 1회 (~2원) — Gemini 릴레이·T-map 연결 확인
- [ ] `POST /api/iap/verify` body `{"jws":"a.b.c"}` → **503 iap_not_configured** (닫힘 확인)
- [ ] 응답 시간 확인: /me/stats p50 < 300ms 수준이면 리전 선택 성공

## E. 배포 후 운영 세팅

- [ ] git push 배포: GH Actions에 `fly deploy` 워크플로 (FLY_API_TOKEN secret) — 수동 `fly deploy`로 시작해도 무방
- [ ] **DB 백업 크론**: GH Actions 주 1회 `supabase db dump` → 프라이빗 아티팩트/스토리지 (무료 티어는 자동 백업 없음!)
- [ ] Sentry에 테스트 에러 1건 보내 수신 확인
- [ ] 프론트에 API BASE URL 전달: `https://<app>.fly.dev/api`

## F. 출시 전 (12월, 별도 시점)

- [ ] Supabase **Pro 업그레이드** ($25/월 — 일일 백업 7일 보관 확보)
- [ ] 커스텀 도메인 연결 (`fly certs add api.freshrun.…`) — IAP 웹훅 URL 등록 전에 확정
- [ ] App Store Server Notifications URL 등록: `https://<도메인>/api/iap/notifications` (IAP_LAUNCH_CHECKLIST.md와 연결)
- [ ] `IAP_MODE=apple` 크리덴셜 세팅 (IAP_LAUNCH_CHECKLIST.md 2절)
- [ ] 부하 재점검: workers=2 또는 머신 증설 필요 여부 (트리거: CPU 70%+ 지속 / p95 악화). 멀티 인스턴스 가면 날씨 캐시 Redis(Upstash) 검토 — 그 전엔 불필요

## 확장 시점 메모 (지금은 안 함)

- 멀티 인스턴스: 날씨 캐시만 인메모리 → 히트율 하락일 뿐 정확성 문제 없음. 레이스 방어 로직들(크루 가입·IAP·coach 캐시)은 전부 DB 원자성 기반이라 그대로 안전 (2026-07-06 전수 확인).
- 로그 구조화(JSON)·APM은 유저 트래픽이 생긴 뒤.
