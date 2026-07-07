# 셀프 감사 잔여 백로그 (노션 이관용)

2026-07-06 전체 백엔드 감사 발견분. **L4~L8까지 전부 처리 완료(2026-07-08)** —
남은 건 DB 원자성(RPC)이 필요한 레이스 묶음뿐. 프론트 연동·베타 진행에 블로커 아님.

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

## 남은 것: 레이스 묶음 (Postgres RPC 필요 — 별도 배치)

- **H3 크루 정원 초과** — `_admit_member`의 count→check→insert 레이스. 동시 가입/승인 2건이 `max_members`를 +1~2 초과. DB에 인원수 제약 불가 → 정원 검사 포함 RPC(트랜잭션/조건부 insert)로 원자화. 보안 아닌 정책 위반이라 실질 중간.
- **M3 AI 쿼터 check→record 창** — free가 잔여 1일 때 동시 3건 → 셋 다 통과, Gemini 3회 유료. 생성 전 예약 insert로 원자 카운트.
- **M8 크루 생성 한도 레이스** — free가 `POST /crews` 2건 동시 → 크루 2개. 원자 카운트 RPC.
  → 세 건(+L8 RSVP 창) 공통 해법이 DB 원자성이라 한 배치로 묶어 처리 권장.
