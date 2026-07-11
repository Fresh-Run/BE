-- 원격 푸시 기기 토큰 (docs/PUSH_NOTIFICATION_DESIGN.md §1).
-- PK=token: 재등록 멱등 + 기기 주인 교체 시 user_id 자동 이전(오발송 차단).
-- 유저당 N행 = N기기. 탈퇴는 FK cascade. 미실행 — 사용자가 SQL Editor에서 실행.

-- [APPLY]
create table if not exists public.push_tokens (
  token      text primary key,   -- Expo push token — 전역 유니크·기기 귀속
  user_id    uuid not null references auth.users(id) on delete cascade,
  platform   text not null check (platform in ('ios', 'android')),
  updated_at timestamptz not null default now()
);
create index if not exists push_tokens_user_idx on public.push_tokens (user_id);
alter table public.push_tokens enable row level security;  -- 표준: 정책 없이 백스톱

-- 실행 후 확인:
-- select tablename, rowsecurity from pg_tables where tablename = 'push_tokens';

-- [ROLLBACK]
-- drop table if exists public.push_tokens;
