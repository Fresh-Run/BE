# PRIVATE_PROFILE_DESIGN — 비공개 프로필 + 팔로우 승인제 + 차단 (설계)

> 2026-07-12. 상태: **v1·v1.5 배포됨** (프로필 visibility+잠금+게이트 / 피드 설정 강제). v2·v3 대기. 결정 완료(§8 A~E). 가시성 체계 전면
> 영향 — 4사이클 분할(§7). 승인 후 사이클별 SQL → 구현.
>
> **확정 결정**: A=크루 내에선 profile 잠금 무시(가입=노출 동의) · B=검색은
> owner 비공개면 route 공개라도 제외 · C=채팅 내 차단 필터는 v3.5 분리 ·
> D=auto_publish OFF는 미지정 run을 private 저장(명시 visibility 존중) ·
> E=v1→v1.5→v2→v3(+v3.5).

## 0. 핵심 개념 정리 (혼동 방지)

세 개의 **독립 축**이 합성된다. 지금까지는 ①만 있었다:
- ① **run visibility** (기존, run별): public/followers/private — 개별 러닝 노출.
- ② **profile visibility** (신규, 계정별): public/followers/private — 계정 자체
  잠금. "비공개 계정"의 축.
- ③ **관계 게이트** (신규 축): 승인제 팔로우(pending) + 차단(blocks).

**설계 원칙**: run visibility는 그대로 두고, profile visibility·차단을
`_can_see_run`과 프로필/피드/검색 게이트에 **AND 합성**한다(더 제한적인 쪽 승).

## 1. Profile visibility 모델 — 별개 축, run과 AND 합성

- `profiles.visibility text default 'public' check in (public,followers,private)`.
  기존 백필: 전원 public(현행 동작 보존).
- **run visibility와의 합성 규칙**: `볼 수 있다 = profile_gate(viewer, owner) AND
  run_visibility_gate(...)`. 즉 **비공개 계정의 public run도 비팔로워에겐 안
  보인다**(계정 잠금이 상위). 이게 "🔒 잠금 화면"의 실체 — 프로필 게이트에서
  먼저 걸림.

### 조합 매트릭스 (viewer = 비팔로워·비크루원·비차단 기준)

| profile\run | run=public | run=followers | run=private |
|---|---|---|---|
| **profile=public** | ✅ 보임 (현행) | ❌(팔로워 아님) | ❌ |
| **profile=followers** | ❌ 계정 잠금 | ❌ | ❌ |
| **profile=private** | ❌ 계정 잠금 | ❌ | ❌ |

- 팔로워 viewer: profile 게이트 통과 → run 축만 적용(기존 그대로).
- **크루 공존 예외 유지**: `_can_see_run`의 "같은 크루원=followers 허용"은
  run 축에만. **profile=followers/private 계정의 크루 피드 노출은?** → 결정
  지점 §8-A(크루는 명시적 상호 공간이라 크루 피드 내에선 프로필 잠금 무시
  추천 — 크루 가입 자체가 노출 동의).

### 게이트 영향 전수 (실코드 스윕)

| 지점 | 현재 | 변경 |
|---|---|---|
| `_can_see_run`(track·상세·kudos·run댓글 4곳 재사용) | run visibility만 | **profile_gate AND 선행** — 시그니처에 owner profile visibility 추가 or 내부 조회 |
| `get_public_profile` | 항상 반환 | profile 게이트 실패 시 **잠금 응답**(§아래) |
| `list_user_runs`(공개 프로필 탭) | run visibility 필터 | profile 잠금이면 빈 목록 or 잠금 |
| 활동 피드·크루 피드 | 팔로우·크루 기반 | profile private가 피드에 흘러드는지 재검토(팔로워 피드는 팔로워라 통과, 크루 피드는 §8-A) |
| 검색(`search_public_routes`·nearby) | is_public route | route owner가 비공개 계정이면 검색 제외(§8-B) |
| route 좋아요/댓글·kudos | run/route visibility | profile 게이트 합성 |

- **`_can_see_run` 시그니처 변경 규모**: 현재 `(owner_id, caller_id,
  visibility)`. profile visibility·차단을 매번 조회하면 N+1. **권장**:
  `_can_see_user(owner_id, caller_id)` 게이트 신설(profile visibility + 차단 +
  팔로우 + 크루를 한 번에 판정, 캐시 가능) → `_can_see_run`이 이걸 선행 호출.
  목록 경로는 **배치판**(`_visible_owners(caller, [owner_ids])`) 필요 —
  briefs·thumb처럼 IN 1쿼리. 규모: 중(게이트 1개 신설 + 배치판 + 6개 호출처
  합성).

