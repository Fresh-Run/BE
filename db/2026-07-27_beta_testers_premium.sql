-- 베타 테스터 전원 프리미엄 (외부 게이트 오픈, 2026-07-27). 실행: Supabase SQL Editor.
-- 정책: 베타 기간 실유저 전원 premium(방식 A). 시드 제외 근거 — test2는 유일한
-- free 픽스처(쿼터 429·기능 잠금 UI 검증용), qa-empty는 빈 피드 QA 전용(tier 무관).
-- demo1~5·test1·운영진·앱리뷰어는 이미 premium(2026-07-27 23:3x KST 실조회).
--
-- [ROLLBACK] — 이 시점(2026-07-27 23:3x KST) tier='free'였던 실유저 4명 박제:
--   adb65b26-5963-4b80-8c2c-b37f58e691b2  로라
--   2976b3f7-7dd1-482e-ac69-8b1872ad6fb3  hwi
--   291eb99c-4fab-4b19-99d2-9730d36556b6  역촌역스크린도어수호자
--   e0148621-ab25-4111-80c8-8e4a9ac9fd58  고말
-- update public.profiles set tier = 'free', updated_at = now()
-- where user_id in ('adb65b26-5963-4b80-8c2c-b37f58e691b2',
--                   '2976b3f7-7dd1-482e-ac69-8b1872ad6fb3',
--                   '291eb99c-4fab-4b19-99d2-9730d36556b6',
--                   'e0148621-ab25-4111-80c8-8e4a9ac9fd58');
-- ※ APPLY가 위 4명 이후 가입자도 승급시킬 수 있음(free 전원 대상) — 전량 원복이
--   필요하면 updated_at으로 이번 실행분을 특정: 실행 직후 [확인쿼리] 결과를 보관.

-- [APPLY] — 시드 픽스처 2계정만 제외하고 free 전원 승급(실행 시점 가입자까지 포함)
update public.profiles
set tier = 'premium', updated_at = now()
where tier = 'free'
  and user_id not in (
    select id from auth.users
    where email in ('test2@freshrun.com', 'qa-empty@freshrun.com'));

-- [확인쿼리] — 판정 기준: free = 2 (test2·qa-empty만), 나머지 전원 premium.
select tier, count(*) as cnt
from public.profiles
group by tier order by tier;
-- 상세(승급분 특정·ROLLBACK 보관용):
select p.user_id, p.nickname, p.tier, p.updated_at, u.email
from public.profiles p join auth.users u on u.id = p.user_id
order by p.tier, u.created_at;
