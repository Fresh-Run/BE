-- 크루 초대 코드: crews.invite_code (크루당 고정 1개, 재생성 시 이전 코드 무효)
-- 적용: Supabase SQL Editor에서 실행 (실행 완료됨)
--
-- UNIQUE 제약이 join-by-code 조회 인덱스를 겸함. 별도 테이블 없음 —
-- 크루 삭제 시 코드는 행과 함께 소멸, 크루장 위임 시 코드 유지.

alter table public.crews
  add column invite_code text
  constraint crews_invite_code_key unique;

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- alter table public.crews drop column if exists invite_code;
