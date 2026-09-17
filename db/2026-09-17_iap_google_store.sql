-- IAP Google Play Billing — store 판별자 + Play 필드 additive (안드 동시출시 P1 스키마).
--   기존 Apple Track B(PK=original_transaction_id) 위에 store-agnostic 확장.
--   PK 재활용(오너 확정): original_transaction_id = "스토어 공통 구매 정체성"
--   (Apple=originalTransactionId, Google=linkedPurchaseToken 체인 앵커 토큰).
--
-- ⚠️ ADDITIVE·기존 애플 행 무영향:
--   · subscriptions.store = default 'apple' → 기존 전 행 자동 'apple' 백필(노출 보존).
--   · purchase_token·order_id = nullable → 애플 행은 NULL(구글만 채움).
--   · 앱 코드도 애플 경로는 store/purchase_token/order_id 키를 **미전송**(persist_verified
--     이 store=='apple'이면 신규 키 생략) → 기존 insert와 바이트 동일, 회귀 0.
--   · iap_notifications_raw.store = default 'apple' → Apple 웹훅 raw 무영향, RTDN 라우팅용.
--
-- §C SQL→배포 순서: **이 SQL 먼저 실행·검증 → 그 다음 코드 배포**(store 키를 쓰는 구글
--   경로는 컬럼 존재 후에만 커밋/배포). 애플 경로는 신규 키 미전송이라 순서와 무관하게 안전.
-- 미실행 — 사용자(지연)가 Supabase SQL Editor에서 실행(지금은 산출만).

-- [ROLLBACK] (역순: 제약 → 컬럼)
-- alter table public.iap_notifications_raw drop column if exists store;
-- alter table public.subscriptions drop constraint if exists subscriptions_store_check;
-- alter table public.subscriptions drop column if exists store;
-- alter table public.subscriptions drop column if exists purchase_token;
-- alter table public.subscriptions drop column if exists order_id;

-- [APPLY]
-- subscriptions: store 판별자(기존행 'apple' 백필) + Play 필드(nullable).
alter table public.subscriptions
  add column if not exists store text not null default 'apple';
alter table public.subscriptions
  drop constraint if exists subscriptions_store_check;
alter table public.subscriptions
  add constraint subscriptions_store_check check (store in ('apple', 'google'));
alter table public.subscriptions
  add column if not exists purchase_token text;   -- 구글 현재 토큰(Play API 호출용). 애플=NULL
alter table public.subscriptions
  add column if not exists order_id text;          -- 구글 latestOrderId. 애플=NULL

-- iap_notifications_raw: store 판별자(reprocess 디코더 라우팅). RTDN envelope는 기존
--   payload jsonb에 그대로 저장(스키마 불변).
alter table public.iap_notifications_raw
  add column if not exists store text not null default 'apple';

-- [확인쿼리] — 판정: 기존 애플 행 전부 store='apple'·purchase_token/order_id NULL
-- select store, count(*) as n,
--        count(purchase_token) as with_token, count(order_id) as with_order
-- from public.subscriptions group by store;
-- select store, count(*) from public.iap_notifications_raw group by store;
