-- route_id 소급 백필 (1회성, 2026-07-29). ✅ 실행 완료(2026-07-30 오너 확인 —
-- 확인쿼리 4행 전부 비null, 동해 시티런 등 4건 연결).
-- 기준(오너 확정·보수): 같은 유저 + run보다 먼저 생성된 코스 + 트랙→코스 40m 중첩 ≥90%.
-- 드라이런(2026-07-29): 대상 46건 중 후보 4건(전부 100%), 경계 82.4% 1건 제외
--   (지연 '또멤버에서 집' — 부분 이탈 주행).
--
-- [ROLLBACK] — 아래 4 run은 백필 전 전부 route_id = null (원복 = null 재설정)
-- update public.runs set route_id = null
-- where id in ('a3b0a5d8-22be-4ce3-9408-3da09dd243e8',
--              '6e8e2179-6fe2-453b-8a7d-fc467bc67439',
--              '17788a33-b149-4175-857f-0c66b87e4537',
--              '72b9f486-82cf-4fa5-ba83-8fb237fffd80');

-- [UPDATE]
update public.runs set route_id = 'ea67642f-3689-4780-ae7c-9be8ce7f1f0b'
 where id = 'a3b0a5d8-22be-4ce3-9408-3da09dd243e8' and route_id is null;   -- 지연 '오 테 2?3?' 중첩 100.0%
update public.runs set route_id = 'd20622b2-4225-439e-a6e2-58e57878f219'
 where id = '6e8e2179-6fe2-453b-8a7d-fc467bc67439' and route_id is null;   -- 이준 'English test' 중첩 100.0%
update public.runs set route_id = 'd6143724-89bf-4461-965f-e137a2d19d06'
 where id = '17788a33-b149-4175-857f-0c66b87e4537' and route_id is null;   -- dentist '동해 시티런' 중첩 100.0%
update public.runs set route_id = '57bcfd40-5e02-4b69-b7a2-a6ec6c417d2d'
 where id = '72b9f486-82cf-4fa5-ba83-8fb237fffd80' and route_id is null;   -- 테스트2 'cu 냠냠' 중첩 100.0%

-- [확인쿼리] — 판정 기준: 4행 반환·route_id 전부 비null
select id, title, route_id from public.runs
where id in ('a3b0a5d8-22be-4ce3-9408-3da09dd243e8',
              '6e8e2179-6fe2-453b-8a7d-fc467bc67439',
              '17788a33-b149-4175-857f-0c66b87e4537',
              '72b9f486-82cf-4fa5-ba83-8fb237fffd80');
