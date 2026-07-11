-- 카드 지도용 축약 폴리라인 (~30pt) — 저장 시 박제 (설계: 조회 시 재계산안은
-- 트랙 길이 비례 DB 전송이라 기각, 실측 근거는 커밋/보고 참조).
-- 적용됨(사용자 실행). 백필: scripts/backfill_polyline_thumb.py (멱등, 10행 완료).

-- [APPLY]
alter table public.run_tracks add column if not exists polyline_thumb jsonb;

-- [ROLLBACK]
-- alter table public.run_tracks drop column if exists polyline_thumb;
