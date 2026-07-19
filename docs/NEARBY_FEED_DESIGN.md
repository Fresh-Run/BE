# NEARBY_FEED_DESIGN — 홈 "전체" 탭 = 위치 기반 public run 탐색 피드

> 상태: **구현 완료**. 2026-07-15. 확답 A~D 반영(bbox+haversine·radius≤20·
> 시간윈도 무제한·트랙 보유 전량 백필).
>
> **오너 룰링 (2026-07-20, TF 리포트 후 현행 유지 확정 — 코드 변경 0)**:
> **비공개 계정(profile `followers`/`private`)은 탐색 피드에서 완전 은닉** —
> 개별 run을 public으로 올려도 안 뜬다. run별 공개설정은 "프로필 내 공개
> 범위"로 해석(계정 잠금이 상위 게이트, `/routes/public` 코스 정책과 일관).
> 베타 피드백 시 재검토.
> SQL: `db/2026-07-15_run_start_coords.sql`(실행 완료 — 컬럼2·부분인덱스·백필 동수·누락0).
> 구현: `run_service.list_nearby_feed`·`create_run` 좌표 자동채움 · `GET /feed/nearby`
> (routes.py) · `tests/test_nearby_feed_integration.py`(전 매트릭스 통과).
> fly deploy는 오너 지시 대기.

## 0. 배경·목표

- **현행**: 홈 "전체" 탭 = 공개 **코스** 피드(`GET /routes/public`, 커밋 82fb401).
  오너 제품 정의(위치 반경 내 실제 러닝)와 어긋남 — 진단으로 확정.
- **오너 스펙(확정)**: 홈 "전체" 탭 = **내 위치 반경 10km 이내 + visibility=public
  run만 + 본인 제외 + 이미 팔로우 중인 유저 제외**.
- **교체 범위**: 홈 "전체" 탭의 데이터소스를 이 신규 피드로 교체. **코스 피드
  엔드포인트(`/routes/public`)는 존치**(다른 서피스가 계속 소비).
- **위치 반경 선례**: `GET /routes/nearby?lat&lng&radius_km`(코스, clamp≤50) ·
  크루 둘러보기 `radius_km≤20`. run에는 위치 필터·컬럼 **전무**(진단).

## 1. 스키마 — runs 위치 컬럼 (실사 → additive)

### 실사 결과 (information_schema/PostgREST 실조회)
- `runs` 컬럼: `area`(text, 행정동명 — 역지오코딩 프론트 처리), `visibility`,
  `ran_at`, `user_id`, … — **인덱싱 가능한 좌표 컬럼 없음**.
- GPS 궤적은 별도 `run_tracks.points`(jsonb, `[{lat,lng}...]`). `points[0]` =
  **출발 좌표**(예: `{'lat':37.510881,'lng':126.995595}`).
- 규모: 전체 run 36 · public 27 · 트랙 보유 34 → **베타 소규모**(bbox 근사 적정).

### 설계: additive 2컬럼 + 백필 + 저장경로 자동 채움
- `runs.start_lat double precision null` / `runs.start_lng double precision null`
  (nullable — 트랙 없는 run은 null → 피드 자동 미노출).
- **백필**: `run_tracks.points[0]`의 lat/lng를 대응 run에 채움(트랙 34건 대상).
  트랙 없는 run(수동 기록)은 null 유지.
- **저장 경로 자동 채움**: `run_service.create_run`에서 run insert record
  (:158~173)에 `start_lat/start_lng`를 `processed.polyline[0]`에서 세팅
  (트랙 있을 때만; `processed is None`이면 null). 트랙 저장(:197~209)과 **같은
  create_run 안**이라 원자적 — run insert 시점에 좌표가 함께 박힘.
- **좌표 백필 범위**: 트랙 보유 run **전부**(visibility 무관) 백필. public만
  채우면 나중에 followers→public 전환 run이 좌표 없이 누락됨. 34건 소규모라
  전량 백필이 안전(피드 노출 게이트는 쿼리의 `visibility='public'`이 담당).

### 인덱스
- 부분 인덱스: bbox 범위 스캔 대상만 인덱싱.
  ```
  create index runs_nearby_idx on runs (start_lat, start_lng)
    where visibility = 'public' and start_lat is not null;
  ```
- 정렬(`ran_at desc`)은 후단 — 소규모라 범위 스캔 후 정렬 비용 무시 가능.
  스케일 시 `(visibility, ran_at)` 보조 인덱스 고려(문서화만).

## 2. SQL 초안 ([APPLY]/[ROLLBACK] — 승인 후 db/로 이관·실행)

