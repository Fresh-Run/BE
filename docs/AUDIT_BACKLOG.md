# 셀프 감사 잔여 백로그 (노션 이관용)

2026-07-06 전체 백엔드 감사 발견분. **🎉 전량 처리 완료(2026-07-08)** — H·M·L
소품 + 레이스 묶음(RPC) 모두 소진. 잔여는 μs급 RSVP 마감 창 하나(선택) +
운영 관측 1건(stale HTTP/2 502, 트리거 대기 — 맨 아래).

## 처리 완료

- 배치1: H1 거리/페이스 sanity, H2 챌린지 생성자 삭제 차단, M1 가짜 프라이버시 테스트, M2 datetime tz 필수
- 배치2: M5 max_length, M6 limit 클램프, M9 int 상한, M7 /places 인증
- 배치3: M4 route 학습 소유권, M10 삭제 시 알림 정리, L1 kudos 가시성, L2 iap 크기 상한, L3 502 detail 고정
- **배치4 (L4~L8, 2026-07-08)**:
  - **L4** preview-by-code — **POST(body, 권장) 추가 + GET(레거시) 유지** 병행 경로. POST는 코드가 URL/access log에 안 남음. 프론트 이관용으로 API_GUIDE에 권장 표시.
  - **L5** transfer_ownership — roles 먼저 → owner_id 플립을 커밋 지점으로 재배열 + **실패 시 보상 복구**(원상 복원, best-effort). RPC 없이 창 최소화·자가 치유.
  - **L6** RSVP 집계 — `_tallies`에 crew_members 교집합 필터 → 탈퇴자 표 제외.
  - **L7** `_week_start_utc` — crew_service가 run_service 정의를 import(단일 소스, 드리프트 제거).
  - **L8** FeedbackRequest.tags dedupe+상한(≤20), distance_km `ge=0.01`(1e-308→0.00 방지), decide_join_request **UPDATE 반환행 있을 때만 알림**(동시 승인 이중발송 방지).
  - 미처리 1건: **RSVP 마감 판정 창**(read→check→upsert 사이의 μs 시간 경쟁) — 앱 레벨 체크는 이미 최선이나 완전 차단은 DB 레벨 필요 → 아래 레이스 묶음과 성격 동일, 함께 처리 시점에 검토.

- **배치5 (레이스 묶음 H3·M3·M8, 2026-07-08)** — 설계 `docs/RACE_FIX_DESIGN.md` 대로 Postgres RPC 3종으로 원자화(`db/2026-07-08_race_fix_rpcs.sql`). 에러 계약 불변(패자는 기존 409/403/429):
  - **H3 정원** — `admit_crew_member`(crews 행 `FOR UPDATE` per-crew 직렬화). `_admit_member`가 RPC 호출로 전환.
  - **M8 크루한도** — `create_crew_limited`(owner advisory lock + count, jsonb로 컬럼 자동 매핑). `create_crew` 핸들러가 tier→limit 계산 후 1 RPC.
  - **M3 AI쿼터** — `reserve_ai_generation`(user advisory lock, Gemini 전에 슬롯 예약) + `release_ai_generation`(실패 시 회수, '실패는 무료' 보존). 옛 check/record 게이트 제거.
  - 검증: 실동시(asyncio.gather) 불변식 — 정원 초과 0(동시 5→admit 1·409 4), free 소유 1(동시 2→성공 1·403 1), 주간 count==limit(동시 3→성공 1·429 2). M3는 Gemini mock 불필요(예약이 호출 전 단계).

- **배치6 (감사 2차, 2026-07-11)**: M-A 커서 '+' 미인코딩 관용(tz 위치 공백 복원 + 가이드 인코딩 명시), M-B push_tokens 유저당 10대 상한(등록 시 정리 + 발송 시 최근 10대 — Expo 100개 한도 방어), L-1 탈퇴 시 run-photos 고아 파일 정리(slot×ext 9조합 무조건 remove), L-4 admin self-kick 문구 중립화, L-5 photos 중복 경로 422. H 0건 — 신규 기능 × 가시성 게이트 우회 미발견.

## 잔여 (선택 — μs급, 저위험)

