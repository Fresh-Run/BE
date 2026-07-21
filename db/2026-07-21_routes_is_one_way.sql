-- routes.is_one_way — 일방통행(end 좌표 동봉) 코스 여부 (Ivan 리포트 D).
-- routes는 end 좌표를 저장하지 않아(start_lat/lng만) 기존 코스에서 일방 여부를
-- 라이브 유도 불가 — 컬럼으로 명시 저장한다. 생성 핸들러가 req.end 존재 시 true.
-- additive · default false(하위호환): 기존 코스는 전부 false(루프)로 백필됨.
-- ⚠️ 소급 정확성 한계(판단 플래그): end 정보가 DB에 없어 과거 일방 코스가
--    있었다면 false로 오표기된다. 소급 복원 불가 — 대부분 루프라 실용상 수용.
-- RLS: routes는 기존 테이블(이미 enable) — 컬럼 추가만이라 정책 무관.
-- ✅ 실행 완료 (2026-07-21, 사용자 SQL Editor). 확인 쿼리: loop_default 63 /
--    one_way 0 / total 63 — 기존 전량 default false 백필 정상(신규 일방은 배포 후부터).

-- [APPLY]
-- alter table public.routes
--   add column if not exists is_one_way boolean not null default false;

-- [확인쿼리] — 컬럼 존재 + 기존 전량 false 백필 확인
-- select count(*) filter (where is_one_way = false) as loop_default,
--        count(*)                                   as total
--   from public.routes;

-- [ROLLBACK]
-- alter table public.routes drop column if exists is_one_way;
