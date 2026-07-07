-- 구 crew_announcement 알림 payload 백필: crew_id 채우기 (딥링크 수선)
-- 2026-07-08 이전 발송분은 payload=None이라 탭해도 크루로 못 감. 그 공지가
-- 속한 크루를 crew_announcements 조인으로 찾아 payload={crew_id}로 채운다.
-- 적용됨(사용자 실행). 멱등 — crew_id 없는 crew_announcement 행만 건드림.
--
-- 주의: notifications.target_id는 uuid 타입(text 아님) — a.id와 직접 비교(캐스팅 불필요).

-- [APPLY]
update public.notifications n
set payload = jsonb_build_object('crew_id', a.crew_id)
from public.crew_announcements a
where n.type = 'crew_announcement'
  and n.target_id = a.id
  and (n.payload is null or n.payload->>'crew_id' is null);

-- 확인(0이어야): 백필 후 crew_id 없는 crew_announcement 알림 수
-- select count(*) from public.notifications
--   where type='crew_announcement' and (payload is null or payload->>'crew_id' is null);

-- [ROLLBACK]  (되돌릴 일 거의 없음 — payload만 추가한 것)
-- update public.notifications set payload = null
--   where type = 'crew_announcement' and payload ? 'crew_id';
