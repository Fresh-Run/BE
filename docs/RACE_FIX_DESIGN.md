# 레이스 컨디션 수정 설계 (H3 · M3 · M8)

2026-07-06 셀프 감사에서 발견된 check-then-act 레이스 3건의 구현 설계.
**구현은 베타 이후 백로그** — 이 문서는 어느 모델로든 바로 구현할 수 있도록
근거·SQL 초안·호출부 변경·테스트·마이그레이션·도입 트리거를 담는다.

전제: 백엔드는 supabase-py(PostgREST) 사용 — **앱 레벨 트랜잭션이 없다.**
그래서 "count→check→act"가 여러 요청에 인터리브되면 DB 제약(unique/PK)만이
최후 방어선인데, 아래 3건은 **행 개수/집계 조건**이라 unique로 못 막는다.
해법의 공통 축: **연산을 Postgres 함수(RPC) 하나로 내려 원자화**하고, 함수
안에서 잠금 후 조건 검사·삽입을 한 트랜잭션(=단일 statement)으로 수행한다.

---

## 0. 공통 패턴 결정

| 건 | 자원 단위 | 잠금 방식 | 근거 |
|---|---|---|---|
| **H3** 정원 | 크루 1행 | `SELECT ... FROM crews WHERE id=_crew_id FOR UPDATE` | 모든 가입/승인이 한 크루 행을 참조 → 그 행을 잠그면 per-crew 직렬화. 동시 삭제까지 방어(FK cascade와 정합). 다른 크루끼리는 안 막힘 |
| **M8** 생성한도 | owner(유저) | `pg_advisory_xact_lock(hashtext('crew_create:'||_owner_id))` | 잠글 "단일 행"이 없다(유저의 소유 크루 **개수**가 자원). 유저 키 advisory lock으로 per-owner 직렬화 |
| **M3** 쿼터 | user+주 | `pg_advisory_xact_lock(hashtext('ai_quota:'||_user_id))` | 마찬가지로 "이번 주 생성 **개수**"가 자원. 유저 키 advisory lock |

**왜 건별로 다른가 (한 스타일로 통일 안 함):** H3은 잠글 실제 행(`crews`)이
존재하고 그 행 잠금이 "크루 삭제 중 가입" 같은 부수 레이스까지 덤으로 막아
`FOR UPDATE`가 최적. M3·M8은 "행 개수"가 자원이라 잠글 단일 행이 없어 advisory
lock이 자연스럽다. 억지로 통일하면 H3에서 crews 행 잠금이 주는 이점을 잃는다.

**조건부 INSERT(`INSERT ... SELECT ... WHERE count < limit`)로 충분한가 →
불충분.** PostgreSQL은 동시 트랜잭션이 서로의 미커밋 INSERT를 count에 반영하지
않으므로(MVCC), WHERE의 count는 여전히 stale하다. 명시적 잠금(FOR UPDATE 또는
advisory)으로 **직렬화**해야만 count가 정확해진다. unique-index 대안은 §각 건에서
개별 기각 근거 명시.

**보안 컨텍스트:** 세 함수 모두 백엔드(service_role 클라이언트)만 호출한다.
service_role은 RLS를 우회하므로 `SECURITY DEFINER` 불필요 — 기본
`SECURITY INVOKER`로 두되, 함수 소유자는 service_role/postgres. (프론트가
직접 rpc를 못 부르게 두는 것이 전제 — 현재 구조 그대로.)

---

## 1. H3 — 크루 정원 초과

**현재 코드:** `crew_service._admit_member` (app/services/crew_service.py:363~)
```
counts = await _member_counts([crew_id])      # ① count
if current >= max_members: raise CrewFull()   # ② check
insert crew_members ...                        # ③ act  ← ①~③ 사이 창
```
`crew_members`의 unique는 `(crew_id, user_id)` — **같은 유저 중복만** 막는다.
서로 다른 두 유저가 정원 `max-1`에서 동시 진입 → 둘 다 ②를 통과 → 둘 다 ③ →
정원 +1~2. 호출 경로 3곳: open join(`join_crew`), 코드 가입(`join_by_code`),
승인(`decide_join_request` → `_admit_member(notify_owner=False)`).

