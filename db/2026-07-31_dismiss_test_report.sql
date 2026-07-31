-- 테스트 신고 dismiss (2026-07-31) — Ivan 신고 파이프 E2E 확인용 신고 1건 정리.
-- 대상: 46d913eb (이반 → SeYoon 런 fff343e0, reason abuse, 11:50Z 접수 — 실신고 아님).
-- 신고는 무알림 설계(POST /reports "무알림")라 피신고 테스터(SeYoon)에게 어떤
-- 알림·표시도 가지 않았고 dismiss도 영향 0.
-- 실행 여부: 미실행(오너 실행 대기). 행 id 하드코딩 — 닉네임 조인 없음(오발 방지).

-- [ROLLBACK]
-- update public.reports set status = 'pending', reviewed_at = null
-- where id = '46d913eb-0097-4c36-bf58-0f023f27bca9';

-- [APPLY]
update public.reports
set status = 'dismissed', reviewed_at = now()
where id = '46d913eb-0097-4c36-bf58-0f023f27bca9' and status = 'pending';

-- [확인쿼리] — 판정 기준: 1행, status='dismissed', reviewed_at 비null(방금 시각)
select id, status, reviewed_at
from public.reports
where id = '46d913eb-0097-4c36-bf58-0f023f27bca9';
