-- [확인쿼리] 해외(한국 bbox 밖) 첫 verified 트랙 도장 — 읽기 전용, 부수효과 없음.
-- 실행: Supabase SQL Editor(오너). 실행 여부: 미실행(오너 실행 대기).
--
-- 판정 기준: 1행이 SeYoon/뉴욕 좌표(40.765509, -73.998047)면 해외 verified 1호 확정.
-- 기준값(2026-07-30 PostgREST 실조회 — 오너 실행 결과와 대조):
--   총 1행. id fff343e0-573c-40a0-9e15-f42f24c8c07a | SeYoon
--   | ran_at 2026-07-30 00:14:44+00 | (40.765509, -73.998047) | 3.75km
--   | has_route_id false | track_points 39 | raw 596 | kept 595 | acc 6m
--   | splits_count 4(마지막 3.69km partial) | server_distance 3.69km
--
-- 'verified' 값은 runs.verification 실데이터 분포(verified 62 / unverified 3)로 확정.
-- 좌표 null 런은 bbox 판별 불가로 제외됨(실조회 기준 verified 중 좌표 null 0건).
select
  r.id,
  p.nickname,
  r.ran_at,
  r.start_lat,
  r.start_lng,
  r.distance_km,
  (r.route_id is not null) as has_route_id,
  r.verification,
  jsonb_array_length(t.points) as track_points,
  t.raw_point_count,
  t.kept_point_count,
  t.avg_accuracy_m,
  jsonb_array_length(t.splits) as splits_count,
  t.server_distance_km
from runs r
join profiles p on p.user_id = r.user_id
left join run_tracks t on t.run_id = r.id
where r.verification = 'verified'
  and not (r.start_lat between 33.0 and 38.7
           and r.start_lng between 124.5 and 131.0)
order by r.ran_at asc;
