-- 배틀(1v1 점수 대전) 스키마 — battles · battle_invites · battle_runs (2026-09-07).
-- 설계: docs/BATTLE_DESIGN_v0_KO.md. 이반 화면 1차 빌드(목데이터) → 서버 실연결.
-- 오너 결정 3건 반영: ① 귀속=runs.ran_at ② 게이팅 병행(30일롤링3+동시active3)
--   ③ 정산 유예 30분(daily 배치 흡수).
--
-- ⚠️ 오너 실행 대기 — Supabase SQL Editor에서 [APPLY] 실행. 실행 여부: 미실행.
-- ⚠️ SQL→배포 순서(§C): 이 SQL 실행 후 코드 배포. 미실행 상태에서 배틀 엔드포인트
--   호출 시 42P01(테이블 없음)→502이나, 기존 기능은 무접촉(additive)이라 무해.
-- 전부 RLS enable(정책 없이 — deny-by-default, 앱은 service_role. §C 표준).

-- ═══════════════════════════════════════════════════════════════════
-- [APPLY]
-- ═══════════════════════════════════════════════════════════════════

-- ── battles (1v1 대전) ──────────────────────────────────────────────
create table if not exists public.battles (
  id             uuid primary key default gen_random_uuid(),
  created_by     uuid not null references auth.users(id) on delete cascade,
  opponent       uuid not null references auth.users(id) on delete cascade,
  title          text not null,
  emoji          text,
  format         text not null default 'points' check (format in ('points','pure')),
  metric         text not null default 'distance_km',
  duration_days  int  not null check (duration_days between 1 and 30),
  status         text not null default 'pending'
                 check (status in ('pending','active','ended','cancelled','forfeited')),
  started_at     timestamptz,     -- 수락 시점(윈도 앵커, 룰링①). null=pending
  ends_at        timestamptz,     -- started_at의 KST날짜 + duration_days → KST 자정
  settled_at     timestamptz,     -- 최종 정산 완료
  winner         uuid references auth.users(id) on delete set null,  -- 무승부·미정 null
  created_at     timestamptz not null default now(),
  check (created_by <> opponent)  -- 자기 자신과 배틀 금지
);
alter table public.battles enable row level security;  -- 정책 없음(service_role만)
create index if not exists idx_battles_created_by on public.battles(created_by);
create index if not exists idx_battles_opponent   on public.battles(opponent);
create index if not exists idx_battles_status      on public.battles(status);

-- ── battle_invites (48h 만료) ───────────────────────────────────────
create table if not exists public.battle_invites (
  id           uuid primary key default gen_random_uuid(),
  battle_id    uuid not null references public.battles(id) on delete cascade,
  inviter      uuid not null references auth.users(id) on delete cascade,
  invitee      uuid not null references auth.users(id) on delete cascade,
  status       text not null default 'pending'
               check (status in ('pending','accepted','declined','expired','cancelled')),
  expires_at   timestamptz not null,       -- 생성 + 48h
  responded_at timestamptz,
  created_at   timestamptz not null default now()
);
alter table public.battle_invites enable row level security;
create index if not exists idx_battle_invites_battle  on public.battle_invites(battle_id);
create index if not exists idx_battle_invites_invitee  on public.battle_invites(invitee, status);

-- ── battle_runs (런↔배틀 귀속 + per-run 점수) ───────────────────────
create table if not exists public.battle_runs (
  id             uuid primary key default gen_random_uuid(),
  battle_id      uuid not null references public.battles(id) on delete cascade,
  user_id        uuid not null references auth.users(id) on delete cascade,
  run_id         uuid not null references public.runs(id) on delete cascade,
  attributed_at  timestamptz not null,      -- = runs.ran_at(귀속 시각, Q4=①)
  counted        boolean not null default false,  -- verified·非flagged·≥1.5km·창내
  run_score      numeric not null default 0,
  breakdown      jsonb,                      -- base/completion/pace/early_bird/milestone
  created_at     timestamptz not null default now(),
  unique (battle_id, run_id)                 -- 런당 배틀별 1회(멱등 정산)
);
alter table public.battle_runs enable row level security;
create index if not exists idx_battle_runs_battle on public.battle_runs(battle_id);
create index if not exists idx_battle_runs_user   on public.battle_runs(battle_id, user_id);

-- ── 알림 타입 3종 추가(§C 함정 — drop→재생성, 타입만 넣고 제약 미수정 시 23514) ──
alter table public.notifications drop constraint if exists notifications_type_check;
alter table public.notifications add constraint notifications_type_check
  check (type in (
    'route_liked', 'route_commented', 'crew_joined', 'challenge_completed',
    'user_followed', 'crew_announcement', 'join_requested', 'join_approved',
    'run_kudoed', 'run_commented',
    'follow_requested', 'follow_request_approved',
    'crew_invited', 'crew_chat',
    'pb_achieved',
    'battle_invited', 'battle_overtaken', 'battle_won'   -- 배틀(2026-09-07)
  ));

-- [확인쿼리] — 판정: 3 테이블 생성 + RLS on + 알림 타입 18종
select table_name, row_security
from information_schema.tables t
join pg_tables p on p.tablename = t.table_name and p.schemaname = 'public'
where t.table_schema = 'public'
  and t.table_name in ('battles','battle_invites','battle_runs')
order by table_name;   -- 기대: 3행, rowsecurity=true

select conname, pg_get_constraintdef(oid)
from pg_constraint where conname = 'notifications_type_check';  -- battle_* 3종 포함 확인


-- ═══════════════════════════════════════════════════════════════════
-- [ROLLBACK]
-- ═══════════════════════════════════════════════════════════════════
-- drop table if exists public.battle_runs;
-- drop table if exists public.battle_invites;
-- drop table if exists public.battles;
-- -- 알림 타입 원복(배틀 3종 제거):
-- alter table public.notifications drop constraint if exists notifications_type_check;
-- alter table public.notifications add constraint notifications_type_check
--   check (type in (
--     'route_liked', 'route_commented', 'crew_joined', 'challenge_completed',
--     'user_followed', 'crew_announcement', 'join_requested', 'join_approved',
--     'run_kudoed', 'run_commented',
--     'follow_requested', 'follow_request_approved',
--     'crew_invited', 'crew_chat', 'pb_achieved'
--   ));
