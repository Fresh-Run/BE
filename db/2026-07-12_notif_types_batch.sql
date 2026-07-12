-- notifications_type_check 재작성 — 4 type 일괄 추가 (함정 묶음, 1회로).
-- 배경(알려진 함정): 새 알림 type마다 CHECK를 drop→재생성해야 삽입이 23514로
-- 실패하지 않는다. v2 팔로우 승인제 + 백로그 2건의 type을 **한 번에 선등록**해
-- 재작성 횟수를 1회로 줄인다. **type만 등록 — 발송 로직은 각 기능 사이클에서**:
--   follow_requested / follow_request_approved : 이번(v2)에 발송까지 구현.
--   crew_invited : 인앱 개인 초대 (백로그) — type만, 발송은 그 작업 때.
--   crew_chat    : 채팅 푸시 (채팅 v2) — type만, 발송은 그 작업 때.
-- target_type CHECK는 무변경 (신규 type의 target_type=user/crew는 기존 포함).
-- 미실행 — 사용자가 SQL Editor에서 실행.

-- [APPLY]
alter table public.notifications drop constraint if exists notifications_type_check;
alter table public.notifications add constraint notifications_type_check
  check (type in (
    'route_liked', 'route_commented', 'crew_joined', 'challenge_completed',
    'user_followed', 'crew_announcement', 'join_requested', 'join_approved',
    'run_kudoed', 'run_commented',
    'follow_requested', 'follow_request_approved',   -- v2 (발송 구현)
    'crew_invited', 'crew_chat'                      -- 선등록 (type만)
  ));

-- 실행 후 확인 (정의에 14종 전부 포함):
-- select pg_get_constraintdef(oid) from pg_constraint
--   where conname = 'notifications_type_check';

-- [ROLLBACK] (기존 10종으로)
-- alter table public.notifications drop constraint if exists notifications_type_check;
-- alter table public.notifications add constraint notifications_type_check
--   check (type in ('route_liked','route_commented','crew_joined','challenge_completed',
--     'user_followed','crew_announcement','join_requested','join_approved',
--     'run_kudoed','run_commented'));
