-- runs.app_version 추가 (additive, 2026-07-31) — 클라 빌드/OTA 식별 자유형 텍스트.
-- 배경: route_id null 판정(구번들 vs 실버그)에서 신·구 번들 서버측 판별 불가
-- 맹점 영구 제거. nullable·default 없음(§D — 기존 행·기존 클라 무영향).
-- 실행 여부: ✅ 실행 완료(2026-07-31 오너 — 확인쿼리 1: text/YES 1행, 확인쿼리 2:
-- filled_count 0 기준 충족). 이후 fly 배포 + 실서버 스모크(smoke-v125 저장→삭제) 통과.
-- (코드는 미전송 시 키 생략이라 SQL 미실행 상태에서도 기존 저장 경로는 무해.)

-- [ROLLBACK]
-- alter table public.runs drop column if exists app_version;

-- [APPLY]
alter table public.runs add column if not exists app_version text;

-- [확인쿼리 1] — 판정 기준: 정확히 1행, data_type='text', is_nullable='YES'
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public' and table_name = 'runs'
  and column_name = 'app_version';

-- [확인쿼리 2] — 판정 기준: filled_count = 0 (기존 행 전부 null, 백필 없음)
select count(*) as total_count, count(app_version) as filled_count
from public.runs;
