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
| 주간 통계 (이번 주 Nkm) | `GET /me/stats` | `week.total_distance_km`, `week.run_count`, `week.delta_distance_km` (지난주 대비), `month`, `all_time` |
| 날씨 + 러닝지수 | `GET /weather?lat&lng` | `temp_c`, `feels_like_c`, `condition`(한글), `pm25/pm10.{value,grade}`, `running_index.{score,label,comment}` — pm은 부분 장애 시 null 가능 |
| AI 코스 생성 | `POST /routes/generate` | body: `start{lat,lng}`, `target_distance_km`, `pitstop_keyword?`, `notes?` → `summary`, `waypoints[]`, `polyline[]`. **free는 주 3회, 초과 시 429** (§5) |
| 남은 생성 횟수 표시 | `GET /me/quota` | `tier`, `ai_generation.{used,limit,remaining,reset_at,unlimited}` |
| 저장한 코스 | `GET /routes/bookmarked?limit&offset` | `PublicRouteResponse[]` (아래 피드와 동일 shape) |
| 코스 북마크 토글 | `POST/DELETE /routes/{id}/bookmark` | 204, 멱등 (더블탭 안전) |

### 기록 탭

| 데이터 | 메서드/경로 | 주요 응답 필드 |
|---|---|---|
| 월 선택 통계 + 캘린더 | `GET /me/stats/monthly?year&month` | `stats`(합계·평균페이스·전월 대비 delta), `days[{date,distance_km,run_count}]` — 뛴 날만 옴, 캘린더 점 찍기용 (KST 기준) |
| 러닝 기록 저장 | `POST /runs` | body: `distance_km`, `duration_sec`, `route_id?`, `avg_pace_sec_per_km?`, `notes?` |
| 기록 목록 | `GET /runs?limit&route_id?` | `RunResponse[]` 최신순 |
| 기록 단건 | `GET /runs/{run_id}` | 본인 것만, 아니면 404 |
| 2탭 피드백 | `PATCH /runs/{run_id}/feedback` | body: `liked`(bool), `tags[]` (허용 태그는 Swagger의 FeedbackTag) |

### 커뮤니티 / 소셜

| 데이터 | 메서드/경로 | 주요 응답 필드 |
|---|---|---|
| **팔로잉 피드** | `GET /feed?limit&offset` | `PublicRouteResponse[]`: `summary`, `owner_nickname`, `like_count`, `comment_count`, `copy_count`, `is_liked`, `polyline` — 팔로우 0명이면 `[]` |
| 전체 공개 코스 | `GET /routes/public?sort=newest\|popular&limit` | 동일 shape |
| 근처 코스 | `GET /routes/nearby?lat&lng&radius_km` | 동일 shape |
| 코스 검색 | `GET /routes/search?q` | 동일 shape |
| 좋아요 토글 | `POST/DELETE /routes/{id}/like` | 204, 멱등 |
| 댓글 | `GET/POST /routes/{id}/comments`, `DELETE /routes/{id}/comments/{comment_id}` | `content` 1~500자 |
| 이 코스 달리기(복사) | `POST /routes/{id}/copy` | 내 코스로 복사본 생성 |
| 팔로우 토글 | `POST/DELETE /users/{user_id}/follow` | 204, 멱등. 자기 자신 400 |
| 공개 프로필 | `GET /users/{user_id}/profile` | `nickname`, `bio`, `tier`, `follower_count`, `following_count`, `is_following`, `is_followed_by`(맞팔 표시) |
| 팔로워/팔로잉 목록 | `GET /users/{user_id}/followers` / `/following` | `[{user_id, nickname, avatar_url, followed_at, is_following}]` — 항목별 팔로우 버튼용 |
| 크루 목록/검색/상세 | `GET /crews`, `/crews/search?q`, `/crews/mine`, `/crews/{id}` | `member_count`, `owner_nickname` 포함 |
| 크루 생성/수정/삭제 | `POST /crews`, `PATCH/DELETE /crews/{id}` | 수정·삭제는 크루장만 |
| **가입** | `POST /crews/{id}/join` | **상태 코드로 분기**: `200`=즉시 가입(`CrewResponse`, open 크루) / `202`=신청 접수(`JoinRequestResponse{status:"pending"}`, 승인제 크루). `409` = 이미 멤버 또는 `already_requested`(중복 신청). 크루의 `join_policy` 필드(`open`/`approval`)로 버튼 라벨을 미리 정할 수 있음 ("가입하기" vs "가입 신청") |
| 내 신청 상태 | `GET /crews/{id}/join-requests/me` | `{status: pending\|approved\|rejected}` — 없으면 404. **거절은 알림이 안 오므로** 이 값으로 버튼 상태 결정: `pending`→"신청됨(취소)", `rejected`→"가입 신청"(재신청 가능), 404→"가입 신청" |
| 신청 취소 | `DELETE /crews/{id}/join-requests/me` | 204 멱등 (없어도 204) |
| 신청 목록 (크루장) | `GET /crews/{id}/join-requests?limit&offset` | `[{id, user_id, nickname, created_at}]` pending만 최신순. 비크루장 403 |
| 신청 승인/거절 (크루장) | `POST /crews/{id}/join-requests/{rid}/approve` / `/reject` | 204. 승인 → 신청자에게 `join_approved` 알림 + 멤버 추가. 승인 시 정원 초과면 409(신청은 pending 유지). 이미 결정된 신청은 404 |
| 탈퇴/강퇴/양도 | `DELETE /crews/{id}/leave`, `DELETE /crews/{id}/members/{target_id}`, `PATCH /crews/{id}/transfer` | |
| 멤버/랭킹 | `GET /crews/{id}/members`, `/crews/{id}/ranking` | 랭킹: 이번 주 KST 거리순, `me` 플래그 |
| 챌린지 | `GET /crews/{id}/challenges/current`, `POST /crews/{id}/challenges` | `achieved_km`, `progress_pct`, `is_completed` 실시간 계산 |
| **공지 목록/상세** | `GET /crews/{id}/announcements?limit&offset`, `GET .../{announcement_id}` | `title`, `body`, `run_at`, `place_name/lat/lng`, `rsvp_open`, `rsvp{going,not_going,maybe}`, `my_rsvp`; 상세엔 `going_members[]` 명단 추가. 크루원만 조회 가능(403) |
| 공지 작성/수정/삭제 | `POST/PATCH/DELETE /crews/{id}/announcements...` | 크루장만. 작성 시 크루원 전체 알림, 수정은 알림 없음 |
| **참석 투표** | `PUT /crews/{id}/announcements/{aid}/rsvp` | body: `{"status": "going"\|"not_going"\|"maybe"}` → 204. 재투표=덮어쓰기 |
| 알림 | `GET /notifications`, `GET /notifications/unread-count`, `PATCH /notifications/read-all`, `PATCH /notifications/{id}/read` | `type` 8종: `route_liked`, `route_commented`, `crew_joined`, `challenge_completed`, `user_followed`, `crew_announcement`, `join_requested`(크루장에게→신청 목록으로 딥링크), `join_approved`(신청자에게→크루로 딥링크) (+`actor_nickname`, `target_id/target_type`) |

