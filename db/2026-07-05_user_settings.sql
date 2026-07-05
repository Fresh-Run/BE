-- 사용자 설정: profiles.settings JSONB 1개
-- 적용: Supabase SQL Editor에서 실행 (실행 완료됨)
--
-- 컬럼 방식 대신 JSONB: 키 15개+가 계속 늘어나는데(오디오 코치 등) 설정으로
-- 유저를 쿼리할 일이 없어 DB 타입 강제/인덱스가 무의미. 타입·범위 검증은
-- 서버 화이트리스트(Pydantic, extra='forbid')가 담당. 저장은 sparse(변경분만),
-- 기본값 단일 소스는 서버 상수 — 앱 배포 없이 기본값 정책 변경 가능.

alter table public.profiles
  add column settings jsonb not null default '{}'::jsonb;

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- alter table public.profiles drop column if exists settings;