```sql
-- 위치 기반 public run 탐색 피드: runs 시작 좌표 2컬럼 + 백필 + 부분 인덱스.
-- 승인 후 db/2026xxxx_nearby_feed.sql 로 이관해 사용자가 실행.

-- [APPLY]
alter table public.runs add column if not exists start_lat double precision;
alter table public.runs add column if not exists start_lng double precision;

-- 백필: run_tracks.points[0] → runs.start_lat/lng (트랙 보유분 전량)
update public.runs r
set start_lat = (t.points->0->>'lat')::double precision,
    start_lng = (t.points->0->>'lng')::double precision
from public.run_tracks t
where t.run_id = r.id
  and r.start_lat is null
  and jsonb_array_length(t.points) > 0;

create index if not exists runs_nearby_idx on public.runs (start_lat, start_lng)
  where visibility = 'public' and start_lat is not null;

-- [ROLLBACK]
-- drop index if exists public.runs_nearby_idx;
-- alter table public.runs drop column if exists start_lng;
-- alter table public.runs drop column if exists start_lat;
```

- idempotent(`if not exists`, 백필은 `start_lat is null` 가드).
- RLS: `runs`는 기존 테이블(이미 enable됨) — 컬럼 추가는 정책 무관.
- `runs`에 신규 알림 타입/CHECK 없음 → 제약 재작성 불요.

## 3. 엔드포인트 계약

| method | 경로 | 응답 |
|---|---|---|
| GET | `/feed/nearby?lat&lng&radius_km&limit&offset` | `ActivityFeedItem[]` |

- **파라미터**: `lat`·`lng`(필수, 한국 bbox 검증), `radius_km`(기본 **10**,
  clamp **≤20** — 크루 선례 정합), `limit`(기본 20, 1~100 clamp),
  `offset`(기본 0).
- `lat`/`lng` 누락 → **400**(`/routes/nearby` 선례와 동형). 한국 bbox
  (lat 33~39, lng 124~132) 밖 → 400.
- **응답 shape = `/feed/activities`와 동일**(`ActivityFeedItem` — run_id,
  user_id, nickname, avatar_url, ran_at, title, distance_km, duration_sec,
  avg_pace_sec_per_km, route_id, route_summary, comment_count, is_mine,
  kudos_count, my_kudos, is_crew_session, session_participant_count, visibility=null).
  → **프론트 run 카드 컴포넌트 재사용**.
- **경로 순서**: `/feed/nearby`는 고정 경로 — 기존 `/feed`·`/feed/activities`
  옆에 선언(패턴 경로 없음, 충돌 없음).
- **정렬**: `ran_at desc`(최신순 기본, 오너 비요구 9 — 인기순 등 후속).

## 4. 지오 쿼리 방식 — bbox 근사 (PostGIS 없이)

1. **bounding box 계산**(서버): 위도 1도≈111km, 경도 1도≈111km·cos(lat).
   `dlat = radius_km/111`, `dlng = radius_km/(111*cos(lat))`.
   → `start_lat between lat-dlat and lat+dlat` AND `start_lng between …`.
   btree 부분 인덱스로 범위 스캔.
2. **정확 거리 후필터(권장, 확답 지점 A)**: bbox는 정사각형 → 모서리는 반경의
   최대 √2배(10km→~14km)까지 포함. "반경 10km 이내"에 충실하려면 후보에
   haversine 후필터로 원형 컷. 소규모라 비용 무시 가능. **또는** bbox만으로 근사
   (오너 point 3 "단순 우선") — 아래 §11 A 확답.
3. **PostGIS 트리거(문서화만)**: run 수가 수만~수십만으로 커지면 `geography`
   컬럼 + `ST_DWithin` + GiST 인덱스로 전환. 베타에선 불요.

## 5. 필터 합성 (순서 + 프라이버시 핵심)

쿼리 파이프라인(순서대로):
1. `visibility = 'public'` (followers/private 제외 — 오너 스펙).
2. `start_lat/start_lng` bbox 범위(§4) — NOT NULL 암묵 포함(트랙 없는 run 제외).
3. `user_id != viewer` (본인 제외).
4. `user_id NOT IN (내가 팔로우 중인 user_id 집합)` (팔로우 유저 제외 —
   `follows.follower_id=viewer` 조회).
5. (선택) haversine 후필터 (§4-2).
6. `ran_at desc` 정렬 + limit/offset.
7. **owner 가시성 필터 — `visible_owners(viewer, owner_ids)`**: 차단(양방향)
   제외 + **비공개 계정 owner 제외**(결정 A′ 기존 패턴, `/routes/public`과 동형).

### 프라이버시 핵심 — 비공개 계정의 public run 누출 차단
- 4번(팔로우 제외)으로 이미 팔로우 유저는 빠지고, 7번 `visible_owners`가
  **비팔로우 비공개 계정을 추가 제외**한다. 순효과: **공개 계정·비팔로우·비차단
  owner의 public run만** 남음.
- 즉 "계정을 비공개로 두고 개별 run만 public"으로 올린 유저는 **탐색 피드에
  노출되지 않는다**(계정 프라이버시 우선 — `/routes/public` 코스 정책과 일관).
  이것이 이 기능의 프라이버시 계약 핵심.
- **차단 양방향**: 내가 차단했거나 나를 차단한 owner의 run 미노출(`visible_owners`
  내부 `blocked_ids_batch`).

## 6. 엣지 케이스

