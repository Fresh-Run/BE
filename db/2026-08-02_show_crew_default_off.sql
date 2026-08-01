-- show_crew 디폴트 재판정: ON→OFF (오너 확정 2026-08-02 — 옵트인 포스처,
-- 셰어 카드 선례 일관). 소급 포함: 기존 런 전부 OFF(유저 재토글 가능).
-- 서버 코드는 컬럼 default 위임(하드코딩 0 — 미전송 키 생략)이라 SQL-only 전환.
-- 실행 여부: 미실행(오너 실행 대기). 배포 불요(푸시≠배포 — 동작은 이 SQL이 전부).

-- [ROLLBACK] — 디폴트 ON 복원 + 전 행 true 소급(2026-08-02 이전 상태)
-- alter table public.runs alter column show_crew set default true;
-- update public.runs set show_crew = true;

-- [APPLY]
alter table public.runs alter column show_crew set default false;
update public.runs set show_crew = false;

-- [확인쿼리 1] — 판정 기준: column_default에 false
select column_name, column_default
from information_schema.columns
where table_schema = 'public' and table_name = 'runs'
  and column_name = 'show_crew';

-- [확인쿼리 2] — 판정 기준: true_count = 0 (전 행 OFF 소급)
select count(*) as total, count(*) filter (where show_crew) as true_count
from public.runs;