- **L8 RSVP 마감 창** — `rsvp` 제출의 read→`_rsvp_open`(시간)→upsert 사이 μs wall-clock 경쟁. count 레이스가 아니라 **시간 경계**라 advisory/FOR UPDATE로 안 닫힘 — DB측 `now()` 조건부 upsert RPC가 필요(별도 기법). 마감 순간 정확히 투표하는 극단 엣지라 실질 무해, 필요 시점에 `rsvp_if_open` RPC로 처리 가능.

- **RLS 드리프트 소급 (2026-07-12, H — 채팅 설계 중 발견·즉시 처리)**: 초기
  커밋 테이블 10종이 RLS 미enable → anon key + 유저 JWT로 타인 데이터 직접
  조회 가능(profiles 신체정보·notifications 포함). 앱은 service_role 경유라
  실피해 없었으나 anon key는 공개값. 전수 실증(24개 중 노출 10 확정, 빈
  테이블 preferences는 임시 행으로 확인) → `db/2026-07-12_rls_backfill.sql`로
  일괄 enable(정책 없이 — 앱 무영향, 회귀 5종 통과) → `scripts/verify_rls.py`
  노출 0 검증. 신규 테이블 RLS 표준이 초기분에 소급 안 됐던 게 원인.

## 운영 관측 (감사 외 — 배포 후 발견, 트리거 대기)

- **stale HTTP/2 연결 재사용 → 간헐적 502** (2026-07-08 진단 → **2026-07-11
  카드 ① 적용, 관측 중**)
  - **발동**: 트리거(주 3회+) 충족 — 7/8 crews/mine 3건 동시 + 7/10 로컬 재현
    + 7/10 /me/stats Sentry + 7/11 회귀 중 2건 (4회).
  - **적용**: supabase 서브클라이언트 4종에 HTTP/1.1 httpx 클라이언트 주입
    (`SyncClientOptions.httpx_client`, `app/core/supabase_client.py`).
    keepalive 단축안은 기본 5s에서도 재발한 실증으로 기각. 주입·h2 비활성은
    결정론 검증(전 서브클라이언트 세션 속성) + 병렬 회귀 5종으로 확인.
  - **판정**: Sentry에서 `httpx.ReadError` 패턴 **2주(~7/25) 무재발이면 종결**,
    재발 시 카드 ②(전송층 에러 한정 1회 재시도) 발동.
  - **발생**: 2026-07-08, `/api/crews/mine` 외 홈 화면 병렬 호출 3건 동시 502 (Sentry 이벤트로 관측 — 연동 당일 실 에러 첫 포착).
  - **원인** (fly logs 트레이스백으로 규명): supabase-py의 동기 httpx 클라이언트가 유휴 keepalive **HTTP/2** 연결을 재사용 → 상대편(Supabase LB)이 idle timeout으로 이미 끊은 연결이라 read 실패(`httpcore _read_exception` 재사용 경로). HTTP/2 다중화 때문에 병렬 요청 여러 개가 죽은 연결 1개에 함께 올라타 **동시 실패**.
  - **심각도: 낮음~중간** — 자가 회복(클라이언트 재시도 1초 내 성공), 데이터 정합성·보안 영향 0. 단 "유휴 후 첫 요청" 패턴이라 베타 테스터의 띄엄띄엄 사용에서 재발 가능.
  - **대응 카드 (지금은 실행 안 함)**:
    - ① supabase 클라이언트 http2 비활성 또는 keepalive expiry 단축 — HTTP/1.1이면 요청 1개만 실패.
    - ② `_bad_gateway` 경로에 전송층 에러 한정 1회 재시도.
  - **발동 트리거**: Sentry에서 이 패턴 주 3회+ 관측 또는 베타 테스터 불만 → 카드 ① 우선 검토.
  - **참고**: 정확한 예외 클래스는 로그 버퍼 소실로 미확정(`httpx.ReadError` 추정) — Sentry 이벤트 상세의 chained exception에서 확인 가능.

