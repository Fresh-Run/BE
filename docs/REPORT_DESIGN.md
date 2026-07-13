# REPORT_DESIGN — 유저/콘텐츠 신고 기능 설계

> 작성 2026-07-13. 상태: **구현 완료(배포 대기)** — SQL 적용됨(사용자 실행,
> `db/2026-07-14_reports.sql`), 코드·테스트 완료. §8 확정: POST 성공 **204** /
> detail 길이 **앱(Pydantic)만** / 운영진 미설정 시 admin **404 fail-safe 수용** /
> status **단방향**(되돌리기 미지원). 배포 전 선행: `fly secrets set
> ADMIN_USER_IDS=<uuid>` 주입.
> 전제(진단 완료, 실조회): `reports` 테이블 없음(신규) · 차단 스택이 additive
> 참고 패턴(`blocks` 테이블·`is_blocked_either` 404 은닉·self CHECK·RLS enable) ·
> 전역 운영진 role 없음(profiles에 role/is_admin 없음, tier는 IAP 전용) · 신고 대상
> 테이블 전부 존재 · enum CHECK가 프로젝트 표준(visibility·join_policy·notif.type·
> crew tags·chat emoji).
>
> **스키마 변경 있음**(신규 `reports` 테이블). SQL은 승인 후 `db/`에
> `[APPLY]`+`[ROLLBACK]`+`[확인쿼리]` 세트로 별도 제공. 이 문서는 방향만.

---

## 1. 요구 / 비요구 (스코프 경계 — 발명 금지)

**요구**
- 유저가 다른 유저를 **신고**(프론트 프로필 ⋯ 메뉴 → "신고하기").
- 신고는 `reports` 테이블에 쌓임. **운영진(나)**이 조회·처리.
- 엔드포인트 3종: 신고 생성 / 운영진 조회 / 운영진 상태 처리.
- reason은 **enum 강제**(+ 자유텍스트 detail optional).
- 중복 pending 신고는 **멱등**(스팸 봉쇄).

**비요구 (발명 금지)**
- **1차는 `target_type='user'`(유저 신고)만** API·프론트 오픈. run/댓글/코스/크루
  메시지 신고는 **테이블 스키마엔 확장 여지만 두고 API는 미오픈**(나중에 검증만 열면 됨).
- **차단 자동 결합 안 함** — 프론트 액션시트가 신고+차단을 함께 줘도 백엔드는
  `POST /reports` + `POST /block` **독립 2호출**. 신고가 차단을 유발하지 않음.
- **운영진 알림 없음**(1차) — 폴링(`GET /admin/reports`). `report_received` 알림
  type 추가 안 함(CHECK drop→재생성 함정 회피, 베타 불필요).
- **어드민 UI 없음** — API만. 조회는 나중에 간단 툴/직접 호출.
- 신고자 신원 노출 정책 변경 없음(신고당한 사람에게 신고 사실·신고자 미노출).
- 자동 조치(자동 정지·숨김) 없음 — 운영진 수동 처리만.

## 2. 엔드포인트 계약 (3종)

경로 순서 규칙: `/admin/reports`(고정)·`/reports`(고정)는 패턴 경로 충돌 없음.
`/admin/reports/{id}`(PATCH)는 `/admin/reports`(GET)와 메서드·형태가 달라 안전.

### 2.1 `POST /reports` — 신고 생성 (인증 필요)
| 항목 | 값 |
|---|---|
| 요청 | `{target_type: "user", target_id: uuid, reason: enum, detail?: str≤500}` |
| 응답 | **201** (또는 204 — 아래 §8 플래그) |
| self 신고 | **400** (`target_id == 나`) — block의 self 400 대칭 |
| 없는 대상·차단 관계 | **404 은닉** (`is_blocked_either` + 대상 존재 확인, block 패턴 복제) |
| 중복 pending | **멱등** — 이미 같은 (reporter, target_type, target_id) pending 있으면 새 행 안 만들고 성공 응답(부분 유니크 인덱스가 DB 봉쇄) |
| `target_type` != 'user' | **422** (`run`/`comment` 등은 스키마엔 있으나 **아직 미오픈**) |
| 잘못된 reason | **422** (enum 밖) |
| detail > 500자 | **422** |

**소비 규칙(프론트)**: ⋯ 메뉴 "신고하기" → 사유 선택 시트(reason enum) + 선택적
상세 입력 → 이 호출. 성공 시 "신고가 접수되었어요" 토스트. 404를 받으면(차단/없는
유저) 조용히 동일 토스트(존재 은닉 — 신고 대상이 사라졌음을 드러내지 않음).

