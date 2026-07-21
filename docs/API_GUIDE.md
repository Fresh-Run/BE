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
| 날씨 + 러닝지수 | `GET /weather?lat&lng` | `temp_c`, `feels_like_c`, `condition`(한글), `pm25/pm10.{value,grade}`, **`uv.{value,grade}`**(grade `낮음/보통/높음/매우높음/위험` 기상청 5단계 — **⚠️ 시맨틱: '오늘 최고 자외선'(solar-noon 최대)이지 '현재'가 아님. 타일 라벨을 "오늘 최고 자외선"으로**), **`is_day`**(일출~일몰 여부 — 프론트 자체 아이콘 셋의 주/야 분기용. 10분 격자 캐시라 일출·일몰 경계에서 최대 10분 지연 수용), `running_index.{score,label,comment,personalized}` — **pm·uv는 부분 장애 시 null 가능 → null이면 해당 타일 숨김.** `personalized: true`면 comment가 내 weather 설정 기준. score/label은 항상 공용 기준 |
| AI 코스 생성 | `POST /routes/generate` | body: `start{lat,lng}`, `target_distance_km?`, `terrain?`, `scenic?`, `avoid_hills?`, `prefer_loop?`, `surface?`, `pitstop_keyword?`(≤50자), `notes?`(≤500자) → `summary`(생성자 언어), `waypoints[]`(이름·설명 생성자 언어), `polyline[]`, `total_distance_km`(소수 1자리), `estimated_duration_min`(정수 분 — **⚠️ 2026-07-20 시맨틱 변경: 러닝 기준 예상 시간**(거리 × 기본 페이스 6'30"/km). 이전엔 T-map 도보 시간(~13분/km)이라 2배쯤 길었음. "예상 시간" 라벨 그대로 사용 가능 — 러닝 기준임. 개인 페이스 반영은 후속), `search_radius_km`, `radius_expanded`, **`target_missed`**(2026-07-14 additive), **`is_one_way`**(2026-07-21 additive — 생성 시 `end` 좌표 동봉 여부. 저장된 코스 조회(`StoredRoute`)에도 노출. **기존 코스는 전부 false**(루프 — end 미저장이라 소급 판별 불가). 카드에 "편도"/"순환" 뱃지 재료). **free는 주 3회, 초과 시 429** (§5). **⚠️ 목표 거리 보장 v2.2(2026-07-20)**: 합격 구간 **`[target−100m, target+500m]`**. 서버가 최대 4회 재시도하며 **시도마다 직전 실측 팽창비를 반영해 조준을 보정**(적응형 — 명중률 개선). **전패 시**: ① **`target+1.0km` 이내의 초과** 후보가 있으면 그중 최선을 **`target_missed: true`**로 반환 — "요청 거리보다 조금 길어요" 안내 권장(오차는 `total_distance_km − target`, 최대 +1.0km) ② 그마저 없으면(미달만이거나 초과가 전부 +1.0km 밖) **생성 실패 — 502 `{error:"route_generation_failed"}`**(쿼터 미소모). 짧은 코스·과대 코스는 서빙하지 않으므로 프론트는 502 시 "조건을 바꿔 다시 시도" 유도. **일방 코스(end 좌표 동봉, v2.3)**: 탐색이 start-end corridor 기준으로 동작. **실행가능성 서버 게이트**: `|start−end| > target×0.8`이면 **422** `{error:"one_way_end_too_far", message:"도착지가 목표 거리에 비해 너무 멀어요 — …", min_target_km}` (쿼터 미소모, Gemini 미호출). **소비 규칙**: end 선택 UI에서 직선거리 > target×0.8이면 사전 안내("이 도착지까지는 최소 `min_target_km`km 코스가 필요해요" — 422 응답의 `min_target_km`를 그대로 슬라이더 최소값 제안에 사용 가능). 우선순위·동적 반경은 표 아래 참고 |
| 남은 생성 횟수 표시 | `GET /me/quota` | `tier`, `ai_generation.{used,limit,remaining,reset_at,unlimited}` |
| **AI 오디오 코치 (프리미엄)** | `POST /routes/{id}/coach-script` | `{route_id, cues[], from_cache, created_at}` — 내 코스만(404), free는 **403 `premium_required`**(§5). route당 1회 생성 후 캐시(`from_cache: true`), AI 생성 쿼터 미차감. 스키마·재생 규칙은 표 아래 참고 |
| 저장한 코스 | `GET /routes/bookmarked?limit&offset` | `PublicRouteResponse[]` (아래 피드와 동일 shape) |
| 코스 북마크 토글 | `POST/DELETE /routes/{id}/bookmark` | 204, 멱등 (더블탭 안전) |
| **코스 삭제** (2026-07-21) | `DELETE /routes/{route_id}` | **본인만 · 하드 삭제 · 복구 없음.** 성공 **204** — 북마크·좋아요·댓글·오디오코치 캐시(cascade)·그 코스 대상 알림(`route_liked`·`route_commented`)이 함께 소멸. **연결된 러닝 기록과 복사본 코스는 잔존**(연결만 끊김 — `runs.route_id`·`copied_from`이 null로. 러닝 기록/파생 코스는 독립 자산). **타인/없음/재삭제 전부 404 은닉**(연타 시 404="이미 삭제됨"으로 무해 처리). **소비 규칙**: 내 코스 목록(저장한 코스·프로필)에서 **스와이프 또는 ⋯ 메뉴 → 파괴 컨펌** — 카피는 "북마크·좋아요·댓글이 함께 삭제돼요"(연결 러닝은 남음을 안내 가능). 통계·PB 등 재계산 대상 없음(코스는 집계 미참여). run-delete와 동일 계약 관성 |

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
> **AI 생성 텍스트는 생성자의 언어 설정(`settings.lang`)을 따릅니다** (기본 `ko`). 코스 생성의 `summary`·경유지 이름/설명, 오디오 코치 멘트가 유저의 `lang`(`ko`/`en`)으로 나옵니다. 언어를 바꾸려면 `PATCH /me/settings {"lang":"en"}` 후 생성하세요. **주의**: 오디오 코치 스크립트는 코스(route)당 1회 생성 후 캐시되므로 **최초 생성 시점 생성자의 언어로 고정**됩니다(이후 언어를 바꿔도 그 코스의 스크립트는 안 바뀜). (월간 인사이트의 AI 텍스트는 생성 중단 — 인사이트 응답 노트 참조.)
>
> **동적 탐색 반경**: 출발지 주변이 좁아 코스 생성이 어려우면 서버가 출발지는 고정한 채 탐색 반경을 자동으로 넓혀가며 재시도합니다(목표 거리 비례 시작, 최대 8km·4시도). 응답의 `search_radius_km`는 사용된 반경, **`radius_expanded: true`면 "주변에 코스가 마땅치 않아 반경을 N km까지 넓혀 찾았어요" 안내를 띄우기 좋습니다**. 반경을 다 넓혀도 목표에 못 미치면 가장 근접한 코스를 그대로 반환하니 `total_distance_km`와 요청 목표를 비교해 "목표보다 짧은 코스예요"를 표시하세요. 정상 생성은 **보통 3~6초**이나, 반경 재시도가 도는 예외 케이스는 더 걸릴 수 있으니 **`radius_expanded: true`일 때 "주변을 더 넓게 찾는 중" 안내**를 띄우고 클라이언트 타임아웃은 여유 있게(예: 60초) 두세요. 쿼터는 재시도 횟수와 무관하게 요청당 1회만 차감됩니다.

### 기록 탭

| 데이터 | 메서드/경로 | 주요 응답 필드 |
|---|---|---|
| 월 선택 통계 + 캘린더 | `GET /me/stats/monthly?year&month` | `stats`(합계·평균페이스·전월 대비 delta), `days[{date,distance_km,run_count}]` — 뛴 날만 옴, 캘린더 점 찍기용 (KST 기준). **무료** |
| **AI 월간 인사이트 (프리미엄)** | `GET /me/insights/monthly?year&month` | 프리미엄 월간 리포트 화면 전체 데이터. free는 **403 `premium_required`**(§5), month 1~12 외 422. 스키마는 표 아래 참고 |
| 러닝 기록 저장 | `POST /runs` | body: `distance_km`(0<d≤350), `duration_sec`(≤7일), `route_id?`, `avg_pace_sec_per_km?`, **`title?`**(≤60자), **`visibility?`**(public/followers/private, 기본 public), `notes?`(≤2000자), **`area?`**(≤50자 지역명 — 프론트가 Kakao SDK 역지오코딩으로 변환해 전송, 예 "성수동". 서버는 저장·서빙만. **과거 run은 null → 지역 라인 숨김**. PATCH /runs로 편집 가능, 카드/타인 상세에도 노출), **`gps_track?`** (아래 규약). **평균 페이스가 1'30"/km보다 빠르면(물리적 불가) 422** — 자율신고 부정 방어. 응답에 `new_records[]` — **비어있지 않으면 "새로운 기록 경신!" 축하 모달** (`{type, previous, current, improvement_pct}`) — 첫 run은 `[]`. **크루 정기런 태깅(L1, 2026-07-13)**: `crew_id?`(="크루 러닝 시작"으로 진입 시 동봉 — 이 러닝이 어느 크루 정기런인지)·`announcement_id?`(집결 공지 연결, 선택). **서버가 crew 멤버십 검증 — 비멤버가 남의 크루 태그 시 400**. 미태그(crew_id 없음)는 일반 러닝. **저장 화면(시안) 필드 매핑·visibility·페이스 비교는 아래 상세 참고**. **⚠️ 미지/오타 필드 422(2026-07-14 extra 금지 — `visibilty` 오타로 private이 public으로 저장되던 갭 봉쇄. **중첩 `gps_track[]` 원소(lat/lng/t/acc/alt)도 동일** — `latitide` 같은 오타 422). **`ran_at`은 받지 않는다 — 서버가 저장 시각을 `now()`로 강제**(백데이트 불가). 과거 보내던 `ran_at`은 무시됐고 이제 **422**(프론트는 보내지 말 것) |

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
| 기록 목록 | `GET /runs?limit&route_id?&before?` | `RunResponse[]` 최신순 — GPS run은 `splits[]`·`has_track`·`verification` 포함. **`kudos_count`**(♥)·**`comment_count`**(💬) 배치 집계(N+1 없음). `my_kudos`는 본인 목록에선 항상 false(본인 kudos 불가 — 키는 존재). **`polyline_thumb`**(≤36pt Coordinate 배열, 좌표 5자리) — 카드 실지도 렌더용, 코스·track과 동일 포맷. **null이면 지도 자리 숨김 또는 일러스트 폴백**(photo_thumb과 대칭). 전체 해상도는 `GET /runs/{id}/track`. 피드·공개 프로필·크루 카드에도 동일 필드. **커서 페이지네이션**: 다음 페이지는 `before=<마지막 run의 ran_at>`(ISO+타임존, naive는 422) — **`+00:00`의 `+`는 반드시 URL 인코딩(`encodeURIComponent`)하거나 `Z`로 치환**(서버가 tz 위치 공백은 관용 복원하지만 인코딩이 정석). 응답이 `limit`보다 짧으면 끝 |
| 기록 단건 | `GET /runs/{run_id}` | **본인 전체 / 타인은 공개범위 내 정제 응답** (track·kudos와 동일 게이트, 범위 밖 404 은닉). **타인 응답에서 null/기본값인 필드**: `notes`(개인 메모)·`liked`/`feedback_*`·`verification`/`is_flagged`/`distance_km_reported`(내부 상태)·`visibility`(null) — 타인 화면은 이 필드들을 렌더하지 말 것. `route_id`는 **연결 코스가 공개일 때만**. `photos`(서명 URL)는 상세에서만, 목록은 `photo_thumb`. **`my_kudos`**(조회자 기준, 피드와 동일 계산) 포함 — 상세 ♥ 초기 상태를 목록 payload 없이 그릴 수 있음(본인 run은 항상 false) |
| **러닝 삭제** (2026-07-15) | `DELETE /runs/{run_id}` | **본인만 · 하드 삭제 · 복구 없음.** 성공 **204** — kudos·댓글·GPS트랙(cascade)·**사진(Storage)**·그 run 대상 알림이 함께 소멸. **타인/없음/재삭제 전부 404 은닉**(연타 시 404="이미 삭제됨"으로 무해 처리). **소비 규칙**: 본인 상세 ⋯ 메뉴 → 2단 파괴 컨펌 — 카피는 **"좋아요·댓글·사진이 함께 삭제돼요"**(캐스케이드 확정). 크루 채팅에 공유한 카드(run_share)는 **스냅샷이라 잔존, 탭 시 404**(→ "삭제된 러닝" 처리 — 기존 계약). PB·주간/월간 통계·정기런 참여자 수·챌린지 km는 **라이브 계산이라 즉시 자동 반영**(PB는 차순위 자동 승계, 재계산 알림 재발송 없음) |
| **러닝 사진** | `POST /runs/{id}/photos/upload-url` → PUT → `PATCH /runs/{id}` `{photos}` | **avatar와 동형 3-step** (≤3장, jpeg/png/webp 5MB — private 버킷이라 URL 직접 접근 불가, 조회는 응답의 **서명 URL(만료 1h)** 로만): ① body `{slot: 1~3, content_type}` → `{upload_url, path}` ② 이미지 PUT ③ `PATCH /runs/{id}` `{photos: [path…]}`(순서 = 표시 순서, 빠진 경로는 서버가 Storage에서 삭제 — 교체·삭제 겸용, `[]`로 전체 삭제. 이 run의 prefix 밖 경로는 422). **⚠️ 업로드 전 클라이언트 재인코딩으로 EXIF(GPS 좌표) 제거 필수 — 계약.** 서명 URL은 1h 만료라 **캐시하지 말고 응답 값을 그대로 사용**. 목록 카드(기록·피드·공개 프로필·크루 피드)엔 `photo_thumb`(첫 장) 제공 |
| **러닝 경로 (지도)** | `GET /runs/{run_id}/track` | `{polyline[{lat,lng}], server_distance_km, elev_gain_m, point_count_raw/kept}` — 활동 상세 지도용. `server_distance_km`는 저장된 서버 계산값(2026-07-11~ 정확값 — 이전 저장분은 splits 파생이라 0.2km 미만이 0.0일 수 있음). `polyline`은 코스의 `polyline`과 동일 포맷(같은 렌더 코드 사용 가능). **접근: 본인 + run 공개범위 내 타인**(public 누구나 / followers는 팔로워·같은 크루 / private 본인만 — kudos·댓글과 동일 게이트). 범위 밖·트랙 없는 run은 404 (`has_track`으로 사전 판단 — 타인 run 카드도 has_track 보고 지도 진입 결정). **러닝 공유 카드(RN 뷰 캡처) 렌더링에도 이 응답 + run 상세 스탯을 사용 — 별도 API 불필요** |
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
>                "longest_streak_days": 5,
>                "run_days": 12 },                            // 이번 달 러닝한 날 수 (꾸준함 지표)
>   "pace_trend": [                                           // 페이스 추이 라인 차트 — 조회 월 포함 최근 3개월, 오래된 달부터
>     { "year": 2026, "month": 4, "avg_pace_sec_per_km": null },   // run 없는 달은 null → 라인 결측(끊김) 표시, 0으로 그리지 말 것
>     { "year": 2026, "month": 5, "avg_pace_sec_per_km": 331 },
>     { "year": 2026, "month": 6, "avg_pace_sec_per_km": 326 } ],  // 마지막 값 == stats.avg_pace_sec_per_km (같은 기준 보장)
>   "month_rank": { "type": "best_5k", "rank": 2, "total": 5,     // 이번 달 가장 최근 러닝의 순위 (2026-07-13) — null 가능
>                   "value": 1725, "distance_km": 6.0, "ran_at": "…", "run_id": "…" },
>   "ai": null   // ⚠️ 항상 null (2026-07-09 AI 코칭·추천 플랜 생성 중단 — 비용/로딩. 필드는 하위 호환용 유지, 타입은 지우지 말 것)
> }
> ```
>
> **`month_rank` 소비 규칙 (2026-07-13)** — "이번 달 {rank}번째로 빠른/긴 {거리대}" 타일 재료. **`type`**으로 문구 축 결정: `best_pace`=빠른 페이스 / `best_5k`=빠른 **5K(환산)** / `longest_distance`=긴 거리 / `longest_duration`=긴 시간. **`rank`**=이번 달 가장 최근 러닝의 순위(1=최고). **`rank==1`이면 "가장 빠른/긴"**, 아니면 "{rank}번째". `total`=그 종목 이번 달 러닝 수("총 {total}회 중"). **⚠️ `month_rank`가 `null`이면 타일 미표시** — 각 종목 verified 러닝이 2회 미만(1회뿐인 "가장 빠른"은 정보량 0이라 서버가 생략) 또는 verified run 없음. **거리대는 기존 4개 기록 차원 재사용**(별도 5k/10k 버킷 없음 — best_5k는 페이스 환산 5K). **verified run만 집계**(PB·랭킹과 동일 — 트랙 없는 수동 기록 제외). 서버가 4차원 중 가장 인상적 1개 선정(순위 낮을수록·동순위면 거리/지구력 차원 우선).
>
> 수치 블록은 매 요청 최신 계산. **`ai`는 항상 null** — AI 코칭 카드·추천 플랜은 렌더하지 않음(생성 중단, 완전 제거는 출시기). **시안 중 심박 존·평균/최대 심박·누적 고도·칼로리·지형 분석·월 목표 링은 백엔드 데이터가 없어 미제공** — 헬스킷 등 로컬 데이터로 채우거나 숨기고, 월 목표는 목표 설정 기능 후속 시 추가 예정. 꾸준함 지표는 `pattern.run_days`(러닝 일수)·`longest_streak_days`(연속)·`weekday_counts`(요일 분포) 조합 사용.

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
| **활동 피드 (run, 홈 친구 탭)** | `GET /feed/activities?limit&offset` | **팔로우한 유저의 run만** — ⚠️ **2026-07-20 스펙 변경: 본인 run 제외**(본인 기록은 기록 탭·프로필 서피스가 담당. 이전 계약 "팔로우+본인"에서 변경 — 친구 탭 소비 기준 오너 룰링). `ran_at` 최신순: 크루 러닝 피드와 같은 필드 + `title`, `is_mine`(**하위호환 유지 — 이제 항상 `false`**, 렌더 분기 불필요), `kudos_count`, `my_kudos`, **`comment_count`**. **visibility 적용**: `private` run 제외(public·followers만). 팔로우 0명이면 `[]`. (`visibility`는 피드에선 null) |
| **홈 "전체" 탭 (위치 run, 2026-07-15)** | `GET /feed/nearby?lat&lng&radius_km&limit&offset` | **내 위치 반경 내 public run 탐색 피드** — `ActivityFeedItem[]`(활동 피드와 **동일 shape** → run 카드 재사용). **`lat`·`lng` 필수**(누락 **400**), **한국 bbox 밖 400**(lat 33~39·lng 124~132). **⚠️ 이 400들의 바디는 FastAPI 기본 `{"detail": "..."}` 형식**(§5의 구조화 `{error, message}` 아님 — 프론트는 `.detail`을 읽을 것): 누락 `{"detail":"lat, lng are required"}`, bbox 밖 `{"detail":"lat/lng out of Korea bounds"}`. `radius_km` 기본 **10**·**상한 20**(초과는 조용히 20으로 clamp → **200**, 에러 아님)·**하한 0.1**(0·음수도 clamp → **200**, 반경 거의 0이라 사실상 `[]`). `ran_at` 최신순, 반경 내 0건이면 `[]`. **필터**: `visibility='public'`만 + **본인 제외** + **이미 팔로우 중인 유저 제외** + **차단(양방향)·비공개 계정 owner 제외**(`visible_owners`) + 반경은 bbox 후 haversine 원형 컷. **⚠️ 프라이버시 계약**: 계정을 비공개(profile `followers`/`private`)로 둔 유저는 개별 run을 public으로 올려도 이 탐색 피드에 **안 뜬다**(`/routes/public` 코스 정책과 일관). 트랙 없는 run(좌표 null)은 미노출. **홈 "전체" 탭의 데이터소스가 이 엔드포인트로 교체됨**(기존 코스 피드 `/routes/public`은 존치 — 코스 탐색 등 다른 서피스가 계속 사용) |
| run kudos | `POST/DELETE /runs/{run_id}/kudos`, `GET /runs/{run_id}/kudos` | 204 멱등(더블탭 안전), 본인 run 400, run 주인에게 `run_kudoed` 알림. GET은 누른 사람 목록 `[{user_id, nickname, avatar_url, created_at}]`. **가시성 게이트**: 내가 볼 수 있는 run(public, 또는 팔로우/크루의 followers)에만 kudos·목록 조회 가능 — 그 외 run_id는 **404**. **코스 좋아요(route like)와 별개** |
| **run 댓글** | `GET /runs/{run_id}/comments?limit&offset`, `POST`, `DELETE /runs/{run_id}/comments/{comment_id}` | route 댓글과 동형. GET **최신순**(닉네임 포함, 페이지네이션) `[{id, run_id, user_id, nickname, content, created_at}]`. POST body `{content}`(1~500자, 초과/빈값 422) → run 주인에게 `run_commented` 알림(본인 댓글 미발송). DELETE는 **작성자 또는 run 주인**(그 외 403). **가시성 게이트 동일**: 안 보이는 run은 404. 카드 수는 위 피드/목록의 `comment_count` |
| 전체 공개 코스 | `GET /routes/public?sort=newest\|popular&limit` | 동일 shape. **차단·비공개 계정 owner의 코스는 제외**(2026-07-13, 검색과 동형 — `visible_owners` 필터). newest는 DB limit 후 필터라 결과가 limit보다 소폭 적을 수 있음 |
| 근처 코스 | `GET /routes/nearby?lat&lng&radius_km` | 동일 shape. `radius_km`은 최대 50으로 클램프, `limit` 1~100 클램프 (음수·거대값도 안전) |
| 코스 검색 | `GET /routes/search?q` | 동일 shape. `limit` 1~100 클램프 |
| **유저 검색** (2026-07-13) | `GET /users/search?q&limit` | 닉네임 **부분 일치(대소문자 무관)**. 결과 `[{user_id, nickname, avatar_url, bio}]`. **`q` 최소 2자**(1자는 422 — 전 유저 열거 방지), `limit` 기본 20·**최대 50**(초과 422). **프라이버시**: ① **차단 상대(양방향) 제외** ② **본인 제외** ③ **잠금(비공개·볼 수 없는) 계정도 결과에 뜨되 `bio=null`**(닉네임·아바타만) — 프론트는 그대로 노출하고 **프로필 진입 시 🔒**(검색에서 숨기면 비공개 유저를 못 찾아 팔로우 요청 자체 불가). 승인제 계정은 정상 노출(팔로우 요청 진입점). 통합 검색 화면: 크루는 `GET /crews/search`, 유저는 이 엔드포인트 |
| **장소 검색 (경유지·출발지)** | `GET /places?keyword&lat?&lng?&radius_m?&limit` | **⚠️ 인증 필수** — 토큰 없이 401. **용도별 2모드**: ① **경유지 검색** — `lat`+`lng` 포함 → 좌표 기준 **거리순**, `radius_m` 기본 2000·최대 20000(**20km 캡은 카카오 API 자체 제약** — 더 넓게는 ②로) ② **출발지 검색** — 좌표 생략 → **전국 정확도순**. 422 케이스: 한쪽 좌표만 / 좌표 없이 `radius_m` / `keyword` 1~50자 밖 / bbox·캡 밖. **출발지 자동완성 UI는 디바운스 300ms+ 권장**(타이핑마다 호출하면 카카오 쿼터 소모) |
| 좋아요 토글 | `POST/DELETE /routes/{id}/like` | 204, 멱등 |
| 댓글 | `GET/POST /routes/{id}/comments`, `DELETE /routes/{id}/comments/{comment_id}` | `content` 1~500자 |
| 이 코스 달리기(복사) | `POST /routes/{id}/copy` | 내 코스로 복사본 생성. **원본 삭제돼도 복사본은 잔존**(`copied_from`이 null로 — 코스 삭제 계약) |
| 팔로우 토글 | `POST/DELETE /users/{user_id}/follow` | 즉시 팔로우 **204**(멱등), 자기 자신 400. **비공개 계정(`visibility='private'`)이면 202**(pending 요청 생성 — 이미 pending 재요청은 409 `follow_request_pending`). 202 받으면 "요청됨" 표시, 승인 전엔 `is_following:false`. **`public`·`followers`는 즉시 204**(private만 요청제) |
| **팔로우 요청제** (v2, 통합 2026-07-13) | `GET /me/follow-requests`, `PATCH /me/follow-requests/{requester_id}` `{approve}`, `DELETE /users/{id}/follow-request` | **진입 조건 = `visibility='private'`**(별도 승인제 토글 폐지 — 아래 ⚠️). 비공개면 신규 팔로우가 요청 대기. **내게 온 요청**: `GET /me/follow-requests`(requester 프로필 목록) → 승인/거절 `PATCH .../{requester_id} {approve:true|false}`(승인 시 follows 생성+알림, 거절 무알림, 없음/처리됨 404). **내 요청 취소**: `DELETE /users/{id}/follow-request`(멱등 — pending만). **기존 팔로워는 비공개 전환해도 관계 불변**(소급 무영향). **재요청 revive(2026-07-14 버그픽스)**: 거절됐거나 **과거 승인 후 언팔로우/팔로워제거된** 쌍의 재팔로우는 정상 **202**(잔존 요청 이력이 pending으로 부활 — 이전엔 승인 이력 잔존 행 때문에 409 영구 스턱이던 버그 수정). **⚠️ `follow_approval` DEPRECATED (Part B 통합)**: 승인제가 `visibility='private'`로 통합됨. `PATCH /me/profile {follow_approval:…}`는 **받되 무시(no-op)**, `GET /me/profile`의 `follow_approval`은 **항상 `false` 고정 반환**. **프론트 조치**: 설정 화면의 "팔로우 승인제" 토글을 제거하고 비공개 토글로 일원화(비공개=요청제). 필드·컬럼 완전 제거는 build #1 예정(프론트가 요청/응답에서 이 필드를 더 이상 쓰지 않음을 확인 후) |
| 공개 프로필 | `GET /users/{user_id}/profile` | `nickname`, `bio`, `tier`, `follower_count`, `following_count`, `is_following`, `is_followed_by`(맞팔 표시), **`public_run_count`**(전체 공개 게시 러닝 수), **`followers_run_count`**(2026-07-15 additive — '팔로워 공개(followers)'로 게시한 러닝 수), **`visibility`**·**`locked`**(비공개 프로필 v1). **⚠️ `locked: true`면 🔒 잠금 화면** — 비공개 계정(`visibility` followers/private)을 볼 권한 없음(비팔로워·비크루원). **⚠️ 카운트는 진실값(2026-07-13 계약 변경 — 인스타 컨벤션)**: `follower_count`·`following_count`·`public_run_count`는 잠금이어도 **실값** 노출("0은 프라이버시가 아니라 오보"). **`followers_run_count` 소비 규칙(A′ "숫자는 사실값, 리스트는 잠금")**: 비팔로워에게도 **열림 프로필(`locked:false`)이면 사실값** 노출 → 프론트는 "팔로우하면 N개 더 볼 수 있어요" CTA 유도에 사용. **단 목록엔 이 run들 미노출**(`GET /users/{id}/runs`는 여전히 public만 — 트랙·제목·날짜 절대 무노출, 리스트 잠금). **잠금 프로필(`locked:true`)엔 `followers_run_count=0`**(잠긴 계정은 followers run 존재 자체를 숨김 — public_run_count만 진실값). **잠기는 건 리스트·콘텐츠**: `bio`=null, 러닝 목록(`GET /users/{id}/runs`)·러닝 상세·검색 제외, **팔로워/팔로잉 명단(`GET /users/{id}/followers`·`/following`)도 빈 배열**. 즉 **"숫자는 열고 명단·콘텐츠는 잠금"**(비대칭). **닉네임·아바타**도 노출(팔로우 버튼용). **팔로우 관계면** `locked:false`로 전체. 그 계정의 `GET /users/{id}/runs`도 잠금 시 빈 배열, 러닝 상세·검색에서도 제외. **⚠️ 결정 A′(2026-07-13, 사양 변경): 크루 예외는 크루 서피스로만** — 비팔로워 크루원에게는 상대 **프로필·러닝 히스토리·통계가 잠긴다(`locked:true`)**. 크루 랭킹·명단·채팅·크루 피드 카드는 그대로 보이되, **프로필/히스토리는 팔로우해야 열림**. 단 **크루 피드에 뜬 run 카드는 탭 시 상세 200**(엣지 ⓑ — private run 제외, "서피스에 보이는 카드는 상세까지"). 즉 비공개 계정이 `locked:false`로 보이는 건 **팔로우 관계** 때문(차단은 이보다 위 — §차단) |
| **공개 프로필 러닝** | `GET /users/{user_id}/runs?limit&offset` | 그 유저의 러닝 카드 — **활동 피드와 동일 shape**(`run_id, user_id, nickname, avatar_url, ran_at, title, distance_km, duration_sec, avg_pace_sec_per_km, route_id, route_summary, is_mine, kudos_count, my_kudos, comment_count`). **조회자 가시성 필터**: 본인=전부 / 타인은 `public` 항상 + `followers`는 내가 그 유저를 팔로우할 때 + `private` 제외. **본인 프로필에서만 각 카드에 `visibility` 채워짐**(뱃지용), 타인 프로필은 `visibility=null`. 좋아요=`kudos_count`, 댓글=`comment_count`(💬) |
| 팔로워/팔로잉 목록 | `GET /users/{user_id}/followers` / `/following` | `[{user_id, nickname, avatar_url, followed_at, is_following}]` — 항목별 팔로우 버튼용. **⚠️ 잠금 계정(볼 권한 없는 비공개)은 빈 배열**(2026-07-13 — 명단 잠금, 카운트는 프로필 응답에서 진실값. "숫자 열고 명단 잠금" 비대칭). 차단 상대는 404(존재 은닉) |
| **팔로워 제거** (remove follower) | `DELETE /me/followers/{user_id}` | 내 팔로워 목록에서 `user_id`를 떼어낸다(인스타 'remove follower') — **상대가 나를 팔로우하던 관계만 끊음**. **⚠️ 언팔로우와 방향 반대**: 언팔로우(`DELETE /users/{id}/follow`)는 내가 나가는 것, 이건 상대를 내 팔로워에서 밀어내는 것. **무알림**(상대는 조용히 언팔당함 — unfollow·block 관성). **재팔로우 허용**(차단과 구분 — 관계만 끊고 재팔로우·노출은 안 막음. 내가 비공개면 그 재팔로우는 요청제로 들어감). **204**(이미 내 팔로워가 아니어도 멱등), self **400**, 없는 유저·**차단 관계 404 은닉**(차단 체크가 앞섬). **소비 규칙**: 팔로워 목록 항목의 "제거" 버튼 → 이 호출 → 성공 시 목록에서 항목 제거(낙관적 갱신), `follower_count` −1. 프론트 확인 모달 권장(비가역 아님이나 재요청은 상대 몫) |
| **차단** (v3) | `POST/DELETE /users/{id}/block`, `GET /me/blocks` | 차단 시 **양방향 노출 완전 차단**(프로필·러닝·검색·kudos·댓글·**코스 좋아요·코스 댓글·팔로우/팔로우요청** 전부 **404 은닉** — 잠금🔒과 달리 존재 자체 숨김) + **양방향 팔로우·pending 요청 자동 해제**. 멱등, self 400. **차단 상대에겐 write도 404**: 코스 좋아요/댓글·팔로우·승인요청 시도 모두 404(관계 행·알림 미생성 — 은닉 우선이라 피드설정 403보다 앞섬). **해제해도 팔로우는 복구 안 됨**(재팔로우 필요). **크루 멤버십은 유지**(강퇴 아님) — 단 크루원이어도 서로의 러닝 상세·프로필은 404. **v3.5·v3.6(2026-07-13 배포)**: 크루 채팅 차단 메시지 "가려진 메시지"(위 채팅 절). **⚠️ 통일 계약 — 차단 상대는 모든 목록에서 제외**: 크루 피드 카드·**kudos 준 사람 목록·run 댓글 목록·코스 댓글 목록** 전부 차단 유저 항목 제거(팔로워/팔로잉 명단은 잠금 시 빈 배열). **단 예외: 크루 랭킹·명단·challenge_km은 차단 무시 유지**(순위·거리 집계 왜곡 방지 — 사양). **count 정합**: kudos_count·comment_count는 **전역 값 유지**(목록만 필터 — 차단 상대가 상호작용한 run은 "카운트 N, 목록 N−1" 미세 불일치 발생 가능. 인스타 동형 — 숫자는 전역, 명단만 가림). `GET /me/blocks`는 차단 목록(프로필 설정 화면) |
| **신고** (v1.1, 2026-07-15 run 오픈) | `POST /reports` | body `{target_type, target_id, reason, detail?}`. **`target_type`: `"user"`(v1) + `"run"`(v1.1)** — 댓글·코스 등은 422(확장 예정). `target_id`는 user면 user_id, run이면 **run_id**. **`reason` 5종 영문 키**: `spam`·`abuse`(욕설/혐오)·`inappropriate`(부적절 콘텐츠)·`impersonation`(사칭)·`other` — **한글 라벨은 프론트 몫**. `detail` ≤500자 optional('other' 보완). **성공 204**(block·follow 관성), **중복 신고도 멱등 204**(같은 (대상타입, 대상) pending 1건만 유지 — 같은 유저를 user로도 run으로도 신고하면 별건). **self 신고 400**(자기 자신·**자기 run** 동일). **404 은닉**: 없는 대상·차단 관계·**내게 안 보이는 run**(private, 비팔로우의 followers 등 — 가시성 게이트가 kudos·상세와 동일. 피드에서 보이는 run 카드라면 항상 신고 가능). **소비 규칙**: 프로필 ⋯ 메뉴 + **run 상세 ⋯ 메뉴(타인 run)에도 "신고하기" 시트 추가** → 사유 시트(reason) + 선택 상세 입력 → 이 호출 → 성공·404 모두 "신고가 접수되었어요" 토스트(은닉 — 대상 상태를 드러내지 않음). **차단과 독립**(액션시트에서 신고+차단 함께 제공 시 `POST /block` 별도 호출 — 차단은 유저 단위이므로 run 신고 시트의 차단은 run 소유자 user_id로). 신고 대상에게 알림·표시 없음 |
| 신고 관리 (⚙️ 운영 전용) | `GET /admin/reports?status&limit&offset`, `PATCH /admin/reports/{id}` `{status}` | **운영진(ADMIN_USER_IDS Fly secret)만 — 비운영진·미설정 시 404 은닉**(프론트 앱은 이 엔드포인트를 호출하지 않음). GET: status 기본 `pending`(외 `reviewed`/`dismissed`), 최신순, 항목에 reporter/target 프로필 brief + **run 신고는 `target_run {run_id, title, owner{user_id,nickname,avatar_url}}`**(user 신고의 `target`은 run이면 null — 상호배타). **신고된 run이 삭제되면 신고 행은 잔존하고 `target_run: null`**(폴리모픽 FK 없음 — `target_id`로 원본 추적, "삭제된 대상" 표시). PATCH: `reviewed`\|`dismissed` **단방향**(pending 되돌리기 422), 없는 id·이미 처리 404 |
| **크루 둘러보기** | `GET /crews?sido&sigungu&lat&lng&include_full&limit` | 공개 크루 + 내 비공개. `member_count`·`owner_nickname`·`sido`·`sigungu`·`lat`·`lng`·`tags`·`distance_km`·**`cover_url`·`icon_url`**(2026-07-13, 없으면 null → 기본 그라데이션/디폴트 아이콘) 포함. **파라미터 없으면 기존 동작**(최신순, distance_km null). 당근식 사용법은 표 아래 참고 |
| **크루 이미지 업로드** | `POST /crews/{id}/cover/upload-url`, `POST /crews/{id}/icon/upload-url` | **운영진(크루장·admin)만**(member 403, 없는 크루 404). 아바타와 동일 **3-step**: ① 이 엔드포인트 → `{upload_url, public_url, max_bytes(5MB), allowed_types}` ② 이미지 바이트를 `upload_url`에 **PUT**(Content-Type 필수, jpeg/png/webp) ③ `public_url`을 `PATCH /crews/{id}`의 `cover_url`/`icon_url`로 저장(**CDN 캐시 무효화 `?v=타임스탬프` 권장**). 경로 크루당 고정(`{crew_id}/cover`·`/icon`)이라 재업로드 자동 덮어쓰기. **⚠️ 업로드 전 클라 재인코딩 + EXIF(GPS) 제거 필수**(서명 URL 직접 업로드라 서버 미경유. 크루 이미지는 **public 버킷**이라 URL만 알면 원본 접근 가능 — 아바타와 동일 하드룰). **⚠️ 크루 이미지는 공개 표면(아바타 동형)**: 크루가 **비공개여도** 커버·아이콘은 둘러보기 카드급 공개 정보로 취급 — `crew_id`를 아는 사람은 public URL로 열람 가능(비회원 크루 상세 404와 별개). **민감한 이미지 업로드는 비권장**(설정 화면에 안내 권장) |
| 크루 검색/상세 | `GET /crews/search?q`, `/crews/mine`, `/crews/{id}` | 검색은 name/area/description 부분일치 |
| 크루 생성/수정/삭제 | `POST /crews`, `PATCH/DELETE /crews/{id}` | 수정·삭제는 크루장만. **생성은 무료 플랜 1개 한도** (내가 owner인 크루 기준) — 초과 시 **403 `premium_required`** `{error, message, feature: "crew_create", limit: 1}` → 업셀 화면. 프리미엄 무제한. 크루를 삭제하거나 소유권을 위임하면 슬롯이 다시 빔. 필드 길이: `name`≤50, `description`≤500, `area`≤50, `sport`≤30, `active_days`≤7개. **상한(2026-07-13 시안 정렬)**: `max_members`≤**100**, `radius_km`≤**20**(km), 챌린지 `goal_km`≤**100**(km) — 초과 시 422. **둘러보기 필드**(전부 optional): `sido`(17개 광역 표준명)·`sigungu`(≤30자)·`lat`/`lng`(한국 bbox)·`tags`(서버 어휘, ≤5개) — 아래 참고. **⚠️ PATCH 삭제 시맨틱(2026-07-13 버그수정)**: `sido`·`sigungu`·`lat`·`lng`는 **명시 `null`=삭제**(그 필드 비움), **생략=유지**, 값=설정 — 이 3분기를 서버가 구분한다(이전엔 명시 null이 무시돼 못 지웠음). **`lat`·`lng`는 좌표쌍이므로 함께 전송 권장**(한쪽만 null 보내면 반쪽 좌표가 됨 — 서버는 독립 허용). `tags`는 삭제 시맨틱 아님 — **비우려면 `[]`**(명시 null은 유지로 무시). `name`은 필수라 삭제 불가(명시 null 무시). **상설 집결지(2026-07-14 additive)**: `meet_place_name`(≤100자)·`meet_lat`/`meet_lng`(한국 bbox) — 캔버스 카드 장소 라인("서울숲 공원 정문 · … · 매주 화·목 06:00", 스케줄은 기존 `active_days`/`active_time` 조합). **공지의 일회성 집결지(place_*)와 완전 독립**(동기화 없음). 생성·수정 모두 optional, 수정은 **명시 null=삭제/생략=유지**(sido/lat/lng와 동일 3분기), `meet_lat`·`meet_lng` **함께 전송 권장**. 응답(CrewResponse — 둘러보기·상세·mine 등 전 경로)에 노출되며 **null이면 카드 장소 라인 숨김**. **크루 이미지**: `cover_url`·`icon_url`은 PATCH로 저장(아래 업로드 참고), **명시 null=삭제**(Storage 정리)·`""`=422·생략=유지. **⚠️ 값은 반드시 업로드가 준 이 크루의 `crew-images/{crew_id}/{cover\|icon}` public_url**(캐시버스터 `?v=` 허용)이어야 함 — 외부 URL·타 크루 경로는 **422**(주입 차단). **미지/오타 필드도 422**(extra 금지 — POST·PATCH 양쪽. 2026-07-13 코드-문서 정합: CrewCreate·CrewUpdate에 `extra="forbid"` 적용, `is_publik` 같은 오타로 `is_public`/`join_policy`가 silent 무시되던 갭 봉쇄. ProfileUpdate/RunUpdate와 정합) |

> **홈 "전체" 탭 = 위치 기반 run 피드 (`GET /feed/nearby`, 2026-07-15) — 프론트 규약**:
> - **데이터소스 교체**: 홈 "전체" 탭은 이제 **`GET /feed/nearby?lat&lng&radius_km`**(위치 반경 내 public **run** 카드)로 붙는다. 기존 코스 피드(`GET /routes/public`)는 **폐기 아님** — 코스 탐색 등 다른 화면에서 계속 사용. 카드 shape는 활동 피드(`/feed/activities`)와 동일하므로 **run 카드 컴포넌트 재사용**.
> - **위치는 프론트가 전달**(크루 둘러보기와 동일 규약): 위치 권한 획득·좌표 확보는 **프론트 몫**, `lat`/`lng`를 쿼리로 보낸다(서버는 지오코딩 안 함, 한국 bbox 검증만). 권한 거부 시 프론트가 안내/기본 위치 UX를 결정. `lat`/`lng` 누락·한국 밖 좌표는 **400**.
> - **반경 확장은 프론트 재호출**: `radius_km` 기본 **10**, 사용자가 넓히면 **≤20**(초과는 서버가 20으로 clamp). **서버 자동 확장 없음** — 0건이면 `[]`를 받고, 프론트가 "반경 넓히기" CTA로 `radius_km`를 키워 **재요청**한다. 최신순 기본(인기순 등은 후속).
> - **프라이버시**: 계정을 비공개로 둔 유저는 개별 run이 public이어도 이 탐색 피드에 **안 뜬다**(본인·팔로우 중 유저·차단 상대도 제외). 즉 여기 뜨는 카드는 "공개 계정·비팔로우·반경 내"의 public run뿐.

> **크루 둘러보기 (당근식) — 프론트 규약 필독**:
> - **위치·행정구역·역지오코딩은 전부 프론트가 처리** — 서버는 검증·필터·정렬만 한다. GPS 좌표 → "성동구" 역지오코딩은 **프론트가 Kakao Local SDK(coord2regioncode)로 클라이언트 측 수행**하고, 크루 생성/수정 시 `lat`/`lng`/`sido`/`sigungu`를 body로 보낸다. (서버는 지오코딩 프록시를 제공하지 않음.)
> - **`sido` 표준 명칭 17개** (프론트 정적 목록·서버 Literal·DB CHECK가 이 문자열로 정확히 일치해야 필터 동작): `서울특별시`·`부산광역시`·`대구광역시`·`인천광역시`·`광주광역시`·`대전광역시`·`울산광역시`·`세종특별자치시`·`경기도`·`강원특별자치도`·`충청북도`·`충청남도`·`전북특별자치도`·`전라남도`·`경상북도`·`경상남도`·`제주특별자치도`. **`sigungu`는 자유 문자열**(예: `성동구`, `수원시`) — 프론트가 시군구 목록을 정적 보유해 표준 명칭으로 보낸다.
> - **`tags` 서버 정의 어휘 13종** (자유입력 아님 — 이 목록에서만, 저장 ≤5개·카드엔 2개): 시간대 `새벽`·`아침`·`저녁`·`야간`·`주말` / 지형 `평지`·`트레일`·`언덕` / 분위기 `입문환영`·`기록도전`·`친목`·`여성전용`·`페이스그룹`. 목록 밖 값은 422.
> - **조회**: `lat`+`lng`를 **둘 다** 보내면 각 크루까지 `distance_km`(1자리, "0.4km") 계산 + **거리 오름차순 정렬**(좌표 없는 크루는 distance_km=null·맨 뒤). `sido`/`sigungu`로 행정구역 필터. `include_full=false`(기본)면 정원 찬 크루 제외. `limit` 1~100(기본 50).
| **가입** | `POST /crews/{id}/join` | **상태 코드로 분기**: `200`=즉시 가입(`CrewResponse`, open 크루) / `202`=신청 접수(`JoinRequestResponse{status:"pending"}`, 승인제 크루). `409` = 이미 멤버 또는 `already_requested`(중복 신청). **이미 멤버면 `join_policy`와 무관하게 409가 최우선** — 승인 직후 등 어떤 타이밍에도 멤버에게 202가 가거나 pending이 생기지 않음(서버가 레이스까지 방어). 크루의 `join_policy` 필드(`open`/`approval`)로 버튼 라벨을 미리 정할 수 있음 ("가입하기" vs "가입 신청") |
| **내 신청 전체 목록** | `GET /me/join-requests?limit&offset` | `[{crew_id, crew_name, status, created_at, decided_at}]` 최신순, 기본 limit 50. **모든 크루의 신청을 한 번에** — 둘러보기 화면 "신청됨" 뱃지용. `status`는 pending/approved/rejected 전부 포함이므로 뱃지는 `pending`만 필터해서 사용 |
| 내 신청 상태 (크루별) | `GET /crews/{id}/join-requests/me` | `{status: pending\|approved\|rejected}` — 없으면 404. **거절은 알림이 안 오므로** 이 값으로 버튼 상태 결정: `pending`→"신청됨(취소)", `rejected`→"가입 신청"(재신청 가능), 404→"가입 신청" |
| 신청 취소 | `DELETE /crews/{id}/join-requests/me` | 204 멱등 (없어도 204) |
| 신청 목록 (크루장) | `GET /crews/{id}/join-requests?limit&offset` | `[{id, user_id, nickname, **avatar_url**, created_at}]` pending만 최신순 (avatar_url은 2026-07-15 additive — null이면 이니셜 폴백). 비크루장 403 |
| 신청 승인/거절 (크루장) | `POST /crews/{id}/join-requests/{rid}/approve` / `/reject` | 204. 승인 → 신청자에게 `join_approved` 알림 + 멤버 추가. 승인 시 정원 초과면 409(신청은 pending 유지). 이미 결정된 신청은 404 |
| 탈퇴/강퇴/양도 | `DELETE /crews/{id}/leave`, `DELETE /crews/{id}/members/{target_id}`, `PATCH /crews/{id}/transfer` | 강퇴는 **owner 또는 kick_members admin**(v2 — admin은 member만, admin/owner 대상 403). 양도(transfer)는 owner 전용 유지 |
| **운영진 role + 세부 권한 (v2, 2026-07-13~)** | `PATCH /crews/{id}/members/{uid}/role` `{role}` · **`PATCH /crews/{id}/members/{uid}/permissions`** `{announcements?,challenges?,edit_crew?,kick_members?,manage_admins?}` | **role 변경**: owner **또는 manage_admins admin**·멱등. 승격(→admin) 시 **시안 기본 permissions 자동 부여**(announcements·challenges ON, edit_crew·kick_members·manage_admins OFF), 강등 시 permissions null. target=owner **422**(transfer로만). **권한 5키(bool)** = 행동 가능 여부(role은 표시·정렬용, 판별은 role·행동은 permissions). 게이트: 공지 CRUD→`announcements` / 챌린지→`challenges` / **크루 수정·이미지→`edit_crew`**(v1 owner전용에서 이관) / 강퇴→`kick_members` / role·권한 변경→`manage_admins`. **owner는 전권 암묵**(멤버 응답에 all-true 합성). 권한 없는 admin 차단은 **403**. **owner 전용 유지**: 위임·크루 삭제·초대 코드·가입 신청 관리. **§3 위임 사슬**: manage_admins admin은 (a) **자기 보유 키만** 부여 (b) **주의 2키(kick_members·manage_admins)는 owner만** 부여 — 위반 403. 대상은 admin이어야(member 대상 422). 크루 상세(`GET /crews/{id}`)에 **`admin_count`**(관리 통계). **하위호환**: `role` 필드·기존 분기 무영향(permissions·admin_count는 additive) |
| **초대 코드 (크루장)** | `GET /crews/{id}/invite` (미발급 404 → POST로 발급), `POST /crews/{id}/invite` (생성/**재생성** — 이전 코드 즉시 무효, 유출 대응) | `{code}` — 8자 대문자+숫자 (I/O/0/1 없음). 카톡 등으로 공유 (딥링크 포맷은 라우팅 표 아래 참조). **⚠️ 소비 규칙: 재생성하면 구코드가 즉시 무효 = 이미 공유된 초대 링크도 함께 죽는다** — 재생성 버튼에 "기존 초대 링크가 무효화됩니다" 경고를, 무효 링크 수신자에겐 preview 404를 "만료된 초대예요"로 표시 |
| 코드 미리보기 | **`POST /crews/preview-by-code`** `{code}` (권장) · `GET /crews/preview-by-code?code=` (레거시) | 가입 확정 전 "어느 크루인지" 확인 — `CrewResponse` 반환. **비공개 크루도 조회됨** (코드 = 초대장). 잘못된 코드 404. **⚠️ POST 사용 권장** — GET은 코드가 URL 쿼리스트링 → 서버 access log에 평문으로 남음. 두 경로 동작·응답 동일하니 신규/변경은 POST(body)로 붙일 것 |
| **코드로 가입** | `POST /crews/join-by-code` body `{code}` | 200 `CrewResponse` (바로 크루 화면 이동). **join_policy·비공개 무관 즉시 가입** — 크루 생성 화면의 "비공개: 초대 링크로만 가입 가능해요"가 이 경로. 대소문자·공백은 서버가 정규화. 이미 멤버/정원 409, 잘못된 코드 404. 승인제에 신청해뒀던 pending은 자동 정리 |
| **인앱 개인 초대** (2026-07-13) | `POST /crews/{id}/invitations` body `{user_id}` | **크루원이면 누구나** 비크루원을 앱 내에서 초대 → 대상에게 `crew_invited` 알림(payload에 초대코드). **204**. 비크루원 발송자·차단 관계·없는 유저 **404 은닉**, 이미 크루원 **409**. 초대코드가 없으면 이 시점 자동 발급(크루 전체 코드). 수신자는 알림 딥링크(`payload.invite_code`)로 preview→join. 링크 공유 시트(`/invite`)와 병행 — 이건 **앱 내 지목 초대** |
| 멤버/랭킹 | `GET /crews/{id}/members`, `/crews/{id}/ranking` | 둘 다 **`avatar_url`**(없으면 null → 이니셜 폴백) 포함. 랭킹: 이번 주 KST 거리순, `me` 플래그. **visibility 무관** — 랭킹·챌린지 누적 거리는 `private` run도 포함(크루=활동 공유 원칙 + 거리 은닉 어뷰징 방지). visibility는 run 카드 노출만 제어, 집계 거리엔 영향 없음. **단 GPS 검증(verified) run만 집계** — 트랙 없는 수동 기록은 랭킹·챌린지 거리에 안 잡힘(UI에 "GPS 기록만 집계" 안내 권장). **멤버 응답에 `challenge_km`**(2026-07-13 additive): 현재 진행 챌린지에서 그 멤버의 기여 거리(km, verified 합) — **진행 챌린지 없으면 null**. ⚠️ **주간 랭킹 km와 별개 값**(랭킹=이번 주 월 KST 창 / `challenge_km`=챌린지 starts~ends 창) — 멤버 리스트에서 "챌린지 N km 기여" 뱃지에 그대로 사용, 랭킹 km와 혼동 금지 |
| **크루 러닝 피드** | `GET /crews/{id}/runs?limit&offset&session_only` | 크루원들의 최근 run, `ran_at` 최신순: `[{run_id, user_id, nickname, avatar_url, ran_at, title, distance_km, duration_sec, avg_pace_sec_per_km, route_id, route_summary, comment_count, is_crew_session, session_participant_count}]`. 크루원만(403). **visibility 적용**: `private`만 제외. 개인 메모/피드백 미포함, `route_summary`는 공개 코스만. 탈퇴·차단 멤버 run 자동 제외(v3.6). **⚠️ 정기런 세션(L1, 2026-07-13)**: `is_crew_session=true`면 **이 크루의 정기런 태그** → "정기런" 배지 + `session_participant_count`("N명 참여" — 같은 세션 distinct 참여자). **참여자 수 정책**: **verified 무관**(참석≠기록검증, 수동 러닝도 카운트)·**private 제외**(숨긴 참석 미노출)·**차단은 전역 카운트**(v3.6 "숫자는 전역, 명단은 L2"). 미태그 run은 `is_crew_session=false`·`session_participant_count=null`. **세션 상세("참여자 명단·기록 모아보기")는 L2**. **⚠️ `session_only`(bool, 기본 false, 2026-07-13 additive)**: 생략/`false`면 위 파이어호스(크루원 전원 활동, 기본 동작 불변). **`true`면 이 크루의 정기런(태그런)만** 반환 → 정기런 전용 탭. 이 뷰는 전부 태그런이라 **`is_crew_session`이 전부 true**(뷰 자체가 필터 — 의도된 동작, 배지 대신 탭 헤더로 대체 가능). 정렬·페이지네이션·private/차단 제외 필터 동일. **태그런 0건이면 빈 배열 `[]`(404 아님)**. 탈퇴 멤버 태그런은 현재-멤버 필터 공유로 미포함(카운트-목록 비대칭은 v3.6과 일관) |
| 챌린지 | `GET /crews/{id}/challenges/current`, `POST /crews/{id}/challenges` | 생성은 **크루장·운영진(admin)**. `achieved_km`, `progress_pct`, `is_completed` 실시간 계산. 생성 시 `starts_at`/`ends_at`은 **ISO 8601 + 타임존 필수** (아래 노트) |
| **공지 목록/상세** | `GET /crews/{id}/announcements?limit&offset`, `GET .../{announcement_id}` | `title`, `body`, `run_at`, `place_name/lat/lng`, `rsvp_open`, `rsvp{going,not_going,maybe}`, `my_rsvp`; 상세엔 `going_members[]` 명단 추가(`{user_id, nickname, avatar_url}` — avatar_url은 2026-07-15 additive, null이면 이니셜 폴백). 크루원만 조회 가능(403). 작성 시 `run_at`/`rsvp_closes_at`은 **ISO 8601 + 타임존 필수**. **집결 좌표 `place_lat`/`place_lng`**(집결지 미니맵·"지도 앱에서 보기"용, `place_name`=표시명과 병존 — 서버는 저장·서빙만, 프론트가 카카오/Apple 어느 쪽으로 선택하든 무관): **한국 bbox 검증**(lat 33~39·lng 124~132, 밖이면 422 — run 좌표와 동일 범위). 셋 다 optional(생략/기존 공지는 null → 미니맵 숨김) |

> **⚠️ 날짜·시각 필드는 타임존 필수 (프론트 필독)**: 챌린지 `starts_at`/`ends_at`, 공지 `run_at`/`rsvp_closes_at`은 **반드시 타임존 오프셋을 포함한 ISO 8601**로 보내세요 — `2026-07-07T20:00:00+09:00`(KST) 또는 `...Z`(UTC). **타임존 없는 `2026-07-07T20:00:00`은 422**로 거부됩니다 (서버가 UTC로 오해석하면 KST 의도가 9시간 밀리기 때문). 에러 메시지에 "timezone" 안내가 포함됩니다.
| 공지 작성/수정/삭제 | `POST/PATCH/DELETE /crews/{id}/announcements...` | **크루장·운영진(admin)**. 작성 시 크루원 전체 알림, 수정은 알림 없음 |
| **크루 채팅** (v1·v1.5) | `GET/POST /crews/{id}/chat/messages`, **`POST /chat/share-run`**, `GET /chat/unread`, `POST /chat/read`, `POST/DELETE /chat/messages/{mid}/react`, `DELETE /chat/messages/{mid}`, `PATCH /chat/mute` | **크루원 전용**(비크루원 404 은닉). **폴링** — 활성 화면 20~30초 주기 권장(Realtime 아님). 목록은 **역순 커서**(`before=<가장 오래된 created_at>`, /runs와 동일 규칙 — `+`는 인코딩/`Z`). 메시지: `reactions{이모지:수}`·`my_reactions[]`·`deleted`(soft)·`sender_nickname/avatar_url`(탈퇴 시 null). 반응 **👍🔥👏💪 4종 고정**(그 외 422)·멱등 토글. `unread`는 배지용(본인 메시지 제외)+`muted`. **삭제: 본인 or 운영진**(soft — content null, 행 잔존). **방별 mute**는 전역 알림과 독립(채팅 푸시 발송 자체가 v2라 지금은 배지에 무영향). **↓ 메시지 `type` 3종 렌더 분기(v1.5)** |
| ↳ **차단 메시지 (v3.5)** | 차단 관계 발신자 메시지 | **`blocked:true`**면 서버가 `content`·`payload`·`sender_nickname`·`sender_avatar_url`를 **null로 보냄**(내용·신원 자체를 서버가 가림 — 클라 필터 아님). 프론트는 **"가려진 메시지" 플레이스홀더** 렌더. **반응 집계(`reactions`)는 유지**(카운트 왜곡 방지), **새 반응 추가는 404**. 랭킹·명단은 차단 무시(잔존), 크루 피드 카드는 차단 상대 run 제외 |
| ↳ **채팅 메시지 type 소비 규칙** | 메시지의 `type` 필드로 프론트 렌더 분기 | **`text`**: 일반 말풍선(`content`=본문, `deleted:true`면 "삭제된 메시지"). **`system`**: 가운데 정렬 시스템 배너 — `content`는 **렌더 키**(현재 `"announcement"`), 문구는 **프론트가 키로 조립**(다국어·문구 변경이 서버 배포 불요), `payload={announcement_id, title}`로 **공지 딥링크**. `sender_id`는 작성 운영진(표기용, null 아님)·**반응 가능·삭제 불가**(누구도, 403). **`run_share`**: 기록 카드 — `content`=캡션(nullable), `payload`=**전송 시점 스냅샷 박제**(`run_id, distance_km, duration_sec, avg_pace_sec_per_km, title, area, ran_at, polyline_thumb, photo_thumb`). **원본 삭제·비공개 전환돼도 카드 요약은 잔존**(카톡 선례). `photo_thumb`는 **경로**(서명 URL 아님) — 이미지는 상세 진입 시 권한 서명 URL로만. **카드 탭 → `GET /runs/{run_id}`는 현재 권한 재평가**(삭제·비공개면 404 — 요약은 보이되 상세는 현재 권한). `notes` 등 개인 필드는 미박제 |
| ↳ **기록 카드 공유** | `POST /crews/{id}/chat/share-run` `{run_id, caption?}` | **본인 run만**(타인 run·없음 404 은닉), **`public`·`followers`만**(private run 422). 201로 `run_share` 메시지 반환. 반응 가능·삭제는 본인/운영진(text와 동일) |
| **참석 투표** | `PUT /crews/{id}/announcements/{aid}/rsvp` | body: `{"status": "going"\|"not_going"\|"maybe"}` → 204. 재투표=덮어쓰기 |
| **원격 푸시 (Expo)** | `POST /me/push-token` body `{token, platform}` / `DELETE /me/push-token` body `{token}` | **앱 계약**: ① 로그인 후 `expo-notifications` 권한 요청 → `getExpoPushTokenAsync()` → POST(앱 시작마다 호출해도 **멱등**, 토큰 갱신 리스너에서도 재호출) ② 로그아웃 시 DELETE(실패해도 로그아웃 진행 — 서버가 죽은 토큰 자동 정리) ③ **푸시 탭 시 `data`의 `type/target_id/target_type/payload`로 아래 딥링크 라우팅 표 재사용**(인앱 탭 핸들러 공유). 형식 밖 토큰 422. 발송은 알림 생성 시 자동(본문은 닉네임+행위만 — 콘텐츠 내용 미포함). **카테고리별 푸시 끄기는 `PATCH /me/settings`의 `notif` 그룹(v1) — 아래 "푸시 알림 설정" 참고** |
| 알림 | `GET /notifications`, `GET /notifications/unread-count`, `PATCH /notifications/read-all`, `PATCH /notifications/{id}/read`, **`DELETE /notifications/{id}`**(스와이프 삭제 — 본인 것만, 없음/남의 것 404, 성공 204), **`DELETE /notifications`**(모두 지우기 — 멱등, 0건이어도 204) | 각 항목: `type`·`actor_nickname`·**`actor_avatar_url`**(null=이니셜 폴백)·`target_id`·`target_type`·**`payload`**(딥링크 보조 jsonb, 없으면 null). **탭 시 목적지·사용 필드는 아래 "딥링크 라우팅 표"를 그대로 따를 것** |

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
> | `follow_requested` | user | **팔로우 요청 목록**(또는 요청자 프로필) | `target_id`(=requester_id) |
> | `follow_request_approved` | user | 승인해준 유저 프로필 | `target_id`(=승인자 id) |
> | **`crew_announcement`** | announcement | 크루 공지 (`/crews/{crew_id}/…`) | **`payload.crew_id`** (target_id는 공지id) + `target_id`(=공지id) |
> | **`pb_achieved`** | run | **내 run 상세** (자기 자신 대상) | `target_id`(=run_id) → `GET /runs/{id}`. `payload.record_types[]`(경신 종류: best_pace·best_5k·longest_distance·longest_duration) |
> | **`crew_chat`** (2026-07-15) | crew | **크루 채팅 화면** | `target_id`(=crew_id) → 채팅 방. 발신자 제외·크루원에게 발송. **인앱은 매 메시지 생성, 푸시는 5분 스로틀**(크루×수신자 — 5분 내 1건)·크루 뮤트·`notif.crewChat` OFF면 푸시만 스킵(인앱 유지). 문구는 닉네임+행위만(본문 미포함) |
> | **`crew_invited`** | crew | **크루 초대 확인 모달**(preview→join) | **`payload.invite_code`** → `POST /crews/preview-by-code` 확인 후 `POST /crews/join-by-code`. `payload.crew_name`·`target_id`(=crew_id) 참고. 초대 = 사전 승인이라 join 시 비공개·승인제 무관 즉시 가입 |
>
> **⚠️ `pb_achieved`는 유일한 '자기 자신 대상' 알림**(수신자==행위자) — 저장 직후 PB 모달(POST /runs 응답 `new_records`)과 별개로 알림함에도 남고, 앱 밖일 때 푸시로 알린다(2026-07-13). 푸시 문구는 경신 종류별(단일: "최고 페이스 경신! ⚡" 등 / 복수: "새 기록을 세웠어요! 🎉"). `notif.pb` 토글로 푸시 끄기(인앱은 유지). `actor_nickname`은 본인이라 렌더 생략 권장.
>
> **주의**: `crew_announcement`는 target_id가 공지id라 **crew_id는 `payload`에만** 있다. `payload.crew_id`가 없으면(2026-07-08 이전 발송분) 크루로 못 가니 폴백으로 무시하거나 크루 목록으로 보낸다. 그 외 type은 target_id만으로 라우팅 가능 — payload 불필요.
>
> **크루 초대 링크 (위 표와 성격 다름 — 알림이 아니라 유저 공유 링크)**: `freshrun://crew-invite?code=XXXXXXXX` (2026-07-09 확정). 발신은 **클라이언트 공유 시트**(서버는 코드만 제공 — `GET·POST /crews/{id}/invite`), 서버가 이 링크를 발송하는 일은 없다. **수신 앱 처리**: `code` 추출 → `POST /crews/preview-by-code`로 크루 확인 모달 → 유저 확인 후 `POST /crews/join-by-code`.

