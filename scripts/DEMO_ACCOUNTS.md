# 데모 계정 목록

시드 스크립트(`scripts/seed_demo_data.py`)가 만드는 데모 세상입니다.
비밀번호는 **전부 `test1234`**.

> **베타 운영(방식 A)**: 테스터 합류 시 `python scripts/grant_beta_premium.py --apply`
> 실행 — tier=free 실계정 전원 premium 승급(시드·운영진 제외, 멱등, 기본 dry-run).
> 출시 전 리셋은 `--revoke --apply`(IAP 구매자는 subscriptions 행으로 자동 보호).
> premium 무제한 근거: 모든 게이트가 get_tier 경유, 수동 premium은 lazy 강등이 존중.

## 계정

| 이메일 | 닉네임 | 역할 |
|---|---|---|
| test1@freshrun.com | 테스트1 | **크루장** (한강 새벽 러닝 크루), 코스 2개(공개1·비공개1) 소유. **premium 테스트 계정** (tier 수동 설정됨 — 오디오 코치·월간 인사이트·크루 무제한 생성 확인용) |
| test2@freshrun.com | 테스트2 | 크루원, test1과 맞팔, 코스 1개, 북마크 1개 |
| demo1@freshrun.com | 새벽러너* | 크루원, 인기 코스("뚝섬 순환") 주인, 팔로워 다수, GPS run 1개. **둘러보기 크루 2개 크루장**(성수동 러닝·강남 인터벌) → 이걸 위해 **premium 승격됨** |
| demo2@freshrun.com | 한강질주 | 크루원, **둘러보기 크루장**(여의도 퇴근런) |
| demo3@freshrun.com | 뚝섬바람 | 크루원 (RSVP 미정), **둘러보기 크루장**(반포 한강 나이트런) |
| demo4@freshrun.com | 마포페이서 | 크루원 (RSVP 불참), **둘러보기 크루장**(잠실 새벽 5시) |
| demo5@freshrun.com | 야간비행 | **가입 신청 pending**(한강 새벽 크루), **둘러보기 크루장**(마포 주말 트레일) |
| freshrun0609+ascreview@gmail.com | 앱리뷰어 | **애플 외부 베타 리뷰 전용**(2026-07-26 수동 생성, 시드 밖). **premium 수동 승급**(`db/2026-07-27_apple_review_premium.sql` — 리뷰어가 오디오 코치·인사이트 등 잠금 없이 확인). user_id `301990b8…`. 베타 종료 후 정리 대상 |
| qa-empty@freshrun.com | 큐에이빈피드 | **QA 전용 — `/feed/nearby` 빈 상태 UI 검증용** (2026-07-15, 시드 밖 수동 생성). 좌표 보유 public run 소유자 **전원을 팔로우** 처리해 탐색 대상 0 → **어느 위치에서든 `/feed/nearby`가 `[]`**. 실기기 폰 GPS로 빈 피드 화면을 재현할 때 이 계정으로 로그인. **run·코스 없음**(카드 유발 금지). ⚠️ **유지 조건 아래** |

\* 닉네임이 선점된 경우 숫자가 붙을 수 있음 (예: 새벽러너84)

> **⚠️ qa-empty 유지 조건 (`/feed/nearby` 빈 피드 보장)**: 이 계정이 `[]`를
> 유지하려면 **좌표 보유 public run을 올리는 모든 공개 계정을 qa-empty가
> 팔로우**하고 있어야 한다(비공개 계정은 `visible_owners`가 자동 제외하므로
> 팔로우 불요지만, 공개 전환 대비로 현재 6명 전원 팔로우해 둠:
> demo1·demo2·demo3·demo4·test1·test2 — 공개는 즉시, 비공개는 요청→승인).
> **새 공개 러너 계정이 시드/운영에 추가되면 qa-empty도 그 계정을 팔로우
> 추가해야 한다** — 안 하면 그 계정의 근처 public run이 빈 피드를 깨뜨린다.
> 검증: qa-empty 로그인 → `GET /feed/nearby?lat=37.529&lng=126.965&radius_km=20`
> 가 `[]`이면 정상. (비번 `test1234`, 닉네임 "큐에이빈피드")

