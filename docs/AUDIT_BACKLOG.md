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

## 잔여 (선택 — μs급, 저위험)

- **L8 RSVP 마감 창** — `rsvp` 제출의 read→`_rsvp_open`(시간)→upsert 사이 μs wall-clock 경쟁. count 레이스가 아니라 **시간 경계**라 advisory/FOR UPDATE로 안 닫힘 — DB측 `now()` 조건부 upsert RPC가 필요(별도 기법). 마감 순간 정확히 투표하는 극단 엣지라 실질 무해, 필요 시점에 `rsvp_if_open` RPC로 처리 가능.

## 운영 관측 (감사 외 — 배포 후 발견, 트리거 대기)

- **stale HTTP/2 연결 재사용 → 간헐적 502** (2026-07-08 진단, 코드 수정 없음)
  - **발생**: 2026-07-08, `/api/crews/mine` 외 홈 화면 병렬 호출 3건 동시 502 (Sentry 이벤트로 관측 — 연동 당일 실 에러 첫 포착).
  - **원인** (fly logs 트레이스백으로 규명): supabase-py의 동기 httpx 클라이언트가 유휴 keepalive **HTTP/2** 연결을 재사용 → 상대편(Supabase LB)이 idle timeout으로 이미 끊은 연결이라 read 실패(`httpcore _read_exception` 재사용 경로). HTTP/2 다중화 때문에 병렬 요청 여러 개가 죽은 연결 1개에 함께 올라타 **동시 실패**.
  - **심각도: 낮음~중간** — 자가 회복(클라이언트 재시도 1초 내 성공), 데이터 정합성·보안 영향 0. 단 "유휴 후 첫 요청" 패턴이라 베타 테스터의 띄엄띄엄 사용에서 재발 가능.
  - **대응 카드 (지금은 실행 안 함)**:
    - ① supabase 클라이언트 http2 비활성 또는 keepalive expiry 단축 — HTTP/1.1이면 요청 1개만 실패.
    - ② `_bad_gateway` 경로에 전송층 에러 한정 1회 재시도.
  - **발동 트리거**: Sentry에서 이 패턴 주 3회+ 관측 또는 베타 테스터 불만 → 카드 ① 우선 검토.
  - **참고**: 정확한 예외 클래스는 로그 버퍼 소실로 미확정(`httpx.ReadError` 추정) — Sentry 이벤트 상세의 chained exception에서 확인 가능.
