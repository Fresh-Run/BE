-- 감사 친구리포트①: profiles.nickname UNIQUE 제약.
--
-- 확인 결과 (2026-07-06 실측): 이 제약은 **이미 실 DB에 존재**한다 —
--   · upsert_profile의 23505→NicknameTaken(409) 경로가 동작 (behavioral 확인),
--     test_profile_body_integration.py step 7이 중복 닉네임 409를 통과.
--   · 현재 중복 닉네임 0건.
-- 초기 커밋에서 생성됐으나 db/*.sql에 기록이 없어(스키마 드리프트) 친구가
-- "제약 없음"으로 오인한 것. 이 파일은 **문서화 + 타 환경 재현용**이며,
-- 이 DB에서는 실행 불필요(중복 실행 시 이미 존재 에러).
--
-- 새 환경/재구축 시에만 아래 실행 (idempotent 형태):

-- ─────────────────────────────────────────────────────────────
-- [APPLY — 새 환경에서만]
-- ─────────────────────────────────────────────────────────────
create unique index if not exists profiles_nickname_key
  on public.profiles (nickname);

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- drop index if exists profiles_nickname_key;