> 닉네임은 실 DB 대조로 갱신함(2026-07-08 — test1·test2가 문서와 달랐던 것
> 정정). 시드는 멱등(감지-스킵)이라 이미 존재하는 프로필의 닉네임을 덮지
> 않는다 — 수동 변경분은 문서와 어긋날 수 있으니 테스트에서 닉네임을 상수로
> 가정하지 말 것(user_id 기준 검증 권장).
>
> **아바타는 시드 재실행으로 복구 가능**(2026-07-12 보수): avatar_url이
> **null인 데모 계정만** DiceBear 시드 아바타를 재부여 — 검증 스크립트가
> 아바타를 지워도 `python scripts/seed_demo_data.py` 1회로 복원.
> non-null(수동 업로드 포함)은 안 덮는다.

## 시딩된 세상

### 신기능 데모 (2026-07-13 리프레시 — §13~18)
- **지역 배정**: test1=한강로동(신용산/용산, `runs.area`), test2=청라동(인천). 정기런 참여자 데모는 **성수 demo 계정끼리**(test1/test2는 지역이 달라 안 묶임 — 각자 지역 개인런).
- **month_rank 타일**: test1이 **거리 분산 verified 3회**(8·6.5·5km — 최근 5km 빠른 페이스) + §8 GPS 2회 → `GET /me/insights/monthly`의 `month_rank`가 **`best_5k` rank 2**("이번 달 2번째로 빠른 5K"). ※ 잔재 러닝이 있으면 longest_distance로 오염되니 `wipe_demo_data.py --reset-test-data`로 정리 후 재시딩.
- **크루 채팅**: 한강 크루에 text 3 + 반응 1 + **공지 생성 시 system 메시지 자동**(정기런 공지).
- **정기런 세션 태깅**: demo2·demo3(성수동)가 같은 날 `crew_id` 태그 러닝 → `session_key` 그룹 → 크루 피드 카드에 **`is_crew_session` 배지 + `session_participant_count`=2**.
- **세부 권한**: demo1을 한강 크루 **admin 승격**(기본 announcements·challenges ON, edit_crew·kick·manage_admins OFF).
- **차단 관계**: demo4 → demo5 차단(양방향 필터·목록 제외 데모).
- **프로필 샘플**: demo2·demo3 `visibility=private`(비공개 → **팔로우 요청제**, 승인제 통합 Part B) + demo5 pending(기존).
- **커버/러닝 사진 미시드**: 커버는 기본 그라데이션, 러닝 사진 없음(실파일 필요 — 실기기 직접 데모).

### 실 GPS 시드런 5종 (2026-07-15 §19 — `scripts/seed_real_tracks.json`)
- **반포 강변런**(test1, 4.01km)·**서울숲 한 바퀴**(test1, 1.59km)·**여의도공원 정기런**(test1, 1.93km — 이준크루 세션 태그, 크루 없으면 무태그 폴백)·**뚝섬 강변런**(test2, 3.02km)·**남산 북측순환로**(test2, 1.48km).
- **실도로 GPS 경로**(시뮬레이션 make_gps_track와 구분 — 원본은 2026-07-14 원오프 생성분을 라이브러리로 편입). 멱등: 같은 title 존재 시 스킵. verification은 원본 판정(verified) 보존.
- **트랙 생성형 시드(2026-07-15)**: §6·§13·§15의 모든 run이 이제 `insert_tracked_run`(진짜 트랙+백데이트) 경유 — 트랙 없는 시드 run은 더 이상 생성되지 않음.

