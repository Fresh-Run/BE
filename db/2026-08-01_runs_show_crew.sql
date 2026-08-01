-- runs.show_crew 추가 (additive, 2026-08-01, Ivan 계약·오너 결정) — K1 퍼블릭
-- 피드 크루 배너의 런별 유저 초이스. 디폴트 ON(오너 결정 ①). 비공개 크루는
-- 플래그 무관 미노출(② 하드 게이트 — 설정은 허용, 효과만 게이트, 앱 코드).
-- 실행 여부: 미실행(오너 실행 대기). 순서: 본 SQL 실행 → 테스트 재검증 → 배포.
-- (코드는 미전송 키 생략 + K1 조회는 컬럼 부재 시 null 폴백 — 순서 역전에도 무해.)

-- [ROLLBACK]
-- alter table public.runs drop column if exists show_crew;

-- [APPLY]
alter table public.runs
  add column if not exists show_crew boolean not null default true;

-- [확인쿼리 1] — 판정 기준: 1행, data_type='boolean', is_nullable='NO',
--               column_default에 true
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public' and table_name = 'runs'
  and column_name = 'show_crew';

-- [확인쿼리 2] — 판정 기준: false_count = 0 (기존 행 전부 true — 디폴트 ON 소급)
select count(*) as total, count(*) filter (where show_crew = false) as false_count
from public.runs;