### 2.2 `GET /admin/reports?status=pending&limit&offset` — 운영진 조회
| 항목 | 값 |
|---|---|
| 게이트 | **운영진(env 화이트리스트)만**. 아니면 **404**(엔드포인트 존재 은닉 — 403 아님) |
| 응답 | `[{id, reporter:{user_id,nickname,avatar_url}, target_type, target_id, target:{user_id,nickname,avatar_url}, reason, detail, status, created_at}]` 최신순 |
| `status` 필터 | `pending`(기본) / `reviewed` / `dismissed` / 생략 시 pending |
| 페이지 | `limit`(기본 20·최대 100) + `offset` |

### 2.3 `PATCH /admin/reports/{report_id}` — 운영진 상태 처리
| 항목 | 값 |
|---|---|
| 게이트 | 운영진만, 아니면 **404** |
| 요청 | `{status: "reviewed" | "dismissed"}` |
| 동작 | status 갱신 + `reviewed_at = now()` 기록. 이미 처리된 것/없는 id → **404** |
| 응답 | **204** |

→ PATCH가 있어야 pending이 무한 적체 안 됨(처리→목록에서 빠짐).

**에러 규약(§5 준수)**: 구조화 필요 시 `{error, message}`. 권한 차단은 **404 은닉**
(운영 표준). 신고 대상 은닉도 404.

## 3. 스키마 (신규 `reports` 테이블 — SQL은 승인 후 별도)

DDL 방향(확정 컬럼):
```
reports:
  id          uuid pk default gen_random_uuid()
  reporter_id uuid not null references auth.users(id) on delete cascade
  target_type text not null check in
              ('user','run','run_comment','route','route_comment','crew_message')
  target_id   uuid not null           -- FK 없음(다형성 — 여러 테이블 대상)
  reason      text not null check in ('spam','abuse','inappropriate','impersonation','other')
  detail      text null               -- ≤500 (앱 검증; DB length check 선택)
  status      text not null default 'pending' check in ('pending','reviewed','dismissed')
  created_at  timestamptz not null default now()
  reviewed_at timestamptz null
```
- **부분 유니크 인덱스**: `unique (reporter_id, target_type, target_id) where status='pending'`
  → 같은 신고자가 같은 대상에 pending 중복 봉쇄(follow_requests 선례 — TOCTOU도 DB가 막음).
- **RLS enable**(정책 없음 — service_role만, 신규 테이블 표준 백스톱).
- **인덱스**: `(status, created_at desc)` 운영 조회용, `target_id` 역방향(선택).
- **target_id는 FK 없음**(다형성). `target_type='user'`면 auth.users(id)를 가리키나
  다른 타입 대비 FK 미설정 — 존재 검증은 앱 레이어(§2.1 404).