### 잠금 응답 (🔒 화면)

`get_public_profile`이 게이트 실패 시 **최소 필드만**: `{user_id, nickname,
avatar_url, visibility:"private", is_following, follow_requested, locked:true}`
— 닉네임·아바타는 잠금 화면 표시용(공개 정보), run_count·bio·follower 수는
미포함. 존재 자체는 은닉 안 함(팔로우 요청하려면 프로필이 보여야 함) — 차단은
다름(§3, 404).

## 2. 팔로우 승인제 — crew join_requests 패턴 재사용

- `profiles.follow_approval boolean default false`. ON이면 팔로우가 즉시가 아닌
  요청.
- **테이블 재사용 불가·신규**: crew_join_requests는 (crew_id,user_id)라 팔로우
  (follower→following)엔 안 맞음. **동형 신규 테이블**:
  ```sql
  create table follow_requests (
    requester_id uuid references auth.users(id) on delete cascade,
    target_id    uuid references auth.users(id) on delete cascade,
    status       text default 'pending' check in (pending,approved,rejected),
    created_at timestamptz default now(),
    primary key (requester_id, target_id)   -- 재요청은 status 갱신
  );
  create unique index follow_req_one_pending on follow_requests
    (requester_id, target_id) where status='pending';  -- pending 중복 봉쇄(TOCTOU)
  ```
  crew 패턴의 **부분 유니크 인덱스로 pending 중복 차단** 그대로 — 앱 트랜잭션
  없이 동시 요청 봉쇄(감사 레이스 원칙).
- **흐름**: `POST /users/{id}/follow` — target이 follow_approval OFF면 현행
  즉시 200. ON이면 **202 + follow_requests pending 삽입**(승인 대기).
  `PATCH /follow-requests/{requester_id}` (target이 승인/거절 — decide_join
  패턴: 승인 시 follows 삽입 + pending→approved, **UPDATE 반환행 있을 때만**
  알림/삽입해 이중 승인 방지, 감사 L8).
- **기존 팔로워 소급 없음**: follow_approval을 켜도 이미 follows에 있는 관계는
  불변(요청은 신규 팔로우에만). 확인 완료 — follows·follow_requests 분리.
- **알림 type**: `follow_requested`·`follow_request_approved` 2종 추가 필요 →
  `notifications_type_check` drop→재생성(현재 10종). **백로그의 crew_invited·
  채팅 푸시와 묶어 제약 재작성 1회**로 처리(함정 항목 — 여러 type을 한 번에).

## 3. 차단 (blocks)

```sql
create table blocks (
  blocker_id uuid references auth.users(id) on delete cascade,
  blocked_id uuid references auth.users(id) on delete cascade,
  created_at timestamptz default now(),
  primary key (blocker_id, blocked_id),
  constraint blocks_no_self check (blocker_id <> blocked_id)
);
```

- **상호 노출 차단 범위** (A가 B를 차단 시, 양방향):
  - 프로필: 서로 `get_public_profile` **404 은닉**(존재 자체 숨김 — 잠금과
    다름). run·track·상세·목록·검색 전부 404/제외.
  - 좋아요·댓글·kudos: 서로의 콘텐츠에 불가(게이트에서 차단 우선).
  - **크루 공존**: 같은 크루에 둘 다 있어도 서로의 run 카드·채팅 메시지가
    **상대에게만 숨겨짐**(크루 자체는 유지 — 강퇴는 크루장 권한, 차단이
    멤버십을 못 건드림). §8-C 결정: 채팅에서 차단 상대 메시지 숨김은 v3
    범위인지(합성 비용) — **추천: v3는 프로필·피드·소셜만, 채팅 내 차단
    필터는 v3.5**(채팅 목록에 차단 합성은 별도 비용).
- **기존 팔로우 자동 해제**: 차단 시 **양방향 follows·follow_requests 삭제**
  (A↔B 4행 정리). 재팔로우는 차단 해제 후에만.
