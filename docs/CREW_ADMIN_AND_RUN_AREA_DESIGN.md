# CREW_ADMIN_AND_RUN_AREA_DESIGN — 운영진 role v1 + run 지역명 (+거리 조사)

> 2026-07-11. 상태: **설계 승인 대기** (§1은 조사 보고 — 수정 별도 승인).

## 1. 거리 불일치 조사 (run 0.18 vs track 0.0) — 판정: 실버그 (표시 파생 결함)

해당 run(`3c6bed7a…`, 신고 0.22km/141초) 실조회 결과:

- **`run.distance_km=0.18`는 서버 계산값** — 신고 0.22 vs 서버 0.18의 괴리가
  10%를 넘어 adjusted 경로(서버 값 대체 + `verified`+`is_flagged`,
  `distance_km_reported=0.22` 보존)로 저장됨. **의도된 시맨틱, 정상.**
- **`track.server_distance_km=0.0`는 버그** — 정확한 서버 거리를 저장하지
  않고 조회 시 splits에서 파생하는데(`마지막 partial의 km, 없으면 정수 랩
  수`), 총거리 0.18km < `MIN_PARTIAL_KM`(0.2)라 **splits가 아예 빈 배열**
  → `len([]) = 0.0`. 동일 패턴 run 2건 더 확인(0.04km도 0.0), 0.2km짜리는
  partial이 있어 정확.
- **심각도 낮음**: 0.2km 미만 트랙 한정(실사용 러닝엔 드묾, 테스트 런 계열),
  표시값만 틀리고 집계(랭킹·PB·챌린지)는 `runs.distance_km`를 쓰므로 무영향.
- **수정 규모 (승인 시)** — 권장안: `run_tracks.server_distance_km` 컬럼
  추가(+저장 1줄, 응답은 컬럼 우선·구 행은 기존 파생 폴백) — SQL 1 + 코드
  3줄 + 테스트, **~1시간**. 무SQL 대안: splits 빈 경우 `runs.distance_km`
  폴백(15분 — verified/adjusted면 동일값이라 사실상 정확, unverified 트랙만
  근사).

## 2. run 지역명 — `area` (프론트 변환·서버 저장/서빙 분업)

- **필드명 `area`** — 크루의 기존 명명과 일치(`CrewCreate.area`: 자유 문자열
  ≤50). 시안 요구가 "성수동" 단일 표시 문자열이라 크루의 sido/sigungu
  구조화가 아닌 area 계열이 맞음. 분업도 가이드 187행 철학 그대로
  (역지오코딩은 프론트 Kakao SDK, 서버는 검증·저장·서빙만).
- SQL: `runs.area text` (nullable — 아래 페어 §4).
- 스키마: `RunRequest.area`(Optional ≤50) / `RunUpdate.area`(저장 후 편집 —
  title·notes와 동급) / `RunResponse.area` / 카드(`CrewRunItem` →
  `ActivityFeedItem` 상속, 공개 프로필·피드·크루 피드)에도 포함(시안 카드
  지역 라인).
- **백필 불가**: 과거 run은 프론트가 변환할 좌표 접근 시점이 없음 — null
  유지, **프론트 표시 규칙 "null이면 지역 라인 숨김"**을 가이드에 명시.
- **타인 상세 화이트리스트: 포함 (의견)** — 동 단위 지역명은 GPS 트랙(정밀
  좌표 공개)보다 훨씬 거친 정보이고, 노출 자체가 이미 visibility 게이트
  뒤에 있음(followers/private는 게이트가 차단). 트랙 없는 run의 area가
  유일한 위치 단서가 되는 경우도 "동" 해상도라 수용 — 방침(PRIVACY_DATA_MAP
  §2)에 항목 추가.

## 3. 크루 운영진 admin role v1

### role 전환 API

- `PATCH /crews/{crew_id}/members/{target_id}/role` body `{role: "admin"|"member"}`
  — **owner 전용**. 규칙:
  - target은 크루 멤버여야 함(아니면 404 은닉).
  - **target=owner 불가**(422 — owner 강등은 존재하지 않음, 위임은 기존
    `PATCH /crews/{id}/transfer` 유지·role API와 분리).
  - admin↔member 양방향, 멱등(같은 role 재설정 200).
  - 응답: 갱신된 멤버 행(`{user_id, role}` — CrewMemberResponse 재사용).
