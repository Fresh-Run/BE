-- 차단 v3 (docs/PRIVATE_PROFILE_DESIGN.md §3). PK (blocker,blocked)로 중복
-- 차단 멱등 봉쇄(승인제/follow_requests와 동일 패턴). 양방향 노출 차단은
-- 앱(can_see_user)이 (blocker,blocked)·(blocked,blocker) 양쪽을 봐서 판정 —
-- blocked_id 인덱스로 역방향 조회. 탈퇴 시 양방향 FK cascade(내가 차단한 것·
-- 나를 차단한 것 모두). 미실행 — 사용자가 SQL Editor에서 실행.

-- [APPLY]
create table if not exists public.blocks (
  blocker_id uuid not null references auth.users(id) on delete cascade,
  blocked_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (blocker_id, blocked_id),
  constraint blocks_no_self check (blocker_id <> blocked_id)
);
create index if not exists blocks_blocked_idx on public.blocks (blocked_id);
alter table public.blocks enable row level security;

-- 실행 후 확인:
-- select tablename, rowsecurity from pg_tables where tablename = 'blocks';

-- [ROLLBACK]
-- drop table if exists public.blocks;
