# CREW_RUN_SESSION_L1_DESIGN — 크루 러닝 세션 태깅 L1 (설계)

> 2026-07-13. 상태: **L1 배포됨** (5건 승인·SQL 적용·구현 완료). L2(세션 상세)·
> L3(실시간) 파킹.
>
> **확정 스코프**: "이 러닝은 OO크루 정기런이었다"를 **사후 태깅**. 실시간 아님 —
> 각자 뛰고 각자 저장, 같은 세션으로 묶임. **세션 그룹 상세는 L2 파킹**,
> **실시간은 L3 로드맵**.

---

## 1. 세션 식별 방식 — ⓐ vs ⓑ vs ⓒ 트레이드오프 · 추천

| 방식 | 장점 | 단점 | 즉흥 크루런 |
|---|---|---|---|
| **ⓐ 집결 공지(place_lat) 기반** — 그 공지에 연결된 러닝 = 한 세션 | 공지(RSVP·place·run_at) 재사용, 정밀(어느 정기런인지 명확) | **공지가 있어야만** 세션 성립 + 저장 시 공지 선택 UI 필요 | ❌ 세션 안 됨 |
| **ⓑ 크루+시간창 자동** — 같은 크루·같은 날 ±N시간 | 완전 자동, 유저 액션 0 | **퍼지**(무관한 러닝 오그룹) + **⚠️ `create_run`이 `ran_at`을 `now()`로 저장**(req.ran_at 무시)이라 그룹 기준이 "실제 러닝 시각"이 아닌 "저장 시각" — 백로그 저장 시 오그룹 | ⚠️ 자동이나 부정확 |
| **ⓒ 유저 명시 선택** — 저장 시 "OO 정기런" 선택 | 명시적·정확·오그룹 0 | 유저 액션 필요 | ✅ 크루만 고르면 됨 |

### 추천: **ⓒ(명시 crew_id 태그) + 서버 파생 날짜 버킷 session_key** (ⓐ는 선택적 정밀화)

- **crew_id는 프론트가 명시**(요구대로 "크루 러닝 시작" 진입 시 저장 요청에 실음
  — run.area·place_lat 분업 선례). 이게 "정기런이다"라는 **의도 신호** — ⓑ 순수
  자동이 "우연히 오늘 뛴 것"과 "크루런"을 구분 못 하는 문제를 해결.
- **session_key는 서버가 파생**: 공지 연결이 있으면 `a:{announcement_id}`(ⓐ 정밀
  — 자정 넘겨도 한 세션), 없으면 `c:{crew_id}:{KST_date}`(ⓑ-lite — 같은 크루
  같은 날 묶음). **즉흥 크루런도 날짜 버킷으로 자연히 그룹**(공지 불요) —
  요구의 "공지 없는 즉흥 크루런" 커버.
- **왜 ⓐ 단독 아님**: 공지 없는 즉흥런이 세션에서 빠짐(가장 흔한 캐주얼 케이스).
  place_lat 공지가 있으면 ⓐ로 정밀화하되, **기본은 crew+date**라 항상 성립.
- **왜 ⓑ 순수 자동 아님**: 의도 신호(crew_id) 없이 시간창만으로 묶으면 오그룹 +
  ran_at=now() 신뢰성 문제. crew_id 태그가 그 둘을 다 해결.
- **L1 한계(문서화)**: 같은 크루가 **하루 2세션**(오전조·저녁조)이면 날짜 버킷이
  하나로 합침. L1 수용(정기런은 대개 주간/일간 1회) — 정밀 분리는 공지 연결(ⓐ)
  또는 L2에서.

---

## 2. 스키마 (L1 — SQL §7)

- `runs.crew_id uuid null references crews(id) on delete set null` — 태그(어느
  크루 정기런). **크루 삭제 시 태그만 소거, run은 보존**(set null). 기존 run =
  null(정기런 아님).
- `runs.session_key text null` — 서버 파생 그룹 키(`a:{ann}` | `c:{crew}:{date}`).
  같은 정기런 묶음. null = 일반 러닝.