### 기존 세계
- **크루**: "한강 새벽 러닝 크루" (승인제, 멤버 6명 + pending 1명)
- **공지 2개**: 토요 정기런(러닝 일시·장소·RSVP 마감 有, 참석3/불참1/미정1 투표됨) + 일반 공지
- **러닝 기록**: 멤버들에게 최근 2주 분산 (3~10km) → 크루 피드·주간 랭킹·통계 살아있음
- **run 공개 범위 (visibility) — 2026-07-15 재배분(Part 2): `public` 위주**. 비팔로워도 "살아있는 세계"를 보게 public을 다수로, `followers`는 소수만 남겨 **Part 1(`followers_run_count` "팔로우하면 N개 더") 시연**을 성립. **스테이징 실분포: public 27 · followers 6 · private 1**(시드 34건 중). 계정별: **demo1**(공개) pub3·**fol1**·**demo4**(공개) pub2·**fol1** → 비팔로워 프로필에 `followers_run_count=1` "팔로우하면 1개 더" CTA 시연 / **demo2·demo3**(비공개) pub·fol1 유지(비공개 스토리) + **demo3 private 1건**(카운트에도 안 잡히는 완전 비공개 시연) / **test2**(비공개) pub6·fol2(청라동 지역 개인런 followers 유지, §13) / **test1** pub11. 공개 run엔 시간대 기반 제목
  - ⚠️ **재시드 재현성(판단 플래그)**: `seed_demo_data.py` §12 `PUBLIC_PLAN`을 public 위주로 갱신해 **정성적으로** 재현(demo3 private 1건도 §12 직후 멱등 처리). 단 개수-기반 PLAN + 실행순서 의존이라 **정확한 27/6/1 재현은 스테이징 핀포인트 PATCH가 진실** — 재시드는 근사만.
