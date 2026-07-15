-- 위치 기반 public run 탐색 피드(홈 "전체" 탭) — runs 시작 좌표 컬럼 + 백필 + 부분 인덱스.
-- 설계: docs/NEARBY_FEED_DESIGN.md (승인 2026-07-15, 확답 A~D 반영).
--
-- 무엇을·왜: runs에 인덱싱 가능한 출발 좌표(start_lat/start_lng)가 없어(진단 확정)
--   위치 반경 피드를 못 만든다. GPS 궤적은 run_tracks.points에만 있음. → additive
--   2컬럼 + run_tracks.points[0]에서 백필 + bbox 범위 스캔용 부분 btree 인덱스.
-- 실행 여부: [작성됨 · 미실행] — 사용자가 Supabase SQL Editor에서 실행 예정.
--   실행 순서: [APPLY] → [BACKFILL] → [확인]. (재적용 시에만 [ROLLBACK] 먼저.)
-- 백필 구분: 기존 run은 아래 [BACKFILL] SQL이 채운다. 신규 run은 코드
--   (run_service.create_run, processed.polyline[0])가 저장 시 자동으로 채운다(별도 턴).
-- 하위호환: 2컬럼 nullable additive — 기존 run·응답 계약 불변. runs는 기존 테이블
--   (RLS 이미 enable) — 컬럼 추가는 정책 무관, 신규 CHECK/알림타입 없음.

-- ============================================================
-- [ROLLBACK]  (최초 설치 시엔 실행 금지 — 주석 유지. 재적용/되돌릴 때만 주석 해제)
-- ============================================================
-- drop index if exists public.runs_nearby_idx;
-- alter table public.runs drop column if exists start_lng;
-- alter table public.runs drop column if exists start_lat;

-- ============================================================
-- [APPLY]  — 2컬럼(nullable) + 부분 btree 인덱스
-- ============================================================
alter table public.runs add column if not exists start_lat double precision;
alter table public.runs add column if not exists start_lng double precision;

create index if not exists runs_nearby_idx
  on public.runs (start_lat, start_lng)
  where visibility = 'public' and start_lat is not null;

-- ============================================================
-- [BACKFILL]  — 기존 run: run_tracks.points[0] → runs.start_lat/lng (트랙 보유분 전량)
--   확답 D: visibility 무관 전량 백필(followers→public 전환 대비). points 없는 run은 건드리지 않음.
--   멱등: start_lat is null 가드 — 재실행해도 이미 채운 행 무변경.
-- ============================================================
update public.runs r
set start_lat = (t.points->0->>'lat')::double precision,
    start_lng = (t.points->0->>'lng')::double precision
from public.run_tracks t
where t.run_id = r.id
  and r.start_lat is null
  and t.points is not null
  and jsonb_typeof(t.points) = 'array'
  and jsonb_array_length(t.points) > 0;

-- ============================================================
-- [확인]  — 실행 후 아래 4개를 돌려 판정 기준과 대조
-- ============================================================

-- 확인① 컬럼 존재/타입
-- 판정: 2행 · data_type=double precision · is_nullable=YES
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public' and table_name = 'runs'
  and column_name in ('start_lat', 'start_lng')
order by column_name;

-- 확인② 부분 인덱스 존재
-- 판정: 1행 · indexdef의 WHERE에 (visibility = 'public' AND start_lat IS NOT NULL) 포함
select indexname, indexdef
from pg_indexes
where schemaname = 'public' and tablename = 'runs'
  and indexname = 'runs_nearby_idx';

-- 확인③ 백필 정합: 좌표 채워진 run 수 == points 보유 트랙 run 수
-- 판정: 두 수 동일(현재 규모상 34 예상). 다르면 트랙 있는데 좌표 누락분 조사.
select
  (select count(*) from public.runs
     where start_lat is not null and start_lng is not null) as runs_with_coords,
  (select count(*) from public.run_tracks
     where points is not null and jsonb_typeof(points) = 'array'
       and jsonb_array_length(points) > 0) as tracks_with_points;

-- 확인④ 노출 누락 점검: public + 트랙 있는데 start_lat null 인 run = 0
-- 판정: 0 (피드 노출 대상인데 좌표 없어 빠지는 public run 없음)
select count(*) as public_tracked_missing_coord
from public.runs r
join public.run_tracks t on t.run_id = r.id
where r.visibility = 'public'
  and t.points is not null and jsonb_typeof(t.points) = 'array'
  and jsonb_array_length(t.points) > 0
  and r.start_lat is null;
