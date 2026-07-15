-- spatial_ref_sys (PostGIS 확장 소유 시스템 테이블) 공개 쓰기 차단.
-- Advisor "rls_disabled_in_public" Error 대응. 실측(2026-07-15): anon SELECT 200
-- (공개 좌표계 참조 — 무해) + anon UPDATE 204(쓰기 열림 — 실위험). 우리 앱은 이
-- 테이블·PostGIS 함수를 직접 쓰지 않아 서비스 영향 0이나 원칙상 public write는 차단.
-- 미실행 — 사용자가 Supabase SQL Editor에서 실행.
--
-- ⚠️ 이 테이블은 PostGIS 확장 소유라 우리 role이 테이블 소유자가 아니다.
--   [APPLY-1] RLS enable을 먼저 시도(성공하면 Advisor 경고가 사라진다).
--   42501(must be owner) 나면 그 문장만 건너뛰고 [APPLY-2] REVOKE만 실행 —
--   REVOKE는 소유권이 아니라 grant 관리 권한이면 되므로 대개 성공한다.
--   REVOKE만 적용 시 Advisor의 'rls_disabled'는 남을 수 있으나(RLS 자체는 여전히
--   off) 실쓰기 위험은 0 — 그 경우 대시보드 Advisor에서 이 lint를 예외처리(무시).

-- ─────────────────────────────────────────────────────────────
-- [APPLY-1] RLS enable 시도 (소유권 있으면 이게 정답 — 경고 소멸)
-- ─────────────────────────────────────────────────────────────
alter table public.spatial_ref_sys enable row level security;
-- ↑ ERROR 42501: must be owner of table spatial_ref_sys  →  이 줄만 건너뛰고 아래로.

-- ─────────────────────────────────────────────────────────────
-- [APPLY-2] anon·authenticated 쓰기 권한 회수 (읽기는 유지 — 공개 표준 데이터)
-- ─────────────────────────────────────────────────────────────
revoke insert, update, delete on table public.spatial_ref_sys from anon, authenticated;

-- ─────────────────────────────────────────────────────────────
-- [확인 쿼리]
-- ─────────────────────────────────────────────────────────────
-- (1) RLS enable 여부 (APPLY-1 성공했으면 t)
select relname, relrowsecurity
  from pg_class where relname = 'spatial_ref_sys';
-- (2) anon/authenticated 잔여 권한 — SELECT만 남아야 정상(INSERT/UPDATE/DELETE 부재)
select grantee, privilege_type
  from information_schema.role_table_grants
 where table_schema = 'public' and table_name = 'spatial_ref_sys'
   and grantee in ('anon', 'authenticated')
 order by grantee, privilege_type;

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- grant insert, update, delete on table public.spatial_ref_sys to anon, authenticated;
-- alter table public.spatial_ref_sys disable row level security;   -- APPLY-1 성공했을 때만
