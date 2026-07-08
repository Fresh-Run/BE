# RUN_TRACK_AND_STATS_DESIGN — 궤적 공개 조회 + 집계 정합 (설계)

> 2026-07-08. 상태: **구현 완료·배포됨** (결정: §2 커서 포함 · §3-A 개인 화면
> 집계는 포함 유지, 제외는 1~5만).
> 프론트 요청 2건 + 집계 정책 1건. SQL 변경 없음(코드 필터·게이트만).

## 1. GET /runs/{id}/track — 전제 정정: 이미 존재, 실제 갭은 권한

**엔드포인트는 이미 있고 API_GUIDE 110행에 문서화돼 있다**
(`routes.py:968`, 응답 `{polyline[{lat,lng}], server_distance_km, elev_gain_m,
point_count_raw/kept}`). 폴리라인은 코스와 **같은 `Coordinate` 모델**
(schemas 880 vs 453)이라 형식 대칭 요구는 이미 충족 — 프론트는 코스 렌더
코드를 그대로 쓸 수 있다.

**실제 갭**: `run_service.get_run_track`이 **본인 소유만** 허용(`eq user_id`,
439행). 기록 탭(본인)은 되지만 **프로필 러닝 카드(타인의 공개 run)** 에서
궤적을 못 가져온다.

### 설계 — 기존 엔드포인트의 접근 규칙만 확장 (신규 경로 없음)

- `get_run_track`의 소유 검사를 kudos·run 댓글이 쓰는 **`_can_see_run` 게이트
  재사용**으로 교체(run_service:604~663 — public/followers/private × 팔로우
  관계 판정이 이미 구현·테스트됨). 본인은 항상 통과(동작 불변 = additive).
- 차단·부재·트랙 없음 → **404 은닉 유지**(현행 계약 그대로. `has_track`이
  사전 판단 신호라는 가이드 문구도 유지).
- **대안 기각**: ① 러닝 상세/목록 응답에 polyline 내장 — 목록 payload 폭증
  (최대 1000pt × N), 지도는 상세 진입 시에만 필요 → 기각. ② 신규 공개 경로
  추가 — 같은 자원에 경로 2개, 이득 없음 → 기각.
- **위치정보 유출 방지 검증**: 가시성 매트릭스 테스트(visibility 3종 × 관계
  3종: 본인/팔로워/무관계) + 비허용 케이스는 **좌표값 문자열이 응답 전체에
  부재**(프라이버시 이중검증)까지 assert.

## 2. GET /runs 페이지네이션 — 실태 (조사 보고)

- **현황**: `limit`만 지원(기본 20, 클램프 1~100 — `run_service.py:1137`),
  offset/cursor 없음. → **100개 초과 히스토리는 어떤 방법으로도 조회 불가.**
  기록 탭 캘린더는 `GET /me/stats/monthly`(월 단위)라 이 상한과 무관 — 전체
  목록 스크롤만 걸린다.
- **개선안 (권장: cursor)**: `?before=<ran_at ISO>` 커서 추가. 최신순 목록이라
  "이 시각 이전" 커서가 자연스럽고, 삭제·삽입으로 밀리는 offset 문제가 없으며
  기존 `ran_at desc` 정렬을 그대로 탄다. 기존 계약 불변(additive).
  - 동률 처리: strict `lt`로 같은 초의 다른 run 1건이 스킵될 수 있음 —
    같은 초 2개 run은 실사용상 희귀해 허용(필요 시 `(ran_at,id)` 복합 커서로
    후속 보강).
  - **변경 규모: 소** — 서비스 ~5줄 + 라우트 파라미터 1개 + API_GUIDE §6 표
    1행 + 테스트 1개(경계에서 중복/누락 없음 assert). Gemini 비용 0.
- 스코프 포함 여부는 사용자 결정 대기.

## 3. 트랙 없는 run 집계 제외 (정책 확정분 구현 설계)

### (a) 집계 지점 전수 (실코드 스윕 결과)

| # | 집계 | 위치 | 현재 필터 | 적용 |
|---|---|---|---|---|
| 1 | PB 4종 조회 (`_compute_records` ← /me/stats·인사이트 records) | run_service:244 | suspect만 제외 | **verified만으로 강화** (오염 실사례 지점) |
| 2 | PB 경신 감지 (`_detect_new_records` + create_run:88 축하 모달) | run_service:279 | 새 run이 suspect면 스킵 | **새 run이 unverified여도 스킵** + prev는 1과 동일 필터 |
| 3 | 크루 주간 랭킹 | crew_service:1036 | `neq suspect` | **`eq verified`로 교체** |
| 4 | 챌린지 진행률(progress_pct) | crew_service:1173 | `neq suspect` | 동일 |
| 5 | 챌린지 완료 판정(저장 시) | run_service:1091 | `neq suspect` | 동일 |
| 6 | /me/stats 주/월/전체 totals | run_service:338·361 | **없음(suspect도 포함)** | §3-A 결정 |
| 7 | 기록 탭 캘린더(월별) | run_service:491 | 없음 | §3-A 결정 |
| 8 | 월간 인사이트 주차합·패턴 | insight_service(_fetch_runs_range) | 없음(records만 suspect 제외) | §3-A 결정 |
| 9 | 완료 화면 "평소보다 N초" (`_pace_vs_recent`) | run_service:199 | 없음 | §3-A 결정 |

