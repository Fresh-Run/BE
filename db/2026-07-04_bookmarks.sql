-- 코스 북마크 (저장된 코스): route_bookmarks 테이블
-- 적용: Supabase SQL Editor에서 [APPLY] 섹션 실행
-- 롤백: [ROLLBACK] 섹션 실행

-- ─────────────────────────────────────────────────────────────
-- [APPLY] route_bookmarks — route_likes와 동일 구조
--   복합 PK로 중복 방지, 북마크는 비공개 행동이라 알림 없음
-- ─────────────────────────────────────────────────────────────
create table public.route_bookmarks (
  route_id   uuid not null references public.routes(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (route_id, user_id)
);

-- "내 저장 코스 목록" 최신순 조회용
create index route_bookmarks_user_created_idx
  on public.route_bookmarks (user_id, created_at desc);

-- 정책 없이 RLS만 활성화: service_role(백엔드)만 접근
alter table public.route_bookmarks enable row level security;

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- drop table if exists public.route_bookmarks;
