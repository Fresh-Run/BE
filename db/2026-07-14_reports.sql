-- 신고(reports) v1 (docs/REPORT_DESIGN.md): 유저/콘텐츠 신고 적재 + 운영진 조회.
-- 폴리모픽(target_type + target_id) — 1차 API는 'user'만 오픈하되 CHECK엔 6종을
-- 미리 넣어 확장 시 스키마 재변경 0(CHECK drop→재생성 함정 회피).
-- 적용됨(사용자 실행 2026-07-14 — 테이블·CHECK·부분 유니크·RLS 확인 완료).
--
-- 설계 확정값: POST 성공 204 / detail 길이는 앱(Pydantic ≤500)만 / 운영진
-- 미설정(ADMIN_USER_IDS 없음) 시 admin 404 fail-safe / status 단방향.

-- ─────────────────────────────────────────────────────────────
-- [APPLY]
-- ─────────────────────────────────────────────────────────────
create table if not exists public.reports (
  id           uuid primary key default gen_random_uuid(),
  reporter_id  uuid not null references auth.users(id) on delete cascade,
  -- 신고 대상: 폴리모픽이라 FK 없음(여러 테이블을 가리킴). 존재 검증은 앱 레이어
  -- (없는 대상·차단 관계 404 은닉). 1차 API는 'user'만 허용, 나머지는 422.
  target_type  text not null check (target_type in
                 ('user','run','run_comment','route','route_comment','crew_message')),
  target_id    uuid not null,
  reason       text not null check (reason in
                 ('spam','abuse','inappropriate','impersonation','other')),
  -- detail 길이(≤500)는 앱 Pydantic 검증만(설계 확정 — bio·notes 관례와 동일).
  detail       text,
  status       text not null default 'pending' check (status in
                 ('pending','reviewed','dismissed')),
  created_at   timestamptz not null default now(),
  reviewed_at  timestamptz
  -- self 신고 방지 CHECK는 DB에 안 둔다: reporter_id와 target_id 비교는
  -- target_type='user'일 때만 의미가 있는데(다른 타입이면 target_id는 run/댓글
  -- id라 비교 자체가 무의미), CHECK는 타입 분기 표현이 번잡하고 폴리모픽 확장마다
  -- 재작성 대상이 된다 → 앱 검증(400)으로 처리(blocks의 self CHECK와 달리 의도적 생략).
);

-- 중복 pending 봉쇄: 같은 신고자가 같은 대상에 pending 중복 불가(멱등 + 동시요청
-- TOCTOU도 DB가 막음 — follow_requests 부분 유니크 선례).
create unique index if not exists reports_one_pending
  on public.reports (reporter_id, target_type, target_id)
  where status = 'pending';

-- 운영진 목록 조회용(GET /admin/reports?status=... 최신순)
create index if not exists reports_status_created_idx
  on public.reports (status, created_at desc);

alter table public.reports enable row level security;  -- 표준: 정책 없음(service_role만)

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- drop index if exists public.reports_status_created_idx;
-- drop index if exists public.reports_one_pending;
-- drop table if exists public.reports;
