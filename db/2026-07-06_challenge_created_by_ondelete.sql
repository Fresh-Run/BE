-- 감사 H2: crew_challenges.created_by에 ON DELETE 절이 없어, 챌린지 생성 후
-- 크루 소유권을 위임하면 생성자의 계정 삭제가 FK 위반으로 영구 차단됨.
-- SET NULL로 변경 (챌린지 이력은 보존, 작성자만 null — 공지 author_id와 동일 정책).
-- 적용: Supabase SQL Editor에서 [APPLY] 실행 (제약명 무관 — 동적 처리).

-- ─────────────────────────────────────────────────────────────
-- [APPLY]
-- ─────────────────────────────────────────────────────────────
-- 1) created_by에 걸린 기존 FK를 이름 무관하게 찾아 제거 (Supabase 기본명이
--    환경마다 다를 수 있으므로 pg_constraint에서 동적 조회).
do $$
declare
  con_name text;
begin
  for con_name in
    select con.conname
    from pg_constraint con
    join pg_attribute att
      on att.attrelid = con.conrelid and att.attnum = any(con.conkey)
    where con.conrelid = 'public.crew_challenges'::regclass
      and con.contype = 'f'
      and att.attname = 'created_by'
  loop
    execute format('alter table public.crew_challenges drop constraint %I', con_name);
  end loop;
end $$;

-- 2) 컬럼을 nullable로 (위임 계정 삭제 시 null 허용)
alter table public.crew_challenges
  alter column created_by drop not null;

-- 3) ON DELETE SET NULL로 재생성
alter table public.crew_challenges
  add constraint crew_challenges_created_by_fkey
  foreign key (created_by) references auth.users(id) on delete set null;

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]  (created_by에 null이 생긴 뒤에는 not null 복구 불가 — 참고)
-- ─────────────────────────────────────────────────────────────
-- alter table public.crew_challenges drop constraint if exists crew_challenges_created_by_fkey;
-- alter table public.crew_challenges
--   add constraint crew_challenges_created_by_fkey
--   foreign key (created_by) references auth.users(id) on delete cascade;
