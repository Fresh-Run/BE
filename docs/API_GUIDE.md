# FreshRun API 연동 가이드 (프론트엔드용)

React Native + Expo + Supabase JS SDK 기준. 전체 엔드포인트의 요청/응답 스키마는 서버 실행 후 **Swagger(`http://<서버>/docs`)** 가 항상 최신이므로, 이 문서는 "어떻게 붙이는지"와 "무엇이 어디 있는지"만 다룹니다.

---

## 1. 아키텍처 원칙

**Supabase를 직접 호출하는 것은 Auth뿐입니다.** (회원가입/로그인/토큰 갱신)
**모든 데이터 읽기/쓰기는 FastAPI를 경유합니다.**

```
[앱] ──(Auth만)──────────→ Supabase Auth
[앱] ──(그 외 전부, Bearer 토큰)──→ FastAPI ──(service_role)──→ Supabase DB
```

이유:
- **비즈니스 로직이 API에 있습니다** — AI 코스 생성 쿼터(free 주 3회), 크루 권한(크루장 전용 작업), RSVP 마감 판정, 팔로우 카운트/맞팔 계산, 알림 발송 등. 앱이 DB를 직접 읽으면 이 규칙들이 전부 우회됩니다.
- DB 테이블들은 **RLS로 잠겨 있어서** anon 키로 직접 읽으면 빈 결과가 나옵니다. 이건 의도된 동작입니다.
- 응답이 화면 단위로 조립돼 나옵니다 (예: 코스 피드에 `like_count`, `is_liked`, `owner_nickname`이 이미 포함) — 앱에서 조인할 필요 없음.

## 2. 인증 흐름

```ts
// 1) Supabase SDK로 로그인 (여기까지만 Supabase 직접)
const { data } = await supabase.auth.signInWithPassword({ email, password });

// 2) 이후 모든 API 요청에 access_token을 Bearer로
const { data: { session } } = await supabase.auth.getSession();
fetch(`${API_BASE}/api/me/profile`, {
  headers: { Authorization: `Bearer ${session.access_token}` },
});
```

- **모든 엔드포인트가 인증 필수**입니다. 토큰이 없거나 만료되면 `401`.
- **토큰 갱신**: Supabase SDK가 자동 갱신합니다. 요청 직전에 `getSession()`으로 꺼내 쓰면 SDK가 만료 시 refresh를 처리해줍니다 (수동 관리 불필요). `401`을 받으면 `supabase.auth.refreshSession()` 후 1회 재시도 → 그래도 401이면 로그인 화면으로.
- 공용 fetch 래퍼 하나 만들어서 헤더 주입 + 401 재시도 + 에러 규약(§5) 처리를 한곳에 두는 걸 권장합니다.

## 3. 개발 환경

