# PUSH_NOTIFICATION_DESIGN — 원격 푸시 (Expo Push Service 경유)

> 2026-07-11. 상태: **설계 승인 대기.** 인앱 알림(10종·딥링크 표)은 완성 —
> 이번 작업은 생성 시점에 발송 훅만 얹는다. 신규 알림 type·Live Activity·
> 로컬 알림은 범위 밖.

## 1. 기기 토큰 스키마

```sql
-- [APPLY] (승인 후 확정)
create table if not exists public.push_tokens (
  token      text primary key,   -- Expo push token — 전역 유니크·기기 귀속이라 PK
  user_id    uuid not null references auth.users(id) on delete cascade,
  platform   text not null check (platform in ('ios', 'android')),
  updated_at timestamptz not null default now()
);
create index if not exists push_tokens_user_idx on public.push_tokens (user_id);
alter table public.push_tokens enable row level security;  -- 표준: 정책 없이 백스톱

-- [ROLLBACK]
-- drop table if exists public.push_tokens;
```

- **PK=token 설계 의도**: 같은 토큰 재등록은 upsert로 멱등이고, **같은 기기에
  다른 계정이 로그인하면 user_id가 자동 이전**(전 주인에게 오발송 차단).
  유저당 여러 행 = 여러 기기(폰 교체·재설치 자연 수용).
- 탈퇴: FK cascade로 자동 소멸(신규 테이블이라 선언부터 확정).
- 엔드포인트:
  - `POST /me/push-token` body `{token, platform}` → **204, upsert 멱등**.
    token 형식 검증(`ExponentPushToken[…]` 프리픽스, ≤200자) — 쓰레기 저장 방지.
  - `DELETE /me/push-token` body `{token}` → 204 멱등, **본인 소유 행만**
    (남의 토큰 삭제 불가 — user_id 스코프). 로그아웃 시 호출.
- 자동 정리: Expo 응답 `DeviceNotRegistered` 수신 시 해당 토큰 행 삭제(§3).

## 2. 발송 훅 — 단일 지점, best-effort, 요청 비차단

- **생성 함수 단일 소스 실확인**: `notification_service.create_notification`
  1곳 — 호출처 10곳(follow·crew·route·run·announcement 서비스) 전부 이 함수
  경유. **훅은 이 함수 끝 1곳**, 분산 수정 없음. (self-skip으로 생성이
  스킵되면 푸시도 자연 스킵.)
- **비차단**: insert 성공 후 `asyncio.create_task(_send_push(...))` —
  fire-and-forget 백그라운드 태스크. 요청 경로는 Expo 왕복(수백 ms)을
  기다리지 않음(워커 1 환경에서 특히 중요). 태스크 전체가 try/except로
  감싸여 **어떤 실패도 로그만**(알림 생성·본 요청에 502 전파 금지 — 기존
  best-effort 원칙). 트레이드오프: 서버 재시작 시 미발송 태스크 유실 —
  푸시는 유실 허용(인앱 알림은 이미 저장됨), 큐/크론은 베타 규모에 과설계.
- 발송 태스크 내부: 수신자 토큰 IN 조회 → 없으면 종료 → 메시지 조립(§4) →
  Expo 1요청(기기 N개 ≤100 한도 내) → 티켓 검사 → DeviceNotRegistered 정리.

## 3. Expo Push API 계약 (실문서 확인 — docs.expo.dev)

- 배치: **요청당 최대 100 메시지**(우리는 알림 1건 × 수신자 기기 수라 여유).
- **티켓**(발송 즉시 응답) / **영수증**(티켓 id로 15분 후 조회, 24h 보관).
  **v1은 티켓 레벨만 처리** — 티켓의 `DeviceNotRegistered`는 즉시 토큰 삭제.
  영수증 폴링(15분 후 재조회)은 저장·스케줄 인프라가 필요해 **v1 제외** —
  영수증에서만 오는 DeviceNotRegistered도 다음 발송의 티켓에서 잡히므로
  자연 수렴. v2 항목으로 기록.
- 에러: `MessageTooBig`(4KiB — §4 페이로드는 수백 B라 무관),
  `MessageRateExceeded`(백오프 — v1은 재시도 없이 드랍+로그, 베타 트래픽상
  비발생 예상), `InvalidCredentials`류(로그).
- 인증: **기본 액세스 토큰 불필요** — v1 미사용. EAS 푸시 보안을 켜는 시점에
  `EXPO_ACCESS_TOKEN` fly secret 추가(코드는 있으면 헤더 첨부).
- 엔드포인트 URL은 `EXPO_PUSH_URL` 설정으로 주입(기본 exp.host) — 테스트
  mock 서버 치환용.

## 4. 페이로드

