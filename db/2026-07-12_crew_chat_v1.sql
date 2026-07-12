-- 크루 채팅 v1 (docs/CREW_CHAT_DESIGN.md §2). text 메시지 + 이모지 반응 +
-- 읽음 상태(안읽은수 파생·방별 mute). system/run_share 타입은 CHECK에 미리
-- 넣어 v1.5가 스키마 변경 없이 사용. 미실행 — 사용자가 SQL Editor에서 실행.

-- [APPLY]
create table if not exists public.crew_messages (
  id         uuid primary key default gen_random_uuid(),
  crew_id    uuid not null references public.crews(id) on delete cascade,
  sender_id  uuid references auth.users(id) on delete set null,  -- 탈퇴 시 익명화
  type       text not null default 'text'
             check (type in ('text', 'system', 'run_share')),
  content    text,
  payload    jsonb,
  created_at timestamptz not null default now()
);
create index if not exists crew_messages_room_idx
  on public.crew_messages (crew_id, created_at desc);   -- 역순 커서 페치
alter table public.crew_messages enable row level security;

create table if not exists public.crew_message_reactions (
  message_id uuid not null references public.crew_messages(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  emoji      text not null check (emoji in ('👍','🔥','👏','💪')),  -- 4종 고정
  created_at timestamptz not null default now(),
  primary key (message_id, user_id, emoji)   -- 유저당 이모지당 1회(멱등)
);
alter table public.crew_message_reactions enable row level security;

create table if not exists public.crew_read_state (
  crew_id      uuid not null references public.crews(id) on delete cascade,
  user_id      uuid not null references auth.users(id) on delete cascade,
  last_read_at timestamptz not null default now(),
  muted        boolean not null default false,   -- 방별 채팅 푸시 mute (발송은 v2)
  primary key (crew_id, user_id)
);
alter table public.crew_read_state enable row level security;

-- 실행 후 확인 (3행, rowsecurity 전부 t):
-- select tablename, rowsecurity from pg_tables where schemaname = 'public'
--   and tablename in ('crew_messages','crew_message_reactions','crew_read_state')
--   order by tablename;

-- [ROLLBACK]
-- drop table if exists public.crew_message_reactions;
-- drop table if exists public.crew_read_state;
-- drop table if exists public.crew_messages;
