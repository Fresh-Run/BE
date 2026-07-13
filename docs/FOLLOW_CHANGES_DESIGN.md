# FOLLOW_CHANGES_DESIGN — 팔로우 2종 변경 설계

> 작성 2026-07-13. 상태: **Part A 구현·배포 완료** · **Part B 구현 완료(배포 대기)**.
> 스키마 변경 없음(A·B 모두). Part B는 컬럼 유예 — follow_approval drop은 build #1.
> 전제(진단 완료, 실조회): `follows`(상태 없는 확정 엣지) / `follow_requests`
> (`status` pending·approved·rejected) / `profiles.visibility`
> (`text default 'public' check in (public,followers,private)`) /
> `profiles.follow_approval`(`boolean not null default false`, visibility와 **독립 축**) /
> 현재 분기 `follow_service._needs_approval()`는 **`follow_approval`만** 조회 /
> `ProfileUpdate`는 `extra="forbid"` / 알림 관성 = unfollow·block **무알림**.
>
> 두 변경은 **독립 배포·독립 롤백 가능**. Part A는 스키마 변경 없음(순수 additive),
> Part B는 컬럼 유예(즉시 스키마 변경 없음). 함께/따로 낼지는 승인 시 결정.

---

## Part A — Remove Follower (내 팔로워 목록에서 상대 떼기)

### A.1 요구 / 비요구 (스코프 경계)

**요구**
- 내가 특정 유저(`target`)를 **"나를 팔로우하는 관계"에서 제거**한다.
- 방향: `follows`에서 **(follower_id=target, following_id=me)** 엣지 1건 삭제.
- 무알림(unfollow·block 선례).
- 멱등(이미 내 팔로워가 아니면 부수효과 0으로 204).

**비요구 (발명 금지)**
- 재팔로우 차단 안 함 — 관계만 끊는다. **차단(block)과 명확히 구분**(block은
  재팔로우·노출까지 봉쇄). remove follower 당한 상대는 나를 **다시 팔로우 가능**
  (내가 통합 후 비공개면 그 재팔로우는 요청제로 들어감 — Part B와 자연 결합).
- 상대에게 알림·표시 없음(인스타 remove follower 동형 — 조용히 언팔당함).
- 대량/일괄 제거 없음(1건 단위).
- 내 팔로잉(내가 남을 팔로우) 방향은 건드리지 않음.

### A.2 기존 unfollow와의 방향 대비 (혼동 방지 — 설계 핵심)

| 동작 | 삭제하는 엣지 | 주체 | 기존/신규 |
|---|---|---|---|
| **unfollow** (내가 남 팔로우 취소) | (follower=**me**, following=target) | 내가 나감 | 기존 `DELETE /users/{id}/follow` |
| **remove follower** (내 팔로워 떼기) | (follower=**target**, following=**me**) | 내가 상대를 밀어냄 | **신규(Part A)** |

→ 두 엔드포인트는 `follows`의 **정반대 방향 행**을 지운다. 구현 시
`follower_id`/`following_id` 자리 바뀜이 유일한 사고 포인트 → 테스트에서 방향
불변식 assert.

### A.3 엔드포인트 계약

| method | 경로 | 요청 | 응답 | 상태코드 |
|---|---|---|---|---|
| **DELETE** | **`/me/followers/{user_id}`** | (없음) | (없음) | 204 |

**네이밍 근거**: 기존 `/me/blocks`·`/me/follow-requests` 컨벤션(내 소유
컬렉션은 `/me/…`)과 정합. `GET /users/{me}/followers`(팔로워 조회)와 대칭적으로
"내 팔로워 컬렉션에서 {user_id} 항목 제거"를 표현. **대안** `DELETE
/users/{user_id}/follower`(기존 `/users/{id}/follow` 톤)도 가능하나, "내 팔로워
목록"이라는 소유 의미가 `/me/…`에 더 잘 드러나 1순위 추천.

**상태코드 규약(§5 준수)**
| 상황 | 코드 | 근거 |
|---|---|---|
| 정상 제거 성공 | 204 | 삭제 완료 |
| 이미 내 팔로워 아님(정상 대상) | **204** | **멱등** — unfollow·block 관성(부수효과 0) |
| 자기 자신(`user_id`=me) | 400 | self 불가(follow의 self 400과 대칭) |
| 없는 user_id | 404 | 존재 은닉 표준 |
| 차단 관계(양방향 어느 쪽이든) | **404** | 차단은 존재 은닉 최우선(§블록 통일 계약) |

