# ACCOUNT_DELETION_DESIGN — 계정 삭제(회원 탈퇴) 설계

> 2026-07-08. 상태: **정책 결정 완료(A-① 완전 즉시 삭제 · B-① 크루장 막고
> 안내 · C 동승/커밋 분리), 설계 승인 대기** (구현·SQL 실행 전).
> 배경: `PRIVACY_DATA_MAP.md`에서 탈퇴 기능 부재 확인. App Store 심사 지침상
> 계정 삭제는 출시 필수 → 베타 전 탑재.

## 0. 스코프 (시안 확인 결과)

- **탈퇴 화면/버튼: 시안에 없음** — `design/profile-screen.jsx` 설정 목록은
  '로그아웃'(danger)이 마지막 항목. 탈퇴 UI는 프론트 신규 필요(로그아웃 모달
  패턴 재사용 가능, `settings-screens.jsx` 로그아웃 confirm 참조).
- **run/route 개별 삭제 버튼: 시안에 없음** ('삭제'는 크루 삭제·공지 삭제뿐)
  → **이번 범위에서 제외.** 단, 계정 삭제가 본인 run/route를 일괄 제거하므로
  개인정보 관점의 삭제권은 충족된다.

## 1. cascade 실증 결과 (2026-07-08, 라이브 DB에서 확정)

방법: SQL 직결이 없어 실증 — 임시 유저를 테이블당 1명씩 만들어 행 배치 →
`auth.users` 삭제 → 잔존 관찰 → 전량 정리. `PRIVACY_DATA_MAP.md` 7절
미확정 1번이 이것으로 해소됨.

| 테이블 | auth.users 삭제 시 | 함의 |
|---|---|---|
| profiles | **CASCADE** | 닉네임·신체정보 소멸, 닉네임 재사용 가능 |
| preferences | ⛔ **NO ACTION — 삭제 자체가 23503으로 차단** | **이 FK를 고치지 않으면 탈퇴 구현 불가.** §3 SQL |
| runs | CASCADE (→ run_tracks·run_comments·run_kudos 연쇄) | GPS 궤적, 타인이 남긴 kudos·런댓글까지 소멸 |
| routes | CASCADE (→ route_comments·likes·bookmarks·coach_scripts 연쇄) | 타인이 내 코스에 남긴 댓글·북마크도 소멸 |
| routes.copied_from | **SET NULL** (별도 실증) | **타인이 복사해 간 코스는 보존** — 출처 표시만 사라짐 |
| crews (owner_id) | **CASCADE — 크루 통째 소멸** (공지·RSVP·챌린지·멤버십 연쇄) | 크루장 탈퇴 = 크루 해산. §2-B 결정 지점 |
| crew_members | CASCADE | 멤버 목록에서 제거 |
| notifications (수신자·actor 양쪽) | CASCADE | 내가 유발한 알림이 **타인 수신함에서도 소멸** (set null 아님 — 깨진 링크 대신 소멸이라 프론트 안전) |
| route_comments / route_likes | CASCADE | 내가 타인 코스에 남긴 것 소멸 |
| follows·bookmarks·run_comments·run_kudos·RSVP·join_requests(신청자)·coach_scripts·monthly_insights·subscriptions·route_generations | CASCADE (db/ 선언 + 일부 실증) | |
| crew_announcements.author_id / crew_challenges.created_by / crew_join_requests.decided_by | SET NULL (db/ 선언) | 크루 공지·챌린지는 **작성자 익명화로 보존** |
| **Storage `avatars/{user_id}`** | **FK 없음 — 잔존** | 코드에서 명시 삭제 필요 (public URL로 접근 가능한 개인정보) |

**타인 화면 무손상 검증 관점**: 소멸 방식이 전부 "행 소멸"이라 타인 화면은
깨지지 않고 항목이 사라질 뿐. 유일한 보존물(공지·챌린지)은 author null 처리
— 프론트가 author 없음을 이미 허용하는지 구현 때 확인.

## 2. 결정 지점 (사용자 결정 필요)

### A. 완전 삭제 vs 소프트 삭제(유예)

- **① 완전 즉시 삭제 (추천)** — auth 삭제 한 방에 cascade로 전부 정리.
  구현 최소, 방침 기술 단순("삭제 시 즉시 파기"), App Store 충족.
  근거: 지인 베타 규모(오삭제 시 지인 채널로 복구 요청 올 텐데 어차피 백업
  90일이 최후 수단), 유예 관리(복구 API·크론·상태 컬럼)는 현 규모에 과설계.