- **공개 프로필 화면** (`GET /users/{id}/profile` + `/users/{id}/runs`): **비팔로워 시점엔 그 유저의 public run만** 목록에 보이고, 열림 프로필이면 **`followers_run_count`로 팔로워 공개 run "존재"를 사실값 노출**(A′ "숫자는 사실값, 리스트는 잠금" — 목록엔 미노출). 팔로우하면 `followers` run까지 목록 노출. **잠금 계정(비공개·비팔로워)엔 `followers_run_count=0`**. 본인 프로필에선 각 카드에 `visibility` 뱃지, 타인 프로필은 null
- **GPS 검증 run**: test1 2개(5km·8km)·demo1 1개 — 서울숲 궤적으로 서버 파이프라인을 태운 **verification=verified + splits(km별 랩·고도)** run. 활동/크루 피드의 run 상세(`GET /runs/{id}`)에 `splits`·`has_track`, `GET /runs/{id}/track`에 폴리라인
- **코스**: 공개 12개+ (좋아요·댓글 달림) + 비공개 1개(크루 피드에서 route_summary null 확인용). 서울 각지(성수·여의도·강남·잠실·반포·마포·남산 등) 3~8km 다양
- **코스 지오메트리 (2026-07-15)**: 모든 시드 코스는 `polyline`(Coordinate[] {lat,lng})·`waypoints`(Waypoint[] {name,coordinate,is_pitstop,description})를 **실제 앱 저장 경로(`route_service.persist_route`)와 동일 포맷**으로 보유 → 프론트 코스 카드가 지도 폴리라인을 그림(예전엔 `waypoints:[]`·polyline null → "네온 폴백"). 유도: `scripts/course_geometry.py`(시더·백필 **단일 소스**)가 §19 실 GPS 트랙 5종(seed_real_tracks.json)에서 코스 시작 좌표에 **가장 가까운 실 트랙을 평행이동**해 실도로 궤적을 재사용. 소비 API(`GET /routes/public`·`GET /feed`)의 `PublicRouteResponse.polyline`에 탑재. **트랙 없는 run과 형제 케이스였음** — 시더 `sb_insert_route` 패치 + 기존 스테이징 21행은 `scripts/backfill_course_geometry.py`로 리시드 없이 핀포인트 backfill(routes 49/49 지오메트리 보유)
- **홈 '전체' 탭 (2026-07-15 교체 → `GET /feed/nearby?lat&lng&radius_km`)**: 이제 **위치 반경 내 public run** 피드(코스 아님). 데모 검증엔 반경 안에 여러 계정의 public run이 필요 — run 시작 좌표(`runs.start_lat/lng`, 트랙 첫 점 백필)가 서울권에 몰려 있어 서울 좌표(예: `lat=37.55&lng=127.0&radius_km=10`)로 조회 시 demo/test 계정 public run이 노출(본인·팔로우·비공개 계정 제외 규칙 적용). **아래 코스 피드는 `GET /routes/public`으로 존치**(다른 서피스).
- **(참고) 코스 피드** (`GET /routes/public?sort=popular|newest`): 공개 코스가 풍성하게 노출. **인기순**(copy_count)은 "성수 서울숲 야경 5km 루프"(♥6·💬2·복사2) 등 상위, **최신순**은 방금 만든 신규 코스. test1/test2 소유 공개 코스도 좋아요·댓글·복사 받음(본인 콘텐츠 반응 확인용). '이 코스 달리기' 복사 이력 4건 → copy_count 살아있음
- **청라(인천) 공개 코스 4개** (2026-07-09, **1회성 수동 생성 — 시드 스크립트 밖**): demo1이 실 파이프라인(`POST /routes/generate` + publish)으로 생성 — 아시아드주경기장 순환 1.8km·수변 4.8km·봉수대로 서측 6.6km·순환 조깅 3.3km. 청라 좌표(37.53, 126.63) 기준 근처 코스/거리순 눈검증용. 시드 미포함 사유: AI 생성은 비결정적+실비용이라 멱등 시드 원칙과 충돌 — 지워졌다면 이 방법으로 재생성
- **팔로우 그래프 (8건 최종 follows — §5)**: `test1↔test2`(맞팔) · `test1→demo1` · `test1→demo2` · `test2→demo1` · `demo1→test1` · `demo2→test1` · `demo3→test1`. **비공개 대상(test1·test2)을 향한 5건은 요청→승인**을 거쳐 follows로 수렴(Part B 승인제 — 재시드도 이 흐름 재현, `follow_request_approved` 알림 동반). pending 잔여 0.
- **kudos**: 멤버들 run에 서로 골고루 (본인 run 제외) → 활동 피드의 kudos_count·my_kudos 살아있음
- **AI 오디오 코치**: test1의 "반포 한강공원 야경 코스"에 코치 스크립트 1개(cues 7개) — `POST /routes/{id}/coach-script`가 캐시 반환
- **AI 월간 인사이트**: test1 2026-06(지난달) 1개 — `GET /me/insights/monthly?year=2026&month=6`에 stats + ai(coaching·plan 3슬롯)
- **신체정보**: test1 프로필에 birth 1992·68.5kg·176cm·male — **본인 `GET /me/profile`에만** 노출(다른 유저 응답엔 없음)
- **둘러보기 크루 7개** (데모 유저 소유, test1/test2 미가입 → 둘러보기 탭에 노출): 성수동 러닝(성동구·입문·open)·여의도 퇴근런(영등포구·중급·open)·반포 한강 나이트런(서초구·무관·approval)·잠실 새벽 5시(송파구·중급·open)·마포 주말 트레일(마포구·트레일·approval)·강남 인터벌 클럽(강남구·고급·**비공개/초대전용**)·**성수 새벽 소수정예(성동구·중급·approval·정원 3/3 모집 마감)**. 각 멤버 2~4명. **비공개 강남 크루는 비멤버에게 숨김**(정상), **모집 마감 크루는 기본 숨김 → `include_full=true` 토글로 노출**(눈검증용, 성수 실좌표라 거리순 상위)
- **당근식 둘러보기 데이터**: 7개 크루 전부 `sido`(서울특별시)·`sigungu`·`lat`/`lng`(서울 곳곳 분산)·`tags`(2개씩) 채워짐 → `GET /crews?lat&lng`로 **가까운 순 정렬 + distance_km**("0.1km"…), `GET /crews?sigungu=성동구`로 **행정구역 필터**(성수동 러닝·한강 새벽 2개), 태그 카드 표시 확인 가능

## 확인 포인트 (test1으로 로그인 시)

- 홈: 주간 통계, 팔로잉 피드 (러닝러버·새벽러너의 코스)
- 활동 피드(`/feed/activities`): 팔로우한 유저+내 run, kudos 수·내가 누른 표시, 내 run이 받은 kudos (`is_mine=true` 카드는 kudos 버튼 비활성). **내 GPS run 2개(5·8km)가 상단에** — 상세 진입 시 splits 차트·경로 지도
- 크루 상세: 러닝 피드(demo1 GPS run 포함), 랭킹, 공지+RSVP 집계, 가입 신청 1건(야간비행)
- 코스 피드: 좋아요/댓글/북마크 표시
- **프리미엄(test1=premium)**: 코스 상세의 오디오 코치 스크립트, 기록 탭의 월간 인사이트(2026-06), 프로필 편집의 신체정보

## 재실행

`python scripts/seed_demo_data.py` — 멱등(감지-스킵)이라 몇 번 돌려도 중복 생성 없음.
**삭제는 하지 않으므로** test1/test2의 실제 기록은 안전합니다.
