-- 운영진 admin role + run 지역명 + 트랙 서버 거리 (3건 통합 —
-- docs/CREW_ADMIN_AND_RUN_AREA_DESIGN.md §1·§2·§3 승인분).
-- 미실행 — 사용자가 SQL Editor에서 실행.

-- [APPLY]
-- ① crew_members.role에 'admin' (현 제약 실증: crew_members_role_check, 23514)
alter table public.crew_members drop constraint if exists crew_members_role_check;
alter table public.crew_members add constraint crew_members_role_check
  check (role in ('owner', 'admin', 'member'));

-- ② run 지역명 (프론트 역지오코딩 결과 저장 — 과거 run은 null 유지, 백필 불가)
alter table public.runs add column if not exists area text;

-- ③ 트랙 서버 계산 거리 (0.2km 미만 splits 부재 → 응답 0.0 버그 수정.
--    신규 저장분만 채움, 구 행 null은 코드가 기존 splits 파생으로 폴백)
alter table public.run_tracks add column if not exists server_distance_km double precision;

-- 실행 후 확인:
-- select conname, pg_get_constraintdef(oid) from pg_constraint
--   where conname = 'crew_members_role_check';
-- select column_name, table_name from information_schema.columns
--   where (table_name = 'runs' and column_name = 'area')
--      or (table_name = 'run_tracks' and column_name = 'server_distance_km');

-- [ROLLBACK]
-- update public.crew_members set role = 'member' where role = 'admin';
-- alter table public.crew_members drop constraint if exists crew_members_role_check;
-- alter table public.crew_members add constraint crew_members_role_check
--   check (role in ('owner', 'member'));
-- alter table public.runs drop column if exists area;
-- alter table public.run_tracks drop column if exists server_distance_km;
