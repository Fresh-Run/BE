-- IAP (Apple 인앱 구독): 구독 상태 + 웹훅 raw 보관
-- 적용: Supabase SQL Editor에서 [APPLY] 섹션 실행 (실행 완료됨)
-- 롤백: [ROLLBACK] 섹션 실행
--
-- NOTE: 실행 시점에 설계 초안과 다르게 확정된 부분 (실 DB 기준으로 기록):
--   * PK = original_transaction_id (거래가 곧 정체성; 유저당 여러 행 = 구독 이력)
--   * 컬럼명 latest_transaction_id (not null)
--   * environment 기본값 'production'
--   → 앱 코드는 이 스키마에 맞춰짐: 재사용 방어는 insert-first + 소유자 확인
--     (iap_service), lazy 강등은 유저의 최신 만료 행 기준 (quota_service).

-- ─────────────────────────────────────────────────────────────
-- [APPLY 1] subscriptions
--   행이 없는 premium = admin 수동 부여(test1 등) → 만료 강등 대상 아님.
-- ─────────────────────────────────────────────────────────────
create table public.subscriptions (
  original_transaction_id text primary key,
  user_id                 uuid references auth.users(id) on delete cascade,
  product_id              text not null,
  latest_transaction_id   text not null,
  status                  text not null default 'active'
                          check (status in ('active','expired','revoked')),
  expires_at              timestamptz not null,
  environment             text not null default 'production',
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

alter table public.subscriptions enable row level security;  -- 정책 없음 (service_role만)

-- ─────────────────────────────────────────────────────────────
-- [APPLY 2] iap_notifications_raw — App Store Server Notifications V2 원본.
--   현재는 수신+저장만. 출시기에 서명 검증·타입별 처리 구현 후
--   processed=false 잔여분을 재처리한다 (서버 로그는 휘발성이라 테이블 보관).
-- ─────────────────────────────────────────────────────────────
create table public.iap_notifications_raw (
  id                uuid primary key default gen_random_uuid(),
  notification_type text,                       -- 출시기 디코드 후 채움
  payload           jsonb not null,             -- {"signedPayload": "..."} 원본
  received_at       timestamptz not null default now(),
  processed         boolean not null default false
);

alter table public.iap_notifications_raw enable row level security;  -- 정책 없음

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- drop table if exists public.iap_notifications_raw;
-- drop table if exists public.subscriptions;
