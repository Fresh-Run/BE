-- account_kind P1.5 (backfill): 확정 11계정에 kind 세팅. **P1 컬럼 추가 이후 실행**.
--   이메일 매칭은 이 backfill 1회성 해석에만 사용(auth.users lower(email) 조인) →
--   저장은 user_id 행에 account_kind로 남긴다. 이후 런타임은 이메일 매칭 안 씀.
--   매핑(합 11): owner=2 / demo=5 / qa=3 / internal=1.
--     owner    = test3@freshrun.com, cvcv0824@gmail.com        (오너 영구 프리미엄 불가침)
--     demo     = demo1@ ~ demo5@freshrun.com                   (데모 계정)
--     qa       = test1@, test2@, qa-empty@freshrun.com         (QA/픽스처)
--     internal = freshrun0609@gmail.com                        (운영진)
--
-- ⚠️ ADDITIVE·BEHAVIOR 무변경 — 이 컬럼을 읽는 코드 0(dual-read는 P2). 배포·코드변경 불요.
-- 안전장치: 전체를 트랜잭션으로 감싸고, UPDATE 직후 kind별 카운트를 assert(DO/RAISE).
--   기대(owner=2/demo=5/qa=3/internal=1, 합11)와 불일치면 EXCEPTION → 자동 롤백.
--   (계정 미존재·이메일 중복·profiles 행 부재는 전부 카운트 부족/초과로 걸려 롤백된다.)
-- 멱등: 재실행해도 같은 11행에 같은 kind → 카운트 불변 → assert 통과.
-- 패턴 출처: db/2026-07-27_apple_review_premium.sql(user_id UPDATE + updated_at=now()).
--
-- 미실행 — 사용자(지연)가 Supabase SQL Editor에서 실행. P1 검증 완료 후 이 블록 전체를
-- 한 번에 실행(begin~commit + 확인 SELECT). assert 실패 시 아무 것도 커밋되지 않음.

-- ── [사전 확인쿼리] (선택 — UPDATE 전 매핑·누락·중복 눈으로 검증) ──────────────
-- 판정: 11행 · email_dupe_count 전부 1 · user_id 전부 non-null 이어야 안전.
-- with want(email, kind) as (values
--   ('test3@freshrun.com','owner'),('cvcv0824@gmail.com','owner'),
--   ('demo1@freshrun.com','demo'),('demo2@freshrun.com','demo'),('demo3@freshrun.com','demo'),
--   ('demo4@freshrun.com','demo'),('demo5@freshrun.com','demo'),
--   ('test1@freshrun.com','qa'),('test2@freshrun.com','qa'),('qa-empty@freshrun.com','qa'),
--   ('freshrun0609@gmail.com','internal'))
-- select w.email, w.kind, u.id as user_id, p.user_id is not null as has_profile,
--        count(*) over (partition by w.email) as email_dupe_count
-- from want w
-- left join auth.users u on lower(u.email) = w.email
-- left join public.profiles p on p.user_id = u.id
-- order by w.kind, w.email;

-- ── [APPLY] (트랜잭션 — assert 실패 시 전체 롤백) ────────────────────────────
begin;

update public.profiles p
set account_kind = 'owner', updated_at = now()
from auth.users u
where u.id = p.user_id
  and lower(u.email) in ('test3@freshrun.com', 'cvcv0824@gmail.com');

update public.profiles p
set account_kind = 'demo', updated_at = now()
from auth.users u
where u.id = p.user_id
  and lower(u.email) in ('demo1@freshrun.com', 'demo2@freshrun.com',
    'demo3@freshrun.com', 'demo4@freshrun.com', 'demo5@freshrun.com');

update public.profiles p
set account_kind = 'qa', updated_at = now()
from auth.users u
where u.id = p.user_id
  and lower(u.email) in ('test1@freshrun.com', 'test2@freshrun.com',
    'qa-empty@freshrun.com');

update public.profiles p
set account_kind = 'internal', updated_at = now()
from auth.users u
where u.id = p.user_id
  and lower(u.email) = 'freshrun0609@gmail.com';

-- assert: kind별 정확 카운트(owner2/demo5/qa3/internal1). 불일치 → EXCEPTION → 롤백.
do $$
declare
  n_owner    int; n_demo int; n_qa int; n_internal int;
begin
  select count(*) into n_owner    from public.profiles where account_kind = 'owner';
  select count(*) into n_demo     from public.profiles where account_kind = 'demo';
  select count(*) into n_qa       from public.profiles where account_kind = 'qa';
  select count(*) into n_internal from public.profiles where account_kind = 'internal';
  if n_owner <> 2 or n_demo <> 5 or n_qa <> 3 or n_internal <> 1 then
    raise exception
      'account_kind backfill 불일치: owner=% demo=% qa=% internal=% (기대 2/5/3/1, 합11). 롤백함 — 사전 확인쿼리로 누락/중복 점검.',
      n_owner, n_demo, n_qa, n_internal;
  end if;
end $$;

commit;

-- [확인쿼리] — 커밋 후. 판정 기준: owner=2 / demo=5 / qa=3 / internal=1 / null=나머지 / 합계행11
select coalesce(account_kind, '(null)') as account_kind, count(*) as n
from public.profiles
group by account_kind
order by account_kind nulls last;

-- [ROLLBACK] (해당 11 user_id 한정 — 이메일 재해석은 롤백 1회성)
-- update public.profiles p
-- set account_kind = null, updated_at = now()
-- from auth.users u
-- where u.id = p.user_id
--   and lower(u.email) in ('test3@freshrun.com','cvcv0824@gmail.com',
--     'demo1@freshrun.com','demo2@freshrun.com','demo3@freshrun.com',
--     'demo4@freshrun.com','demo5@freshrun.com',
--     'test1@freshrun.com','test2@freshrun.com','qa-empty@freshrun.com',
--     'freshrun0609@gmail.com');
