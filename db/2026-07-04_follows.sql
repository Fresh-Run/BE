-- 팔로우 기능: follows 테이블 + notifications type CHECK 갱신
-- 적용: Supabase SQL Editor에서 [APPLY] 섹션 실행
-- 롤백: [ROLLBACK] 섹션 실행

-- ─────────────────────────────────────────────────────────────
-- [0] 사전 확인 — notifications의 현재 CHECK 제약 이름/정의 조회
--     (아래 [2]의 제약 이름 notifications_type_check가 안 맞으면
--      이 결과의 conname으로 바꿔서 실행)
-- ─────────────────────────────────────────────────────────────
-- select conname, pg_get_constraintdef(oid)
-- from pg_constraint
-- where conrelid = 'public.notifications'::regclass and contype = 'c';

-- ─────────────────────────────────────────────────────────────
-- [APPLY 1] follows 테이블 + 인덱스 + RLS
-- ─────────────────────────────────────────────────────────────
create table public.follows (
  follower_id  uuid not null references auth.users(id) on delete cascade,
  following_id uuid not null references auth.users(id) on delete cascade,
  created_at   timestamptz not null default now(),
  primary key (follower_id, following_id),
  constraint follows_no_self check (follower_id <> following_id)
);

-- 팔로잉 목록: "내가 팔로우하는 사람들" 최신순
create index follows_follower_created_idx
  on public.follows (follower_id, created_at desc);

-- 팔로워 목록: "나를 팔로우하는 사람들" 최신순 + 팔로워 카운트
create index follows_following_created_idx
  on public.follows (following_id, created_at desc);

-- 정책 없이 RLS만 활성화: anon/authenticated 직접 접근 전면 차단,
-- service_role(백엔드)만 통과. 비공개 계정 도입 대비 SELECT도 비공개.
alter table public.follows enable row level security;

-- ─────────────────────────────────────────────────────────────
-- [APPLY 2] notifications type CHECK에 'user_followed' 추가
-- ─────────────────────────────────────────────────────────────
alter table public.notifications
  drop constraint if exists notifications_type_check;

alter table public.notifications
  add constraint notifications_type_check
  check (type in (
    'route_liked',
    'route_commented',
    'crew_joined',
    'challenge_completed',
    'user_followed'
  ));

-- ─────────────────────────────────────────────────────────────
-- [APPLY 3] notifications target_type CHECK에 'user' 추가
--   (통합 테스트에서 발견: target_type에도 별도 CHECK가 존재,
--    'user_followed' 알림의 target_type='user' 삽입이 거부됨)
-- ─────────────────────────────────────────────────────────────
alter table public.notifications
  drop constraint if exists notifications_target_type_check;

alter table public.notifications
  add constraint notifications_target_type_check
  check (target_type in ('route', 'crew', 'user'));

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK] 역순 복구
-- ─────────────────────────────────────────────────────────────
-- alter table public.notifications
--   drop constraint if exists notifications_target_type_check;
--
-- alter table public.notifications
--   add constraint notifications_target_type_check
--   check (target_type in ('route', 'crew'));
--
-- alter table public.notifications
--   drop constraint if exists notifications_type_check;
--
-- alter table public.notifications
--   add constraint notifications_type_check
--   check (type in (
--     'route_liked',
--     'route_commented',
--     'crew_joined',
--     'challenge_completed'
--   ));
--
-- drop table if exists public.follows;
