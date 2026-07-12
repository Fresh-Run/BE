-- 팔로우 승인제 v2 (docs/PRIVATE_PROFILE_DESIGN.md §2).
-- crew join_requests 패턴 재사용. PK (requester,target)가 요청당 1행을 강제 —
-- pending 중복 TOCTOU를 PK 충돌(23505)로 원천 봉쇄(별도 부분 유니크 불필요,
-- 크루는 id PK라 부분 유니크가 필요했으나 여기선 PK가 그 역할). 재신청은
-- rejected→pending status 갱신(거절 이력은 미보존 — 단순, 재신청 허용 충족).
-- 미실행 — 사용자가 SQL Editor에서 실행.

-- [APPLY]
alter table public.profiles
  add column if not exists follow_approval boolean not null default false;

create table if not exists public.follow_requests (
  requester_id uuid not null references auth.users(id) on delete cascade,
  target_id    uuid not null references auth.users(id) on delete cascade,
  status       text not null default 'pending'
               check (status in ('pending', 'approved', 'rejected')),
  created_at   timestamptz not null default now(),
  decided_at   timestamptz,
  primary key (requester_id, target_id),
  constraint follow_req_no_self check (requester_id <> target_id)
);
create index if not exists follow_requests_target_pending_idx
  on public.follow_requests (target_id, created_at desc) where (status = 'pending');
alter table public.follow_requests enable row level security;

-- 실행 후 확인:
-- select column_name from information_schema.columns
--   where table_name='profiles' and column_name='follow_approval';
-- select tablename, rowsecurity from pg_tables where tablename='follow_requests';

-- [ROLLBACK]
-- drop table if exists public.follow_requests;
-- alter table public.profiles drop column if exists follow_approval;