**RPC 초안:**
```sql
create or replace function admit_crew_member(
  _crew_id uuid, _user_id uuid, _role text default 'member'
) returns table(status text, member_count int)
language plpgsql as $$
declare _max int; _cur int;
begin
  -- 크루 행 잠금 = per-crew 직렬화 (동시 삭제도 대기시킴)
  select max_members into _max from public.crews where id = _crew_id for update;
  if not found then
    status := 'crew_not_found'; member_count := 0; return next; return;
  end if;
  if exists (select 1 from public.crew_members
             where crew_id = _crew_id and user_id = _user_id) then
    select count(*) into _cur from public.crew_members where crew_id = _crew_id;
    status := 'already_member'; member_count := _cur; return next; return;  -- 멱등
  end if;
  select count(*) into _cur from public.crew_members where crew_id = _crew_id;
  if _max is not null and _cur >= _max then
    status := 'crew_full'; member_count := _cur; return next; return;
  end if;
  insert into public.crew_members (crew_id, user_id, role)
    values (_crew_id, _user_id, _role);
  status := 'admitted'; member_count := _cur + 1; return next;
end $$;
```
`FOR UPDATE`가 두 번째 동시 호출을 첫 트랜잭션 커밋까지 대기시킨 뒤 count를
다시 읽게 하므로(now +1) 정원이면 `crew_full`을 정확히 반환.

**호출부 변경 (`_admit_member`):** count·check·insert 블록을 rpc 호출로 교체.
```python
res = await asyncio.to_thread(
    lambda: get_supabase_admin().rpc(
        "admit_crew_member",
        {"_crew_id": crew_id, "_user_id": user_id, "_role": "member"},
    ).execute()
)
row = res.data[0]                      # {'status':..., 'member_count':...}
status = row["status"]
if status == "crew_full":
    raise CrewFull()
if status == "crew_not_found":
    raise CrewNotFound()
# 'admitted' 또는 'already_member' → 성공. notify_owner 로직은 'admitted'에서만.
current = row["member_count"]
if status == "admitted" and notify_owner:
    await notification_service.create_notification(... crew_joined ...)
return current
```
`_admit_member`의 반환(`current`)·`notify_owner` 시맨틱을 그대로 보존. 기존
23505 멱등 처리는 함수의 `already_member` 분기가 대체(경합 시에도 함수 내부
잠금이라 중복 insert 자체가 발생하지 않음).

**unique-index 기각:** "크루당 N명"은 행 개수 제약이라 unique index로 표현
불가(부분 unique로도 개수는 못 센다).

---

## 2. M8 — 크루 생성 한도 (무료 1개)

**현재 코드:** `quota_service.ensure_crew_creation` (app/services/quota_service.py) —
`count(crews where owner_id) >= FREE_CREW_LIMIT` 검사 후, 핸들러가 이어서
`crew_service.create_crew`로 insert. count→insert 창에 동시 2건 → free가 2개.

**설계 판단:** 한도 검사와 생성(크루 insert + owner 멤버십 insert)을 한 함수로
묶어 원자화. tier→limit 해석은 Python에 유지(get_tier의 lazy IAP 강등 로직을
SQL로 옮기지 않는다) — 함수엔 **정해진 한도(int, null=무제한=프리미엄)**를 넘긴다.

**RPC 초안:**
```sql
create or replace function create_crew_limited(
  _owner_id uuid, _limit int, _crew jsonb
) returns public.crews
language plpgsql as $$
declare _cnt int; _new public.crews;
begin
  perform pg_advisory_xact_lock(hashtext('crew_create:' || _owner_id::text));
  if _limit is not null then
    select count(*) into _cnt from public.crews where owner_id = _owner_id;
    if _cnt >= _limit then
      raise exception 'crew_limit_exceeded' using errcode = 'P0001';
    end if;
  end if;
  insert into public.crews (
    owner_id, name, description, area, radius_km, sport, level,
    max_members, is_public, join_policy, active_days, active_time, color
  ) values (
    _owner_id, _crew->>'name', _crew->>'description', _crew->>'area',
    (_crew->>'radius_km')::float8, _crew->>'sport', _crew->>'level',
    (_crew->>'max_members')::int, (_crew->>'is_public')::bool,
    _crew->>'join_policy',
    coalesce((select array_agg(x) from jsonb_array_elements_text(_crew->'active_days') x), '{}'),
    _crew->>'active_time', _crew->>'color'
  ) returning * into _new;
  insert into public.crew_members (crew_id, user_id, role)
    values (_new.id, _owner_id, 'owner');
  return _new;
end $$;
```
advisory lock이 xact 스코프라 커밋 시 자동 해제. 동시 2건 중 두 번째는 대기 후
count(now +1)를 보고 `crew_limit_exceeded` raise. crew를 jsonb로 넘겨 13필드
시그니처 폭발을 피함(필드 추가 시 SQL만 수정).