- **차단은 404 은닉**: 차단당한 쪽은 "차단됨"을 모른다(프로필 404 = "없는
  유저"처럼). 차단 목록은 blocker 본인만 조회.

## 4. 피드 설정 강제

- `profiles.settings.feed`(기존 settings jsonb 화이트리스트 확장 — 신규 컬럼
  불요): `{auto_publish, allow_likes, allow_comments}`.
- **auto_publish 의미 해석**(시안): "자동 게시 OFF" = run 저장 시 **기본
  visibility를 followers로**(피드 노출 안 함)가 아니라, **명시 안 하면 private
  저장**으로 해석 추천 — "게시"의 반대는 "비공개". 단 기존 기본이 public이라
  breaking → **auto_publish OFF면 POST /runs의 visibility 미지정 시 기본을
  private**로(명시 visibility는 존중). 결정 §8-D.
- **allow_likes/comments OFF 게이트 지점**:
  - 좋아요: `POST /routes/{id}/like`·`/runs/{id}/kudos` — owner 설정 OFF면
    403(`likes_disabled`). 게이트 2곳.
  - 댓글: `POST /routes/{id}/comments`·`/runs/{id}/comments` — owner 설정 OFF면
    403(`comments_disabled`). 게이트 2곳.
  - 기존 좋아요·댓글은 소급 삭제 안 함(설정은 신규 행위만 차단).

## 5. 프라이버시 (PRIVACY_DATA_MAP)

- **신규 수집**: `blocks`(차단 목록 — 유저가 명시 생성) + `follow_requests`
  (팔로우 요청 이력). 방침 수집 항목·제3자 무관·탈퇴 처리 추가.
- **탈퇴 시**: blocks·follow_requests 전부 **cascade 삭제**(양방향 FK — 내가
  차단한 것·나를 차단한 것 모두). profile visibility·follow_approval은 profiles
  cascade에 포함(기존).

## 6. 게이트 합성 요약 (구현 시 단일 소스)

```
can_see_user(viewer, owner):
  if viewer == owner: return True
  if blocked(viewer, owner) or blocked(owner, viewer): return False   # 차단 최우선
  if owner.profile_visibility == 'public': return True
  if owner.profile_visibility == 'followers': return follows(viewer, owner)
  if owner.profile_visibility == 'private': return follows(viewer, owner)
  # (followers/private 차이는 "요청 노출" UX만 — 게이트 동일)

can_see_run(viewer, owner, run_vis):
  return can_see_user(viewer, owner) AND run_visibility_gate(viewer, owner, run_vis)
```

- 크루 피드·채팅은 §8-A/§8-C 결정에 따라 can_see_user를 우회(멤버십이 상위)
  할지 명시.

## 7. 사이클 분할 (견적)

- **v1 — 프로필 visibility + 잠금 화면 (~1.5일)**: profiles.visibility 컬럼 +
  `can_see_user`(차단·승인 제외한 profile 축만) + get_public_profile 잠금 응답 +
  `_can_see_run` 합성(6 호출처) + 배치판. 테스트: 조합 매트릭스 3×3 전수 +
  피드·검색 합성.
- **v2 — 팔로우 승인제 (~1일)**: follow_approval + follow_requests(부분 유니크)
  + 202/승인/거절 흐름 + 알림 2type(제약 재작성 묶음). 테스트: 승인제 pending
  중복 봉쇄(gather 동시)·승인 후 follows·기존 팔로워 무영향·거절 재요청.
- **v3 — 차단 (~1.5일)**: blocks + can_see_user에 차단 최우선 합성(전 게이트
  404 은닉) + 팔로우 자동 해제 + 차단 관리 API. 테스트: 양방향 차단 매트릭스·
  팔로우 해제·404 은닉·크루 공존.
- **v1.5 — 피드 설정 (~0.5일, v1과 v2 사이 삽입 가능)**: settings.feed +
  좋아요/댓글 4게이트 + auto_publish 기본 visibility. 독립적이라 순서 유연.
- **총 ~4.5일 / 4사이클.** v1이 게이트 리팩터(can_see_user 신설)를 지므로 가장
  무겁고, v2·v3는 그 위에 축 추가. **v1 먼저 배포·검증 후 진행 강력 권장**
  (가시성 전면 리팩터라 회귀 표면적 큼).

## 8. 결정 지점 (승인 시 확인)

- **A. 크루 피드 내 profile 잠금**: 크루 가입=노출 동의로 보고 크루 피드·랭킹
  에선 profile visibility 무시(추천) vs 엄격 적용.
- **B. 검색에서 비공개 계정 route**: is_public route라도 owner 비공개면 검색
  제외(추천) vs route 공개면 노출.
- **C. 채팅 내 차단 필터**: v3는 소셜·프로필만, 채팅 메시지 차단 숨김은 v3.5로
  분리(추천) vs v3에 포함.
- **D. auto_publish OFF 시맨틱**: 미지정 run을 private 저장(추천) vs
  followers vs 피드제외 플래그 신설.
- **E. 사이클 순서**: v1→v1.5→v2→v3(추천) vs 다른 절단선.
