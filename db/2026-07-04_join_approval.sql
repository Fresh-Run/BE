-- 크루 가입 승인제: crews.join_policy + crew_join_requests
-- + notifications 8종 (join_requested, join_approved 추가)
-- 적용: Supabase SQL Editor에서 [APPLY] 섹션 실행 (실행 완료됨)
-- 롤백: [ROLLBACK] 섹션 실행

-- ─────────────────────────────────────────────────────────────
-- [APPLY 1] crews.join_policy — 기본 'open'이라 기존 크루 동작 불변
-- ─────────────────────────────────────────────────────────────
alter table public.crews
  add column join_policy text not null default 'open'
  constraint crews_join_policy_check check (join_policy in ('open', 'approval'));

-- ─────────────────────────────────────────────────────────────
-- [APPLY 2] crew_join_requests — 가입 신청
--   pending 중복만 막고(부분 유니크) 거절 이력은 남겨 재신청 허용
-- ─────────────────────────────────────────────────────────────
create table public.crew_join_requests (
  id         uuid primary key default gen_random_uuid(),
  crew_id    uuid not null references public.crews(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  status     text not null default 'pending'
             check (status in ('pending', 'approved', 'rejected')),
  created_at timestamptz not null default now(),
  decided_at timestamptz,
  decided_by uuid references auth.users(id) on delete set null
);

create unique index crew_join_requests_one_pending_idx
  on public.crew_join_requests (crew_id, user_id) where (status = 'pending');

create index crew_join_requests_pending_idx
  on public.crew_join_requests (crew_id, created_at desc) where (status = 'pending');

alter table public.crew_join_requests enable row level security;  -- 정책 없음

-- ─────────────────────────────────────────────────────────────
-- [APPLY 3] notifications type CHECK: 8종
-- ─────────────────────────────────────────────────────────────
alter table public.notifications drop constraint if exists notifications_type_check;
alter table public.notifications add constraint notifications_type_check
  check (type in ('route_liked', 'route_commented', 'crew_joined',
                  'challenge_completed', 'user_followed', 'crew_announcement',
                  'join_requested', 'join_approved'));

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK] 역순 복구 (알림 delete 먼저 — CHECK 재생성 검증 통과용)
-- ─────────────────────────────────────────────────────────────
-- delete from public.notifications where type in ('join_requested', 'join_approved');
--
-- alter table public.notifications drop constraint if exists notifications_type_check;
-- alter table public.notifications add constraint notifications_type_check
--   check (type in ('route_liked', 'route_commented', 'crew_joined',
--                   'challenge_completed', 'user_followed', 'crew_announcement'));
--
-- drop table if exists public.crew_join_requests;
-- alter table public.crews drop column if exists join_policy;