- **Gemini spend cap 초과 → 코스 생성·코치 신규 전 유저 502** (2026-07-09, 해소됨)
  - **발생**: AI Studio 프로젝트 월간 spend cap 초과 → `POST /routes/generate` 연속 502 `route_generation_failed` (~수 시간, 프론트 리포트로 인지). 크레딧 소진과 **동일한 429 RESOURCE_EXHAUSTED**라 잔액이 있어도 발생 — CLAUDE.md 함정 항목 보강함.
  - **규명**: fly logs 링버퍼 소실 전 원본 예외 확보 + Sentry 체인(RateLimitError)으로 즉시 판정. 최소 body 실호출 재현 → cap 상향 후 스모크 200 확인.
  - **조치**: 코드 수정 없음(429→502 변환·'실패는 무료' 쿼터 보존 전부 설계대로 동작). **cap을 ₩5,000으로 현실화**(결제 액션). 재발 시 확인처: https://ai.studio/spend
  - ~~출시 전 검토: Sentry `include_local_variables=False`~~ → **해소**
    (2026-07-11 적용 — App Privacy "충돌 데이터 신원 미연결" 정합. before_send
    가로채기 대조 검증: True에서 지역변수·이메일 값 노출, False에서 전부 부재).

## 기능 백로그 (트리거 대기)

- **코스 생성 에러 구분 — 쿼터 소진 vs 산포 전패** (2026-07-21 등록, 검토만). 현재 생성 실패는 전부 502 `route_generation_failed`("조건에 맞는 코스를 못 찾았어요 — 조건을 바꿔보라"). **산포 전패엔 정확하나, 외부 API(T-map/Gemini) 쿼터 소진 시엔 거짓 안내**(조건 바꿔도 소용없음). 진단(2026-07-21): 사용자 502 2건은 T-map·Gemini 직접 1콜 200 정상 → **산포 502 확정**(쿼터 아님). 하지만 무료 T-map 815/1000 도달 이력상 소진 상황이 실제로 임박. **제안**: T-map 429/Gemini 429(RESOURCE_EXHAUSTED)를 잡아 `route_generation_unavailable` + "잠시 후 다시 시도해주세요"로 구분(HTTP 503). **트리거: 오너 결정 or 쿼터 소진 재발 시 승격.** 알려진 함정(Gemini 429→502 변환)과 연계.

- ~~**인앱 개인 초대**~~ — **처리됨(2026-07-13)**: `POST /crews/{id}/invitations {user_id}`(크루원 발송, 비크루원·차단 404·이미 멤버 409). `crew_invited` 알림 payload에 초대코드 → 수신자 preview→join 재사용. 푸시 템플릿+crewJoin 카테고리(M-11 정합). SQL 0(선등록 type). 초대코드 생성 단일 소스화(`_issue_invite_code`).
- **알림 중복 억제 (감사 2차 L-2)** — 팔로우/kudos 토글 반복이 알림+푸시를 매번 재발송(기존 인앱 축의 푸시 증폭). 최근 N시간 내 동일 (actor, recipient, type) 억제안. **트리거: 베타 중 테스터 불만 시 승격.**
- **Expo 배치 발송 최적화 (감사 2차 L-6)** — 공지·챌린지 완료 시 크루원 N명 = 푸시 태스크 N개·Expo N요청. 100/요청 배치로 묶기. 트리거: 크루 규모 성장 시.
- **UV '현재값' 소스 교체 검토** — 현 `/2.5/uvi`는 '오늘 최고(solar-noon)' 시맨틱(2026-07-12 계약 relabel로 대응). **트리거: 베타 중 '현재 UV' 요구 피드백 시** ⓑ 재검토 — One Call 3.0(유료 구독) 또는 Open-Meteo(신규 처리위탁 — PRIVACY_DATA_MAP 갱신 동반).
- **러닝 공유 카드 (프론트 주도)** — 시안 외 신규 확정(2026-07-09, 결정: 지연 — 유저 공유 = 0원 마케팅 채널, 스트라바 Share Activity 참고). RN 뷰 캡처 방식, **백엔드 갭 0**(`GET /runs/{id}/track` 폴리라인 + 러닝 스탯으로 충족). 웹 랜딩(링크 공유용)은 베타 범위 밖. **트리거: 프론트 착수.**
- ~~**PB 축하 푸시 (`notif.pb` 게이트 연결)**~~ — **처리됨(2026-07-13)**: `create_run`의 `new_records[]` 비지 않으면 본인에게 `pb_achieved` 인앱+푸시(self-only 알림, allow_self=True). 신규 type CHECK 재작성(db/2026-07-13_notif_pb_achieved.sql)+`_TEMPLATES`/`_CATEGORY`(pb)+기록 종류별 문구. (`runReminder`·`weekly`는 스케줄러 필요라 여전히 별도.)