- ② 소프트 삭제(30일 유예) — 오삭제 복구 가능하나 "유예 중" 상태의 노출
  처리(랭킹·크루·검색 전부 분기)가 전 코드에 퍼짐. 베타 이후 필요 시 도입.

### B. 크루장 탈퇴 처리

- **① 막고 안내 (추천)** — 소유 크루가 있으면 `409 {error:"crew_owner",
  crew_ids:[...], message:"크루를 위임하거나 삭제한 후 탈퇴할 수 있어요"}`.
  기존 위임(transfer_ownership)·크루 삭제 기능이 이미 있으므로 사용자가 선택.
  근거: cascade 해산은 **다른 멤버의 데이터**(공지·RSVP·챌린지 진행)를 본인
  동의 없이 파괴 — 지인 베타에서 최악의 경험. 자동 위임은 받는 사람 동의
  없이 소유권을 떠넘김. App Store는 "삭제 가능"을 요구할 뿐 선행 단계 안내는
  허용된다.
- ② cascade 해산 그대로(구현 0) / ③ 최고참 자동 위임(+동의 문제).
- 멤버가 본인뿐인 크루는 ①에서도 자동 삭제 허용(막을 이유 없음).

### C. Sentry request body 건 동승 여부

- **의견: 동승 추천, 커밋 분리.** `app/main.py` `sentry_sdk.init`에
  `max_request_body_size="never"` **한 줄**(+주석). 완전 독립 변경이라 리스크
  0이고, 같은 배포 사이클에 태우면 `PRIVACY_DATA_MAP.md` 미확정 2번이 함께
  해소된다. 예상 변경량: 1줄 + 문서 2곳.

### D. (참고, 결정 불요) 엔드포인트 확인 절차

재인증 없이 **본인 토큰 + 프론트 2단 confirm 모달**로 충분(App Store 요건에
재인증 없음). 서버 측 추가 안전장치로 body/쿼리의 confirm 필드는 두지 않는다
— DELETE에 body는 비표준이고, 오호출 방지는 프론트 confirm + 크루장 409가
실질적으로 담당.

## 3. 스키마 변경 — preferences FK 재작성 (탈퇴의 전제)

`db/2026-07-09_account_deletion.sql` (승인 후 사용자가 SQL Editor에서 실행):

```sql
-- 계정 삭제 전제: preferences.user_id FK가 NO ACTION이라 auth.users 삭제가
-- 차단됨(실증 23503). cascade로 재작성. 미실행 — 승인 후 적용.

-- [APPLY]
alter table public.preferences
  drop constraint if exists preferences_user_id_fkey;
alter table public.preferences
  add constraint preferences_user_id_fkey
  foreign key (user_id) references auth.users(id) on delete cascade;

-- [ROLLBACK]
-- alter table public.preferences drop constraint if exists preferences_user_id_fkey;
-- alter table public.preferences add constraint preferences_user_id_fkey
--   foreign key (user_id) references auth.users(id);
```

신규 테이블 없음 → RLS 변경 없음. RPC 불필요 — 원자성은 §5.

## 4. 엔드포인트

| method | 경로 | 요청 | 응답 | 에러 |
|---|---|---|---|---|
| DELETE | `/me` | 없음 (Bearer 토큰만) | **204** | 401 미인증 · **409** `{error:"crew_owner", crew_ids, message}`(B-① 채택 시) · **403** `{error:"demo_account", message}`(데모 계정) · 502 Supabase 실패 |

- 경로 순서: `/me`는 고정 경로 — 기존 `GET /me` 옆에 선언(패턴 경로 충돌 없음).
- **데모 계정 보호**: 시드 규칙(삭제 금지)에 따라 test1·test2·demo1~5 이메일
  목록을 서버 상수로 차단(403). 이메일은 `auth.get_user` 응답에서 확인.
- 하위 호환: 신규 엔드포인트 추가만 — 기존 동작 불변. Gemini 비용 0.

## 5. 삭제 순서·원자성

```
① 사전 검사 (읽기만): 데모 계정? → 403 / 소유 크루(멤버 2인 이상)? → 409
② 멤버 본인뿐인 소유 크루 삭제 (기존 delete_crew 경로 재사용)
③ avatars/{user_id} 스토리지 삭제 — best-effort (실패 시 로그만, 진행)
④ auth.admin.delete_user(user_id) — 이것 하나가 커밋 지점.
   public 데이터 전부가 DB cascade로 원자적으로 소멸 (§1 실증).
```

