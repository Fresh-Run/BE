-- 크루 세부 권한 v2 (docs/CREW_PERMISSIONS_V2_DESIGN.md). crew_members에
-- permissions jsonb(5키 bool) 추가. 소급: 기존 admin은 v1 동작 보존 —
-- announcements·challenges·edit_crew·kick_members ON, manage_admins OFF(F3:
-- v1 admin은 role 관리 권한이 없었으므로 OFF가 진짜 보존). member/owner는 null
-- (member=권한없음, owner=암묵 전권). 적용 완료 — 사용자가 SQL Editor 실행.

-- [ROLLBACK] (먼저)
-- alter table public.crew_members drop column if exists permissions;

-- [APPLY]
alter table public.crew_members add column if not exists permissions jsonb;

update public.crew_members
   set permissions = '{"announcements":true,"challenges":true,"edit_crew":true,'
                     '"kick_members":true,"manage_admins":false}'::jsonb
 where role = 'admin' and permissions is null;   -- 멱등(재실행 무해)

-- 실행 후 확인:
-- select role, count(*) as rows, count(permissions) as with_perms
--   from public.crew_members group by role;
--   → admin: rows==with_perms / owner·member: with_perms==0