백엔드 로컬 실행은 [README](../README.md#로컬-실행) 참고 (`uvicorn app.main:app --reload`, 포트 8000).

**Expo에서 로컬 서버 주소 주의:**

| 실행 환경 | API_BASE |
|---|---|
| iOS 시뮬레이터 | `http://localhost:8000` |
| Android 에뮬레이터 | `http://10.0.2.2:8000` |
| **실기기 (Expo Go)** | `http://<맥의 LAN IP>:8000` (예: `http://192.168.0.15:8000`) — 맥에서 `ipconfig getifaddr en0`로 확인, 같은 와이파이여야 함 |

`app.config.ts`의 `extra`나 환경변수로 API_BASE를 분리해두세요.

## 4. 화면별 API 매핑

경로는 전부 `/api` 프리픽스 뒤 기준입니다. 응답 필드는 대표적인 것만 — 전체는 Swagger.

### 홈

| 데이터 | 메서드/경로 | 주요 응답 필드 |
|---|---|---|
| 주간 통계 (이번 주 Nkm) | `GET /me/stats` | `week.total_distance_km`, `week.run_count`, `week.delta_distance_km` (지난주 대비), `month`, `all_time`, `records`(PB 4종, 아래 참고) |
| 날씨 + 러닝지수 | `GET /weather?lat&lng` | `temp_c`, `feels_like_c`, `condition`(한글), `pm25/pm10.{value,grade}`, `running_index.{score,label,comment,personalized}` — pm은 부분 장애 시 null 가능. **`personalized: true`면 comment가 내 weather 설정 기준**(예: "설정하신 미세먼지 기준(PM10 50)을 넘었어요"). score/label은 항상 공용 기준 |
| AI 코스 생성 | `POST /routes/generate` | body: `start{lat,lng}`, `target_distance_km?`, `terrain?`, `scenic?`, `avoid_hills?`, `prefer_loop?`, `surface?`, `pitstop_keyword?`(≤50자), `notes?`(≤500자) → `summary`(생성자 언어), `waypoints[]`(이름·설명 생성자 언어), `polyline[]`, `total_distance_km`(소수 1자리), `estimated_duration_min`(정수 분), `search_radius_km`, `radius_expanded`. **free는 주 3회, 초과 시 429** (§5). 우선순위·동적 반경은 표 아래 참고 |
| 남은 생성 횟수 표시 | `GET /me/quota` | `tier`, `ai_generation.{used,limit,remaining,reset_at,unlimited}` |
| **AI 오디오 코치 (프리미엄)** | `POST /routes/{id}/coach-script` | `{route_id, cues[], from_cache, created_at}` — 내 코스만(404), free는 **403 `premium_required`**(§5). route당 1회 생성 후 캐시(`from_cache: true`), AI 생성 쿼터 미차감. 스키마·재생 규칙은 표 아래 참고 |
| 저장한 코스 | `GET /routes/bookmarked?limit&offset` | `PublicRouteResponse[]` (아래 피드와 동일 shape) |
| 코스 북마크 토글 | `POST/DELETE /routes/{id}/bookmark` | 204, 멱등 (더블탭 안전) |

> **코스 생성 거리 상한**: `target_distance_km` 최대 **32.2** (초과 422). 서버는 단위 무관하게 **km만 받는** 안전망이고, UI 상한은 단위 모드별로 프론트가 관리 — **km 모드 30km / 마일 모드 20mi(=32.19km)**.
>
> **코스 생성 우선순위 — body > 내 설정 > 서버 기본값**: `target_distance_km`와 선호 5종(`terrain`/`scenic`/`avoid_hills`/`prefer_loop`/`surface`)은 body에서 생략하면 내 `settings.ai_course` 값이 자동 적용됩니다 (`target_distance_km`는 `default_distance_km`로 폴백 — **이제 생략 가능**). body에 보낸 필드는 그 요청에 한해 설정을 덮어쓰므로, 화면 슬라이더 값은 항상 body로 보내면 됩니다. `false`도 명시값으로 취급되어 설정을 덮어씁니다.
>
> **오디오 코치 cues 스키마 (프론트 TTS 재생 규칙)**:
>
> ```jsonc
> "cues": [
>   { "trigger": "start",       "at": null, "text": "오늘은 서울숲을 도는 5킬로미터 코스예요." },
>   { "trigger": "distance_km", "at": 1.0,  "text": "1킬로미터 지났어요." },   // GPS 누적거리 도달 시
>   { "trigger": "waypoint",    "at": 2,    "text": "곧 은행나무길이에요…" },   // waypoints[2] 좌표 ~50m 근접 시
>   { "trigger": "finish",      "at": null, "text": "완주했어요!" }
> ]
> ```
>
> `distance_km`는 GPS 누적거리로, `waypoint`는 해당 인덱스 좌표 **~50m 근접 시** 재생하세요. 멘트는 TTS 낭독형 한국어(숫자 한글 표기)로 옵니다. **실시간 수치 낭독(거리/페이스/칼로리 — 설정의 안내 항목)과 날씨 멘트는 프론트 로컬 계산 몫**입니다 — 날씨는 러닝 시작 직전 `GET /weather`의 `running_index.comment`(개인화 반영됨)를 읽으면 됩니다. `voice`/`rate`는 `settings.audio_coach` 값을 TTS 엔진에 적용.
>
> **AI 생성 텍스트는 생성자의 언어 설정(`settings.lang`)을 따릅니다** (기본 `ko`). 코스 생성의 `summary`·경유지 이름/설명, 오디오 코치 멘트, 월간 인사이트 coaching/plan이 모두 유저의 `lang`(`ko`/`en`)으로 나옵니다. 언어를 바꾸려면 `PATCH /me/settings {"lang":"en"}` 후 생성하세요. **주의**: 오디오 코치 스크립트는 코스(route)당 1회 생성 후 캐시되므로 **최초 생성 시점 생성자의 언어로 고정**됩니다(이후 언어를 바꿔도 그 코스의 스크립트는 안 바뀜). 월간 인사이트는 본인 전용이라 본인 `lang`을 따릅니다.
>
> **동적 탐색 반경**: 출발지 주변이 좁아 코스 생성이 어려우면 서버가 출발지는 고정한 채 탐색 반경을 자동으로 넓혀가며 재시도합니다(목표 거리 비례 시작, 최대 8km·4시도). 응답의 `search_radius_km`는 사용된 반경, **`radius_expanded: true`면 "주변에 코스가 마땅치 않아 반경을 N km까지 넓혀 찾았어요" 안내를 띄우기 좋습니다**. 반경을 다 넓혀도 목표에 못 미치면 가장 근접한 코스를 그대로 반환하니 `total_distance_km`와 요청 목표를 비교해 "목표보다 짧은 코스예요"를 표시하세요. 정상 생성은 **보통 3~6초**이나, 반경 재시도가 도는 예외 케이스는 더 걸릴 수 있으니 **`radius_expanded: true`일 때 "주변을 더 넓게 찾는 중" 안내**를 띄우고 클라이언트 타임아웃은 여유 있게(예: 60초) 두세요. 쿼터는 재시도 횟수와 무관하게 요청당 1회만 차감됩니다.

### 기록 탭

| 데이터 | 메서드/경로 | 주요 응답 필드 |
|---|---|---|
| 월 선택 통계 + 캘린더 | `GET /me/stats/monthly?year&month` | `stats`(합계·평균페이스·전월 대비 delta), `days[{date,distance_km,run_count}]` — 뛴 날만 옴, 캘린더 점 찍기용 (KST 기준). **무료** |
| **AI 월간 인사이트 (프리미엄)** | `GET /me/insights/monthly?year&month` | 프리미엄 월간 리포트 화면 전체 데이터. free는 **403 `premium_required`**(§5), month 1~12 외 422. 스키마는 표 아래 참고 |
| 러닝 기록 저장 | `POST /runs` | body: `distance_km`(0<d≤350), `duration_sec`(≤7일), `route_id?`, `avg_pace_sec_per_km?`, **`title?`**(≤60자), **`visibility?`**(public/followers/private, 기본 public), `notes?`(≤2000자), **`gps_track?`** (아래 규약). **평균 페이스가 1'30"/km보다 빠르면(물리적 불가) 422** — 자율신고 부정 방어. 응답에 `new_records[]` — **비어있지 않으면 "새로운 기록 경신!" 축하 모달** (`{type, previous, current, improvement_pct}`) — 첫 run은 `[]`. **저장 화면(시안) 필드 매핑·visibility·페이스 비교는 아래 상세 참고** |

> **저장 화면 (시안) — 필드 매핑 · 공개 범위 · 완료 화면 데이터**
> - **제목** `title` (optional, ≤60자): 시안 "야간 러닝". **프론트가 시간대 기반 기본값을 생성해 보냄** (서버는 저장만). 미전송이면 null.
> - **메모** = **`notes`** (기존 필드 그대로, ≤2000자): **개인 메모 — 본인만 봄.** 활동 피드·크루 피드·공개 프로필 어디에도 절대 노출 안 됨. 시안 "메모"는 이 필드에 매핑.
> - **공개 범위** `visibility` 3단 (기본 **`public`** — 시안 저장 화면 기본이 "전체 공개"):
>   - `public`(전체): 누구나 — **공개 프로필 `GET /users/{id}/runs`에 노출**, 활동/크루 피드, 아무나 kudos 가능.
>   - `followers`(팔로워만): 나를 팔로우한 사람 + **같은 크루원**에게 노출 (활동 피드·크루 피드·kudos 가능). 비팔로워·비크루원은 공개 프로필에서 못 봄.
>   - `private`(비공개): **본인만.** 모든 피드·프로필·kudos에서 제외.
>   - **기존 run(이 기능 이전 저장분)은 전부 `followers`로 백필** — 당시 노출(팔로워/크루)을 그대로 보존, 공개 프로필엔 안 뜸. 새 run만 기본 public.
> - **완료 화면 비교 rows** (`POST /runs` 응답에만): `recent_avg_pace_sec_per_km`(최근 30일 평균 페이스, **이번 run 제외**) + `pace_delta_sec`(이번 페이스 − 최근 평균, **음수 = "평소보다 N초 빨라요"**). 히스토리 없으면(첫 run 등) 둘 다 null → 비교 UI 숨김. **주간 누적은 기존 `GET /me/stats`의 `week`로 표시.**
> - 응답에도 `title`·`visibility` 포함(저장 확인용).
| 기록 목록 | `GET /runs?limit&route_id?&before?` | `RunResponse[]` 최신순 — GPS run은 `splits[]`·`has_track`·`verification` 포함. **`kudos_count`**(♥)·**`comment_count`**(💬) 배치 집계(N+1 없음). 본인 목록이라 `my_kudos`는 없음(본인 kudos 불가). **커서 페이지네이션**: 다음 페이지는 `before=<마지막 run의 ran_at 그대로>`(ISO+타임존, naive는 422) — 응답이 `limit`보다 짧으면 끝 |
| 기록 단건 | `GET /runs/{run_id}` | 본인 것만, 아니면 404. 목록과 동일하게 **`kudos_count`** 포함 |
| **러닝 경로 (지도)** | `GET /runs/{run_id}/track` | `{polyline[{lat,lng}], server_distance_km, elev_gain_m, point_count_raw/kept}` — 활동 상세 지도용. `polyline`은 코스의 `polyline`과 동일 포맷(같은 렌더 코드 사용 가능). **접근: 본인 + run 공개범위 내 타인**(public 누구나 / followers는 팔로워·같은 크루 / private 본인만 — kudos·댓글과 동일 게이트). 범위 밖·트랙 없는 run은 404 (`has_track`으로 사전 판단 — 타인 run 카드도 has_track 보고 지도 진입 결정) |
| 2탭 피드백 | `PATCH /runs/{run_id}/feedback` | body: `liked`(bool), `tags[]` (허용 태그는 Swagger의 FeedbackTag) |

> **AI 월간 인사이트 응답** (`GET /me/insights/monthly`):
>
> ```jsonc
> {
>   "year": 2026, "month": 6,
>   "stats": { /* PeriodStats — 합계·평균페이스·전월 delta */ },
>   "weeks": [ { "index": 1, "distance_km": 8.2, "run_count": 2, "avg_pace_sec_per_km": 326 } ],  // KST 월요일 주차, 빈 주 포함 (차트용)
>   "records": [ { "type": "best_pace", "value": 286, "ran_at": "…", "distance_km": 5.2,
>                  "all_time_best": true } ],   // 이번 달 개인 기록 — all_time_best=true가 시안의 up 화살표
>   "pattern": { "weekday_counts": [1,3,1,2,1,3,1],          // 월~일
>                "time_of_day": "morning", "time_of_day_pct": 58,  // dawn|morning|day|evening|night
>                "longest_streak_days": 5 },
>   "ai": { "coaching": "…(3~5문장)", "generated_at": "…", "from_cache": true,
>           "plan": [ { "slot": "goal", "title": "7월 목표", "body": "…" },
>                     { "slot": "focus", "title": "…", "body": "…" },
>                     { "slot": "challenge", "title": "…", "body": "…" } ] }  // slot → 아이콘: goal=target, focus=flame, challenge=trending
> }
> ```
>
> 수치 블록은 매 요청 최신 계산, `ai`만 캐시(지난달 영구, 이번 달은 러닝할 때만 갱신). **해당 월 run 0회면 `ai: null`** — 빈 상태 UI로 처리. **시안 중 심박 존·평균/최대 심박·누적 고도·칼로리·지형 분석·월 목표 링은 백엔드 데이터가 없어 미제공** — 헬스킷 등 로컬 데이터로 채우거나 숨기고, 월 목표는 목표 설정 기능 후속 시 추가 예정.

> **GPS 트랙 규약 (`POST /runs`의 `gps_track`)** — **러닝 종료 시 일괄 전송** (실시간 스트리밍 아님):
>
> ```jsonc
> "gps_track": [ { "lat": 37.544512, "lng": 127.037431,
>                  "t": 1783300000000,   // epoch ms
>                  "acc": 8.2,           // horizontalAccuracy(m) — 필터 정확도를 위해 강력 권장
>                  "alt": 34.6 } ]       // altitude(m) — 고도 차트용, 없으면 elev null
> ```
>
> - 샘플링: **3~5초 또는 10m 이동 간격** (iOS `distanceFilter=10`). **상한 5,000pt** (≈4초 간격 5.5시간) 초과 시 422.
> - 서버가 노이즈 필터(accuracy>30m, 순간이동, 일시정지 gap) 후 거리·km 스플릿·고도를 계산합니다. `gps_track` 없는 저장(수동 입력)은 기존과 완전히 동일하게 동작.
> - **`verification` 의미** (3종 + `is_flagged`): `unverified`(GPS 없음/판정 보류 — 기존 run 전부), `verified`(검증 통과), `suspect`(자전거/차량 의심 — 기록은 남지만 **PB·크루 랭킹·챌린지 집계에서 제외**, `is_flagged=true`). **신고 거리가 서버 계산과 ±10% 초과 괴리면** `verified` + `is_flagged=true`로 오고 **`distance_km`가 서버 값으로 대체**되며 원본은 `distance_km_reported`에 보존 — `is_flagged=true`면 "서버가 기록을 조정/표시했어요" UI 권장.
> - `splits[]`: `{km, sec, elev_gain_m, partial}` — 시안 "페이스 & 고도 분석" 차트에 그대로 바인딩 (partial=마지막 부분 킬로).

> **개인 최고 기록 (PB)** — `GET /me/stats`의 `records` 블록 (프로필 헤더 "최고 페이스", 기록 화면용):
>
> ⚠️ **PB·경신 모달은 GPS 검증(verified) run만 자격** — 트랙 없는 수동 기록·부정 의심 run은 집계에서 제외됩니다(오염 방지). **verified run이 하나도 없는 유저는 `records` 각 항목이 null** — 프론트는 null 처리(기존 계약)만 하면 됨. 주/월/전체 `total_distance_km` 등 개인 통계는 수동 기록도 계속 포함.
>
> ```jsonc
> "records": {                     // 각 항목은 자격 run이 없으면 null
>   "best_pace":        { "value": 286,  "run_id": "…", "ran_at": "…", "distance_km": 5.2 },  // sec/km, 1km 이상 run만
>   "best_5k":          { "value": 1478, "run_id": "…", "ran_at": "…", "distance_km": 6.1 },  // sec, 5km 이상 run의 평균 페이스 환산
>   "longest_distance": { "value": 10.0, "run_id": "…", "ran_at": "…", "distance_km": 10.0 }, // km
>   "longest_duration": { "value": 3165, "run_id": "…", "ran_at": "…", "distance_km": 8.4 }   // sec
> }
> ```
>
> `value` 단위는 종류별(주석 참고), `ran_at`·`distance_km`는 "5월 28일 · 6.1km" 같은 서브 표기용. 동률이면 먼저 달성한 run이 유지됩니다. PB는 저장 테이블 없이 조회 시 계산이라 run 삭제·수정에도 항상 정확합니다.
>
> **배지 노트**: 별도 배지 시스템은 없습니다. 시안의 "디지털 배지"(챌린지 완료 리워드)는 완료된 챌린지 데이터(`challenge_completed` 알림 + 챌린지 목록)로 그리면 됩니다 — 배지 컬렉션 화면이 시안에 추가되면 백엔드 후속 예정.

### 커뮤니티 / 소셜

| 데이터 | 메서드/경로 | 주요 응답 필드 |
|---|---|---|
| **팔로잉 피드 (코스, 홈 v1)** | `GET /feed?limit&offset` | `PublicRouteResponse[]`: `summary`, `owner_nickname`, `like_count`, `comment_count`, `copy_count`, `is_liked`, `polyline` — 팔로우 0명이면 `[]`. **홈 피드 v1은 이 코스 피드로 연결** |
| **활동 피드 (run, 홈 v2)** | `GET /feed/activities?limit&offset` | 팔로우한 유저 **+ 내** run, `ran_at` 최신순: 크루 러닝 피드와 같은 필드 + `title`, `is_mine`, `kudos_count`, `my_kudos`, **`comment_count`**. **visibility 적용**: 팔로우 대상의 `private` run은 제외(public·followers만), 내 run은 전부. **`is_mine=true`인 내 카드는 kudos 버튼 비활성** (본인 kudos는 400). (`visibility`는 피드에선 null) |
| run kudos | `POST/DELETE /runs/{run_id}/kudos`, `GET /runs/{run_id}/kudos` | 204 멱등(더블탭 안전), 본인 run 400, run 주인에게 `run_kudoed` 알림. GET은 누른 사람 목록 `[{user_id, nickname, avatar_url, created_at}]`. **가시성 게이트**: 내가 볼 수 있는 run(public, 또는 팔로우/크루의 followers)에만 kudos·목록 조회 가능 — 그 외 run_id는 **404**. **코스 좋아요(route like)와 별개** |
| **run 댓글** | `GET /runs/{run_id}/comments?limit&offset`, `POST`, `DELETE /runs/{run_id}/comments/{comment_id}` | route 댓글과 동형. GET **최신순**(닉네임 포함, 페이지네이션) `[{id, run_id, user_id, nickname, content, created_at}]`. POST body `{content}`(1~500자, 초과/빈값 422) → run 주인에게 `run_commented` 알림(본인 댓글 미발송). DELETE는 **작성자 또는 run 주인**(그 외 403). **가시성 게이트 동일**: 안 보이는 run은 404. 카드 수는 위 피드/목록의 `comment_count` |
| 전체 공개 코스 | `GET /routes/public?sort=newest\|popular&limit` | 동일 shape |
| 근처 코스 | `GET /routes/nearby?lat&lng&radius_km` | 동일 shape. `radius_km`은 최대 50으로 클램프, `limit` 1~100 클램프 (음수·거대값도 안전) |
| 코스 검색 | `GET /routes/search?q` | 동일 shape. `limit` 1~100 클램프 |
| **장소 검색 (경유지 후보)** | `GET /places?keyword&lat&lng&radius_m&limit` | **⚠️ 인증 필수로 전환됨 (프론트 필독)** — 토큰 없이 호출하면 **401**. `keyword`(1~50자), 좌표(한국 bbox), `radius_m`(1~20000), `limit`(1~15) 범위 밖은 422. 경유지 선택 UI에서 쓰면 반드시 Authorization 헤더 포함 |
| 좋아요 토글 | `POST/DELETE /routes/{id}/like` | 204, 멱등 |
| 댓글 | `GET/POST /routes/{id}/comments`, `DELETE /routes/{id}/comments/{comment_id}` | `content` 1~500자 |
| 이 코스 달리기(복사) | `POST /routes/{id}/copy` | 내 코스로 복사본 생성 |
| 팔로우 토글 | `POST/DELETE /users/{user_id}/follow` | 204, 멱등. 자기 자신 400 |
| 공개 프로필 | `GET /users/{user_id}/profile` | `nickname`, `bio`, `tier`, `follower_count`, `following_count`, `is_following`, `is_followed_by`(맞팔 표시), **`public_run_count`**(그 유저가 전체 공개로 게시한 러닝 수 — 시안 "게시한 러닝 · 공개 N") |
| **공개 프로필 러닝** | `GET /users/{user_id}/runs?limit&offset` | 그 유저의 러닝 카드 — **활동 피드와 동일 shape**(`run_id, user_id, nickname, avatar_url, ran_at, title, distance_km, duration_sec, avg_pace_sec_per_km, route_id, route_summary, is_mine, kudos_count, my_kudos, comment_count`). **조회자 가시성 필터**: 본인=전부 / 타인은 `public` 항상 + `followers`는 내가 그 유저를 팔로우할 때 + `private` 제외. **본인 프로필에서만 각 카드에 `visibility` 채워짐**(뱃지용), 타인 프로필은 `visibility=null`. 좋아요=`kudos_count`, 댓글=`comment_count`(💬) |
| 팔로워/팔로잉 목록 | `GET /users/{user_id}/followers` / `/following` | `[{user_id, nickname, avatar_url, followed_at, is_following}]` — 항목별 팔로우 버튼용 |
| **크루 둘러보기** | `GET /crews?sido&sigungu&lat&lng&include_full&limit` | 공개 크루 + 내 비공개. `member_count`·`owner_nickname`·`sido`·`sigungu`·`lat`·`lng`·`tags`·`distance_km` 포함. **파라미터 없으면 기존 동작**(최신순, distance_km null). 당근식 사용법은 표 아래 참고 |
| 크루 검색/상세 | `GET /crews/search?q`, `/crews/mine`, `/crews/{id}` | 검색은 name/area/description 부분일치 |
| 크루 생성/수정/삭제 | `POST /crews`, `PATCH/DELETE /crews/{id}` | 수정·삭제는 크루장만. **생성은 무료 플랜 1개 한도** (내가 owner인 크루 기준) — 초과 시 **403 `premium_required`** `{error, message, feature: "crew_create", limit: 1}` → 업셀 화면. 프리미엄 무제한. 크루를 삭제하거나 소유권을 위임하면 슬롯이 다시 빔. 필드 길이: `name`≤50, `description`≤500, `area`≤50, `sport`≤30, `active_days`≤7개, `max_members`≤100000. **둘러보기 필드**(전부 optional): `sido`(17개 광역 표준명)·`sigungu`(≤30자)·`lat`/`lng`(한국 bbox)·`tags`(서버 어휘, ≤5개) — 아래 참고 |

> **크루 둘러보기 (당근식) — 프론트 규약 필독**:
> - **위치·행정구역·역지오코딩은 전부 프론트가 처리** — 서버는 검증·필터·정렬만 한다. GPS 좌표 → "성동구" 역지오코딩은 **프론트가 Kakao Local SDK(coord2regioncode)로 클라이언트 측 수행**하고, 크루 생성/수정 시 `lat`/`lng`/`sido`/`sigungu`를 body로 보낸다. (서버는 지오코딩 프록시를 제공하지 않음.)
> - **`sido` 표준 명칭 17개** (프론트 정적 목록·서버 Literal·DB CHECK가 이 문자열로 정확히 일치해야 필터 동작): `서울특별시`·`부산광역시`·`대구광역시`·`인천광역시`·`광주광역시`·`대전광역시`·`울산광역시`·`세종특별자치시`·`경기도`·`강원특별자치도`·`충청북도`·`충청남도`·`전북특별자치도`·`전라남도`·`경상북도`·`경상남도`·`제주특별자치도`. **`sigungu`는 자유 문자열**(예: `성동구`, `수원시`) — 프론트가 시군구 목록을 정적 보유해 표준 명칭으로 보낸다.
> - **`tags` 서버 정의 어휘 13종** (자유입력 아님 — 이 목록에서만, 저장 ≤5개·카드엔 2개): 시간대 `새벽`·`아침`·`저녁`·`야간`·`주말` / 지형 `평지`·`트레일`·`언덕` / 분위기 `입문환영`·`기록도전`·`친목`·`여성전용`·`페이스그룹`. 목록 밖 값은 422.
> - **조회**: `lat`+`lng`를 **둘 다** 보내면 각 크루까지 `distance_km`(1자리, "0.4km") 계산 + **거리 오름차순 정렬**(좌표 없는 크루는 distance_km=null·맨 뒤). `sido`/`sigungu`로 행정구역 필터. `include_full=false`(기본)면 정원 찬 크루 제외. `limit` 1~100(기본 50).
| **가입** | `POST /crews/{id}/join` | **상태 코드로 분기**: `200`=즉시 가입(`CrewResponse`, open 크루) / `202`=신청 접수(`JoinRequestResponse{status:"pending"}`, 승인제 크루). `409` = 이미 멤버 또는 `already_requested`(중복 신청). **이미 멤버면 `join_policy`와 무관하게 409가 최우선** — 승인 직후 등 어떤 타이밍에도 멤버에게 202가 가거나 pending이 생기지 않음(서버가 레이스까지 방어). 크루의 `join_policy` 필드(`open`/`approval`)로 버튼 라벨을 미리 정할 수 있음 ("가입하기" vs "가입 신청") |
| **내 신청 전체 목록** | `GET /me/join-requests?limit&offset` | `[{crew_id, crew_name, status, created_at, decided_at}]` 최신순, 기본 limit 50. **모든 크루의 신청을 한 번에** — 둘러보기 화면 "신청됨" 뱃지용. `status`는 pending/approved/rejected 전부 포함이므로 뱃지는 `pending`만 필터해서 사용 |
| 내 신청 상태 (크루별) | `GET /crews/{id}/join-requests/me` | `{status: pending\|approved\|rejected}` — 없으면 404. **거절은 알림이 안 오므로** 이 값으로 버튼 상태 결정: `pending`→"신청됨(취소)", `rejected`→"가입 신청"(재신청 가능), 404→"가입 신청" |
| 신청 취소 | `DELETE /crews/{id}/join-requests/me` | 204 멱등 (없어도 204) |
| 신청 목록 (크루장) | `GET /crews/{id}/join-requests?limit&offset` | `[{id, user_id, nickname, created_at}]` pending만 최신순. 비크루장 403 |
| 신청 승인/거절 (크루장) | `POST /crews/{id}/join-requests/{rid}/approve` / `/reject` | 204. 승인 → 신청자에게 `join_approved` 알림 + 멤버 추가. 승인 시 정원 초과면 409(신청은 pending 유지). 이미 결정된 신청은 404 |
| 탈퇴/강퇴/양도 | `DELETE /crews/{id}/leave`, `DELETE /crews/{id}/members/{target_id}`, `PATCH /crews/{id}/transfer` | |
| **초대 코드 (크루장)** | `GET /crews/{id}/invite` (미발급 404 → POST로 발급), `POST /crews/{id}/invite` (생성/**재생성** — 이전 코드 즉시 무효, 유출 대응) | `{code}` — 8자 대문자+숫자 (I/O/0/1 없음). 카톡 등으로 공유 |
| 코드 미리보기 | **`POST /crews/preview-by-code`** `{code}` (권장) · `GET /crews/preview-by-code?code=` (레거시) | 가입 확정 전 "어느 크루인지" 확인 — `CrewResponse` 반환. **비공개 크루도 조회됨** (코드 = 초대장). 잘못된 코드 404. **⚠️ POST 사용 권장** — GET은 코드가 URL 쿼리스트링 → 서버 access log에 평문으로 남음. 두 경로 동작·응답 동일하니 신규/변경은 POST(body)로 붙일 것 |
| **코드로 가입** | `POST /crews/join-by-code` body `{code}` | 200 `CrewResponse` (바로 크루 화면 이동). **join_policy·비공개 무관 즉시 가입** — 크루 생성 화면의 "비공개: 초대 링크로만 가입 가능해요"가 이 경로. 대소문자·공백은 서버가 정규화. 이미 멤버/정원 409, 잘못된 코드 404. 승인제에 신청해뒀던 pending은 자동 정리 |
| 멤버/랭킹 | `GET /crews/{id}/members`, `/crews/{id}/ranking` | 랭킹: 이번 주 KST 거리순, `me` 플래그. **visibility 무관** — 랭킹·챌린지 누적 거리는 `private` run도 포함(크루=활동 공유 원칙 + 거리 은닉 어뷰징 방지). visibility는 run 카드 노출만 제어, 집계 거리엔 영향 없음. **단 GPS 검증(verified) run만 집계** — 트랙 없는 수동 기록은 랭킹·챌린지 거리에 안 잡힘(UI에 "GPS 기록만 집계" 안내 권장) |
| **크루 러닝 피드** | `GET /crews/{id}/runs?limit&offset` | 크루원들의 최근 run, `ran_at` 최신순: `[{run_id, user_id, nickname, avatar_url, ran_at, title, distance_km, duration_sec, avg_pace_sec_per_km, route_id, route_summary, comment_count}]`. 크루원만(403). **visibility 적용**: `private`만 제외 — `public`·`followers`는 크루원에게 노출(크루=활동 공유 관계). 개인 메모/피드백은 절대 미포함, `route_summary`는 공개 코스만(비공개면 null). 탈퇴 멤버의 run은 자동 제외 |
| 챌린지 | `GET /crews/{id}/challenges/current`, `POST /crews/{id}/challenges` | `achieved_km`, `progress_pct`, `is_completed` 실시간 계산. 생성 시 `starts_at`/`ends_at`은 **ISO 8601 + 타임존 필수** (아래 노트) |
| **공지 목록/상세** | `GET /crews/{id}/announcements?limit&offset`, `GET .../{announcement_id}` | `title`, `body`, `run_at`, `place_name/lat/lng`, `rsvp_open`, `rsvp{going,not_going,maybe}`, `my_rsvp`; 상세엔 `going_members[]` 명단 추가. 크루원만 조회 가능(403). 작성 시 `run_at`/`rsvp_closes_at`은 **ISO 8601 + 타임존 필수** |

> **⚠️ 날짜·시각 필드는 타임존 필수 (프론트 필독)**: 챌린지 `starts_at`/`ends_at`, 공지 `run_at`/`rsvp_closes_at`은 **반드시 타임존 오프셋을 포함한 ISO 8601**로 보내세요 — `2026-07-07T20:00:00+09:00`(KST) 또는 `...Z`(UTC). **타임존 없는 `2026-07-07T20:00:00`은 422**로 거부됩니다 (서버가 UTC로 오해석하면 KST 의도가 9시간 밀리기 때문). 에러 메시지에 "timezone" 안내가 포함됩니다.
| 공지 작성/수정/삭제 | `POST/PATCH/DELETE /crews/{id}/announcements...` | 크루장만. 작성 시 크루원 전체 알림, 수정은 알림 없음 |
| **참석 투표** | `PUT /crews/{id}/announcements/{aid}/rsvp` | body: `{"status": "going"\|"not_going"\|"maybe"}` → 204. 재투표=덮어쓰기 |
| 알림 | `GET /notifications`, `GET /notifications/unread-count`, `PATCH /notifications/read-all`, `PATCH /notifications/{id}/read`, **`DELETE /notifications/{id}`**(스와이프 삭제 — 본인 것만, 없음/남의 것 404, 성공 204), **`DELETE /notifications`**(모두 지우기 — 멱등, 0건이어도 204) | 각 항목: `type`·`actor_nickname`·`target_id`·`target_type`·**`payload`**(딥링크 보조 jsonb, 없으면 null). **탭 시 목적지·사용 필드는 아래 "딥링크 라우팅 표"를 그대로 따를 것** |

> **알림 딥링크 라우팅 표** — 알림 탭 시 이 표대로 화면을 특정한다. **`target_type`으로 분기**하고 표의 "사용 필드"로 id를 얻는다. (대부분 `target_id`면 충분, `crew_announcement`만 `payload.crew_id` 필요.)
>
> | type | target_type | 목적지 화면 | 사용 필드 |
> |---|---|---|---|
> | `route_liked` / `route_commented` | route | 코스 상세 | `target_id`(=route_id) |
> | `run_kudoed` / `run_commented` | run | 내 run 상세 (수신자=run 주인) | `target_id`(=run_id) → `GET /runs/{id}` |
> | `crew_joined` / `join_approved` | crew | 크루 상세 | `target_id`(=crew_id) |
> | `join_requested` | crew | 크루 **신청 관리** 화면 | `target_id`(=crew_id) |
> | `challenge_completed` | crew | 크루 챌린지 화면 | `target_id`(=crew_id) + `payload.challenge_id`(특정 챌린지, 2026-07-08~ 신규 발송분) |
> | `user_followed` | user | 유저 공개 프로필 | `target_id`(=follower_id) |
> | **`crew_announcement`** | announcement | 크루 공지 (`/crews/{crew_id}/…`) | **`payload.crew_id`** (target_id는 공지id) + `target_id`(=공지id) |
>
> **주의**: `crew_announcement`는 target_id가 공지id라 **crew_id는 `payload`에만** 있다. `payload.crew_id`가 없으면(2026-07-08 이전 발송분) 크루로 못 가니 폴백으로 무시하거나 크루 목록으로 보낸다. 그 외 type은 target_id만으로 라우팅 가능 — payload 불필요.

### 프로필

| 데이터 | 메서드/경로 | 주요 응답 필드 |
|---|---|---|
| 내 정보 | `GET /me` (auth 확인), `GET /me/profile` | `nickname`, `avatar_url`, `bio`, `tier` + **신체 정보 4종** `birth_year`/`weight_kg`/`height_cm`/`gender` — **본인 조회에만 존재** (다른 유저가 보는 모든 응답에 절대 미포함). 체중은 칼로리 로컬 계산용 |
| 프로필 생성/수정 | `PATCH /me/profile` | `nickname`(2~20자, 중복 시 409) + 신체 정보 4종 optional — 보낸 것만 갱신. 범위: birth_year 1920~2026, weight 20~300, height 100~250, gender `female`\|`male`\|`undisclosed`(시안: 여성/남성/선택 안 함). `bio`≤500자, `avatar_url`≤500자. 범위·길이 밖 422. **tier는 보내도 무시됨** (관리자/IAP 전용) |
| **아바타 업로드** | `POST /me/avatar/upload-url` | **3단계 흐름**: ① 이 엔드포인트 호출 → `{upload_url, public_url, max_bytes, allowed_types}` ② 이미지 바이트를 `upload_url`에 **PUT** (Content-Type 필수 — jpeg/png/webp만, 5MB 상한은 Storage가 거부) ③ `public_url`을 `PATCH /me/profile`의 `avatar_url`로 저장 — **CDN 캐시 무효화를 위해 `?v=타임스탬프`를 붙여서**. 경로는 유저당 고정이라 재업로드가 자동 덮어쓰기 (옛 파일 잔여 없음) |
| **회원 탈퇴 (계정 삭제)** | `DELETE /me` | **204** — 계정·모든 데이터 즉시 삭제(복구 불가, 백업에만 최대 90일 잔존). **프론트 소비 규칙**: ① 호출 전 2단 confirm 모달 필수(로그아웃 모달 패턴, "모든 기록이 영구 삭제됩니다" 명시) ② **409 `{error:"crew_owner", crew_ids, message}`** → "운영 중인 크루" 안내 후 해당 크루의 위임(`PATCH /crews/{id}/transfer`)/삭제 화면으로 유도 — 본인뿐인 크루는 자동 삭제되므로 409 대상 아님 ③ **403 `{error:"demo_account"}`** → 데모 계정 안내 토스트 ④ 204 수신 시 로컬 세션·토큰 폐기 후 온보딩으로. 같은 이메일 재가입 가능(새 계정, 데이터 없음) |
| 누적 통계 | `GET /me/stats` | `all_time.{total_distance_km,run_count,avg_pace_sec_per_km}` — 프로필 헤더 "최고 페이스"는 같은 응답의 `records.best_pace.value`(sec/km) 사용 |
| 티어/쿼터 | `GET /me/quota` | premium이면 `ai_generation.unlimited=true`. IAP 구독이 만료된 유저는 **이 호출(또는 아무 프리미엄 게이트) 시점에 자동 강등**되어 free로 옴 |
| **구독 구매 검증** | `POST /iap/verify` | **프론트: StoreKit 2 구매 완료 직후 받은 `signedTransaction`(JWS)을 `{"jws": "..."}`로 전송** → 서버 검증 후 `{tier: "premium", product_id, expires_at, environment}`. 같은 거래 재전송은 멱등(복원/갱신에 안전), 다른 계정의 거래 재사용은 **409 `transaction_already_used`**. 유효하지 않으면 400(`invalid_transaction`/`transaction_expired`), 서버 미준비 상태는 **503 `iap_not_configured`**(출시 전 현재 상태 — UI에서 결제 버튼 숨김) |
| Apple 서버 알림 (웹훅) | `POST /iap/notifications` | Apple 전용(App Store Server Notifications V2) — 프론트 호출 없음. 현재 수신+보관만, 갱신/환불 처리는 출시기 (`docs/IAP_LAUNCH_CHECKLIST.md`) |
| **설정 조회** | `GET /me/settings` | 항상 **기본값이 머지된 완전한 객체** — null 체크 없이 바로 바인딩 가능. 프로필 미생성 유저도 기본값 반환 |
| **설정 저장** | `PATCH /me/settings` | **보낸 키만 deep merge** (예: `{"run":{"haptics":false}}`는 haptics만 변경), 멱등, 응답은 머지 후 전체 객체. 화이트리스트 밖 키/범위 밖 값 → **422** (저장 안 됨). 프로필 미생성 404 |

**설정 기본값 표** (허용 키/값 전체):

```jsonc
{
  "run":       { "auto_pause": true, "voice_cue": true, "haptics": true, "keep_screen_on": false },
  "units":     "km",          // "km" | "mi"
  "theme":     "light",       // "light" | "dark"
  "lang":      "ko",          // "ko" | "en"
  "ai_course": { "terrain": "mixed",        // "flat" | "mixed" | "hill"
                 "default_distance_km": 5.0, // 1.0 ~ 32.2 (서버 안전망 — UI 상한은 단위 모드별)
                 "scenic": true, "avoid_hills": false, "prefer_loop": true,
                 "surface": "any" },         // "any" | "paved" | "trail"
  "weather":   { "avoid_dust": true, "dust_level_pm10": 80,   // 30 ~ 150
                 "avoid_heat": true, "heat_temp_c": 28,       // 20 ~ 38
                 "avoid_rain": false },
  "audio_coach": { "enabled": true,
                   "voice": "joy",              // "joy"(활기찬) | "david"(차분한)
                   "rate": 1.0,                 // 0.6 ~ 1.6 (TTS 말하기 속도)
                   "cue_interval_km": 1.0,      // 0.5 ~ 3.0 (안내 간격)
                   "announce_distance": true, "announce_pace": true,
                   "announce_calories": false } // 안내 항목 (프론트 로컬 낭독)
}
```

> **theme/lang 구현 힌트**: 로컬 캐시 + 서버 동기화 권장 — 첫 프레임(로그인 전·오프라인)은 AsyncStorage 캐시로 그리고, 로그인 후 `GET /me/settings` 값으로 갱신하세요.
>
> **ai_course/weather는 실제 파이프라인에 반영됩니다** (전 티어 공통, 무료 포함):
> - `ai_course` → `POST /routes/generate`가 body에 없는 필드의 기본값으로 사용 (우선순위: body > 설정 > 서버 기본값, §홈 표 참고).
> - `weather` → `GET /weather`의 `running_index.comment`가 내 기준(`avoid_dust`/`dust_level_pm10`, `avoid_heat`/`heat_temp_c`, `avoid_rain`)을 넘으면 개인화되고 `personalized: true`가 됩니다. 복수 기준 초과 시 미세먼지 > 더위 > 비 순으로 하나만 표시. `score`/`label`은 공용 기준 그대로.

## 5. 에러 규약

에러 바디는 `{"detail": ...}` — detail이 문자열이거나, 구조화된 경우 `{"error": "<코드>", "message": "<한글 안내>", ...}` 객체입니다.

| 코드 | 의미 | 프론트 처리 권장 |
|---|---|---|
| **401** | 토큰 없음/만료 | refresh 후 1회 재시도 → 실패 시 로그인 화면 |
| **403** | 권한 없음 (비크루원 조회, 크루장 아님 등) | 해당 UI 숨김/비활성이 원칙, 받으면 토스트. **`premium_required`**(구조화: `{error, message, feature}`) → 프리미엄 업셀 화면으로 이동. 한도형 게이트(크루 생성 등)는 `limit` 필드가 추가로 옴 — "무료는 N개까지" 안내에 사용 |
| **404** | 없거나 볼 수 없음 (비공개 코스, 남의 기록도 404) | "존재하지 않음" 처리 — 403과 구분해 존재 여부를 숨기는 의도 |
| **409** | 상태 충돌 | `nickname taken`(닉네임 중복) → 인라인 에러 표시. **`rsvp_closed`** → 투표 버튼 비활성 + "마감되었습니다" (사전에 `rsvp_open` 플래그로 버튼 상태 결정 가능). **`crew_owner`**(탈퇴 차단, `crew_ids` 포함) → 크루 위임/삭제 유도 (프로필 §"회원 탈퇴" 참조) |
| **429** | **AI 생성 쿼터 초과** | `detail.{limit,used,remaining,reset_at}` 제공 → "이번 주 3회를 모두 사용했어요, 월요일 리셋" + 프리미엄 업셀 화면. `reset_at`은 KST ISO |
| **502** | 외부 서비스 장애 (OpenAI/지도/날씨) | "잠시 후 다시 시도" + 재시도 버튼. 코스 생성 실패는 구조화 바디 **`route_generation_failed`** — 서버가 이미 반경 확장까지 재시도한 뒤이므로 즉시 자동 재시도하지 말고 유저 액션(재시도 버튼)으로 |
| **503** | 날씨 설정 문제: `weather_not_configured` / **`weather_key_inactive`**(키 활성화 대기) | 날씨 위젯만 숨기거나 placeholder — 앱 전체 에러로 띄우지 말 것 |

멱등 엔드포인트(좋아요/북마크/팔로우/RSVP/언팔 등)는 더블탭·재시도에 안전하므로 **옵티미스틱 UI + 실패 시 롤백** 패턴을 써도 됩니다.

## 6. 페이지네이션 규약

목록 엔드포인트는 `?limit=20&offset=0` 쿼리를 받습니다 (기본 limit 20, 서버측 최대 100).

- 다음 페이지: `offset += limit`. 응답 길이가 `limit`보다 짧으면 마지막 페이지.
- 지원: `/feed`, `/routes/bookmarked`, `/users/{id}/followers·following`, `/crews/{id}/announcements`.
- 일부 목록(`/routes/public`, `/notifications` 등)은 `limit`만 받습니다 — offset을 보내면 무시되므로 Swagger에서 파라미터 확인.
- `GET /runs`는 offset 대신 **커서**(`before=<마지막 ran_at>`)를 받습니다 — 기록 목록 행 참조.
- 주의: 북마크 목록은 비공개 전환된 코스가 숨겨져 한 페이지가 `limit`보다 짧게 올 수 있습니다 — "짧으면 끝" 판정에 예외적으로 걸릴 수 있으니 빈 배열로 끝 판정하는 게 안전합니다.

## 7. 전체 레퍼런스

서버 실행 후 **`http://localhost:8000/docs`** (Swagger UI)에서:
- 전 엔드포인트의 요청/응답 스키마 (Pydantic 모델 그대로)
- 각 엔드포인트 한글 summary
- Try it out으로 직접 호출 (Authorize 버튼에 Bearer 토큰 입력)

스키마 정의 원본: [`app/models/schemas.py`](../app/models/schemas.py)
