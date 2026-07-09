# RUN_DETAIL_AND_PHOTOS_DESIGN — run 상세 개방 + 러닝 사진 (설계)

> 2026-07-09. 상태: **구현 완료·배포됨** (§1-C verification 타인 제외 ·
> §2-A 방식 B · §2-E 목록 첫 장만. SQL 적용됨 — db/2026-07-09_run_photos.sql).

## 1. run 상세/트랙 가시성 (②)

### 재현 결과 (스테이징 실호출, test1 public run × test2·demo3)

| 호출 | 결과 | 판정 |
|---|---|---|
| `GET /runs/{id}/track` | **200** (맞팔·무관계 모두) | **회귀 아님** — 게이트(19169e8) 정상. 리포터의 track 404는 **구코드(게이트 배포 전) 또는 followers 제한 run 가능성** |
| `GET /runs/{id}` 상세 | **404** (타인 전부) | **실재 갭** — owner-only가 현재 구현·문서("본인 것만") 그대로. 개방 설계 필요 |
| comments | 200 | 게이트 사용 중 (일관) |

### 설계 — 상세를 `_can_see_run` 게이트로 개방 + 타인 응답 필드 정제

- 접근: track·kudos·댓글과 동일 게이트. 본인 동작 불변, 차단·부재는 404
  은닉 유지 (additive).
