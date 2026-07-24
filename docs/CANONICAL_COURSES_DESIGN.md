# 캐노니컬 코스 레이어 — 설계 (2026-07-24)

> 오너 통찰: **"러너는 아는 코스를 뛴다. 집 앞 호수공원 4.8km를 두고 조립 루프를 주는
> 건 에바"**(실사용 리포트). 검증된 실명 코스가 있으면 생성 풀보다 **우선** 서빙한다.

## 1. 개념

생성(Gemini+앵커)은 "새 코스 조립"이다. 그러나 러너는 대개 **집 앞의 아는 코스**
(청라호수공원 순환·석촌호수 등)를 반복해 뛴다. 이 레이어는 **큐레이션된 실코스 DB**를
두고, 시작점이 그 코스 진입권 안이면 **생성 대신 그 코스를 서빙**한다. 미스면 현행 생성
폴백(무변경). 실명 노출은 **발명이 아니라 DB 조회**라 중립 라벨 원칙(§v78)과 충돌 없음
(오너 룰링) — 카드 제목만 실명, waypoint 라벨은 중립 유지.

## 2. 스키마 — `canonical_courses`

| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | uuid pk (gen_random_uuid) | |
| name | text not null | 실명 카드 제목 — "청라호수공원 순환" |
| region | text | 필터/관측용 — "청라" |
| distance_km | numeric not null | 코스 순환 실측(T-map 스냅) |
| polyline | jsonb not null | `[[lat,lng],…]` 코스 궤적(그리기용) |
| access_points | jsonb not null | `[[lat,lng],…]` 진입 좌표들(둘레 균등 대표점) |
| active | boolean default true | 소프트 토글 |
| created_at | timestamptz default now() | |

- **RLS enable**(정책 없이 — deny-by-default 백스톱, §C 표준. 앱은 service_role만).
- 시드는 **큐레이션**(지금). 장기는 run 히트맵 파생(설계 (다) 기존 항목과 접속 — 실제
  많이 뛴 궤적을 클러스터링해 자동 등재). 슬라이스 1은 큐레이션 1호만.

## 3. 매처 (생성 풀보다 우선)

`canonical_service.match_and_build(start, target_km)` — **loop 요청(end 없음)만**:
1. `active` 코스 로드(get_supabase_admin, `asyncio.to_thread`). 소형 테이블.
2. 각 코스: 시작점에서 **최근접 access_point** 거리 `d`. `d ≤ _ACCESS_RADIUS_M(800m)`.
3. 진입 왕복 추정 `access_rt ≈ 2·d·1.3`(직선×스냅팽창). **`|distance_km + access_rt −
   target| ≤ _CANONICAL_BAND_KM(0.6)`** 이면 후보.
4. 후보 중 `|총거리 − target|` 최소 채택. 히트 시:
   - 진입 leg **T-map 스냅**(home→access, access→home) + 코스 polyline **스티치**.
   - `summary = 코스 실명`, waypoints=[출발·진입·복귀](중립 라벨), polyline=스티치 궤적.
   - `total_distance_km = 진입out + distance_km + 진입back`(스냅 실측).
   - `gen_meta.engine="canonical"`, `course_id`·`course_name` 관측.
5. 미스(후보 0 또는 스냅 실패) → **현행 생성 폴백**(무변경, best-effort — 캐노니컬 예외가
   생성을 막지 않는다).

**밴드 근거**: 코스는 고정 거리라 조준 불가 — 아는 코스 서빙 가치가 정확거리보다 우선
(오너 통찰). ±0.6km는 4.4~5.6 코스가 5.0 요청에 매칭. `target_missed`는 정직하게
`|총−target|>0.5`로 세팅(카드 실명이 있으니 사용자는 무엇을 받는지 앎).

## 4. 훅 지점

`create_running_route`: target 해석·loop/one-way 게이트 통과 **직후**, 생성 풀 진입
**전**(route_service L648 부근). one-way(end 있음)는 스킵(코스=루프). 캐노니컬 히트면
즉시 반환(gemini 0콜·쿼터 미소모), 미스면 기존 흐름.

## 5. 하위 호환

- 신규 테이블·신규 서비스 — 기존 엔드포인트 동작 불변. `POST /routes/generate` 계약
  동일(RouteResponse). `summary`만 실명(additive — 필드 기존재).
- 미스 시 100% 현행 생성. 캐노니컬 장애는 로그만(생성 폴백).

## 6. 슬라이스 경계

- **슬라이스 1(지금)**: 시드 1호(청라호수공원 순환 4.71km, 실측·229점 폴리라인) +
  매처 + 서빙 + gen_meta 관측. 합격선: 오너 홈 격자 5km ×3 → 3/3 호수공원 서빙 +
  회귀(신사·강남역 캐노니컬 미스 → 기존 동작 불변).
- **슬라이스 2(후속)**: 시드 확장(석촌호수·여의도), **바퀴수 배수 매칭**(2.5km×2바퀴=5km),
  run 히트맵 자동 등재. 지금은 1코스 1바퀴 개념 증명.

## 7. 시드 1호 실측 (T-map, 2026-07-24)

청라호수공원 순환 — 호수 둘레 12점 타원 → T-map 스냅 → **4.71km**(밴드 4.6~5.0 중앙),
polyline 229점. access_points 4개(둘레 균등). 오너 홈(37.53323,126.63037)→최근접
진입점 ~190m(< 800m) → 매칭 성립. 진입 왕복 ~0.4km + 4.71 = ~5.1km(target 5.0, diff 0.1).