- **원자성은 ④의 단일 삭제가 보장** — 앱 레벨 다단계 트랜잭션 불필요, RPC 불필요.
- ③이 ④보다 앞인 이유: ④ 이후엔 개인정보(공개 URL 아바타)가 고아로 남는
  쪽이 계정만 남는 쪽보다 나쁨. ③ 실패 시 best-effort 원칙(CLAUDE.md)으로
  로그만 남기고 진행하되, ④ 실패 시엔 아바타만 지워진 상태 — 사용자가 재시도
  하면 되고 재업로드도 가능(치명 아님).
- ①~② 사이 레이스(검사 후 크루 생성/가입)는 실해 없음: ④의 cascade가 어떤
  상태든 정리하고, 최악은 "안내 없이 크루가 해산"인데 창이 ms급 + 본인 행동
  → 감사 기준 L급, 방어 안 함(명시).

## 6. 엣지 케이스

- **재가입**: 이메일·닉네임 모두 재사용 가능(행 소멸). 의도된 동작.
- **쿼터 리셋 악용**: route_generations cascade → 탈퇴+재가입으로 주간 AI
  쿼터(3회) 리셋 가능. 지인 베타에서 무시(악용 비용 > 이득). 출시 시 재검토.
- **subscriptions cascade**: Apple 거래 이력도 소멸 — IAP 미개통이라 현재
  무관. **실결제 개통 시 탈퇴-환불 분쟁 근거 보존을 재설계할 것**(IAP 출시
  체크리스트에 추가 필요).
- **백업 잔존**: 주간 pg_dump artifact에 최대 90일 — 방침에 기재할 사실
  (`PRIVACY_DATA_MAP.md` §6).
- **진행 중 챌린지/RSVP**: 행 소멸로 집계가 즉시 줄어듦 — 기존 탈퇴(크루
  leave) 동작과 동일 패턴, 추가 처리 없음.

## 7. 테스트 계획 — `tests/test_account_deletion_integration.py`

풀 배치 유저 A(run+GPS track, 공개 route, 크루 소속, 타인 코스에 댓글·좋아요,
아바타 업로드, 알림 유발) + 관찰자 B 구성 후:

1. **(e) 크루장 차단**: A가 2인 크루 소유 상태로 DELETE /me → 409 구조화
   assert + **DB 무변화 assert**(모든 A 데이터 잔존).
2. 크루 위임 후 DELETE /me → 204.
3. **(a) 본인 데이터 부재**: profiles·runs·run_tracks·routes·comments·likes·
   follows·notifications·preferences 전부 0건(테이블별 count assert) +
   avatars 객체 GET 404 + **A 닉네임 문자열이 B가 보는 응답 전체에 부재**
   (프라이버시 이중검증 레시피 응용).
4. **(b) 타인 화면 무손상**: B의 코스 상세(A 댓글 소멸·개수 감소), B의 복사
   코스 잔존(copied_from null), 크루 공지 목록(작성자 A → author null 렌더
   가능 형태), B 알림 목록 200 — 각각 상태코드+본문 assert.
5. **(c) 재가입**: 같은 이메일 가입 200 → 새 user_id, 옛 닉네임 등록 가능.
6. **(d) 데모 보호**: test2 토큰으로 DELETE /me → 403 `demo_account` +
   DB 무변화.
7. 1인 크루 소유자 탈퇴 → 204 + 크루 소멸.
8. 회귀: crew_manage·notifications·profile_body·follow 통합 테스트 재실행.

Gemini 실호출 0 (AI 무관 기능). 종료 시 생성 데이터 전량 삭제(B 포함).

## 8. 구현 시 함께 (승인 후)

- `docs/API_GUIDE.md`: DELETE /me 행 + 프론트 소비 규칙(409 crew_owner →
  위임/삭제 유도 모달, 403 demo_account) + §5 에러 표 갱신.
- `PRIVACY_DATA_MAP.md` §6·§7 갱신(탈퇴 절차·cascade 확정 반영). — §7
  미확정 1번은 본 설계로 이미 해소, 문서 반영은 구현 커밋에서.
- Sentry 한 줄(C 채택 시, 커밋 분리).
- 배포 + 스모크(신규 기능 1사이클) — freshrun-deploy.
