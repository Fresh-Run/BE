# CREW_CHAT_DESIGN — 크루 채팅 (설계)

> 2026-07-12. 상태: **설계 승인 대기.** 이번 달 최대 신규 도메인 —
> 전송 모델(§1)이 나머지 전부를 규정. 승인 후 SQL → 구현(사이클 분할 §7).

## 1. 전송 모델 — **폴링 채택** (Realtime 기각, 실검증 근거)

### 실검증 결과 (라이브)

- **폴링 비용**: count형 요청 스테이징 p50 **287ms**. 30초 주기 × 베타 동시
  ~10명 = **0.33 req/s** — 워커 1·인메모리 캐시 환경에서 무해.
- **Realtime의 전제 붕괴**: Supabase Realtime `postgres_changes`는 **클라이언트
  anon key + 유저 JWT로 직접 구독**하며, RLS 정책으로만 필터된다. 우리 표준은
  "신규 테이블 RLS enable + **정책 없이** deny 백스톱"(앱은 service_role로만
  접근). 이 표준을 채팅 테이블에 그대로 적용하면 **정책이 없어 클라이언트가
  아무것도 구독 못 한다**(실증: push_tokens·run_tracks는 anon+JWT select가
  0 rows). Realtime을 쓰려면 "크루 멤버만 그 방 메시지" RLS 정책을 SQL로 짜야
  하는데, 이는 (a) 앱 레벨 멤버십 게이트(`ensure_member`)를 SQL로 **중복 구현**
  (b) "인증 외 전부 백엔드 경유" 원칙 **위반** (c) 정책 드리프트 시 조용한
  누출 — 3중으로 우리 아키텍처와 충돌.

### 결론

**폴링.** `GET /crews/{id}/chat/messages`(역순 커서, §5) + `GET .../chat/unread`
(안 읽은 수, 배지용)를 **활성 화면에서 20~30초 주기**로. 기존 모든 데이터
경로(service_role + app 게이트)와 동일 — 신규 인프라 0. "즉시성"은 채팅
활성 시 주기 단축(예: 화면 포커스 10초, 백그라운드 중지)으로 프론트가 조절.
기획 원안의 "30초~1분 타협"과 정합.

> ⚠️ **부수 발견(별도 보안 사안, §끝 플래그)**: 초기 테이블(runs·crews·
> notifications·crew_members)은 RLS가 **미enable**이라 anon key로 직접 읽힌다.
> 채팅 설계와 무관하게 처리 필요 — Realtime을 안 쓰는 이번 결정이 이 노출을
> 넓히지 않는다는 점만 여기 기록.

## 2. 스키마

```sql
-- [APPLY] (승인 후 확정)
create table if not exists public.crew_messages (
  id         uuid primary key default gen_random_uuid(),
  crew_id    uuid not null references public.crews(id) on delete cascade,
  sender_id  uuid references auth.users(id) on delete set null,  -- 탈퇴 시 익명화(공지 패턴)
  type       text not null default 'text'
             check (type in ('text', 'system', 'run_share')),
  content    text,                 -- text: 본문 / system: 렌더 키 / run_share: 캡션(nullable)
  payload    jsonb,                -- run_share 스냅샷·system 파라미터
  created_at timestamptz not null default now()
);
create index if not exists crew_messages_room_idx
  on public.crew_messages (crew_id, created_at desc);   -- 역순 커서 페치
alter table public.crew_messages enable row level security;  -- 표준(정책 없이 백스톱)

create table if not exists public.crew_message_reactions (
  message_id uuid not null references public.crew_messages(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  emoji      text not null check (emoji in ('👍','🔥','👏','💪')),  -- 4종 고정
  created_at timestamptz not null default now(),
  primary key (message_id, user_id, emoji)   -- 유저당 이모지당 1회(멱등 토글)
);

-- 안읽은수: 마지막 읽은 시점 저장 방식 (카운터 대비 §아래)
create table if not exists public.crew_read_state (
  crew_id      uuid not null references public.crews(id) on delete cascade,
  user_id      uuid not null references auth.users(id) on delete cascade,
  last_read_at timestamptz not null default now(),
  muted        boolean not null default false,   -- 방별 채팅 푸시 mute (§mute)
  primary key (crew_id, user_id)
);
alter table public.crew_message_reactions enable row level security;
alter table public.crew_read_state enable row level security;

-- [ROLLBACK]
-- drop table if exists public.crew_message_reactions;
-- drop table if exists public.crew_read_state;
-- drop table if exists public.crew_messages;
```