### 프로필

| 데이터 | 메서드/경로 | 주요 응답 필드 |
|---|---|---|
| 내 정보 | `GET /me` (auth 확인), `GET /me/profile` | `nickname`, `avatar_url`, `bio`, `tier` + **신체 정보 4종** `birth_year`/`weight_kg`/`height_cm`/`gender` — **본인 조회에만 존재** (다른 유저가 보는 모든 응답에 절대 미포함). 체중은 칼로리 로컬 계산용 |
| 프로필 생성/수정 | `PATCH /me/profile` | **부분 PATCH — 보낸 필드만 갱신, 생략은 유지.** `nickname`(2~20자, 중복 시 409) + 신체 정보 4종 + **`visibility`**(public/followers/private — 계정 공개범위, 비공개면 비팔로워에게 잠금) + `follow_approval` 전부 optional. **⚠️ 공개범위 토글만 보내면 됨: `{"visibility":"private"}` 단독 200**(2026-07-12~. 이전엔 nickname 필수라 단독 전송이 422로 실패 → 저장 안 됨. 그 "nickname 동봉" 계약 폐지). **단 최초 프로필 생성(신규 유저)만 `nickname` 필수**(없으면 422 — 생성 분기). **nickname 명시 null·`""`·1자는 422**(닉네임은 삭제 개념 없음 — 생략으로 유지). **아바타 삭제 = `{"avatar_url": null}`**(명시 null → DB null + Storage 파일 삭제, 성공 후 프론트는 캐시된 URL 폐기. **필드 생략은 유지, `""`는 422** — "PATCH 명시 null = 삭제" 시맨틱의 선례 필드). 범위: birth_year 1920~2026, weight 20~300, height 100~250, gender `female`\|`male`\|`undisclosed`(시안: 여성/남성/선택 안 함). `bio`≤500자, `avatar_url`≤500자. 범위·길이 밖 422. **미지/오타 필드도 422**(2026-07-13 extra 금지 — `visibilty` 같은 오타로 프라이버시 토글이 silent 무시되던 갭 봉쇄. `PATCH /runs`도 동일). **tier는 보내면 422** (extra 금지 — 미지 필드. 관리자/IAP 전용이라 스키마에 없음. 구계약 "무시됨"은 2026-07-13 M-7 forbid로 강화) |
| **아바타 업로드** | `POST /me/avatar/upload-url` | **3단계 흐름**: ① 이 엔드포인트 호출 → `{upload_url, public_url, max_bytes, allowed_types}` ② 이미지 바이트를 `upload_url`에 **PUT** (Content-Type 필수 — jpeg/png/webp만, 5MB 상한은 Storage가 거부) ③ `public_url`을 `PATCH /me/profile`의 `avatar_url`로 저장 — **CDN 캐시 무효화를 위해 `?v=타임스탬프`를 붙여서**. 경로는 유저당 고정이라 재업로드가 자동 덮어쓰기 (옛 파일 잔여 없음). **⚠️ 업로드 전 클라이언트 재인코딩 + EXIF(GPS 좌표) 제거 필수 — 러닝 사진과 동일 하드룰**(서명 URL 직접 업로드라 서버 미경유, **아바타는 public 버킷이라 URL만 알면 누구나 원본을 받으므로 특히 중요**) |
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
                   "announce_calories": false }, // 안내 항목 (프론트 로컬 낭독)
  "feed": { "auto_publish": true,     // 프로필 설정 화면 (2026-07-12). OFF면 POST /runs의
                                      //   visibility 미지정 시 기본 private (명시값은 존중)
            "allow_likes": true,      // OFF면 내 run/코스에 타인 좋아요·kudos 403 likes_disabled
            "allow_comments": true }  // OFF면 내 run/코스에 타인 댓글 403 comments_disabled
}
```
> **피드 설정 강제 (서버측)** — `allow_likes/comments` OFF면 **타인**의 kudos/좋아요·댓글이 **403 구조화**(`{error: likes_disabled|comments_disabled, message}`)로 거부됩니다(내 콘텐츠엔 항상 가능). 프론트는 이 403을 받으면 버튼 비활성 + 안내("이 사용자는 좋아요를 받지 않아요"). **404가 아닌 403인 이유**: 콘텐츠는 이미 보이는 상태(가시성 통과)라 존재 은닉 대상이 아님 — 반대로 **안 보이는 run은 설정 게이트 전에 404**(은닉 우선). `auto_publish` OFF는 저장 화면 기본 공개범위만 바꿉니다(visibility 슬라이더를 명시하면 그 값 우선). 기존 유저는 3키 전부 기본 true라 동작 변화 없음. 토글 위치는 프로필 설정 화면.
>
> **`allow_likes`·`allow_comments` 렌더 힌트 (2026-07-13 additive)** — 위 403을 **사전에 피하는** 힌트를 3곳 응답에 노출: **① `GET /users/{id}/profile`**(공개 프로필) **② `GET /runs/{id}`**(타인·본인 상세) **③ `GET /feed/activities`**(활동 피드 아이템). 값은 **소유자 설정 그대로**(bool 2개, 본인 응답에도 참값). **소비 규칙**: `false`면 해당 **버튼(좋아요/댓글) 렌더를 생략** — 눌러서 403 받기 전에 숨기는 게 UX 정석. **403은 레이스 폴백**(힌트 받은 뒤 소유자가 설정을 바꾼 찰나) — 여전히 403 처리는 유지하되 평소엔 힌트로 미리 숨김. **⚠️ 잠금 프로필(`locked:true`) 응답엔 두 필드 `null`** — 잠긴 계정엔 좋아요/댓글 affordance 자체가 없어 무의미(렌더 대상 아님). 신규 엔드포인트 없음(아바타 필드 선례 — 응답 필드만 additive).

> **푸시 알림 설정 (`settings.notif`, 시안 FrNotifSettings v1)** — `PATCH /me/settings {"notif":{"likes":false}}`처럼 카테고리별 토글. **키 12종**(camelCase 그대로): `master`(마스터 스위치)·`crewChallenge`·`crewNotice`·`crewChat`·`crewJoin`·`likes`·`comments`·`followers`·`runReminder`·`weekly`·`pb`·`marketing`. **기본 전부 ON**(`marketing`만 OFF) → 기존 유저 동작 변화 0.
>
> **게이트 대상은 푸시만** — **인앱 알림(`GET /notifications`)은 이 설정과 무관하게 항상 생성**됩니다. 설정은 원격 푸시(Expo) 발송 여부만 제어. `master` OFF면 전 카테고리 푸시 스킵, 아니면 알림 type의 카테고리 토글을 확인해 스킵/발송.
>
> **알림 type → 카테고리 매핑** (프론트가 "무엇을 끄면 무엇이 안 오는지" 안내용):
> | 카테고리 | 꺼지는 푸시 |
> |---|---|
> | `likes` | 코스 좋아요·러닝 응원(kudos) |
> | `comments` | 코스·러닝 댓글 |
> | `followers` | 팔로우·팔로우 요청·요청 수락 (팔로우 관계 알림 전부 — 승인제 2종 포함, 전용 토글 없이 이 계열로 묶임) |
> | `crewJoin` | 크루 가입·가입 신청·신청 승인·(크루 초대) |
> | `crewNotice` | 크루 공지 |
> | `crewChallenge` | 크루 챌린지 달성 |
> | `crewChat` | 크루 채팅 *(발송은 채팅 v2 — 토글은 선반영)* |
>
> **발송 주체가 아직 없는 토글**: `runReminder`·`weekly`·`pb`(러닝 리마인더·주간 리포트·개인기록 축하)와 `marketing`은 **키는 저장되지만 현재 서버 발송 기능이 없습니다** — 프론트는 토글을 노출·저장하되 "예약 알림은 준비 중" 정도로 두면 됩니다. **각 발송 기능이 생기는 사이클에서 이 토글에 게이트를 연결**할 예정(PB는 러닝 저장 시 감지 가능 → 백로그 소품).
>
> **theme/lang 구현 힌트**: 로컬 캐시 + 서버 동기화 권장 — 첫 프레임(로그인 전·오프라인)은 AsyncStorage 캐시로 그리고, 로그인 후 `GET /me/settings` 값으로 갱신하세요.
>
> **ai_course/weather는 실제 파이프라인에 반영됩니다** (전 티어 공통, 무료 포함 — 2026-07-09 티어 결정 ⓐ 확정: 생성 기능이 free 주3회로 열려 있어 설정도 개방, 차등은 쿼터로. 시안의 프리미엄 잠금은 제거됨·설정 UI도 전 티어):
> - `ai_course` → `POST /routes/generate`가 body에 없는 필드의 기본값으로 사용 (우선순위: body > 설정 > 서버 기본값, §홈 표 참고).
> - `weather` → `GET /weather`의 `running_index.comment`가 내 기준(`avoid_dust`/`dust_level_pm10`, `avoid_heat`/`heat_temp_c`, `avoid_rain`)을 넘으면 개인화되고 `personalized: true`가 됩니다. 복수 기준 초과 시 미세먼지 > 더위 > 비 순으로 하나만 표시. `score`/`label`은 공용 기준 그대로.

> **아바타 필드 일람 (2026-07-11 additive)**: `PublicRouteResponse.owner_avatar_url` · run/route 댓글 `avatar_url` · 크루 멤버/랭킹 `avatar_url` · 알림 `actor_avatar_url` · 공지 `author_avatar_url` · **가입 신청 목록 `avatar_url` · 공지 상세 `going_members[].avatar_url`(2026-07-15 마감 — 이로써 멤버성 표면 전부 커버)** — 전부 **없으면 null → 이니셜 폴백**(기존 관례). 탈퇴 작성자가 남긴 공지는 `author_nickname`과 함께 avatar도 null.

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
