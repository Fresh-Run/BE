-- 크루 상설 집결지 (docs/CREW_MEET_PLACE_DESIGN.md): crews에 additive 3컬럼.
-- 공지의 일회성 집결지(place_*)와 독립 — 크루 자체의 상설 집결지(캔버스 카드
-- "서울숲 공원 정문 · 성수동 · 매주 화·목 06:00"의 장소 부분. 스케줄은 기존
-- active_days/active_time 재사용).
-- 적용됨(사용자 실행 2026-07-14 — 3컬럼 nullable·default 없음 확인 완료).
--
-- 검증은 DB CHECK 없이 앱(Pydantic)만: 길이 ≤100자(공지 place_name과 동일 확정),
-- bbox lat 33~39·lng 124~132(공지 place_lat/lng와 동일). 공지 place_*도 DB CHECK
-- 없이 앱 검증인 것과 정합 — 규칙 변경 시 DDL 재작업 없이 앱만 고치면 됨.
-- 전부 nullable·default 없음 → 기존 행 자동 null(백필 불필요, non-breaking).

-- ─────────────────────────────────────────────────────────────
-- [APPLY]
-- ─────────────────────────────────────────────────────────────
alter table public.crews
  add column if not exists meet_place_name text,
  add column if not exists meet_lat  double precision,
  add column if not exists meet_lng  double precision;

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- alter table public.crews drop column if exists meet_lng;
-- alter table public.crews drop column if exists meet_lat;
-- alter table public.crews drop column if exists meet_place_name;