- transfer는 무변경 — 단 admin이 owner가 되는 경우(transfer target이 admin)
  기존 로직이 roles를 owner/member로 플립하므로 그대로 동작.

### ensure_owner 사용처 전수 분류 (실코드 스윕 — 13곳)

| 액션 (함수) | v1 판정 |
|---|---|
| 공지 생성/수정/삭제 (announcement create·update·delete) | **admin 확장** |
| 챌린지 생성 (create_challenge) | **admin 확장** |
| 멤버 강퇴 (kick_member) | **admin 확장 — 단 target이 member일 때만** (admin이 admin/owner 강퇴 → 403; owner는 기존대로 admin·member 강퇴 가능, self 불가 유지) |
| 가입 신청 목록/승인 (list_join_requests·decide_join_request) | owner 유지 — 지시 범위 밖, **v2 후보로 기록** |
| 초대 코드 조회/재생성 | owner 유지 |
| 크루 설정 수정 (update_crew) | owner 유지 |
| 위임 (transfer_ownership) | **owner 전용 필수** |
| 크루 삭제 (delete_crew) | **owner 전용 필수** |
| role 변경 (신규) | **owner 전용 필수** |

- 구현: `ensure_manager(crew_id, caller_id)` 게이트 신설(owner 또는
  role='admin', 실패 시 기존 NotOwner → 403 계약 유지) — 확장 5곳만 교체,
  나머지는 ensure_owner 그대로. 멤버 목록 정렬을 owner→admin→member로
  (기존 owner 우선 정렬의 자연 확장).
- 탈퇴/계정 삭제와의 상호작용: admin도 일반 멤버처럼 leave 가능(제약 없음),
  cascade 무영향.

### 알림 — 의견: v1 제외

role 변경 통지는 새 알림 type이 필요한데, `notifications_type_check` 재작성
(함정 항목)이 따라옴. 저빈도 이벤트 + 크루 화면에서 확인 가능하므로 v1
제외하고, **백로그의 인앱 초대(crew_invited)와 묶어 제약 재작성 1회로 같이
추가**하는 게 효율적 — 백로그에 연계 메모.

### 시안의 per-운영진 세부 권한 토글: **v2 범위 제외** (명시)

## 4. SQL (승인 후 확정 — 페어)

```sql
-- [APPLY]
-- ① crew_members.role에 'admin' (제약 이름·현 제약 존재 실증: 23514,
--    crew_members_role_check)
alter table public.crew_members drop constraint if exists crew_members_role_check;
alter table public.crew_members add constraint crew_members_role_check
  check (role in ('owner', 'admin', 'member'));
-- ② run 지역명
alter table public.runs add column if not exists area text;

-- [ROLLBACK]
-- update public.crew_members set role = 'member' where role = 'admin';
-- alter table public.crew_members drop constraint if exists crew_members_role_check;
-- alter table public.crew_members add constraint crew_members_role_check
--   check (role in ('owner', 'member'));
-- alter table public.runs drop column if exists area;
```

## 5. 테스트 계획

- **권한 매트릭스 전수**: owner/admin/member × (공지 생성·수정·삭제 / 챌린지
  생성 / member 강퇴 / admin 강퇴 / role 변경 / transfer / 크루 수정 / 크루
  삭제 / 초대 코드) — 기대 200/403 전 칸 assert. admin 승격→강등 후 권한
  소멸 재확인.
- role API: target=owner 422, 비멤버 404, 멱등, 비owner 호출 403.
- area: 저장→상세/편집/타인 상세(화이트리스트)/피드 카드 왕복 + null 숨김
  계약(기존 run area null) + ≤50 검증 422.
- 회귀: crew_manage·announcements·challenge·kick 관련 + run 상세/피드.
- Gemini 0, SQL은 사용자 실행 후 진행.