- **인앱 문구는 프론트 조립**(서버는 type+actor_nickname만 제공)임을 확인 →
  푸시 제목/본문은 **서버 템플릿 신설**. 발송 태스크 안에서 actor 닉네임
  1조회 + **수신자 `settings.lang` 반영(ko/en 템플릿)** — AI 생성물이 lang을
  따르는 기존 정책과 일관(조회 1회 추가는 태스크 내부라 무비용).
- 문구 초안 (ko — en은 대칭, 제목은 앱명 고정 "FreshRun"):

| type | 본문 |
|---|---|
| route_liked / route_commented | "{닉네임}님이 회원님의 코스를 좋아해요 / 코스에 댓글을 남겼어요" |
| run_kudoed / run_commented | "{닉네임}님이 회원님의 러닝을 응원해요 / 러닝에 댓글을 남겼어요" |
| user_followed | "{닉네임}님이 회원님을 팔로우해요" |
| crew_joined | "{닉네임}님이 크루에 가입했어요" |
| join_requested / join_approved | "{닉네임}님이 크루 가입을 신청했어요" / "크루 가입이 승인됐어요" |
| crew_announcement | "크루에 새 공지가 올라왔어요" |
| challenge_completed | "크루 챌린지를 달성했어요! 🎉" |

- **프라이버시 원칙(잠금화면 노출 전제): 본문에는 공개 정보인 닉네임 +
  행위 유형만.** 러닝 제목·댓글 내용·코스명·크루명은 **미포함** — 비공개
  러닝 제목/비공개 크루명이 잠금화면에 새는 축을 원천 차단(콘텐츠 미리보기는
  가시성 검토 후 v2).
- `data`: `{type, target_id, target_type, payload}` — **기존 딥링크 라우팅
  표를 그대로 동봉**, 프론트는 알림 탭과 푸시 탭이 같은 라우터를 재사용.
  4KiB 한도 대비 수백 B.

## 5. 설정 연동 — v1: 전체 발송 (추천)

실확인: `UserSettings`에 알림 계열 없음 + 시안 설정의 '알림 센터'는 목록
이동일 뿐 **per-type 토글 화면이 시안에 없음**. → v1은 전체 발송, 끄기는
OS 알림 권한(표준 UX). per-type 토글은 시안이 생기면
`settings.notifications` 그룹 additive 추가(화이트리스트 구조라 저비용) —
발송 태스크의 lang 조회와 같은 지점에서 체크하면 됨. (대안인 "서버 토글
선반영"은 UI 없는 설정이 됨 — 기각.)

## 6. 프론트 계약 초안 (API_GUIDE 갱신안)

1. 로그인 후: `expo-notifications` 권한 요청 → `getExpoPushTokenAsync()` →
   `POST /me/push-token {token, platform}` (앱 시작마다 호출해도 멱등).
   토큰 갱신 리스너에서도 재호출.
2. 로그아웃 시: `DELETE /me/push-token {token}` (실패해도 로그아웃 진행 —
   서버가 DeviceNotRegistered로 자연 정리).
3. 푸시 탭: `data`의 `type/target_id/target_type/payload`로 **알림 딥링크
   라우팅 표 재사용**(인앱 탭 핸들러 공유).
4. 포그라운드 수신 처리·배지는 프론트 몫(범위 밖).

## 7. 테스트 계획

- 토큰 등록: 같은 토큰 2회 → 1행(멱등) / **같은 토큰 다른 유저 재로그인 →
  user_id 이전·1행** / 형식 밖 422 / 삭제 멱등 + 남의 토큰 삭제 불가.
- **발송 훅 비차단**: `EXPO_PUSH_URL`을 로컬 mock으로 — mock이 500/타임아웃/
  DeviceNotRegistered여도 **알림 유발 요청(예: 팔로우)은 항상 정상 응답 +
  인앱 알림 행 존재**. DeviceNotRegistered 티켓 → 토큰 행 삭제 assert.
- 페이로드: mock 수신 body 검사 — to/title/body(닉네임 포함·콘텐츠 제목
  부재)/data(라우팅 표 필드) + lang=en 수신자 영어 문구.
- 탈퇴: push_tokens cascade 소멸(기존 탈퇴 테스트 확장).
- **실발송 스모크 1회**: 실 Expo API에 유효 형식 토큰으로 발송 → 티켓 응답
  수신 확인(실기기 없어도 API 왕복·티켓 체계 검증). 실기기 수신 확인은
  프론트 연동 시 사용자 확인 항목.
- Gemini 0. 회귀: 알림 유발 경로(follow·kudos·comments·announcements) 통합
  테스트 재실행 — 훅이 기존 응답을 안 바꾸는 것.