### 안 읽은 수: **마지막 읽은 시점(last_read_at) 저장 채택**

| | last_read_at (채택) | 카운터 컬럼 |
|---|---|---|
| 계산 | `count(created_at > last_read_at)` — 1쿼리 | 증감 트리거 필요 |
| 동기화 리스크 | **없음**(파생값 — 진실은 메시지 테이블) | 메시지 삭제·다기기·경쟁 시 카운터 드리프트 |
| 다기기 | last_read_at 최댓값 자연 수렴 | 기기별 카운터 충돌 |

카운터는 "빠른 읽기" 이점이 있지만 채팅 규모(크루당 수백)에서 count가 인덱스
(`crew_id, created_at desc`)로 즉시 — 드리프트 리스크를 질 이유 없음.

### 방별 mute: **crew_read_state.muted 플래그 채택** (settings 동적 키 기각)

- read_state가 이미 (crew_id, user_id) PK라 mute의 자연스러운 집. 크루 탈퇴 시
  cascade로 함께 소멸(settings jsonb에 crew_id 키를 쌓으면 탈퇴한 크루 잔재가
  남아 청소 필요). 발송 훅에서 read_state 1행 조회로 판정 — settings 화이트리스트
  확장·탈퇴 청소 불요. 전역 알림 설정과 독립(요구 충족).

## 3. 시스템 메시지 — 신규 훅 (create_notification과 별개 단일 소스)

- 실확인: 공지 생성은 `announcement_service.create_announcement`가 유일 진입
  (`_notify_members` 알림 훅 보유), RSVP 마감은 시간 파생(`_rsvp_open`)이라
  **이벤트 지점이 없다**(cron 없음 — 조회 시 계산). 따라서:
  - **공지 생성 → 시스템 메시지 삽입**: create_announcement 끝에 훅 1줄
    (`chat_service.post_system(crew_id, "announcement", {announcement_id})`).
    create_notification과 나란한 위치, best-effort(실패해도 공지 성공).
  - **RSVP 마감**: 이벤트 지점이 없어 v1 제외 — "마감됐어요" 시스템 메시지는
    별도 트리거(크론/첫 조회 시 1회)가 필요. v1.5에서 공지의 rsvp_closes_at
    도달을 첫 채팅 조회 시 lazy 삽입하는 방식 검토(멱등 키 필요). **v1은 공지
    생성 유입만**.
- system 메시지 `content`는 렌더 키(예: `"announcement"`), `payload`에 파라미터
  (announcement_id) — 프론트가 키로 문구 조립(다국어·문구 변경이 서버 배포
  불요). 딥링크는 payload로 공지 이동.

## 4. 기록 카드 공유 (run_share)

- `POST /crews/{id}/chat/messages {type:"run_share", run_id, caption?}`.
- **가시성 게이트 재사용 + 스냅샷 박제**: 전송 시 `_can_see_run(run_owner,
  sender, visibility)` 통과 필수(아니면 403) — **단 크루 채팅은 크루원 전용
  공간이므로, followers-only 런은 "sender가 볼 수 있으면" 공유 허용**(sender가
  이미 그 런을 볼 권한이 있고, 크루원 = followers 게이트의 허용 대상과
  실질 동일 집단). private 런은 본인만 → 본인이 자기 런 공유는 허용.
- **payload에 스냅샷 박제**(원본 링크 아님): `{run_id, distance_km, duration_sec,
  area, ran_at, polyline_thumb}` — **원본 삭제/비공개 전환 후에도 채팅 카드는
  전송 시점 스냅샷으로 남는다**(공유 = 그 시점 게시 행위, 소급 철회 안 함 —
  카톡에 사진 보낸 뒤 원본 지워도 대화엔 남는 것과 동형). run_id는 "상세로
  이동" 링크용이나 **탭 시 `GET /runs/{id}`가 현재 가시성으로 재평가**(삭제됨
  404·비공개 전환 404) → 카드 요약은 보이되 상세 진입은 현재 권한 따름.
  프라이버시와 UX의 균형점.

