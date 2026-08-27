-- runs.avg_cadence_spm 추가 (additive, 2026-08-27) — 평균 케이던스(steps/min).
-- 배경: 이반 케이던스 기능 선행 — RunRequest가 extra="forbid"라 클라가 이 필드를
-- 보내면 컬럼/모델 없이는 422. avg_pace_sec_per_km와 동형(int·nullable). 2단계
-- (post-run 저장·빌드13 실시간) 모두 이 단일 필드로 커버.
-- nullable·default 없음(§D — 기존 행·기존 클라 무영향).
-- ⚠️ SQL→배포 순서: 코드 insert는 avg_cadence_spm을 **미전송 시 키 생략**(app_version
--   전례, run_service._log 조건부 추가)이라 컬럼 미적용 DB에서도 **무cadence 저장은
--   무해**. cadence를 실제로 보내는 요청만 컬럼에 의존 → 클라가 필드를 보내기 전에
--   이 SQL을 실행하면 안전. 권장 순서: 이 SQL 실행 → 코드 배포 → 클라 케이던스 송신.
-- 실행 여부: ⏳ **미실행 — 오너 Supabase SQL Editor 실행 대기.** 멱등(if not exists)
--   이라 재실행 무해 no-op. 실행 후 확인쿼리 1(integer/YES 1행)·2(filled_count 0) 판정.

-- [ROLLBACK]
-- alter table public.runs drop column if exists avg_cadence_spm;

-- [APPLY]
alter table public.runs add column if not exists avg_cadence_spm int;

-- [확인쿼리 1] — 판정 기준: 정확히 1행, data_type='integer', is_nullable='YES'
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public' and table_name = 'runs'
  and column_name = 'avg_cadence_spm';

-- [확인쿼리 2] — 판정 기준: filled_count = 0 (기존 행 전부 null, 백필 없음)
select count(*) as total_count, count(avg_cadence_spm) as filled_count
from public.runs;
