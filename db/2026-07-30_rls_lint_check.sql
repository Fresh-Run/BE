-- Supabase 린터 rls_disabled_in_public 경고(7/26 메일) 판별·해소 (실행: 오너).
--
-- 서버측 사전 조사(2026-07-30): ① 데이터 프로브(scripts/verify_rls.py) — 33테이블 중
--   29 deny 확정, 4는 빈 테이블이라 판정 보류(iap_notifications_raw·monthly_insights·
--   preferences·subscriptions) ② DDL 파일 전수 — 전 테이블 enable 문 존재(단 §B:
--   파일 존재 ≠ 실행 보장) ③ PostGIS 확장 소유 3종(spatial_ref_sys·geometry_columns·
--   geography_columns)은 RLS enable 자체가 불가 — **린터 경고의 유력 후보이며 무해**
--   (07-15에 spatial_ref_sys 공개 쓰기 revoke 완료. 뷰 2종은 읽기 전용 카탈로그).
--
-- [1단계 — 판별 쿼리] 실제 rowsecurity=false 테이블 목록(이게 메일의 대상 목록):
select tablename, rowsecurity
from pg_tables
where schemaname = 'public'
order by rowsecurity, tablename;

-- [ROLLBACK] — 아래 APPLY 대상별(1단계 결과에 실린 앱 테이블만):
-- alter table public.<테이블명> disable row level security;

-- [APPLY] — 판정 보류 4종 멱등 enable(이미 enable이면 no-op·무해. 1단계 결과에
-- 다른 앱 테이블이 나오면 같은 문형으로 추가):
alter table public.iap_notifications_raw enable row level security;
alter table public.monthly_insights      enable row level security;
alter table public.preferences           enable row level security;
alter table public.subscriptions         enable row level security;

-- [확인쿼리] — 판정 기준: rowsecurity=false 잔여가 PostGIS 3종(불가 항목)뿐이면 정상.
select tablename
from pg_tables
where schemaname = 'public' and rowsecurity = false
order by tablename;
