-- GPS 데이터 파이프라인: runs 검증 컬럼 + run_tracks (처리 결과 저장)
-- 적용: Supabase SQL Editor에서 [APPLY] 섹션 실행 (실행 완료됨)
-- 롤백: [ROLLBACK] 섹션 실행
--
-- NOTE: 실행 시점에 설계 초안과 다르게 확정된 부분 (실 DB 기준으로 기록):
--   * verification 3종 (adjusted 없음) + is_flagged boolean —
--     "거리 조정"은 verified + is_flagged=true + distance_km_reported로 표현
--   * run_tracks 컬럼명: points / raw_point_count / kept_point_count,
--     관측용 max_speed_kmh·avg_accuracy_m 추가,
--     server_distance_km·elev_gain_m 컬럼 없음 → API가 splits에서 파생

-- ─────────────────────────────────────────────────────────────
-- [APPLY 1] runs 검증 컬럼 (기존 행은 자동 'unverified' — non-breaking)
--   unverified: GPS 없음/판정 보류 (기존·수동 입력 — 통계·랭킹 포함, 현행 유지)
--   verified  : 트랙 검증 통과 (is_flagged=true면 거리 서버 대체됨)
--   suspect   : 자전거/차량 의심 — PB·크루 랭킹·챌린지 집계 제외 (저장은 허용)
-- ─────────────────────────────────────────────────────────────
alter table public.runs
  add column if not exists distance_km_reported double precision,
  add column if not exists verification text not null default 'unverified'
    check (verification in ('unverified','verified','suspect')),
  add column if not exists is_flagged boolean not null default false;

-- ─────────────────────────────────────────────────────────────
-- [APPLY 2] run_tracks — GPS 처리 결과 (상세 화면 전용; raw는 미보관)
-- ─────────────────────────────────────────────────────────────
create table public.run_tracks (
  run_id           uuid primary key references public.runs(id) on delete cascade,
  points           jsonb not null,   -- 간축 [{lat,lng}] ≤1000pt
  splits           jsonb not null,   -- [{"km":1,"sec":318,"elev_gain_m":4}, …]
  raw_point_count  int not null,
  kept_point_count int not null,
  max_speed_kmh    double precision, -- 필터 전 최고 구간 속도 (관측용)
  avg_accuracy_m   double precision, -- 평균 accuracy (관측용)
  created_at       timestamptz not null default now()
);

alter table public.run_tracks enable row level security;  -- 정책 없음 (service_role만)

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- drop table if exists public.run_tracks;
-- alter table public.runs drop column if exists is_flagged;
-- alter table public.runs drop column if exists verification;
-- alter table public.runs drop column if exists distance_km_reported;
