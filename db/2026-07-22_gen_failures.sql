-- 502 가시화 (§3 처방 STEP 1, 2026-07-22) — RouteGenerationFailed 시 관측 영속.
-- 배경: RouteGenerationFailed는 routes 행을 안 만들어(코스 아님) gen_meta가 유실됨
--   → 실패 케이스 snap 분포가 완전 불가시(캠페인에서 강남 0/4 무데이터). 성공분만
--   보는 survivorship bias 제거용. **관측 전용** 경량 테이블 — routes 무오염.
-- 프라이버시: 유저 식별·정밀 좌표 미저장. 시작점은 격자 수준(소수 2자리≈1.1km)만.
-- 앱은 service_role로만 접근 → RLS enable(정책 없이, deny-by-default 백스톱, 전 테이블 표준).

-- ============================================================
-- [APPLY]  (Supabase SQL Editor에서 실행)
-- ============================================================
create table if not exists public.gen_failures (
  id         uuid        primary key default gen_random_uuid(),
  created_at timestamptz not null    default now(),
  -- gen_meta 동형(관측): snaps·pool_size·snapped_count·tmap_legs·snap_errors·
  -- elapsed_s·one_way·target_km·fail(사유) + grid_lat/grid_lng(격자 수준만).
  meta       jsonb       not null
);

alter table public.gen_failures enable row level security;   -- 정책 없음(service_role 전용)

-- 시간 범위 조회용(캠페인 분석은 최근 N건/기간)
create index if not exists gen_failures_created_idx
  on public.gen_failures (created_at desc);

-- ============================================================
-- [ROLLBACK]
-- ============================================================
-- drop index if exists public.gen_failures_created_idx;
-- drop table if exists public.gen_failures;

-- ============================================================
-- [VERIFY]  (적용 후 실행 — 존재·RLS·컬럼 확인)
-- ============================================================
-- select relname, relrowsecurity
--   from pg_class where relname = 'gen_failures';          -- relrowsecurity = t 여야
-- select column_name, data_type
--   from information_schema.columns
--   where table_schema='public' and table_name='gen_failures'
--   order by ordinal_position;                              -- id/created_at/meta
