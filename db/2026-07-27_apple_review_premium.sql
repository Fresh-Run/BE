-- 애플 외부 베타 리뷰용 데모 계정 premium 수동 승급 (2026-07-27).
-- 대상: 301990b8-e4fd-4612-926a-53be235dae0f (닉네임 "앱리뷰어",
--       freshrun0609+ascreview@gmail.com, 2026-07-26 생성).
-- 사전 확인(2026-07-27 실조회): 301990b8 프리픽스 매칭 정확히 1건 · 현재 tier=free.
-- 실행: Supabase SQL Editor.

-- [사전 확인쿼리] — 판정 기준: cnt=1 (1 아니면 중단)
select count(*) as cnt
from public.profiles
where user_id::text like '301990b8%';

-- [ROLLBACK]
-- update public.profiles set tier = 'free', updated_at = now()
-- where user_id = '301990b8-e4fd-4612-926a-53be235dae0f';

-- [APPLY]
update public.profiles
set tier = 'premium', updated_at = now()
where user_id = '301990b8-e4fd-4612-926a-53be235dae0f';

-- [확인쿼리] — 판정 기준: 1행 · nickname=앱리뷰어 · tier=premium
select user_id, nickname, tier, updated_at
from public.profiles
where user_id = '301990b8-e4fd-4612-926a-53be235dae0f';
