-- POST /runs/{id}/copy-as-route — 러닝을 코스로 저장 (Ivan "이 경로 달리기").
-- ① routes.source_run_id: 어느 run에서 복사됐나(copied_from=route 복사와 별개).
--    on delete set null — 원본 run 삭제돼도 코스 잔존(copied_from 관성).
-- ② unique(user_id, source_run_id): 같은 유저가 같은 run을 두 번 저장 못 함(멱등
--    재호출은 기존 row 반환). partial(source_run_id not null) — 일반 생성 코스는
--    source_run_id=null이라 유니크 대상 아님.
-- ③ notifications_type_check에 route_saved 추가(16종째) — 알려진 함정: 새 알림
--    type은 CHECK drop→재생성 필수(안 하면 23514 삽입 실패).
-- additive · nullable(기존 코스 null). RLS: routes·notifications 기존 테이블.
-- ⚠️ 실행 완료 여부: 미실행 — 사용자 SQL Editor. **배포 전 선행 필수**
--    (컬럼·CHECK 없이 배포하면 insert가 실패해 코스 저장·알림 발송 안 됨).

-- ══ ① routes.source_run_id ══════════════════════════════════════════════
-- [APPLY]
-- alter table public.routes
--   add column if not exists source_run_id uuid
--   references public.runs(id) on delete set null;

-- [확인] 컬럼 존재 + 기존 전량 null
-- select count(*) filter (where source_run_id is null) as null_cnt, count(*) as total
--   from public.routes;

-- [ROLLBACK]
-- alter table public.routes drop column if exists source_run_id;

-- ══ ② 멱등 유니크 (user_id, source_run_id) ═══════════════════════════════
-- [APPLY]
-- create unique index if not exists routes_one_per_source_run
--   on public.routes (user_id, source_run_id)
--   where source_run_id is not null;

-- [ROLLBACK]
-- drop index if exists public.routes_one_per_source_run;

-- ══ ③ notifications_type_check 재작성 (route_saved 추가, 16종째) ══════════
-- [APPLY]
-- alter table public.notifications drop constraint if exists notifications_type_check;
-- alter table public.notifications add constraint notifications_type_check
--   check (type in (
--     'route_liked', 'route_commented', 'crew_joined', 'challenge_completed',
--     'user_followed', 'crew_announcement', 'join_requested', 'join_approved',
--     'run_kudoed', 'run_commented',
--     'follow_requested', 'follow_request_approved',
--     'crew_invited', 'crew_chat', 'pb_achieved',
--     'route_saved'                                 -- 러닝→코스 저장 (2026-07-21)
--   ));

-- [확인] 제약 정의
-- select pg_get_constraintdef(oid) from pg_constraint
--   where conname = 'notifications_type_check';

-- [ROLLBACK] route_saved 제외 15종으로 되돌림
-- alter table public.notifications drop constraint if exists notifications_type_check;
-- alter table public.notifications add constraint notifications_type_check
--   check (type in (
--     'route_liked', 'route_commented', 'crew_joined', 'challenge_completed',
--     'user_followed', 'crew_announcement', 'join_requested', 'join_approved',
--     'run_kudoed', 'run_commented',
--     'follow_requested', 'follow_request_approved',
--     'crew_invited', 'crew_chat', 'pb_achieved'
--   ));
