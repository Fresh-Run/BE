-- 레이스 컨디션 수정 RPC 3종 (H3 정원 · M8 크루한도 · M3 AI쿼터)
-- 설계: docs/RACE_FIX_DESIGN.md. check-then-act를 Postgres 함수 하나로 원자화.
-- service_role만 호출(RLS 우회) → SECURITY INVOKER 기본. 데이터 마이그레이션 없음.

-- ─────────────────────────────────────────────────────────────
-- [APPLY]
-- ─────────────────────────────────────────────────────────────

-- H3: 크루 정원 — crews 행 FOR UPDATE로 per-crew 직렬화
create or replace function admit_crew_member(
  _crew_id uuid, _user_id uuid, _role text default 'member'
) returns table(status text, member_count int)
language plpgsql as $$
declare _max int; _cur int;
begin
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

-- M8: 크루 생성 한도 — owner advisory lock + count. crew를 jsonb로 받아
-- jsonb_populate_record로 로우 구성(컬럼 자동 매핑 — 신규 컬럼도 SQL 무변경).
create or replace function create_crew_limited(
  _owner_id uuid, _limit int, _crew jsonb
) returns public.crews
language plpgsql as $$
declare _cnt int; _row public.crews;
begin
  perform pg_advisory_xact_lock(hashtext('crew_create:' || _owner_id::text));
  if _limit is not null then
    select count(*) into _cnt from public.crews where owner_id = _owner_id;
    if _cnt >= _limit then
      raise exception 'crew_limit_exceeded' using errcode = 'P0001';
    end if;
  end if;
  -- jsonb → crews 로우. 알 수 없는 키는 무시, 미지정 컬럼은 null.
  -- id/created_at/owner_id는 서버가 강제(클라 지정 무시).
  _row := jsonb_populate_record(null::public.crews, _crew);
  _row.id := gen_random_uuid();
  _row.created_at := now();
  _row.owner_id := _owner_id;
  insert into public.crews values (_row.*) returning * into _row;
  insert into public.crew_members (crew_id, user_id, role)
    values (_row.id, _owner_id, 'owner');
  return _row;
end $$;

-- M3: AI 생성 쿼터 — user advisory lock + 주간 count, Gemini 전에 슬롯 예약.
-- 실패 시 앱이 이 id 행을 삭제(release)해 "실패는 무료" 시맨틱 보존.
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
  return _id;
end $$;

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]  (앱 코드를 먼저 revert한 뒤 실행)
-- ─────────────────────────────────────────────────────────────
-- drop function if exists admit_crew_member(uuid, uuid, text);
-- drop function if exists create_crew_limited(uuid, int, jsonb);
-- drop function if exists reserve_ai_generation(uuid, int, timestamptz);
