-- 러닝 사진: runs.photos(경로 배열 ≤3) + private 버킷 run-photos.
-- 왜: 사진 업로드(방식 B — run id 기준 경로, 서명 URL 3-step) —
-- docs/RUN_DETAIL_AND_PHOTOS_DESIGN.md §2. 버킷은 private 필수(가시성
-- 게이트 우회 방지 — 읽기는 응답 시점 만료 1h 서명 URL로만).
-- 미실행 — 사용자가 SQL Editor에서 실행.

-- [APPLY]
alter table public.runs
  add column if not exists photos text[] not null default '{}'
  constraint runs_photos_max3
  check (array_length(photos, 1) is null or array_length(photos, 1) <= 3);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('run-photos', 'run-photos', false, 5242880,
        array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do nothing;

-- 실행 후 확인:
-- select column_name from information_schema.columns
--   where table_name = 'runs' and column_name = 'photos';
-- select id, public, file_size_limit from storage.buckets where id = 'run-photos';

-- [ROLLBACK]
-- alter table public.runs drop column if exists photos;
-- delete from storage.objects where bucket_id = 'run-photos';
-- delete from storage.buckets where id = 'run-photos';
