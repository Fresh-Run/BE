-- run 댓글: run_comments (route_comments 미러) + run_commented 알림 타입(10종째)
-- 적용됨(사용자 실행 — RLS enable 포함).
-- 가시성/권한은 앱 레이어(_can_see_run 게이트, 작성자+run주인 삭제)에서 강제하고,
-- service_role 클라이언트가 RLS를 우회하므로 RLS는 anon/authenticated 직접
-- 접근 차단용 방어선이다.

-- [APPLY]
create table if not exists public.run_comments (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.runs(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  content text not null,
  created_at timestamptz not null default now()
);
create index if not exists run_comments_run_created_idx
  on public.run_comments (run_id, created_at desc);   -- 최신순 목록·카운트용

-- RLS 활성화 (직접 접근 차단 — 앱은 service_role로만 접근).
alter table public.run_comments enable row level security;

-- run_commented 알림 타입 추가 (10종째). target_type 'run'은 2026-07-05_run_kudos에서 이미 허용.
alter table public.notifications drop constraint if exists notifications_type_check;
alter table public.notifications add constraint notifications_type_check
  check (type in ('route_liked', 'route_commented', 'crew_joined',
                  'challenge_completed', 'user_followed', 'crew_announcement',
                  'join_requested', 'join_approved', 'run_kudoed',
                  'run_commented'));

-- [ROLLBACK]
-- alter table public.notifications drop constraint if exists notifications_type_check;
-- alter table public.notifications add constraint notifications_type_check
--   check (type in ('route_liked', 'route_commented', 'crew_joined',
--                   'challenge_completed', 'user_followed', 'crew_announcement',
--                   'join_requested', 'join_approved', 'run_kudoed'));
-- drop table if exists public.run_comments;
