-- route 댓글 1-레벨 답글 (additive, 2026-08-06, Ivan 계약 — run 답글 동형 이식).
-- nullable·default 없음(§D — 기존 행·클라 무영향). FK는 자기 테이블 참조 +
-- ON DELETE CASCADE(run과 동일 규칙 — 부모 삭제 시 답글 동반 소멸, comment_count는
-- 행 수 기반이라 자동 동기). 1-레벨 강제는 서버 검증(422 reply_depth_exceeded).
-- 실행 여부: 미실행(오너 실행 대기). 순서: 본 SQL 실행 → 테스트 재검증 → 배포.
-- (코드는 미전송 시 키 생략이라 SQL 미실행 상태에서도 기존 댓글 경로 무해.)

-- [ROLLBACK]
-- alter table public.route_comments drop column if exists parent_comment_id;

-- [APPLY]
alter table public.route_comments
  add column if not exists parent_comment_id uuid
  references public.route_comments(id) on delete cascade;

-- [확인쿼리 1] — 판정 기준: 1행, data_type='uuid', is_nullable='YES'
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public' and table_name = 'route_comments'
  and column_name = 'parent_comment_id';

-- [확인쿼리 2] — 판정 기준: 1행, delete_rule='CASCADE'
select rc.constraint_name, rc.delete_rule
from information_schema.referential_constraints rc
join information_schema.key_column_usage kcu
  on kcu.constraint_name = rc.constraint_name
 and kcu.constraint_schema = rc.constraint_schema
where kcu.table_schema = 'public' and kcu.table_name = 'route_comments'
  and kcu.column_name = 'parent_comment_id';

-- [확인쿼리 3] — 판정 기준: filled = 0 (기존 댓글 전부 null)
select count(*) as total, count(parent_comment_id) as filled
from public.route_comments;
