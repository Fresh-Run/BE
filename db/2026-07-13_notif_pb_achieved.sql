-- PB 축하 푸시 (백로그 소품) — 알림 type 'pb_achieved' 신설.
-- notifications_type_check 재작성(15종째). 지난 묶음(2026-07-12) 선등록 후보에
-- 없던 신규 발송 type이라 CHECK 재작성 불가피 — 단독 1종이지만 페어로 기록.
-- PB는 유일한 '자기 자신 대상' 알림(recipient==actor) — create_notification의
-- allow_self=True 예외 경로 사용. 미실행 — 사용자가 SQL Editor에서 실행.

-- [APPLY]
alter table public.notifications drop constraint if exists notifications_type_check;
alter table public.notifications add constraint notifications_type_check
  check (type in (
    'route_liked', 'route_commented', 'crew_joined', 'challenge_completed',
    'user_followed', 'crew_announcement', 'join_requested', 'join_approved',
    'run_kudoed', 'run_commented',
    'follow_requested', 'follow_request_approved',   -- v2
    'crew_invited', 'crew_chat',                     -- 선등록 (type만)
    'pb_achieved'                                    -- PB 축하 (2026-07-13, 자기 대상)
  ));

-- 실행 후 확인:
-- select conname, pg_get_constraintdef(oid) from pg_constraint
--   where conname = 'notifications_type_check';

-- [ROLLBACK]
-- alter table public.notifications drop constraint if exists notifications_type_check;
-- alter table public.notifications add constraint notifications_type_check
--   check (type in (
--     'route_liked', 'route_commented', 'crew_joined', 'challenge_completed',
--     'user_followed', 'crew_announcement', 'join_requested', 'join_approved',
--     'run_kudoed', 'run_commented',
--     'follow_requested', 'follow_request_approved',
--     'crew_invited', 'crew_chat'
--   ));
