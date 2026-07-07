-- 알림 딥링크 보조 데이터: notifications.payload (범용 jsonb)
-- crew_announcement 알림에 crew_id를 담아 크루 딥링크 가능하게. 다른 타입은
-- target_id로 충분하므로 payload=null. 적용됨(사용자 실행).

-- [APPLY]
alter table public.notifications add column if not exists payload jsonb;

-- [ROLLBACK]
-- alter table public.notifications drop column if exists payload;