### A.4 스키마 변경
- **없음.** `follows` 테이블·인덱스 그대로. DELETE 1행만.

### A.5 하위호환
- 순수 additive(신규 경로 1개). 기존 엔드포인트 동작 불변. 응답 스키마 무변경.

### A.6 알림
- **무알림.** notification 미생성(unfollow·block과 동일). best-effort 아님 —
  애초에 발송 로직을 붙이지 않는다.

### A.7 엣지 케이스
- **레이스**: 같은 (target,me) 엣지에 동시 remove 2회 → DELETE는 멱등, 둘 다
  204(둘째는 0행 삭제). 원자성 불필요(단일 DELETE).
- **경로 순서**: `/me/followers/{user_id}`(DELETE)는 기존 `GET
  /users/{id}/followers`와 경로 접두가 다르므로 충돌 없음. `/me/…` 고정 경로군에
  추가 — 패턴 경로보다 앞 선언 규칙 유지.
- **가시성**: remove 후 상대 관점 — 자기 팔로잉 목록에서 나는 사라지지 않되(자기
  기준 following=me 행 삭제됨) `is_following:false`로 보임. 재팔로우 진입점 정상.

---

## Part B — 승인제 통합 (follow_approval 제거 → visibility='private'이면 요청제)

### B.1 요구 / 비요구 (스코프 경계)

**요구**
- `_needs_approval()` 분기를 **`follow_approval` 조회 → `visibility='private'`
  조회**로 교체. 비공개 계정이면 신규 팔로우가 무조건 요청(pending).
- `follow_approval` 컬럼은 **즉시 drop 안 함** — deprecate 유예(아래 B.4).
- `ProfileUpdate.follow_approval`은 **계속 받되 no-op**(저장 안 함) — `extra=
  "forbid"`라 필드를 지우면 기존 프론트 PATCH가 422로 깨지므로.

**비요구 (발명 금지)**
- `follow_approval=True & public` 유저(예: 한강질주)를 **private으로 백필하지
  않는다** — 본인 동의 없이 비공개화 금지. 통합 후 이들은 **즉시팔로우로 전환**
  (승인제 상실은 의도된 결과).
- `follow_requests` 테이블·요청/승인/거절 플로우 자체는 **불변**(진입 조건만 교체).
- 새 알림 type 추가 없음(기존 `follow_requested`·`follow_request_approved` 유지).

### B.2 정책 확정 — 분기 교체

**현재 (follow_service.py:311 `_needs_approval`)**
```python
res = ...select("follow_approval").eq("user_id", target_id)...
if not (res.data and res.data[0].get("follow_approval")):
    return False
return not await _follows(follower_id, target_id)
```
**통합 후 (설계)**
```python
res = ...select("visibility").eq("user_id", target_id)...
vis = (res.data[0]["visibility"] if res.data else "public")
if vis != "private":                       # ⚠️ B.8 판단 지점: followers 처리
    return False                           # public·followers → 즉시 팔로우
return not await _follows(follower_id, target_id)  # private + 신규 → 요청
```
- "이미 팔로워면 즉시"(소급 무영향) 규칙은 **그대로 유지**(`_follows` 재확인).
- **선행 게이트 불변**: 차단 체크(follow_service.py:63) → 승인 분기 순서 유지.
  차단 상대는 여전히 404 은닉이 앞섬.

### B.3 통합으로 실제 동작이 바뀌는 유저 (실조회 근거)

교차표(profiles 18건 실조회) — `follow_approval` × `visibility` 정렬 안 됨:

| follow_approval | visibility | 명수 | 현재 | 통합 후 |
|---|---|---|---|---|
| False | public | 14 | 즉시 | 즉시 (불변) |
| False | private | 2 (테스트1·뚝섬바람) | 즉시 | **요청제** |
| True | public | 1 (한강질주) | 요청제 | **즉시(승인제 상실)** |
| True | private | 1 | 요청제 | 요청제 (불변) |

→ **백필 안 함이 정책.** 위 3명의 동작 변화는 통합의 의도된 귀결. 데모 계정이라
프로덕션 영향 없음(시드는 B.7에서 정리).

### B.4 하위호환 · Deprecate 유예 전략 (핵심)

**컬럼 drop·필드 완전 제거는 build #1(첫 IAP 빌드 / 키 재발급·정리)로 파킹.**
그 전까지 유예 규칙:

| 대상 | 유예 기간 동작 | 근거 |
|---|---|---|
| **DB `profiles.follow_approval` 컬럼** | **유지**(drop 안 함) | 롤백 여지·기존 값 보존. 분기가 안 읽으므로 무해 |
| **`ProfileUpdate.follow_approval`** (요청) | **필드 유지 + no-op**(받되 저장 안 함) | `extra="forbid"` — 지우면 기존 프론트 422. 조용히 무시 |
| **`ProfileResponse.follow_approval`** (응답) | **항상 `false` 고정 반환**(컬럼값 무시) — *권고안* | 승인제 개념 소멸. 설정 UI가 살아있어도 "꺼짐"으로 보여 프론트가 토글 제거를 유도. no-op 저장과 정합 |

> **응답 필드 권고 상세**: 실제 컬럼값(한강질주 True 등)을 계속 내보내면 설정
> 화면 토글은 ON인데 동작은 visibility 기반 → **UI-동작 불일치**로 혼란.
> 그래서 유예 기간엔 `follow_approval`을 **응답에서 상수 false**로 고정하는 것을
> 추천(필드 자체 제거는 프론트가 그 값을 참조 중이면 깨질 수 있어 build #1로 미룸).

**유예 종료 조건 (build #1에서 일괄)**
1. 프론트가 `follow_approval`을 더 이상 **PATCH로 보내지 않음** 확인(앱 배포·구
   빌드 소진).
2. 프론트가 응답의 `follow_approval`을 더 이상 **읽지 않음** 확인.
3. → 그 시점에 `ProfileUpdate`/`ProfileResponse`에서 필드 제거 + `ALTER TABLE
   profiles DROP COLUMN follow_approval`([APPLY]/[ROLLBACK] 페어, freshrun-sql).

### B.5 스키마 변경 (이번 스프린트)
- **없음.** 컬럼 유예이므로 즉시 DDL 0건. 분기가 `visibility`를 읽는 것뿐(기존
  컬럼). build #1에서 drop SQL 페어를 별도 발행.

### B.6 기존 pending follow_requests 처리
- 실조회: 현재 pending 1건 존재. 통합은 **진입 조건만** 바꾸고 `follow_requests`
  테이블·승인/거절 경로는 불변 → 기존 pending은 **그대로 승인/거절 가능**.
- 통합 후 `follow_approval=True & public`이던 계정(한강질주)에 남은 pending도
  사후 처리 경로(PATCH `/me/follow-requests/{id}`)가 불변이므로 정상 처리됨.
  새 요청만 안 생기고, 기존 요청은 유효 — 데이터 정합 OK. **소급 정리 불필요.**

### B.7 시드 정리
- `seed_demo_data.py:793` demo2 `{"follow_approval": true}` → **`{"visibility":
  "private"}`** 로 교체(통합 후 요청제를 데모에서 재현). 멱등·삭제 금지 원칙 유지.
- `DEMO_ACCOUNTS.md` 문구 갱신(demo2 승인제 → demo2 비공개).

### B.8 판단 필요 지점 (확신 90% 미만 — 플래그)
**`visibility='followers'` 계정의 팔로우 진입을 요청제로 볼 것인가?**
- 사용자 지시는 "`visibility='private'`이면 요청제" — 문자 그대로면 `followers`는
  **즉시 팔로우**(위 B.2 코드 = `vis != "private"`).
- 그러나 `followers`는 "콘텐츠를 팔로워에게만" 공개 상태 → 아무나 즉시 팔로워가
  되면 그 게이트가 사실상 뚫림(팔로우 한 번으로 followers 콘텐츠 접근).
- **추천**: 1차 통합은 지시대로 **private만 요청제**(followers·public 즉시)로
  단순하게. followers까지 요청제로 묶을지는 별도 결정. → **승인 시 확인 요청.**

### B.9 알림
- **불변.** `follow_requested`(요청 생성)·`follow_request_approved`(승인) 그대로.
  거절 무알림도 유지. type 목록·CHECK 제약 변경 없음.

---

## 공통 — 테스트 계획 (완료의 정의 §A 풀세트)

### 신규 통합 테스트

**`tests/test_remove_follower_integration.py` (Part A)**
1. B가 A를 팔로우 → A가 `DELETE /me/followers/{B}` → **204** + `follows`에서
   (follower=B, following=A) 행 **삭제 assert**, 역방향(A→B 있었다면) **불변 assert**.
2. 방향 불변식: A가 remove 후에도 A→B 팔로우(있었으면) 유지 — **자리 바뀜 회귀 방어**.
3. 멱등: 팔로워 아닌 상대 remove → 204 + `follows` 행 수 불변(0 삭제).
4. self(`DELETE /me/followers/{me}`) → 400.
5. 없는 user_id → 404.
6. 차단 관계(A↔B block) → **404 은닉** + 행 미변경.
7. **무알림 검증**: remove 후 상대의 `notifications`에 관련 행 **부재 assert**.
8. 재팔로우 가능: remove 후 B가 다시 A 팔로우 시도 → A가 public이면 204 즉시,
   A가 private(Part B 결합)이면 202 요청제.

**`tests/test_follow_approval_unify_integration.py` (Part B)** — matrix
1. target `visibility=private` + 신규 → `POST /users/{id}/follow` **202** +
   `follow_requests` pending 생성 assert.
2. target `visibility=public` + 신규 → **204** 즉시 + `follows` 생성 assert.
3. target `visibility=followers` + 신규 → **204**(B.8 추천안 기준 — 확정 시 조정).
4. target `visibility=private` + **이미 팔로워** → 204(소급 무영향, pending 미생성).
5. `follow_approval=True`인데 `visibility=public` → **즉시 204**(승인제 상실 확인).
6. **no-op 검증**: `PATCH /me/profile {follow_approval:true}` → 200 + DB
   `follow_approval` **변경 안 됨 assert** + 응답 `follow_approval` **false 고정 assert**.
7. 승인/거절 경로 불변: pending → `PATCH /me/follow-requests/{id} {approve:true}`
   → follows 생성 + `follow_request_approved` 알림(기존 회귀).
8. 프라이버시 이중검증: private 계정 팔로우 요청 흐름에서 응답 전체에 내부 상태
   문자열 부재.

### 재작성 필요한 기존 테스트 (회귀)
| 파일 | 현재 | 통합 후 |
|---|---|---|
| `test_follow_approval_integration.py` | follow_approval=true로 요청제 | **visibility='private'로 요청제** 재작성 |
| `test_profile_partial_patch_integration.py:99` | follow_approval 단독 PATCH 저장 | **no-op(저장 안 됨·응답 false)** 검증으로 변경 |
| `test_audit3_batch2_integration.py:103` | follow_approval 오타 키 → 422 | follow_approval은 이제 **유효(no-op) 필드** → 오타 테스트를 **다른 필드로 교체** |
| `test_block_write_gate_integration.py:120` | 승인제 계정 팔로우 404 | **visibility='private' 계정** 팔로우 404로 변경 |

### 회귀 재실행 목록(무변경 확인)
`test_private_profile_integration.py`(profile_gate·visibility 잠금),
`test_follow_*`(팔로워/팔로잉 목록·차단 자동해제), block 계열.

### 테스트 규율
- 임시 유저 admin API 생성 → 종료 시 전부 삭제. Gemini 무관(실호출 0).
- 권한 차단 **404** 기대(403 아님). 레이스는 A.7·B는 pending 부분 유니크
  인덱스가 이미 방어(진단 확인) — 필요 시 `asyncio.gather`로 동시 요청 + 정원(중복
  pending 0) 불변식.

---

## 완료의 정의 (이 작업의 §A 체크리스트)
1. 신규 2파일 + 재작성 4파일 + 회귀 전부 통과(실패 시 자가 수정 후 재실행).
2. DB 부수효과 assert: `follows` 삭제/불변, `follow_requests` pending 생성,
   `follow_approval` no-op 불변.
3. `db/`: Part A **SQL 없음**(명시). Part B **이번 스프린트 SQL 없음**(컬럼 유예),
   build #1용 DROP 페어는 유예 종료 시 별도 발행 — 문서에 예약 기재.
4. `docs/API_GUIDE.md` 갱신: §4 팔로우 표에 remove follower 행 추가 + 승인제
   행(§189)을 "visibility='private'이면 요청제"로 재작성 + `follow_approval`
   deprecate 유예 소비 규칙 명시(프론트: 토글 제거 유도).
5. 커밋 전 키 패턴 grep clean.
6. 임시 데이터 정리, 키·값 화면 출력 0.
7. 스테이징: 팔로우 플로우 전반 영향 → `fly deploy` + `/health` + (private
   계정 팔로우 요청 → 승인 / remove follower) 스모크 1사이클.
8. 보고: 통과 목록 / 변경 파일 표 / 판단 플래그 / 실패 원인 1줄.

---

## 승인 전 확답 필요 (2건)
1. **Part B.8** — `visibility='followers'` 계정은 즉시 팔로우(추천) vs 요청제?
2. **배포 단위** — Part A·B를 한 커밋/배포로 묶을지, 분리할지(둘 다 독립 가능).
