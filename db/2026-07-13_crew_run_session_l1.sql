-- 크루 러닝 세션 태깅 L1 (docs/CREW_RUN_SESSION_L1_DESIGN.md). runs에 crew_id
-- 태그 + session_key(서버 파생 그룹 키). 기존 run은 둘 다 null(정기런 아님) —
-- 백필 없음. 크루 삭제 시 태그만 소거(set null), run 보존. runs는 이미 RLS
-- enable. 적용 완료 — 사용자가 SQL Editor에서 실행.

-- [ROLLBACK] (먼저)
-- drop index if exists runs_session_key_idx;
-- drop index if exists runs_crew_id_idx;
-- alter table public.runs drop column if exists session_key;
-- alter table public.runs drop column if exists crew_id;

-- [APPLY]
alter table public.runs add column if not exists crew_id uuid
  references public.crews(id) on delete set null;      -- 크루 삭제 시 태그만 소거
alter table public.runs add column if not exists session_key text;
create index if not exists runs_crew_id_idx     on public.runs (crew_id);
create index if not exists runs_session_key_idx on public.runs (session_key);

-- 실행 후 확인:
-- select column_name from information_schema.columns
--   where table_name='runs' and column_name in ('crew_id','session_key');
--   → 2행(crew_id·session_key)