**호출부 변경:** 현재 핸들러(routes.py:964~)의 `ensure_crew_creation` +
`create_crew` 2단계를 1개 rpc로. Python이 tier→limit 계산:
```python
tier = await quota_service.get_tier(user_id)     # lazy IAP 강등 포함
limit = None if tier == "premium" else FREE_CREW_LIMIT
try:
    res = await asyncio.to_thread(lambda: sb.rpc("create_crew_limited",
        {"_owner_id": owner_id, "_limit": limit, "_crew": req.model_dump(mode="json")}
    ).execute())
except APIError as exc:
    if "crew_limit_exceeded" in str(exc): raise CrewLimitExceeded(FREE_CREW_LIMIT)
    raise
crew = res.data[0]
return await _one_response(crew, member_count=1)
```
`level`은 `req.level.value`(문자열)로 직렬화되도록 model_dump 처리 주의.

**unique-index 기각:** free당 1개는 부분 unique로 흉내낼 수 있으나 ① 한도가
설정값(1→2→3 변경 가능) ② premium 무제한 ③ crews에 tier 미저장 →
부분 unique로 "tier별 가변 한도"를 표현 불가. advisory lock+count가 유일하게
일반적.

---

## 3. M3 — AI 생성 쿼터 창

**현재 코드:** routes.py 생성 핸들러 — `check_ai_quota`(:377) → Gemini 파이프라인
(:393) → `record_ai_generation`(:405). 검사와 기록이 분리되어, free가 잔여 1일
때 3건 동시 → 셋 다 `used=2<3` 통과 → **Gemini 3회 유료** 후 각각 기록.
기록이 "성공 후"인 이유: 실패한 생성은 쿼터를 소모하지 않게 하려는 의도.

**설계 판단: 예약(reserve)→(Gemini)→실패 시 해제(release).**
- 검사+기록을 `reserve_ai_generation` 한 함수로 원자화해 Gemini **전에** 슬롯을
  선점. 이로써 동시 3건 중 1건만 예약 성공 → 나머지는 즉시 429.
- 실패 시 예약 행 삭제(release)로 **"실패는 무료" 시맨틱 보존**(오늘과 동일).
- premium은 `_limit=null` → 검사 없이 삽입만(생성 로그는 유지 — get_quota의
  `used` 표시 보존).

**RPC 초안:**
```sql
create or replace function reserve_ai_generation(
  _user_id uuid, _limit int, _week_start timestamptz
) returns uuid
language plpgsql as $$
declare _cnt int; _id uuid;
begin
  perform pg_advisory_xact_lock(hashtext('ai_quota:' || _user_id::text));
  if _limit is not null then
    select count(*) into _cnt from public.route_generations
      where user_id = _user_id and created_at >= _week_start;
    if _cnt >= _limit then
      raise exception 'quota_exceeded' using errcode = 'P0001';
    end if;
  end if;
  insert into public.route_generations (user_id) values (_user_id) returning id into _id;
  return _id;  -- 예약 id (실패 시 이 행을 삭제)
end $$;
```
advisory lock은 count+insert 동안만 유지되고 rpc 커밋 시 해제 → **Gemini 호출은
잠금 밖**(느린 부분을 직렬화하지 않음). `_week_start`는 Python이 기존
`_week_start_utc()`(KST 월요일)로 계산해 전달.

