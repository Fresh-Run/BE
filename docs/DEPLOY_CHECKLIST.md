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

- [x] Fly.io 가입 + 결제 수단 등록 → `brew install flyctl`(v0.4.67) → `fly auth login` ✅ (2026-07-07, org `moominii`)
- [x] Supabase 리전 확인 — 동북아(서울), 도쿄 서버와 근접 ✅ (p50 실측 아래 D절)
- [ ] Sentry 가입(무료) → FastAPI 프로젝트 → DSN 확보 — **보류**(DSN 미설정 = no-op, 배포 지장 없음. 계정은 나중에)

## C. 첫 배포 — ✅ 완료 (2026-07-07)

- [x] `fly apps create freshrun-api` (기존 fly.toml 유지, 리전 **nrt**)
- [x] `fly.toml` 확인: `min_machines_running = 1`, `auto_stop_machines = "off"`, `/health` 체크
- [x] **secrets 등록** (`fly secrets import` — stdin 파이프로 값 미노출, 12개 스테이징):
  - [x] `ENVIRONMENT=production` ← fly.toml `[env]`에 이미 있음(secret 아님)
  - [x] `IAP_MODE` **미설정** (기본 apple = 닫힘) — D절 503으로 확인됨
  - [x] `OPENWEATHER_BASE_URL` **미설정** (실서버 기본값)
  - [x] `OPENAI_BASE_URL` = Gemini 릴레이 **등록됨**
  - [x] SUPABASE_URL / SUPABASE_KEY / SUPABASE_SERVICE_ROLE_KEY / OPENAI_API_KEY / OPENAI_MODEL / KAKAO_REST_API_KEY / TMAP_APP_KEY / MAP_PROVIDER / OPENWEATHER_API_KEY / NAVER_MAP_CLIENT_ID / NAVER_MAP_CLIENT_SECRET (SENTRY_DSN은 보류)
- [x] `fly deploy` → 성공. Fly가 HA용 2대 자동 생성 → **설계대로 `fly scale count 1`로 1대 축소**

## D. 배포 검증 (스모크) — ✅ 전 항목 통과 (2026-07-07)

- [x] `GET /health` → `{"status":"ok","environment":"production"}` (139ms)
- [x] test1 로그인 → `GET /api/me/quota` 200
- [x] `GET /api/weather?lat=37.5445&lng=127.0374` 200 (OpenWeather 실키·PM·러닝지수 정상)
- [ ] `POST /api/routes/generate` — Gemini 무료 티어 일일 quota 상황 따라 별도 확인(코드 검증 완료분이라 배포 게이트는 아님)
- [x] `POST /api/iap/verify` `{"jws":"a.b.c"}` → **503 iap_not_configured** (mock 닫힘 확인 ✅)
- [x] `/me/stats` p50 **~290ms** (< 300ms) → 도쿄↔서울 리전 선택 성공

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

---

## 🚀 운영 메모 (2026-07-07 배포 완료)

**앱 URL**
- 서비스: `https://freshrun-api.fly.dev`
- **프론트 연동 BASE URL**: `https://freshrun-api.fly.dev/api`
- Swagger: `https://freshrun-api.fly.dev/docs` · Health: `https://freshrun-api.fly.dev/health`
- 대시보드(그래프·머신): https://fly.io/apps/freshrun-api/monitoring
- 구성: 도쿄(nrt) 머신 1대 (shared-cpu-1x 512MB, 상시 실행). org `moominii`.

**로그 보기** (`fly`는 `/opt/homebrew/bin/fly`)
```
fly logs --app freshrun-api            # 실시간 스트리밍(따라붙기)
fly logs --app freshrun-api --no-tail  # 최근 로그만 한 번
fly status --app freshrun-api          # 머신 상태·헬스체크·버전
```

**재배포** (코드 변경 후)
- 방법 A — 로컬 수동 (지금 바로 됨): 프로젝트 루트에서
  ```
  fly deploy --app freshrun-api
  ```
  Docker 빌드 → 이미지 푸시 → 머신 교체(무중단). 코드만 올라가고 secrets는 Fly에 저장된 값 유지.
- 방법 B — git push 자동 (최초 1회 설정 필요): `.github/workflows/fly-deploy.yml` 있음. 활성화하려면 로컬에서 `fly tokens create deploy` → 출력 토큰을 GitHub repo Settings > Secrets > Actions에 **`FLY_API_TOKEN`**으로 등록. 그 뒤엔 `main`에 push할 때마다 자동 배포. (토큰 없으면 워크플로만 실패, 서비스엔 무영향 → 방법 A로 배포)

**서버 끄고 켜기**
```
fly scale count 0 --app freshrun-api   # 완전 정지 (머신 0대 — 과금 최소, /health도 죽음)
fly scale count 1 --app freshrun-api   # 다시 켜기 (1대, 설계 기본값)
fly machine restart <MACHINE_ID> --app freshrun-api   # 재시작만 (ID는 fly status)
```
> ⚠️ 스케일은 항상 **count 1**로 되돌릴 것. Fly는 재배포 때 HA용으로 2대를 만들려 하는데, 예산(월 $3~5)은 1대 기준. 2대로 늘면 `fly scale count 1`로 축소.

**환경변수(secrets) 변경**
```
fly secrets list --app freshrun-api                  # 키 이름·다이제스트만(값 안 보임)
fly secrets set KEY=값 --app freshrun-api            # 추가/변경 → 자동 재배포
fly secrets unset KEY --app freshrun-api             # 제거
```
- Sentry 켜기: `fly secrets set SENTRY_DSN=<dsn>` (DSN 없으면 no-op 유지).
- IAP 실결제 열기(출시 때): `IAP_MODE=apple` + 크리덴셜 (IAP_LAUNCH_CHECKLIST.md). 지금은 미설정 = 503으로 닫혀 있음.

**문제 시 1분 점검**
1. `fly status` — 머신 started·checks passing 인가
2. `fly logs` — 부팅 traceback 있나 (secret 누락이면 여기 찍힘)
3. `curl https://freshrun-api.fly.dev/health` — 200 `production` 나오나

## E. 배포 후 운영 세팅 (진행 상황)

- [x] git push 배포 워크플로 파일 추가 (`.github/workflows/fly-deploy.yml`) — 활성화는 `FLY_API_TOKEN` 등록 시(위 방법 B). 그전까진 수동 `fly deploy`
- [ ] **DB 백업 크론**: GH Actions 주 1회 `supabase db dump` (무료 티어 자동 백업 없음) — 미설정
- [ ] Sentry 테스트 에러 수신 — 계정 생성 후
- [x] 프론트에 API BASE URL 전달: `https://freshrun-api.fly.dev/api`