## 5. API · 페이지네이션 · 삭제 · 탈퇴

| method | 경로 | 비고 |
|---|---|---|
| GET | `/crews/{id}/chat/messages?before?&limit` | **역순 커서**(created_at desc, 기존 `before` 커서 패턴 재사용 — ISO+tz). 크루원만(ensure_member, 404 은닉) |
| GET | `/crews/{id}/chat/unread` | `{unread_count}` 배지용 (last_read_at 파생) |
| POST | `/crews/{id}/chat/messages` | text/run_share. 크루원만. content ≤2000, 반응 아님 |
| POST | `/crews/{id}/chat/read` | last_read_at = now() (화면 진입·이탈 시) |
| POST/DELETE | `/crews/{id}/chat/messages/{mid}/react {emoji}` | 4종 검증, 멱등 토글(PK) |
| DELETE | `/crews/{id}/chat/messages/{mid}` | **본인 메시지 or 운영진**(ensure_manager 재사용 — admin role v1 게이트). soft: content→null·type 유지("삭제된 메시지"). system은 삭제 불가 |
| PATCH | `/crews/{id}/chat/mute {muted}` | read_state.muted 토글 |

- **탈퇴/강퇴**: sender_id `on delete set null` — 메시지 본문은 보존, 작성자
  익명화(공지 author 패턴과 동일). reactions·read_state는 cascade 소멸.
- 삭제는 soft(내용만 제거) — 반응·스레드 맥락 유지. 운영진 삭제는 감사 로그
  없이 즉시(베타 규모).

## 6. 프라이버시 (PRIVACY_DATA_MAP 영향)

- **신규 수집 항목: 채팅 내용**(자유 텍스트) — §3 활동 데이터에 `crew_messages`
  행 추가 필요. **개인정보처리방침 1항(수집 항목) 갱신 대상**으로 표기.
- 노출: 크루원 전용(ensure_member 게이트). run_share 스냅샷은 위치 파생
  (polyline_thumb·area) 포함 — 크루원에게만.
- 탈퇴 시: 본인이 쓴 메시지는 **익명화 보존**(set null) — cascade 삭제가 아님을
  방침에 명시(다른 크루원의 대화 맥락 보존 vs 완전 삭제의 트레이드오프 —
  공지·챌린지 익명화 선례와 일관). reactions·read_state·mute는 cascade 삭제.
- PRIVACY_DATA_MAP §3·§6 갱신 항목으로 등재(구현 시).

## 7. 규모 추정 · 사이클 분할

- 스키마 3테이블 + API 8개 + 서비스 신설(chat_service) + 폴링 클라이언트 계약.
- **v1 (코어, ~1.5일)**: crew_messages(text)·reactions·read_state + 메시지
  목록(역순 커서)·전송·읽음·안읽은수·반응 토글·mute + 삭제(본인/운영진). 테스트:
  멤버십 게이트(404)·역순 커서·반응 멱등·안읽은수 파생·mute·삭제 권한 매트릭스.
- **v1.5 (~0.5일)**: 시스템 메시지(공지 생성 유입 훅) + run_share(스냅샷 박제·
  가시성 게이트·삭제/비공개 후 상세 404). 테스트: 시스템 유입·공유 권한·
  원본 삭제 후 카드 잔존+상세 404.
- **v2 (백로그)**: RSVP 마감 시스템 메시지(트리거 필요), 채팅 푸시 발송(§mute
  연동 — create_notification 훅 확장이 아니라 chat 전용 발송, 알림 type 추가 시
  crew_invited 제약 재작성 묶음과 함께).
- **푸시 연동 주의**: 요구의 "방별 mute"는 read_state.muted로 저장하되, **실제
  채팅 푸시 발송 자체가 v2**(신규 알림 type 필요). v1은 mute 필드만 두고
  발송은 인앱 배지 폴링으로 — mute는 v2 발송이 붙을 때 게이트로 활성.

## 8. 결정 지점 (승인 시 확인)

1. **run_share 원본 삭제 정책**: 스냅샷 박제 + 상세 404(추천) vs 카드도 소급
   제거. → 추천안으로 진행할지.
2. **v1 범위**: 위 v1/v1.5 분할대로 2사이클 vs 한 번에. → 신규 도메인이라
   v1 먼저 배포·검증 후 v1.5 권장.
