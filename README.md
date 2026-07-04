# FreshRun Backend

[한국어](#한국어) | [English](#english)

---

## 한국어

**FreshRun**은 AI 기반 한국 러닝 앱입니다 (iOS, 2026년 12월 출시 목표).

이 저장소는 **백엔드(BE)** 입니다. 프론트엔드는 [Fresh-Run/FE](https://github.com/Fresh-Run/FE) (React Native + Expo)를 참고하세요.

### 주요 기능

- **AI 코스 생성** — Gemini + T맵 보행자 경로로 실제 달릴 수 있는 코스 생성 (free 티어 주 3회, 서버측 쿼터)
- **러닝 기록·통계** — 기록 저장, 2탭 피드백 루프, 주간/월간/전체 통계 + 월별 캘린더
- **크루** — 생성·가입·주간 랭킹·챌린지(목표 달성 알림)
- **공개 코스 피드** — 좋아요·댓글·복사("이 코스 달리기")·북마크
- **팔로우/피드** — 팔로우한 유저들의 공개 코스 피드, 공개 프로필(맞팔 표시)
- **날씨** — 현재 날씨 + 미세먼지 등급 + 규칙 기반 AI 러닝지수 (위치 격자 캐싱)
- **프리미엄 티어** — tier 저장 + 서버측 강제 (IAP는 출시 전 연동 예정)

### 기술 스택

- **FastAPI** (Python) — 전 데이터 접근은 service_role 클라이언트, 인증 필수
- **Supabase** — Auth(JWT) + Postgres + RLS
- **외부 API** — Gemini(코스 생성), T맵(보행자 경로), 카카오(장소 검색), OpenWeather(날씨·미세먼지)

### 로컬 실행

```bash
# 1. 가상환경 + 의존성
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 환경변수 — .env.example을 복사해 값 채우기
cp .env.example .env
```

필요한 환경변수 (값은 각 서비스 콘솔에서 발급):

| 변수 | 용도 |
|---|---|
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` | 코스 생성 LLM (Gemini의 OpenAI 호환 엔드포인트 사용) |
| `SUPABASE_URL`, `SUPABASE_KEY` | Supabase 프로젝트 URL + anon 키 (토큰 검증) |
| `SUPABASE_SERVICE_ROLE_KEY` | 데이터 접근용 service_role 키 — **서버 전용, 절대 노출 금지** |
| `TMAP_APP_KEY`, `KAKAO_REST_API_KEY`, `MAP_PROVIDER` | 보행자 경로·장소 검색 |
| `OPENWEATHER_API_KEY` | 날씨 + 미세먼지 |

```bash
# 3. 서버 실행
uvicorn app.main:app --reload
```

### API 문서

서버 실행 후 http://localhost:8000/docs (Swagger UI)에서 전체 엔드포인트를 확인할 수 있습니다.

DB 스키마 변경 SQL은 `db/`, 통합 테스트는 `tests/` (`python tests/test_<기능>_integration.py`)에 있습니다.

---

## English

**FreshRun** is an AI-powered running app for South Korea (iOS, launching December 2026).

This repository is the **backend (BE)**. The frontend lives at [Fresh-Run/FE](https://github.com/Fresh-Run/FE) (React Native + Expo).

### Features

- **AI course generation** — Gemini + T-map pedestrian routing produce runnable courses (free tier: 3/week, enforced server-side)
- **Run tracking & stats** — run logs, two-tap feedback loop, weekly/monthly/all-time stats with a monthly calendar breakdown
- **Crews** — create/join, weekly distance ranking, challenges with completion notifications
- **Public course feed** — likes, comments, copy ("run this course"), bookmarks
- **Follows & feed** — a feed of public courses from users you follow, public profiles with mutual-follow flags
- **Weather** — current conditions + PM2.5/PM10 grades + a rule-based running index (grid-cell caching)
- **Premium tier** — tier storage + server-side enforcement (IAP integration planned before launch)

### Tech stack

- **FastAPI** (Python) — all data access via the service_role client; auth required on every endpoint
- **Supabase** — Auth (JWT) + Postgres + RLS
- **External APIs** — Gemini (course generation), T-map (pedestrian routing), Kakao (place search), OpenWeather (weather & air quality)

### Running locally

```bash
# 1. Virtualenv + dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Environment — copy the example and fill in values
cp .env.example .env
```

Required variables (issue keys from each service's console): `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` (Gemini via its OpenAI-compatible endpoint), `SUPABASE_URL` / `SUPABASE_KEY` / `SUPABASE_SERVICE_ROLE_KEY` (service_role is server-only — never expose), `TMAP_APP_KEY` / `KAKAO_REST_API_KEY` / `MAP_PROVIDER`, `OPENWEATHER_API_KEY`.

```bash
# 3. Run
uvicorn app.main:app --reload
```

### API docs

With the server running, browse all endpoints at http://localhost:8000/docs (Swagger UI).

Schema migration SQL lives in `db/`; integration tests in `tests/` (`python tests/test_<feature>_integration.py`).
