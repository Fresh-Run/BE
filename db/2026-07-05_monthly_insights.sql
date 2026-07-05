-- AI 월간 인사이트: AI 텍스트(coaching + plan) 캐시 — run_count 무효화 방식
-- 적용: Supabase SQL Editor에서 [APPLY] 섹션 실행 (실행 완료됨)
-- 롤백: [ROLLBACK] 섹션 실행

-- ─────────────────────────────────────────────────────────────
-- [APPLY] monthly_insights — 유저·월당 1행.
--   run_count = 생성 시점 해당 월 run 수: 이번 달은 러닝할 때만 재생성되고
--   지난달은 run_count가 변하지 않으므로 자동 영구 캐시가 된다.
--   수치 블록은 캐시하지 않는다 (매 요청 계산 — AI 텍스트만 저장).
-- ─────────────────────────────────────────────────────────────
create table public.monthly_insights (
  user_id    uuid not null references auth.users(id) on delete cascade,
  year       int  not null,
  month      int  not null,
  run_count  int  not null,
  coaching   text not null,
  plan       jsonb not null,  -- [{slot: goal|focus|challenge, title, body} × 3]
  model      text,
  created_at timestamptz not null default now(),
  primary key (user_id, year, month)
);

alter table public.monthly_insights enable row level security;  -- 정책 없음 (service_role만)

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- drop table if exists public.monthly_insights;
