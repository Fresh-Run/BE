-- Storage 버킷 소스 트래킹 (감사 3차 M-6/M-7 대응 — 기록용).
--
-- crew-images·avatars 두 버킷은 앱 코드가 참조하나(crew_service·profile_service)
-- db/ SQL에 생성 기록이 없었다(run-photos만 있었음). 실제로는:
--   · avatars     : 초기 세팅 때 콘솔에서 생성 (public) — pre-existing.
--   · crew-images : 2026-07-13 크루 이미지 기능 착수 시 Storage API로 생성 (public).
-- 둘 다 라이브에 이미 존재하므로 이 파일은 **재현성·source-of-truth 확보용**이며
-- on conflict do nothing이라 재실행해도 무해(멱등). 실행 여부: [APPLY]는 사실상
-- no-op(이미 존재) — 신규 프로젝트 부트스트랩 시에만 실제 생성.
--
-- 버킷 privacy 모델(감사 3차 M-6 확정): avatars·crew-images는 **public**
-- (프로필/크루가 공개 표면 — 아바타·크루 카드가 비회원에게 노출되는 존재).
-- run-photos만 private(개인 위치·EXIF 민감). crew-images가 public이라 비공개
-- 크루의 커버/아이콘도 URL 추측 시 열람 가능 — 목록급 공개 정보로 수용(결정).
-- 상세는 docs/PRIVACY_DATA_MAP.md·API_GUIDE.md "크루 이미지" 절.

-- [APPLY]
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('avatars', 'avatars', true, 5242880,
        array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do nothing;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('crew-images', 'crew-images', true, 5242880,
        array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do nothing;

-- 실행 후 확인:
-- select id, public, file_size_limit from storage.buckets
--   where id in ('avatars', 'crew-images', 'run-photos') order by id;

-- [ROLLBACK]
-- (운영 버킷 삭제는 파일 유실 위험 — 롤백 비권장. 부트스트랩 실수 정리 시에만:)
-- delete from storage.objects where bucket_id = 'crew-images';
-- delete from storage.buckets where id = 'crew-images';
