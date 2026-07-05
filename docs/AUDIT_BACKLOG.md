# 셀프 감사 잔여 백로그 (노션 이관용)

2026-07-06 전체 백엔드 감사에서 발견 후 배치 1~3에서 처리하지 않은 항목.
심각도 낮음(L) + 레이스 묶음(RPC 필요). 프론트 연동·베타 진행에 블로커 아님.

## 레이스 묶음 (Postgres RPC 필요 — 별도 배치)

- **H3 크루 정원 초과** — `_admit_member`의 count→check→insert 레이스. 동시 가입/승인 2건이 `max_members`를 +1~2 초과. DB에 인원수 제약 불가 → 정원 검사 포함 RPC(트랜잭션/조건부 insert)로 원자화. 보안 아닌 정책 위반이라 실질 중간.
- **M3 AI 쿼터 check→record 창** — free가 잔여 1일 때 동시 3건 → 셋 다 통과, Gemini 3회 유료. 생성 전 예약 insert로 원자 카운트.
- **M8 크루 생성 한도 레이스** — free가 `POST /crews` 2건 동시 → 크루 2개. 원자 카운트 RPC.
  → 세 건 공통 해법이 RPC라 한 배치로 묶어 처리 권장.

## 낮음 (L4~L8, 개별)

- **L4 초대 코드 access log 노출** — `GET /crews/preview-by-code?code=`의 코드가 uvicorn access log(INFO)에 평문. 수정: preview를 POST body로 받거나 배포 시 access log 쿼리 마스킹.
- **L5 transfer_ownership 비원자** — crews.owner_id→role→demote 다단계 UPDATE, 중간 실패 시 불일치. 드묾. 수정: 단일 RPC (코드 주석도 동일 제안).
- **L6 RSVP 집계 탈퇴자 포함** — `_cleanup_member_rsvps` best-effort 실패 시 `_tallies`가 현재 멤버 필터 없이 전 행 카운트. 수정: crew_members 교집합 필터.
- **L7 `_week_start_utc` 중복 구현** — crew_service vs run_service 동일 로직 2벌, 드리프트 시 랭킹/통계 주 경계 어긋남. 수정: crew_service가 run_service 것 import.
- **L8 자잘한 입력** — FeedbackRequest.tags 무제한 배열(dedupe+상한), distance_km=1e-308→0.00(ge=0.01), 이중 승인 알림(decide_join_request UPDATE 반환행 있을 때만 발송), RSVP 마감 판정 창(미세).

## 처리 완료 (배치 1~3, 참고)

- 배치1: H1 거리/페이스 sanity, H2 챌린지 생성자 삭제 차단, M1 가짜 프라이버시 테스트, M2 datetime tz 필수
- 배치2: M5 max_length, M6 limit 클램프, M9 int 상한, M7 /places 인증
- 배치3: M4 route 학습 소유권, M10 삭제 시 알림 정리, L1 kudos 가시성, L2 iap 크기 상한, L3 502 detail 고정