**호출부 변경 (생성 핸들러):**
```python
tier = await quota_service.get_tier(user.user_id)
limit = None if tier == "premium" else AI_WEEKLY_LIMIT
try:
    reservation_id = await quota_service.reserve_ai_generation(user.user_id, limit)
except QuotaExceeded as exc:
    raise HTTPException(429, detail={...})           # 기존 429 바디 그대로
try:
    route = await route_service.create_running_route(req, user_id=user.user_id)
except Exception:
    await quota_service.release_ai_generation(reservation_id)  # 실패 = 무료 보존
    raise HTTPException(502, detail={"error": "route_generation_failed", ...})
# 성공: 예약이 곧 기록 — 별도 record 없음 (기존 record_ai_generation 제거)
return route
```
`reserve_ai_generation`(Python 래퍼): rpc 호출, `quota_exceeded` errcode →
`QuotaExceeded` 매핑. `release_ai_generation(id)`: `route_generations` 그 id
delete(best-effort — 실패해도 다음 주 리셋으로 회수되므로 치명 아님).

**unique-index 기각:** 주간 카운트 한도라 개수 제약 → unique 불가.

---

## 4. 실패 시 동작 (유저 체감)

세 함수 모두 **잠금 내부에 외부 호출(Gemini/T-map)이 없다** — 잠금 구간은
count+insert 수 ms. 따라서 "동시 클릭"의 패자는:

| 건 | 대기 | 패자가 받는 응답 |
|---|---|---|
| H3 | crews 행 잠금 ~ms | `409 CrewFull`(정원 찼으면) — 정상적인 "정원 마감"과 구분 불가·문제 없음 |
| M8 | owner advisory ~ms | `403 premium_required`(feature=crew_create, limit) — 업셀 화면 |
| M3 | user advisory ~ms | `429 quota_exceeded`(reset_at 포함) — "이번 주 소진" |

핵심: 잠금 대기가 사람이 못 느끼는 수준(ms)이고, 패자는 **이미 정의된 정상
에러**(409/403/429)를 받는다 — 새 에러 코드·타임아웃 없음. 크루장이 두 창에서
같은 신청을 동시 승인해도 H3 함수 내부 잠금으로 한쪽만 admit, 다른 쪽은
already_member(멱등).

**데드락 없음:** 각 rpc는 잠금을 **1개만**(crews 행 또는 advisory 키 하나) 잡고
단일 statement로 끝나 중첩·순서 문제가 없다.

---

## 5. 테스트 전략

**join 레이스 때의 mock 순차 패치는 여기 안 통한다.** 그때는 Python 레벨
TOCTOU(`_is_member` 두 번 호출 사이)라 `_is_member`를 `[False, True]`로 패치해
재현했지만, H3·M3·M8의 원자성은 **DB 안**에 있어 Python 패치로는 검증 불가.

**→ 실동시 요청 통합 테스트** 채택:
```python
# 예: H3 — max_members=N, 이미 N-1명. 서로 다른 유저 K명이 동시 가입.
results = await asyncio.gather(*[
    join_as(user_k) for user_k in extra_users
], return_exceptions=True)
# 불변식 검증 (수정본은 항상 성립):
assert member_count(crew) == N            # 절대 초과 안 함
assert sum(r == 204 for r in codes) == 1  # 정확히 1명만 admit
assert all(r == 409 for r in losers)      # 나머지 CrewFull
```
- **M3**: used=limit-1 상태에서 동시 3건 generate → `route_generations` 주간
  카운트 == limit(초과 없음), 성공 1건, 나머지 429. (Gemini 비용 우려 →
  `openai_service.generate_route`를 mock으로 대체해 파이프라인만 태우고 예약
  경로를 검증 — 예약은 Gemini 전에 일어나므로 mock으로 충분.)
- **M8**: 동시 2건 create → free 소유 크루 == 1, 성공 1·403 1.

**주의(결정성):** 수정본은 불변식이 **항상** 성립하므로 이 테스트는 안정적
(flaky 아님). 반면 "옛 버그 재현"(수정 전 초과 발생)은 창이 좁아 K를 크게
(예: 10~20 동시) 하거나 인위 지연이 필요할 수 있음 — 재현 데모는 선택,
**불변식 검증이 본질**. `asyncio.gather`로 같은 httpx.AsyncClient 동시 발사가
가장 현실적(별도 프로세스 불필요, 단일 uvicorn에 진짜 동시 도달).

