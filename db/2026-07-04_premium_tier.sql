-- 프리미엄 티어 기반: profiles.tier + AI 생성 쿼터 로그 테이블
-- 적용: Supabase SQL Editor에서 [APPLY] 섹션 실행
-- 롤백: [ROLLBACK] 섹션 실행

-- ─────────────────────────────────────────────────────────────
-- [APPLY 1] profiles.tier — 'free'/'premium', 기본 free
--   쓰기 경로는 관리자(대시보드)뿐. 앱 코드는 읽기만 하며,
--   ProfileUpdate에 tier가 없어 유저 자가 승급 불가.
--   나중에 IAP 웹훅이 이 컬럼을 갱신하는 구조로 확장.
-- ─────────────────────────────────────────────────────────────
alter table public.profiles
  add column tier text not null default 'free'
  constraint profiles_tier_check check (tier in ('free', 'premium'));

-- ─────────────────────────────────────────────────────────────
-- [APPLY 2] route_generations — AI 코스 생성 불변 로그
--   쿼터 카운트 전용 (routes 카운트는 삭제-리필 루프홀이 있어 사용 안 함).
--   생성 성공 시 1행 insert, 주간 카운트는 created_at >= 월요일 00:00 KST.
-- ─────────────────────────────────────────────────────────────
create table public.route_generations (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);

create index route_generations_user_created_idx
  on public.route_generations (user_id, created_at desc);

-- 정책 없이 RLS만 활성화: service_role(백엔드)만 접근 가능
alter table public.route_generations enable row level security;

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK] 역순 복구
-- ─────────────────────────────────────────────────────────────
-- drop table if exists public.route_generations;
-- alter table public.profiles drop column if exists tier;