### §3-A 결정 지점 — 개인 화면 집계(6~9)까지 제외할까?

**추천: 포함 유지 (제외는 1~5 소셜·경쟁·기록만).** 근거: 정책 문구가
"히스토리에는 남되 최고기록·랭킹·크루 통계 제외" — 개인 주간/월간/총거리와
캘린더는 히스토리 성격. 수동 입력(gps_track 없는 저장)은 정상 사용 흐름으로
설계돼 있어(스키마 주석), 수동 기록 유저의 주간 거리가 0이 되면 UX가 무너진다.
6~9는 본인만 보는 값이라 오염의 피해자도 본인뿐.

### (b) 제외 기준 — 선택지

- **① `verification = 'verified'`만 집계 (추천)** — verification은 "트랙 존재
  + 파이프라인 통과 + sanity"를 이미 한 값으로 요약(트랙이 있어도 쓰레기면
  unverified, 부정 의심은 suspect). `runs` 컬럼이라 **조인 없이 DB 필터 가능**,
  기존 `neq suspect` 자리를 `eq verified`로 바꾸면 끝. `not null default`라
  null 함정 없음(라이브 0건 실확인).
- ② `has_track`(run_tracks 존재) — 조인 필요 + "트랙은 있는데 검증 실패"가
  통과하는 구멍.
- ③ kept point 임계 — 파이프라인이 이미 MIN_TRACK_POINTS=10으로 반영(미달 시
  unverified). ①에 포함되므로 중복.

### (c) 기존 오염 데이터 — 재계산 도구 불필요 (구조상)

**PB는 저장하지 않는다** — 테이블 없이 조회 시마다 runs에서 계산
(run_service:227 주석). 필터를 고치면 test1의 3'45" 오염 포함 **기존 오염이
즉시 자연 치유**된다. 백필·재계산 도구·SQL 전부 불필요.

예외 1건: `monthly_insights` 캐시는 생성 시점 records가 **텍스트로 박제** —
과거 인사이트에 오염 기록이 남아 있을 수 있다. 과거 리포트 소급 수정은 하지
않는 게 자연스럽고(신규 생성분부터 정확), test1 방치 결정과 일치. 실유저
클레임 시 해당 (user, year, month) 행 삭제 후 재조회로 재생성됨 — 이 한 줄을
운영 방법으로 문서에 남긴다(도구 개발 불요).

### (d) 하위 호환

- `new_records`·`records` 응답 스키마 불변(후보 조건만 좁아짐). RecordsBlock
  필드는 원래 Optional — **verified run이 하나도 없는 유저는 records가 null**이
  될 수 있음 → API_GUIDE에 프론트 소비 규칙으로 명시(기존에도 run 0개면 null).
- 랭킹·챌린지 합계가 줄어들 수 있음 — 정책 의도 그대로. 에러 계약·정렬 불변.

## 4. 테스트 계획

- **궤적 가시성 매트릭스**: visibility(public/followers/private) × 관계(본인/
  팔로워/무관계) 9칸 → 기대 200/404 전수 + 404 케이스는 좌표값 문자열 부재
  이중검증. 트랙 없는 run 404. has_track 계약 확인.
- **집계 제외**: 한 유저에 verified(느림)+unverified(빠름) run 배치 →
  records.best_pace가 verified 것 / unverified 새 run 저장 시 new_records 빈
  배열 / 크루 랭킹·챌린지 진행이 verified 합만 / (§3-A 결정에 따라) 개인
  totals 검증 / verified 0개 유저 records null.
- (§2 채택 시) cursor 경계: limit걸린 두 페이지 이어붙여 중복·누락 0.
- 회귀: stats·ranking·challenge·gps_track·run_visibility 통합 테스트.
- Gemini 실호출 0.

## 5. 구현 시 함께

- API_GUIDE: 110행 track 표 갱신(가시성 규칙 — "본인 + 공개범위 내 타인",
  has_track 관계 재명시), records null 가능성, (§2 채택 시) §6 페이지네이션 표.
- PRIVACY_DATA_MAP §2 GPS 노출 경로에 "타인 조회는 visibility 게이트" 문구 반영.