**enum 값 = 영문 서버 키**(spam/abuse/…). 한글 라벨("스팸"·"욕설/혐오"·"부적절한
콘텐츠"·"사칭"·"기타")은 프론트 몫.

**target_type CHECK엔 6종 다 넣되 API는 'user'만 허용** — run/댓글 신고를 나중에
열 때 **스키마 재변경 0**(API 검증에서 타입만 추가). CHECK를 미리 넓게 두는 게
"CHECK drop→재생성" 재작업을 피하는 길(알려진 함정).

## 4. 운영진 게이트 구현 방향 (env 화이트리스트)

- `app/core/config.py` `Settings`에 **`admin_user_ids: str = ""`** 추가(콤마구분
  UUID). Fly secret으로 주입: `fly secrets set ADMIN_USER_IDS=uuid1,uuid2`.
- 파싱 헬퍼: `settings.admin_user_ids.split(",")` → 공백 strip → set. 빈 문자열이면
  빈 set(운영진 0명 = 모든 admin 엔드포인트 404).
- 의존성 함수 `require_admin`(auth.py 또는 deps): `get_current_user`로 유저 얻고
  `user.user_id not in admin_ids`면 **404 raise**(403 아님 — 존재 은닉).
  `GET/PATCH /admin/reports`가 이 의존성 사용.
- **키 노출 금지**: ADMIN_USER_IDS 값(내 UUID)은 로그·화면 출력 안 함. 진단·테스트도
  os.environ/settings에서 조용히 읽음.
- **확장 여지 메모**: 다인 운영 필요 시 `profiles.is_admin boolean default false`
  additive 컬럼으로 승격 → `require_admin`이 그 컬럼을 보게 교체(env는 fallback 유지
  가능). 지금은 1인 베타라 env로 충분.

## 5. 하위호환 — 순수 additive
- 신규 테이블 + 신규 엔드포인트 3종. **기존 계약·엔드포인트·스키마 전부 불변.**
- 새 알림 type 없음 → `notifications_type_check` 안 건드림(함정 회피).
- 기존 유저 데이터 소급·백필 없음.

## 6. 테스트 계획 (완료의 정의 §A 풀세트)

**`tests/test_report_integration.py` (신규)**
신고 생성:
1. 정상 신고: `POST /reports {target_type:'user', target_id:B, reason:'spam'}` →
   201/204 + `reports` 행 생성 **assert**(status='pending', reporter=나).
2. detail 포함 신고 → 저장 assert.
3. self 신고(`target_id=나`) → **400** + 행 미생성.
4. 없는 유저 신고 → **404** + 행 미생성.
5. 차단 관계(A↔B block) 신고 → **404 은닉** + 행 미생성.
6. 중복 pending → **멱등**(2회 호출, `reports` pending 행 **1개만** assert).
7. `target_type='run'`(미오픈) → **422** + 행 미생성.
8. 잘못된 reason(enum 밖) → **422**. detail>500자 → **422**.
9. **레이스**: 같은 (reporter,target) 동시 5신고 → `asyncio.gather` → pending **1행만**
   (부분 유니크 TOCTOU 봉쇄, follow_requests 레이스 선례).

운영진 조회/처리 (env에 테스트 admin UUID 주입):
10. 운영진 `GET /admin/reports` → **200** + pending 목록(reporter/target brief 포함).
11. 비운영진 `GET /admin/reports` → **404 은닉**.
12. 운영진 `PATCH /admin/reports/{id} {status:'reviewed'}` → **204** + DB status·
    reviewed_at 갱신 assert. 처리 후 pending 목록에서 **빠짐** assert.
13. 비운영진 PATCH → **404**. 없는 id·이미 처리된 id PATCH → **404**.

**프라이버시 이중검증**: 신고당한 사람이 볼 수 있는 어떤 응답에도 신고 사실·
신고자 부재(신고는 운영 전용 — 일반 API 응답에 안 샘).

**회귀**: block 계열(`test_block_integration`) — 신고가 차단과 독립임 확인(신고해도
follows·blocks 무변경).

**테스트 규율**: admin API로 임시 유저 생성→정리. env ADMIN_USER_IDS는 테스트에서
임시 주입(monkeypatch/환경변수), 값 화면 출력 0. Gemini 무관(실호출 0).

## 7. 완료의 정의 (이 작업 §A 체크리스트)
1. 신규 통합 테스트 13+케이스 + block 회귀 전부 통과(실패 시 자가 수정).
2. DB 부수효과 assert: `reports` 행 생성/미생성/멱등 1행/status·reviewed_at 갱신.
3. `db/2026-07-13_reports.sql`: `[APPLY]`(테이블+부분유니크+인덱스+RLS)/`[ROLLBACK]`/
   `[확인쿼리]` 세트 — **사용자가 SQL Editor에서 실행**, 우리는 안 침.
4. `docs/API_GUIDE.md` 갱신: 신고 3종 계약 + 소비 규칙(프론트 ⋯ 메뉴·사유 시트·
   404 토스트·운영 전용 조회) 표.
5. 키 패턴 grep clean(ADMIN_USER_IDS 값 노출 0).
6. 임시 데이터 정리.
7. 스테이징: `fly secrets set ADMIN_USER_IDS=...`(내 UUID) → `fly deploy` +
   `/health` + (유저 신고→운영진 조회→처리) 스모크 1사이클.
8. 보고: 통과 목록 / 변경 파일 표 / 판단 플래그 / 실패 원인 1줄.

## 8. 잔여 판단 지점 (확답 필요 — 확신 90% 미만)
1. **성공 응답 코드**: `POST /reports` → **201**(리소스 생성, Location 없이) vs
   **204**(block·follow처럼 no-content). 프로젝트 write 관성은 대부분 **204**
   (block·kudos·follow). **추천: 204**(관성 정합, 멱등 재신고도 204로 통일). 확인 요청.
2. **detail 길이 제약 위치**: 앱(Pydantic ≤500)만 vs DB length CHECK도. **추천: 앱만**
   (다른 텍스트 필드도 앱 검증 관성 — bio·notes). DB CHECK는 과함.
3. **운영진 0명일 때**(ADMIN_USER_IDS 미설정): admin 엔드포인트가 **전부 404**가 되어
   나조차 못 봄. **추천: 의도된 안전 기본값**(secret 설정 전엔 닫힘) — 배포 시
   반드시 secret 주입. 이 동작을 수용하는지 확인.
4. **처리 상태 되돌리기**: `reviewed`→`pending` 재개방 허용? **추천: 1차 미지원**
   (pending→reviewed/dismissed 단방향). 필요 시 나중에.
