-- 크루 커버 + 아이콘 이미지 (시안: 운영진이 변경, 기본은 그라데이션/디폴트).
-- crews에 cover_url·icon_url 2컬럼 additive(nullable). 업로드는 아바타 3-step
-- 패턴 재사용(고정 경로 {crew_id}/cover·{crew_id}/icon + 캐시버스터). 이미지
-- 바이트는 Storage(public 버킷 'crew-images')에, 여기엔 public_url만 저장.
-- crews는 이미 RLS enable(rls_backfill) — 컬럼 추가만, 정책 변경 없음.
-- 명시 null=삭제(선례 규칙), Storage 정리는 앱이 best-effort. 미실행 — 사용자
-- 가 SQL Editor에서 실행.

-- [APPLY]
alter table public.crews add column if not exists cover_url text;
alter table public.crews add column if not exists icon_url  text;

-- 실행 후 확인:
-- select column_name from information_schema.columns
--   where table_name='crews' and column_name in ('cover_url','icon_url');

-- [ROLLBACK]
-- alter table public.crews drop column if exists cover_url;
-- alter table public.crews drop column if exists icon_url;
