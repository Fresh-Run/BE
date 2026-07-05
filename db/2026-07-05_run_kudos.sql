-- run kudos + 활동 피드: run_kudos 테이블 + 알림 9종/target_type 'run'
-- 적용: Supabase SQL Editor에서 [APPLY] 섹션 실행 (실행 완료됨)
-- 롤백: [ROLLBACK] 섹션 실행

-- ─────────────────────────────────────────────────────────────
-- [APPLY 1] run_kudos — route_likes와 동형 (응원 좋아요)
--   집계·my_kudos 조회는 PK의 run_id prefix로 커버, 추가 인덱스 불필요.
--   활동 피드의 runs 조회는 기존 runs_user_ran_at_idx를 그대로 사용.
-- ─────────────────────────────────────────────────────────────
create table public.run_kudos (
  run_id     uuid not null references public.runs(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (run_id, user_id)
);

alter table public.run_kudos enable row level security;  -- 정책 없음 (service_role만)

-- ─────────────────────────────────────────────────────────────
-- [APPLY 2] notifications: type 9종 + target_type에 'run' 추가
-- ─────────────────────────────────────────────────────────────
alter table public.notifications drop constraint if exists notifications_type_check;
alter table public.notifications add constraint notifications_type_check
  check (type in ('route_liked', 'route_commented', 'crew_joined',
                  'challenge_completed', 'user_followed', 'crew_announcement',
                  'join_requested', 'join_approved', 'run_kudoed'));

alter table public.notifications drop constraint if exists notifications_target_type_check;
alter table public.notifications add constraint notifications_target_type_check
  check (target_type in ('route', 'crew', 'user', 'announcement', 'run'));

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK] 역순 복구 (알림 delete 먼저 — CHECK 재생성 검증 통과용)
-- ─────────────────────────────────────────────────────────────
-- delete from public.notifications where type = 'run_kudoed';
--
-- alter table public.notifications drop constraint if exists notifications_type_check;
-- alter table public.notifications add constraint notifications_type_check
--   check (type in ('route_liked', 'route_commented', 'crew_joined',
--                   'challenge_completed', 'user_followed', 'crew_announcement',
--                   'join_requested', 'join_approved'));
--
-- alter table public.notifications drop constraint if exists notifications_target_type_check;
-- alter table public.notifications add constraint notifications_target_type_check
--   check (target_type in ('route', 'crew', 'user', 'announcement'));
--
-- drop table if exists public.run_kudos;
