-- 계정 삭제(회원 탈퇴) 전제: preferences.user_id FK 재작성 (NO ACTION → CASCADE).
-- 왜: 실증(2026-07-08)에서 이 FK가 auth.users 삭제를 23503으로 차단 — 탈퇴의
-- 유일한 스키마 블로커. 나머지 유저 참조 테이블은 전부 cascade/set null 확정
-- (docs/ACCOUNT_DELETION_DESIGN.md §1). 미실행 — 사용자가 SQL Editor에서 실행.

-- [APPLY]
alter table public.preferences
  drop constraint if exists preferences_user_id_fkey;
alter table public.preferences
  add constraint preferences_user_id_fkey
  foreign key (user_id) references auth.users(id) on delete cascade;

-- 실행 후 확인 (confdeltype가 'c'면 cascade):
-- select conname, confdeltype from pg_constraint
-- where conname = 'preferences_user_id_fkey';

-- [ROLLBACK]
-- alter table public.preferences drop constraint if exists preferences_user_id_fkey;
-- alter table public.preferences add constraint preferences_user_id_fkey
--   foreign key (user_id) references auth.users(id);
