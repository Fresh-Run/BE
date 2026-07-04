-- 크루 러닝 피드: runs (user_id, ran_at desc) 복합 인덱스
-- (크루 피드의 user_id IN + ORDER BY ran_at DESC와 개인 통계 쿼리 가속)
-- 적용: Supabase SQL Editor에서 실행 (실행 완료됨)

create index if not exists runs_user_ran_at_idx
  on public.runs (user_id, ran_at desc);

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- drop index if exists public.runs_user_ran_at_idx;