---

## 6. 마이그레이션 순서 · 롤백

**데이터 마이그레이션 없음** — 세 함수는 순수 로직, 테이블 스키마 무변경
(route_generations/crew_members/crews 그대로). 그래서 가감이 자유롭다.

**배포 순서(전진):**
1. `CREATE OR REPLACE FUNCTION` 3종 먼저 적용 — 아무도 안 부르니 무해(옛 코드와
   공존).
2. 앱 코드 배포(rpc 호출로 전환).

**롤백(후진):**
1. 앱 코드 먼저 revert(rpc 호출 중단 → 옛 count-based 경로 복귀).
2. 함수는 남겨둬도 무해(아무도 안 부름). 원하면 `DROP FUNCTION admit_crew_member,
   create_crew_limited, reserve_ai_generation`.

**함수 교체 단순성:** `CREATE OR REPLACE`라 재적용 idempotent, 시그니처 불변이면
무중단 교체. 시그니처를 바꿔야 하면 `DROP` 후 `CREATE`(그 사이 호출은 잠깐
실패하므로 배포창에). 각 SQL 파일에 `[APPLY]`(CREATE OR REPLACE)와
`[ROLLBACK]`(DROP FUNCTION ... ) 섹션을 두는 기존 db/ 관례 유지.

---

## 7. 도입 트리거 (언제 백로그에서 꺼낼지)

**공통 강신호 — 멀티 인스턴스 전환:** uvicorn `workers>1` 또는 머신 2대+로 가는
순간 세 창이 모두 실질적으로 넓어진다(현재 단일 프로세스+베타 저동시성이라 창이
거의 안 열림). **멀티 인스턴스 계획이 서면 3건 일괄 구현.**

**건별 조기 신호(불변식 위반 쿼리가 곧 증거):**
- **H3**: `select cm.crew_id, count(*), c.max_members from crew_members cm
  join crews c on c.id=cm.crew_id where c.max_members is not null
  group by 1,3 having count(*) > c.max_members` — 1행이라도 나오면 이미 뚫림.
  또는 인기 크루(정원 근접)·초대링크 대량 공유·"정원 초과" 유저 리포트.
- **M3**: `select user_id, count(*) from route_generations
  where created_at >= <이번주 월요일 KST> group by 1 having count(*) > 3` —
  free 한도(3) 초과 유저 = 레이스 히트. Gemini 비용 이상치 알림도 신호.
- **M8**: `select owner_id, count(*) from crews group by 1 having count(*) > 1`
  ∩ free 유저 — free가 2개 소유 = 히트. 크루 생성이 과금 레버가 되면 상업적
  중요도 상승.

**우선순위:** 셋 다 실질 심각도 중간(H3=정책 위반, M3=소액 비용, M8=정책) —
베타 블로커 아님. 위 쿼리를 주 1회 크론으로 돌려 **행이 나오기 시작하면 그 건을
먼저** 꺼내고, 멀티 인스턴스 전환 시엔 선제적으로 3건 모두.

---

## 부록: 구현 체크리스트 (구현 시점에 이 순서로)

- [ ] `db/<날짜>_race_fix_rpcs.sql` — 3함수 CREATE OR REPLACE + ROLLBACK 주석
- [ ] Supabase에서 함수 적용(사용자 실행) 후 `select proname from pg_proc where proname in (...)`로 존재 확인
- [ ] `quota_service`: `reserve_ai_generation`/`release_ai_generation` 래퍼, `ensure_crew_creation`은 create RPC로 흡수(또는 tier→limit 계산만 남김)
- [ ] `crew_service._admit_member`·`create_crew` rpc 전환
- [ ] routes.py 생성 핸들러: check/record → reserve/release, create_crew 핸들러: 2단계 → 1 rpc
- [ ] 실동시 통합 테스트 3종(asyncio.gather, 불변식 검증). M3는 Gemini mock
- [ ] 기존 회귀: crew_manage·join_approval·challenge·quota·crew_limit 전체
- [ ] API_GUIDE 무변경 예상(에러 코드 동일 409/403/429) — 확인만