- **announcement_id 별도 컬럼 없음**(L1 최소) — 공지 연결은 session_key에 인코딩.
  L2 세션 상세에서 공지 조인 수요 시 컬럼 승격.
- 인덱스: `create index on runs(session_key)`(참여자 집계·크루 피드 조인용) +
  `create index on runs(crew_id)`(크루별 정기런 조회). runs는 이미 RLS enable.
- **verified 무관 태깅**: 수동(unverified) 러닝도 정기런 태그 가능(참석은 기록
  검증과 독립). "N명 참여" 집계 정책은 §3.

---

## 3. 저장 흐름 · 게이트

- 프론트 "크루 러닝 시작" → 크루 선택 → 러닝 → `POST /runs`에 **`crew_id`**
  (+ 선택 `announcement_id`) 동봉. RunRequest에 additive 필드(Optional).
- 서버(create_run):
  1. `crew_id`가 있으면 **caller가 그 크루 멤버인지 검증**(ensure_member) —
     **비멤버가 남의 크루 태그 방지**(400/403). 비멤버·없는 크루 → 태그 거부.
  2. `announcement_id`가 있으면 그 크루 소속 공지인지 확인 → session_key =
     `a:{announcement_id}`, 아니면 `c:{crew_id}:{KST(now).date}`.
  3. record에 crew_id·session_key 기록. **하위호환**: crew_id 없으면 기존과 동일
     (둘 다 null).
- **에러 계약**: 비멤버 크루 태그 → 400(잘못된 요청 — run 저장 자체는 실패시킬지
  vs 태그만 무시할지 §판단). **추천**: 400으로 거부(명시적 — 잘못된 태그를 조용히
  무시하면 프론트가 성공으로 오인). 단 crew_id 없는 일반 저장은 무영향.

---

## 4. 크루 피드 집계 (배지 + 참여자 수)

- `list_crew_runs`(크루 피드)가 이미 크루원 run을 반환 — 여기에 additive:
  - 각 카드가 **이 크루의 정기런**인가 = `run.crew_id == 조회 크루_id` (배지).
  - **참여자 수** = 그 run의 `session_key`를 공유하는 **distinct user 수**.
- **N+1 금지(배치)**: 피드 rows의 session_key 집합에 대해 **단일 쿼리**로
  `session_key → distinct user_count` 집계(runs GROUP BY session_key). 피드
  빌더의 기존 asyncio.gather에 편승.
- **CrewRunItem additive**: `is_crew_session: bool`(배지) + `session_participant_count:
  Optional[int]`(정기런 아니면 null). 기존 필드 불변 — 안 읽는 프론트 무영향.

### 참여자 수 집계 정책 (판단)
- **verified 무관**(attendance ≠ performance): 참여자 수는 "누가 나왔나"라
  수동 러닝도 카운트. 랭킹·챌린지(거리=performance, verified-only)와 **다른
  의미** → verified-agnostic 추천.
- **visibility 필터**: **private run은 참여자 수에서 제외**(크루 피드가 이미
  private 제외 — 카드 안 뜨는 사람을 카운트하면 "숨긴 참석"이 노출됨). 즉
  `session_key 공유 + visibility != private`의 distinct user. private 저장 =
  "참석 숨김" 존중.
- **차단(v3.6)**: 참여자 **카운트는 전역 유지**(v3.6 "숫자는 전역, 명단만 가림"
  선례 — kudos_count와 동형). 참여자 **명단**(L2 세션 상세)에서 차단 상대 제외.
  L1엔 명단 없음 → 카운트만, 전역.

---

## 5. 가시성 · 프라이버시

- **A′ 크루 서피스 예외**: 정기런 배지·참여자 수는 크루 피드(크루 서피스)라
  **크루원끼리 보임**(A′ — 크루 가입=크루 화면 내 활동 공유 동의). 프로필 축과
  독립. 일관.
