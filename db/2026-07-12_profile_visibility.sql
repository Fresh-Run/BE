-- 비공개 프로필 v1 (docs/PRIVATE_PROFILE_DESIGN.md §1) — profiles.visibility.
-- run visibility와 별개 축(계정 잠금). run 백필은 'followers'(노출 보존)였지만
-- profile은 **전원 public이 현행 동작(모두 보임) 보존**이라 default 'public'
-- 단순 — 2단계 default 트릭 불필요. profiles RLS는 이미 enable(2026-07-12
-- 백필분). 미실행 — 사용자가 SQL Editor에서 실행.

-- [APPLY]
alter table public.profiles
  add column if not exists visibility text not null default 'public'
  check (visibility in ('public', 'followers', 'private'));

-- 실행 후 확인 (전원 public 백필 — 현행 동작 보존):
-- select visibility, count(*) from public.profiles group by visibility;

-- [ROLLBACK]
-- alter table public.profiles drop column if exists visibility;
