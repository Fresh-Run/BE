# 데모 계정 목록

시드 스크립트(`scripts/seed_demo_data.py`)가 만드는 데모 세상입니다.
비밀번호는 **전부 `test1234`**.

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

\* 닉네임이 선점된 경우 숫자가 붙을 수 있음 (예: 새벽러너84)

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

### 기존 세계
- **크루**: "한강 새벽 러닝 크루" (승인제, 멤버 6명 + pending 1명)
- **공지 2개**: 토요 정기런(러닝 일시·장소·RSVP 마감 有, 참석3/불참1/미정1 투표됨) + 일반 공지
- **러닝 기록**: 멤버들에게 최근 2주 분산 (3~10km) → 크루 피드·주간 랭킹·통계 살아있음
- **run 공개 범위 (visibility)**: 대부분 `followers`(팔로워·크루원만), 일부 `public`으로 승격(수정 API `PATCH /runs` 경유) → **공개 프로필 데모용 자연스러운 mix**. 분포: test1 4개 공개(GPS 2 + 일반 2)·test2 1·demo1 2·demo2 1·demo4 1, demo3은 0(비공개만). 공개 run엔 시간대 기반 제목(새벽/아침/한낮/저녁/야간 러닝)
- **공개 프로필 화면** (`GET /users/{id}/profile` + `/users/{id}/runs`): **비팔로워 시점엔 그 유저의 public run만** 보임 (예: test1을 팔로우 안 하는 demo4가 보면 게시 러닝 4개 = `public_run_count` 일치). 팔로우하면 `followers` run까지 노출. 본인 프로필에선 각 카드에 `visibility` 뱃지, 타인 프로필은 null
- **GPS 검증 run**: test1 2개(5km·8km)·demo1 1개 — 서울숲 궤적으로 서버 파이프라인을 태운 **verification=verified + splits(km별 랩·고도)** run. 활동/크루 피드의 run 상세(`GET /runs/{id}`)에 `splits`·`has_track`, `GET /runs/{id}/track`에 폴리라인
- **코스**: 공개 12개+ (좋아요·댓글 달림) + 비공개 1개(크루 피드에서 route_summary null 확인용). 서울 각지(성수·여의도·강남·잠실·반포·마포·남산 등) 3~8km 다양
- **홈 '전체' 탭** (`GET /routes/public?sort=popular|newest`): 공개 코스가 풍성하게 노출. **인기순**(copy_count)은 "성수 서울숲 야경 5km 루프"(♥6·💬2·복사2) 등 상위, **최신순**은 방금 만든 신규 코스. test1/test2 소유 공개 코스도 좋아요·댓글·복사 받음(본인 콘텐츠 반응 확인용). '이 코스 달리기' 복사 이력 4건 → copy_count 살아있음
- **청라(인천) 공개 코스 4개** (2026-07-09, **1회성 수동 생성 — 시드 스크립트 밖**): demo1이 실 파이프라인(`POST /routes/generate` + publish)으로 생성 — 아시아드주경기장 순환 1.8km·수변 4.8km·봉수대로 서측 6.6km·순환 조깅 3.3km. 청라 좌표(37.53, 126.63) 기준 근처 코스/거리순 눈검증용. 시드 미포함 사유: AI 생성은 비결정적+실비용이라 멱등 시드 원칙과 충돌 — 지워졌다면 이 방법으로 재생성
- **팔로우**: test1↔test2 맞팔, 데모 유저들 ↔ test1 등 8건 → 팔로잉 피드 확인 가능
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