- **반경 내 0건** → 빈 배열 `[]`(프론트 빈 상태). **서버 자동 반경 확장 없음**
  (오너 비요구 9). 프론트가 `radius_km`를 키워 재요청.
- **트랙 없는 public run**(수동 기록, start_lat null) → bbox 범위에서 자연 탈락.
- **bbox 경계**: `between`은 양끝 포함 — 경계 좌표 run 포함(테스트로 검증).
- **경도 cos(lat) 0 division**: 한국 위도(33~39)에서 cos>0.77 → 안전. bbox 검증이
  극점 좌표를 애초에 400으로 막음.
- **좌표 정밀도**: double precision 저장, 6자리(≈0.1m)면 충분(백필 소스도 6자리).
- **팔로우 0명**: 4번 NOT IN이 공집합 → 전체 public 후보 유지(정상).

## 7. 테스트 계획 — `tests/test_nearby_feed_integration.py`

매트릭스(임시 유저 생성 → GPS run 저장 → assert → 정리):
| # | 시나리오 | 기대 |
|---|---|---|
| 1 | 반경 5km 내 타인 public run | **노출** |
| 2 | 반경 밖(예: 15km) public run | **제외** |
| 3 | 반경 내 followers run | **제외**(visibility 게이트) |
| 4 | 반경 내 private run | **제외** |
| 5 | 본인 public run(반경 내) | **제외**(본인 제외) |
| 6 | 내가 팔로우 중인 유저의 반경 내 public run | **제외**(팔로우 제외) |
| 7 | 나를 차단 / 내가 차단한 owner의 public run | **제외**(visible_owners) |
| 8 | 비공개 **계정**(profile private)의 public run, 비팔로우 | **제외**(프라이버시 핵심) |
| 9 | 트랙 없는(start_lat null) public run | **제외** |
| 10 | bbox 경계 좌표 run | 포함(경계 검증) |
| 11 | (haversine 채택 시) bbox 안·원 밖 모서리 run | **제외** |
| 12 | 페이지네이션(limit/offset) | 중복·누락 없음 |
| 13 | lat/lng 누락 / 한국 bbox 밖 | **400** |
| 14 | 반경 내 0건 | `[]`(200) |

- **프라이버시 이중검증**(8번): 응답에 그 run_id 부재 **+** 그 유저 닉네임·트랙
  문자열이 응답 전체에 부재.
- DB 부수효과: 백필 후 `start_lat` NOT NULL 개수 assert. POST /runs 후 해당 run
  `start_lat`가 트랙 첫점과 일치 assert.

## 8. 프론트 계약 변경 (Ivan 전달 재료)

- **홈 "전체" 탭 데이터소스 교체**: `GET /routes/public`(코스) →
  **`GET /feed/nearby?lat&lng&radius_km`(run)**. 카드 = run 카드(`/feed/activities`와
  동일 shape) — 기존 run 카드 컴포넌트 재사용.
- **위치 파라미터 필수**: 프론트가 위치 권한 획득 후 `lat`/`lng` 전달(카카오/지역
  기능과 동일 관례 — 서버는 지오코딩 안 함, bbox 검증만). 권한 거부 시 프론트가
  안내/기본 위치 UX 결정.
- **radius_km**: 기본 10, 사용자가 넓히면 ≤20. 0건이면 빈 상태 + "반경 넓히기" CTA.
- **코스 피드는 폐기 아님**: `/routes/public`·`/feed`는 그대로 — 다른 화면(코스
  탐색 등)에서 계속 사용 가능.

## 9. 비요구 (스코프 밖 — 발명 금지)

- 서버 자동 반경 확장 **없음**(프론트가 radius_km 조절).
- 정렬은 **최신순 기본**(인기순·거리순은 후속).
- 코스 피드 **폐기 아님**(엔드포인트 존치).
- 시간 윈도(최근 N일) — 오너 미언급. v1은 무제한(확답 지점 C).

## 10. 하위 호환

- `runs.start_lat/lng`는 nullable additive — 기존 run·응답 계약 불변.
- `/feed/nearby`는 신규 경로 — 기존 엔드포인트 동작 무변경.
- `ActivityFeedItem` 재사용 — 신규 스키마 없음.

## 11. 확답 필요 지점 (오너 검토)

- **A. bbox-only vs bbox+haversine 후필터**: "반경 10km"를 정확한 원으로 볼지
  (haversine 후필터, 모서리 ~14km run 컷) vs 정사각형 근사 허용(단순, 오너 point 3
  성향). **추천: bbox+haversine**(비용 무시 가능·"반경"에 정직). 원치 않으면
  bbox-only.
- **B. radius_km 상한**: 크루 선례 정합 **≤20** 추천. 다른 값 원하면 지정.
- **C. 시간 윈도**: 탐색 피드에 오래된 run도 노출할지 vs 최근 N일 컷.
  오너 미언급 → **v1 무제한** 추천(발명 금지), 후속에서 재검토.
- **D. 좌표 백필 범위 재확인**: 트랙 보유 run **전량**(visibility 무관) 백필 추천
  (전환 대비). public만 원하면 축소.
