-- 프로필 신체 정보 4종 (선택 입력, 본인 전용 — /me/profile에만 노출)
-- 적용: Supabase SQL Editor에서 [APPLY] 섹션 실행
-- 롤백: [ROLLBACK] 섹션 실행
--
-- 프라이버시: 이 컬럼들은 ProfileResponse(/me/profile)에만 매핑된다.
-- 다른 유저가 보는 응답 모델(공개 프로필·팔로우·로스터·피드·kudos·RSVP)은
-- 전부 명시 필드라 스키마 차원에서 노출이 차단됨 — 테스트로 전수 검증.

-- ─────────────────────────────────────────────────────────────
-- [APPLY]
-- ─────────────────────────────────────────────────────────────
alter table public.profiles
  add column if not exists birth_year int
    check (birth_year between 1920 and 2026),
  add column if not exists weight_kg double precision
    check (weight_kg between 20 and 300),
  add column if not exists height_cm double precision
    check (height_cm between 100 and 250),
  add column if not exists gender text
    check (gender in ('female','male','undisclosed'));  -- 시안: 여성/남성/선택 안 함

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- alter table public.profiles drop column if exists gender;
-- alter table public.profiles drop column if exists height_cm;
-- alter table public.profiles drop column if exists weight_kg;
-- alter table public.profiles drop column if exists birth_year;
