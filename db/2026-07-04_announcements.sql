-- 크루 공지 + 참석 투표(RSVP): crew_announcements, crew_announcement_rsvps
-- + notifications 6번째 타입 'crew_announcement'
-- 적용: Supabase SQL Editor에서 [APPLY] 섹션 실행 (실행 완료됨)
-- 롤백: [ROLLBACK] 섹션 실행

-- ─────────────────────────────────────────────────────────────
-- [APPLY 1] crew_announcements — 공지 (크루장 작성)
-- ─────────────────────────────────────────────────────────────
create table public.crew_announcements (
  id             uuid primary key default gen_random_uuid(),
  crew_id        uuid not null references public.crews(id) on delete cascade,
  author_id      uuid references auth.users(id) on delete set null,  -- 탈퇴해도 공지 보존
  title          text not null check (char_length(title) between 1 and 100),
  body           text not null check (char_length(body) between 1 and 2000),
  run_at         timestamptz,           -- 러닝 일시 (있어야 RSVP 가능)
  place_name     text,
  place_lat      double precision,
  place_lng      double precision,
  rsvp_closes_at timestamptz,           -- null이면 run_at이 사실상 마감
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint ann_place_pair      check ((place_lat is null) = (place_lng is null)),
  constraint ann_rsvp_needs_run  check (rsvp_closes_at is null or run_at is not null),
  constraint ann_rsvp_before_run check (rsvp_closes_at is null or rsvp_closes_at <= run_at)
);

create index crew_announcements_crew_created_idx
  on public.crew_announcements (crew_id, created_at desc);

alter table public.crew_announcements enable row level security;

-- ─────────────────────────────────────────────────────────────
-- [APPLY 2] crew_announcement_rsvps — 참석 투표 (한 명당 한 표)
-- ─────────────────────────────────────────────────────────────
create table public.crew_announcement_rsvps (
  announcement_id uuid not null references public.crew_announcements(id) on delete cascade,
  user_id         uuid not null references auth.users(id) on delete cascade,
  status          text not null check (status in ('going', 'not_going', 'maybe')),
  updated_at      timestamptz not null default now(),
  primary key (announcement_id, user_id)
);

alter table public.crew_announcement_rsvps enable row level security;

-- ─────────────────────────────────────────────────────────────
-- [APPLY 3] notifications CHECK 갱신 (type 6종 + target_type 4종)
-- ─────────────────────────────────────────────────────────────
alter table public.notifications drop constraint if exists notifications_type_check;
alter table public.notifications add constraint notifications_type_check
  check (type in ('route_liked', 'route_commented', 'crew_joined',
                  'challenge_completed', 'user_followed', 'crew_announcement'));

alter table public.notifications drop constraint if exists notifications_target_type_check;
alter table public.notifications add constraint notifications_target_type_check
  check (target_type in ('route', 'crew', 'user', 'announcement'));

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK] 역순 복구
--   주의: CHECK를 되돌리기 전에 crew_announcement 알림을 먼저 지워야
--   재생성 검증(기존 행 전체 검사)에 걸리지 않음
-- ─────────────────────────────────────────────────────────────
-- delete from public.notifications where type = 'crew_announcement';
--
-- alter table public.notifications drop constraint if exists notifications_type_check;
-- alter table public.notifications add constraint notifications_type_check
--   check (type in ('route_liked', 'route_commented', 'crew_joined',
--                   'challenge_completed', 'user_followed'));
--
-- alter table public.notifications drop constraint if exists notifications_target_type_check;
-- alter table public.notifications add constraint notifications_target_type_check
--   check (target_type in ('route', 'crew', 'user'));
--
-- drop table if exists public.crew_announcement_rsvps;   -- 자식 먼저
-- drop table if exists public.crew_announcements;
