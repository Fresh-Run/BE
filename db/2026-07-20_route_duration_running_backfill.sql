-- 기존 코스 estimated_duration_min 러닝 환산 backfill (v2.2 시맨틱 변경 짝).
-- 신규 생성분은 코드가 러닝 기준(거리 × 6.5분/km)으로 저장하지만, 기존 저장분은
-- T-map 도보 시간(~13분/km)이 그대로 남아 목록·상세에서 2배쯤 길게 보인다.
-- ✅ 실행 완료 (2026-07-20, 사용자 SQL Editor — 스냅샷 _backup_route_duration_20260720
-- 생성 후 APPLY). 실측 검증: total 55 = 러닝 기준 55 (ok 50 + 5건은 total=5.0의
-- 32.5분 경계에서 Postgres round=33 vs 앱 Python banker's=32 관례 차이 — 알려진
-- 함정, ±1분 코스메틱이라 수용). 백업 테이블은 안정 확인 후 drop 예정.
--
-- 주의: [ROLLBACK]은 근사 복원이다 — 원 도보 시간은 T-map 산출값이라 저장 원값을
-- 지우면 정확 복원 불가. 정확 롤백이 필요하면 [APPLY] 전에 스냅샷을 떠둘 것:
--   create table _backup_route_duration as
--     select id, estimated_duration_min from public.routes;

-- [APPLY]
-- update public.routes
--    set estimated_duration_min = round(total_distance_km * 6.5)
--  where total_distance_km is not null;

-- [확인쿼리] — 러닝 페이스(6.5분/km) 정합 행 수 == 전체 행 수
-- select count(*) filter (where estimated_duration_min = round(total_distance_km * 6.5)) as ok,
--        count(*) as total
--   from public.routes
--  where total_distance_km is not null;

-- [ROLLBACK] (근사 — 도보 페이스 13분/km 역산. 스냅샷 있으면 그쪽 우선)
-- update public.routes
--    set estimated_duration_min = round(total_distance_km * 13)
--  where total_distance_km is not null;
