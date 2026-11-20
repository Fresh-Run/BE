-- account_kind P1 (컬럼 추가): 이메일 기반 계정 보호 → user_id 기반 이관 1단계.
--   profiles에 account_kind를 additive·nullable·default null로 추가한다.
--   저장위치 설계 확정 = (ii) profiles.account_kind (ACCOUNT_KIND 이관 설계).
--
-- ⚠️ 이 단계는 ADDITIVE·BEHAVIOR 무변경 — 컬럼 추가만, 값 채움은 P1.5(별도 파일),
--    "읽는 코드"는 아직 0(dual-read는 P2). 따라서 **배포·코드변경 불요**(SQL만).
--    · nullable·default null → 기존 profiles 전 행 무영향(§D additive).
--    · GET/PATCH /me/profile 무영향 확인: ProfileResponse는 extra 기본='ignore'
--      (ProfileUpdate만 extra='forbid') → select("*")가 account_kind를 실어와도
--      응답 모델이 조용히 드롭 → **클라 노출 0·계약 불변**(behavior 무변경 근거).
--    · RLS: profiles는 이미 RLS enable(기존 테이블) → 신규 컬럼 자동 커버, 정책 추가 불요.
--    · 패턴 출처: db/2026-07-27_apple_review_premium.sql(user_id 기반 profiles 조작).
--
-- 미실행 — 사용자(지연)가 Supabase SQL Editor에서 실행. **P1 먼저 실행·검증 → 그 다음
-- db/2026-09-15_account_kind_backfill.sql(P1.5)**. 한 번에 붙여넣지 말 것.

-- [ROLLBACK] (역순: 제약 → 컬럼)
-- alter table public.profiles drop constraint if exists profiles_account_kind_check;
-- alter table public.profiles drop column if exists account_kind;

-- [APPLY]
alter table public.profiles
  add column if not exists account_kind text default null;

-- CHECK: 4값 또는 NULL. (idempotent: drop→add 재작성 — 재실행 안전)
alter table public.profiles
  drop constraint if exists profiles_account_kind_check;
alter table public.profiles
  add constraint profiles_account_kind_check
  check (account_kind is null or account_kind in ('owner','demo','qa','internal'));

-- [확인쿼리] — 판정 기준: 컬럼 존재 + CHECK 정의에 4값 열거 + 기존 행 전부 null
-- select count(*) as total, count(account_kind) as non_null_kind  -- non_null_kind=0 기대
-- from public.profiles;
-- select pg_get_constraintdef(oid) from pg_constraint
-- where conname = 'profiles_account_kind_check';