### 프로필

| 데이터 | 메서드/경로 | 주요 응답 필드 |
|---|---|---|
| 내 정보 | `GET /me` (auth 확인), `GET /me/profile` | `nickname`, `avatar_url`, `bio`, `tier` |
| 프로필 생성/수정 | `PATCH /me/profile` | `nickname`(2~20자, 중복 시 409). **tier는 보내도 무시됨** (관리자/IAP 전용) |
| 누적 통계 | `GET /me/stats` | `all_time.{total_distance_km,run_count,avg_pace_sec_per_km}` |
| 티어/쿼터 | `GET /me/quota` | premium이면 `ai_generation.unlimited=true` |

## 5. 에러 규약

에러 바디는 `{"detail": ...}` — detail이 문자열이거나, 구조화된 경우 `{"error": "<코드>", "message": "<한글 안내>", ...}` 객체입니다.

| 코드 | 의미 | 프론트 처리 권장 |
|---|---|---|
| **401** | 토큰 없음/만료 | refresh 후 1회 재시도 → 실패 시 로그인 화면 |
| **403** | 권한 없음 (비크루원 조회, 크루장 아님 등) | 해당 UI 숨김/비활성이 원칙, 받으면 토스트 |
| **404** | 없거나 볼 수 없음 (비공개 코스, 남의 기록도 404) | "존재하지 않음" 처리 — 403과 구분해 존재 여부를 숨기는 의도 |
| **409** | 상태 충돌 | `nickname taken`(닉네임 중복) → 인라인 에러 표시. **`rsvp_closed`** → 투표 버튼 비활성 + "마감되었습니다" (사전에 `rsvp_open` 플래그로 버튼 상태 결정 가능) |
| **429** | **AI 생성 쿼터 초과** | `detail.{limit,used,remaining,reset_at}` 제공 → "이번 주 3회를 모두 사용했어요, 월요일 리셋" + 프리미엄 업셀 화면. `reset_at`은 KST ISO |
| **502** | 외부 서비스 장애 (OpenAI/지도/날씨) | "잠시 후 다시 시도" + 재시도 버튼 |
| **503** | 날씨 설정 문제: `weather_not_configured` / **`weather_key_inactive`**(키 활성화 대기) | 날씨 위젯만 숨기거나 placeholder — 앱 전체 에러로 띄우지 말 것 |

멱등 엔드포인트(좋아요/북마크/팔로우/RSVP/언팔 등)는 더블탭·재시도에 안전하므로 **옵티미스틱 UI + 실패 시 롤백** 패턴을 써도 됩니다.

## 6. 페이지네이션 규약

목록 엔드포인트는 `?limit=20&offset=0` 쿼리를 받습니다 (기본 limit 20, 서버측 최대 100).

- 다음 페이지: `offset += limit`. 응답 길이가 `limit`보다 짧으면 마지막 페이지.
- 지원: `/feed`, `/routes/bookmarked`, `/users/{id}/followers·following`, `/crews/{id}/announcements`.
- 일부 목록(`/routes/public`, `/runs`, `/notifications` 등)은 `limit`만 받습니다 — offset을 보내면 무시되므로 Swagger에서 파라미터 확인.
- 주의: 북마크 목록은 비공개 전환된 코스가 숨겨져 한 페이지가 `limit`보다 짧게 올 수 있습니다 — "짧으면 끝" 판정에 예외적으로 걸릴 수 있으니 빈 배열로 끝 판정하는 게 안전합니다.

## 7. 전체 레퍼런스

서버 실행 후 **`http://localhost:8000/docs`** (Swagger UI)에서:
- 전 엔드포인트의 요청/응답 스키마 (Pydantic 모델 그대로)
- 각 엔드포인트 한글 summary
- Try it out으로 직접 호출 (Authorize 버튼에 Bearer 토큰 입력)

스키마 정의 원본: [`app/models/schemas.py`](../app/models/schemas.py)