- **차단**: 크루 피드 카드는 v3.6이 이미 차단 멤버 제외. 참여자 카운트 전역(§4).
- **프라이버시 판정(§요구5)**: 크루 태그가 "이 사람이 이 크루 정기런에 나왔다"를
  크루원에게 노출 — **동의 범위 내**. 근거: ① 크루 멤버십(A′ 크루 서피스 공유) +
  ② **유저가 명시적으로 crew_id 태그**(이중 동의). ③ 숨기려면 **private 저장**
  (크루 피드·참여자 카운트 양쪽에서 제외 — §4). 신규 프라이버시 리스크 없음.
  PRIVACY_DATA_MAP에 "runs.crew_id/session_key = 크루 정기런 참석 맥락" 항목 추가.

---

## 6. 규모 · 절단선 (L1 최소선)

- **L1 (이번)**: crew_id 태그 + session_key(서버 파생) + 크루 피드 "정기런" 배지
  + 참여자 수. 저장 시 멤버십 게이트. **끝**.
- **L2 (파킹)**: **세션 그룹 상세** — "이 정기런 참여자 5명 기록 모아보기"(참여자
  **명단** + 각 기록 집계, 차단 v3.6 필터). session_group 엔티티·announcement_id
  컬럼 승격·RSVP↔실참석 대조. → **세션 상세 보기는 L2**(명확히).
- **L3 (로드맵)**: 실시간 세션(라이브 트래킹·라이브 참여).

---

## 7. SQL 페어 (승인 후 사용자 실행 — 아직 미실행)

```sql
-- [ROLLBACK] (먼저)
-- drop index if exists runs_session_key_idx;
-- drop index if exists runs_crew_id_idx;
-- alter table public.runs drop column if exists session_key;
-- alter table public.runs drop column if exists crew_id;

-- [APPLY]
alter table public.runs add column if not exists crew_id uuid
  references public.crews(id) on delete set null;      -- 크루 삭제 시 태그만 소거
alter table public.runs add column if not exists session_key text;
create index if not exists runs_crew_id_idx     on public.runs (crew_id);
create index if not exists runs_session_key_idx on public.runs (session_key);

-- 기존 run은 crew_id·session_key null(정기런 아님) — 백필 없음.
-- 실행 후 확인:
-- select column_name from information_schema.columns
--   where table_name='runs' and column_name in ('crew_id','session_key');
```

---

## 8. 테스트 계획 (구현 시)

- **태깅**: crew_id 동봉 저장 → run에 crew_id·session_key 기록(DB assert).
  비멤버 crew_id → 400(태그 거부). crew_id 없음 → 기존 동일(null).
- **session_key 파생**: 같은 크루·같은 날 2인 저장 → session_key 동일(그룹).
  announcement_id 동봉 → `a:{ann}` 키. 다른 날 → 다른 키.
- **크루 피드 배지·카운트**: 정기런 태그 run은 `is_crew_session=true`+참여자 수
  정확 / 일반 run은 배지 없음·null. **N+1 없음**(쿼리 수 — spy).
- **참여자 집계 정책**: private 참여자 제외 / unverified 참여자 포함(attendance) /
  차단 참여자는 카운트 포함(전역, v3.6).
- **가시성**: 비크루원은 크루 피드 자체 404(기존) — 배지 노출 안 됨.
- 회귀: run_track_and_stats·crew_runs·feed·block·decision_a_prime.

## 9. 판단 플래그 (승인 시 확정)

1. **세션 식별 = ⓒ(명시 crew_id) + 서버 파생 날짜 버킷 session_key**(ⓐ는 공지
   연결 시 정밀화). ⓑ 순수 자동은 ran_at=now() 문제로 비채택. → 승인.
2. **비멤버 crew_id 태그 = 400 거부**(조용한 무시 아님). → 승인.
3. **참여자 수 = verified 무관 + private 제외 + 차단 전역 카운트**(§4). → 승인.
4. **세션 상세(참여자 명단·기록 모아보기) = L2**(L1은 배지+카운트만). → 승인.
5. **하루 2세션은 L1에서 날짜 버킷으로 합쳐짐**(수용, 공지 연결/L2로 정밀화). → 승인.

승인·확정 후: SQL 페어 실행(사용자) → 구현(RunRequest crew_id·저장 게이트·
session_key 파생·크루 피드 배지/카운트 배치·테스트).
