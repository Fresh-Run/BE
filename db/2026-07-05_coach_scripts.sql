-- AI 오디오 코치: 코스별 코칭 멘트 스크립트 캐시 (route당 1회 생성)
-- 적용: Supabase SQL Editor에서 [APPLY] 섹션 실행 (실행 완료됨)
-- 롤백: [ROLLBACK] 섹션 실행

-- ─────────────────────────────────────────────────────────────
-- [APPLY] coach_scripts — routes와 1:1, 목록 쿼리에서 스크립트가
--   딸려오지 않도록 routes JSONB 컬럼 대신 별도 테이블로 분리.
-- ─────────────────────────────────────────────────────────────
create table public.coach_scripts (
  route_id   uuid primary key references public.routes(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  script     jsonb not null,          -- {"cues": [{trigger, at, text}, ...]}
  model      text,                    -- 생성 모델 기록 (프롬프트 개선 추적용)
  created_at timestamptz not null default now()
);

alter table public.coach_scripts enable row level security;  -- 정책 없음 (service_role만)

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- drop table if exists public.coach_scripts;
