# 셀프 감사 잔여 백로그 (노션 이관용)

2026-07-06 전체 백엔드 감사 발견분. **🎉 전량 처리 완료(2026-07-08)** — H·M·L
소품 + 레이스 묶음(RPC) 모두 소진. 잔여는 μs급 RSVP 마감 창 하나(선택).

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