- **타인 응답은 명시적 화이트리스트로 정제** — 이미 확립된 타인 노출 계약
  (`ActivityFeedItem` — "no notes/feedback fields, route_summary는 공개
  코스만")을 상세에 적용:

| 구분 | 필드 | 타인 응답 |
|---|---|---|
| 유지 | id, user_id, ran_at, distance_km, duration_sec, avg_pace_sec_per_km, title, has_track, splits, kudos_count, comment_count | 그대로 (트랙이 공개면 splits도 공개가 일관) |
| 조건부 | route_id | **연결 코스가 public일 때만** (비공개 코스 id 프로브 차단 — list_user_runs와 동일 규칙) |
| **제거(null)** | **notes**(개인 메모 — "절대 미노출" 기존 계약), liked, feedback_tags, feedback_at, **distance_km_reported·is_flagged**(부정 판정 내부 상태 — 낙인·로직 노출), visibility(기존 타인 응답 null 관례), new_records 등 POST 전용 | null/기본값 |
| **결정 §1-C** | verification | **제외 권장** — 타인에게 "suspect" 노출은 낙인. 프론트가 GPS 뱃지를 원하면 `has_track`으로 충분 |

- 구현: `get_run(run_id, caller_id)` — owner면 현행, 아니면 게이트 통과 후
  화이트리스트 사본 반환 (~25줄). 향후 필드 추가 시 기본이 "타인 미노출"이
  되도록 화이트리스트 방식(블랙리스트 아님).
- 테스트: 가시성 매트릭스 3×3(track 때와 동일) + **프라이버시 이중검증**
  (notes 값 문자열이 타인 응답 전체에 부재) + **피드↔상세 일관성**(피드/공개
  프로필에 보이는 run은 상세도 200, 안 보이는 run은 404).

## 2. 러닝 사진 업로드 (①) — photos ≤3, jpeg/png/webp 5MB, 동영상 v2

### A. 업로드 시점 — 결정 지점 (추천: B)

| | (A) pre-save batch (run 저장 전) | **(B) post-save (run id 기준, 추천)** |
|---|---|---|
| 경로 키 | run id가 없어 임시 uuid → 저장 실패 시 **고아 파일** → 청소 크론 필요 | `{run_id}/{n}` — 발급 시 run 존재+소유 검증, 고아 최소 |
| 삭제·가시성 연동 | 임시키→run 매핑 관리 필요 | run에 묶여 자동 단순 |
| UX | 저장 버튼 전에 업로드 진행 가능 | 저장 즉시 완료 → 사진은 백그라운드 업로드 후 `PATCH /runs/{id}` — 기존 저장 흐름 무변경 |
| 실패 모드 | run 없는 사진 잔존 | 사진 없는 run(재시도 가능 — 양성) |

### B. 스키마 + Storage

- **`runs.photos text[]`** (테이블 대신 컬럼 — 사진은 run 속성, ≤3 고정, 조인
  불요. 순서/캡션 메타가 생기면 v2에서 테이블 분리): 저장 값은 **경로만**
  (`{run_id}/1.jpg`), URL 아님.
  ```sql
  -- [APPLY] (승인 후 확정)
  alter table public.runs add column if not exists photos text[] not null default '{}'
    check (array_length(photos, 1) is null or array_length(photos, 1) <= 3);
  -- 버킷: run-photos, private (public=false), 5MB, jpeg/png/webp
  insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values ('run-photos', 'run-photos', false, 5242880,
          array['image/jpeg','image/png','image/webp'])
  on conflict (id) do nothing;
  -- [ROLLBACK]
  -- alter table public.runs drop column if exists photos;
  -- delete from storage.buckets where id = 'run-photos';
  ```
- **버킷은 private 필수** (avatars와 다름) — public이면 URL을 아는 누구나
  접근해 비공개 러닝 사진이 게이트를 우회함. RLS: storage 정책 없음(deny) —
  service_role 서명 URL로만 읽기/쓰기.

### C. 흐름 (avatar 3-step 확장)

1. `POST /runs/{run_id}/photos/upload-url` `{slot: 1~3, content_type}` —
   **소유자만**(404 은닉), run 존재 검증 후 서명 업로드 URL 발급 (기존 객체
   있으면 선삭제 — avatar 패턴).
2. 앱이 이미지 PUT (Storage가 5MB·MIME 강제).
3. `PATCH /runs/{run_id}` `{photos: ["{run_id}/1.jpg", ...]}` — 소유자만,
   경로 형식 검증(`{run_id}/` prefix 강제 — 남의 run 사진 경로 참조 차단).
   **배열에서 빠진 기존 경로는 Storage에서 best-effort 삭제**(교체/삭제 연동).
4. **조회: 응답 시점 서명 읽기 URL 발급** — `GET /runs/{id}`(및 §2-E 채택
   범위)가 `_can_see_run` 통과 후 photos 경로를 **만료 1시간 서명 URL 배열로
   변환**해 반환. 가시성 게이트와 구조적으로 일관(비공개 사진 URL 유출 불가,
   만료로 재공유도 차단).

### D. EXIF — 결정 포함 (추천: 클라이언트 제거 + 계약 명시)

- 폰 사진엔 GPS 좌표 EXIF가 박힘 — **자택 좌표 유출 축**.
- **서버 제거 불가 구조**: 서명 URL 직접 업로드라 서버가 바이트를 안 거침.
  서버 제거를 하려면 업로드 프록시(서버 경유)로 구조 변경 — 5MB×3 트래픽이
  Fly 512MB 단일 머신을 지나는 비용·복잡도라 기각.
- **추천: 클라이언트 재인코딩 시 EXIF 제거를 계약으로** — RN 이미지 리사이즈/
  압축 라이브러리(expo-image-manipulator 등)는 재인코딩 시 EXIF를 기본
  미보존. API_GUIDE에 "업로드 전 재인코딩(EXIF 제거) 필수" 명시 +
  PRIVACY_DATA_MAP §2에 "러닝 사진: EXIF(GPS 포함)는 클라이언트에서 제거 후
  업로드, 서버는 원본 EXIF를 저장하지 않음" 기재.
- 잔여 리스크(클라 구현 누락): 베타 수용, **출시 전 검토 항목**으로 "서버
  사후 EXIF 스캔(주기 잡)" 등재.

### E. 노출 범위 — 결정 지점 (추천: 상세 전체 + 목록 첫 장)

- 상세(`GET /runs/{id}`): photos 전체 서명 URL.
- 목록(피드·공개 프로필·크루 피드): **첫 장만** 서명 URL(`photo_thumb` 1개) —
  카드 썸네일 용도, 서명 발급 비용(행당 1회)과 payload 절충. 전체는 상세에서.
- 서명 발급은 로컬 연산(supabase-py `create_signed_url`)이지만 목록 N행 × 3장
  전부는 과함 — 첫 장 정책이 균형.

### F. 삭제 연동

- **계정 삭제**: `run-photos/{run_id}/…`는 FK가 없어 잔존(아바타와 같은 축) —
  `delete_account`에 "유저 run id 목록 → 각 prefix 삭제(best-effort)" 추가.
  ACCOUNT_DELETION_DESIGN §5의 ③(아바타 삭제) 단계에 편입.
- **run 개별 삭제**: 현재 API 없음 — 생기면 같은 훅. PATCH로 배열에서 제거
  시엔 §C-3이 처리.
- PRIVACY_DATA_MAP §6 갱신: 사진 보관·삭제 경로.

### 테스트 계획 (①)

- 3-step 왕복: 발급(소유자) → PUT → PATCH → 상세에서 서명 URL 3개 + 실제
  GET 200. 비소유자 발급 404. `{run_id}/` prefix 밖 경로 PATCH 422.
- **가시성 연동**: private run의 사진 — 타인 상세 404(사진 URL 자체가 응답에
  없음) + 서명 만료 동작. 매트릭스는 ②와 공유.
- 교체: PATCH로 1장 제거 → Storage 객체 삭제 확인. 4장째 422.
- 계정 삭제 통합: run-photos prefix 소멸 assert (기존 탈퇴 테스트 확장).
- Gemini 0. Storage 실호출은 로컬 테스트로 충분.
