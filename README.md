# FreshRun Backend

[한국어](#한국어) | [English](#english)

---

## 한국어

**FreshRun**은 AI 기반 한국 러닝 앱입니다 (iOS, 2026년 12월 출시 목표 — 현재 지인 베타 준비).

이 저장소는 **백엔드(BE)** 입니다. 프론트엔드는 [Fresh-Run/FE](https://github.com/Fresh-Run/FE) (React Native + Expo).

### 현황 요약

코어 러닝(기록·GPS 서버 검증·통계·개인 최고기록), AI(코스 생성 + 오디오 코치·월간
리포트 — 프리미엄), 소셜(팔로우·활동 피드·kudos·댓글·러닝 사진), 크루(랭킹·챌린지·
공지/RSVP·운영진 role·초대 코드), 알림(인앱 + Expo 원격 푸시), 회원 탈퇴(완전 삭제),
프리미엄 티어(서버 강제, IAP 서버 준비 완료 — 실결제는 출시기). **전 기능·응답
스키마·프론트 소비 규칙은 [docs/API_GUIDE.md](docs/API_GUIDE.md)가 단일 소스**
(이 README에 기능 상세를 중복 서술하지 않습니다 — 드리프트 방지).

### 기술 스택 · 인프라

- **FastAPI** (Python 3.13+) — 전 데이터 접근은 Supabase service_role, 전 엔드포인트 인증 필수
- **Supabase** — Auth(JWT) + Postgres(RLS 백스톱) + Storage(아바타·러닝 사진)
- **Fly.io** — 스테이징 `https://freshrun-api.fly.dev` (도쿄 nrt, 1대) + **Sentry** 에러 트래킹
- **외부 API** — Gemini(OpenAI 호환 엔드포인트), T맵(보행 경로), 카카오(장소 검색), OpenWeather(날씨·미세먼지·자외선), Expo Push(원격 알림)

### 로컬 실행 (30분 목표)

```bash
# 1. 가상환경 + 의존성
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 환경변수 — 예시를 복사해 값 채우기 (변수별 설명은 .env.example 주석)
cp .env.example .env

# 3. 서버 실행
uvicorn app.main:app --reload
```

- Swagger: http://localhost:8000/docs — 전체 엔드포인트의 단일 최신 소스.
- `--reload` 없이 띄웠다면 **코드 수정 후 반드시 재시작** (구코드로 인한 헛디버깅 방지).
- 필수 키 최소셋: Supabase 3종 + Gemini(OPENAI_*) — 지도·날씨·Sentry·푸시는 없어도 서버는 뜨고 해당 기능만 비활성/에러.

### 테스트

```bash
python tests/test_<기능>_integration.py   # 로컬 서버(8000) 실행 상태에서
```

- 통합 테스트는 실 Supabase에 임시 유저를 만들고 종료 시 전부 정리합니다(멱등).
- 앱 모듈을 import하는 일부 테스트(pb_records, join_approval 등)는 `.venv/bin/python`으로 실행.
- 데모 데이터: `python scripts/seed_demo_data.py` (멱등 — [scripts/DEMO_ACCOUNTS.md](scripts/DEMO_ACCOUNTS.md)).

### 배포 (스테이징)

**`git push`는 배포가 아닙니다** — 반영하려면 명시적으로:

```bash
fly deploy --app freshrun-api && fly scale count 1 --app freshrun-api
```

배포 후 `/health` + 변경 기능 스모크 1사이클. 상세 절차·로그·secrets 규칙은
[docs/DEPLOY_CHECKLIST.md](docs/DEPLOY_CHECKLIST.md), 백업은 [docs/BACKUP.md](docs/BACKUP.md).

### 문서 지도

| 문서 | 내용 |
|---|---|
| [docs/API_GUIDE.md](docs/API_GUIDE.md) | **프론트 연동 단일 소스** — 화면별 매핑·응답 스키마·에러 규약·딥링크 |
| [docs/AUDIT_BACKLOG.md](docs/AUDIT_BACKLOG.md) | 셀프 감사 이력(2회) + 운영 관측 + 기능 백로그(트리거 대기) |
| [docs/PRIVACY_DATA_MAP.md](docs/PRIVACY_DATA_MAP.md) | 개인정보처리방침 원천 자료(수집·제3자·삭제 실증) |
| [docs/DEPLOY_CHECKLIST.md](docs/DEPLOY_CHECKLIST.md) / [BACKUP.md](docs/BACKUP.md) | 배포·백업 운영 |
| docs/*_DESIGN.md | 기능별 설계 기록(레이스 수정·계정 삭제·사진·운영진·푸시 등) |
| `db/` | 스키마 변경 SQL — `[APPLY]`+`[ROLLBACK]` 페어, 실행 여부 주석 |

---

## English

**FreshRun** is an AI-powered running app for South Korea (iOS, targeting December 2026 — currently preparing a friends-and-family beta).

This repository is the **backend (BE)**. The frontend lives at [Fresh-Run/FE](https://github.com/Fresh-Run/FE) (React Native + Expo).

### Status summary

Core running (logs, server-side GPS verification, stats, personal bests), AI (course
generation + audio coach & monthly report — premium), social (follows, activity feed,
kudos, comments, run photos), crews (ranking, challenges, announcements/RSVP, admin
roles, invite codes), notifications (in-app + Expo remote push), account deletion
(full erasure), premium tier (server-enforced; IAP server-side ready, live billing at
launch). **[docs/API_GUIDE.md](docs/API_GUIDE.md) is the single source** for every
endpoint, schema, and frontend consumption rule — this README intentionally avoids
duplicating feature details (drift prevention).

### Stack & infra

- **FastAPI** (Python 3.13+) — all data access via Supabase service_role; auth required everywhere
- **Supabase** — Auth (JWT) + Postgres (RLS backstop) + Storage (avatars, run photos)
- **Fly.io** — staging at `https://freshrun-api.fly.dev` (nrt, 1 machine) + **Sentry** error tracking
- **External APIs** — Gemini (OpenAI-compatible endpoint), T-map (pedestrian routing), Kakao (place search), OpenWeather (weather/PM/UV), Expo Push

### Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in values; each variable is documented inline
uvicorn app.main:app --reload
```

Swagger at http://localhost:8000/docs is the always-current endpoint reference.
Without `--reload`, **restart after every code change**. Minimum keys to boot:
Supabase ×3 + Gemini (`OPENAI_*`) — maps/weather/Sentry/push degrade gracefully.

### Tests & deploy

Integration tests: `python tests/test_<feature>_integration.py` (local server must be
running; tests create and fully clean up temp users). Some import app modules — run
those with `.venv/bin/python`. Demo seed: `python scripts/seed_demo_data.py` (idempotent).

**`git push` does not deploy.** Staging: `fly deploy --app freshrun-api` then
`fly scale count 1` — see [docs/DEPLOY_CHECKLIST.md](docs/DEPLOY_CHECKLIST.md).
