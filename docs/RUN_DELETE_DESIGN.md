# RUN_DELETE_DESIGN — 러닝 기록 삭제 (DELETE /runs/{id})

> 작성 2026-07-15. 상태: **구현 완료(배포 대기)** — §8 확정: 재삭제 404 /
> run 대상 알림 전부 삭제(run_kudoed·pb_achieved 포함) / 인사이트 캐시 동수
> 엣지 방치. 스키마 무변경.
> 배경: run 삭제 수단 없음(405). 오기록·테스트 run을 비공개 처리밖에 못 하는 갭 —
> 베타 불만 1순위 예상. Ivan 어포던스 준비 완료(본인 상세 삭제 + 파괴 컨펌).

## 0. 진단 결과 (실조회 — 설계의 토대)

| 참조 | 실구조 | 삭제 시 |
|---|---|---|
| kudos | `run_kudos.run_id` **FK on delete cascade** (db/2026-07-05) | DB 자동 소멸 |
| 댓글 | `run_comments.run_id` **FK cascade** (db/2026-07-08) | DB 자동 소멸 |
| GPS 트랙 | `run_tracks.run_id` **FK cascade** (db/2026-07-06) | DB 자동 소멸 |
| 사진 | `runs.photos`(경로 배열) + Storage `run-photos/{run_id}/…` (private) | 행은 함께 소멸, **Storage 파일은 명시 정리 필요**(선례: run_service.py:547·1514) |
| **PB(기록)** | **저장 안 함 — 라이브 계산**(`run_service._compute_records`가 매 조회 시 runs에서 산출) | **재계산 로직 불필요** — 다음 조회가 차순위 자동 승계 |
| 월간/주간 통계 | 라이브 계산 | 자동 차감 |
| 월간 인사이트 AI 캐시 | `monthly_insights` 캐시 키 = (user,year,month)+**run_count** | run_count 변화로 **자동 재생성** (동월 삭제1+추가1 동수 엣지만 stale — 무시 가능, §8) |
| 크루 세션 카운트 | `_session_participant_counts` 라이브(session_key로 매 조회 집계) | 자동 감소. 혼자였으면 남은 태그런이 없으므로 배지 자체가 안 뜸 — **별도 처리 불필요** |
| 챌린지 achieved_km | 라이브 계산(`real-time computed`) | 자동 차감 |
| **알림** | `notifications.target_id` **FK 없음**(polymorphic) | **명시 정리 필요** — 방치 시 stale(탭 404). run_kudoed·run_commented·pb_achieved 해당 |
| run_share 채팅 스냅샷 | `crew_messages.payload`에 **박제**(전송 시점 요약) — API_GUIDE 기존 계약: *"원본 삭제·비공개 전환돼도 카드 요약은 잔존(카톡 선례), 카드 탭 → 현재 권한 재평가(삭제면 404)"* | **이미 삭제를 전제한 계약** — 추가 재료 불필요. 프론트는 탭 404를 "삭제된 러닝" 처리(기존 계약 그대로) |
| 코스 연결 | `runs.route_id` 단방향 | 코스는 무영향(연결만 소멸) |

## 1. 핵심 결정 — **하드 삭제** (소프트 삭제 기각)

**이 코드베이스에서 하드 삭제의 실비용은 사실상 0이다**: 파생 3종은 FK cascade,
집계 전부(PB·통계·세션·챌린지·인사이트 캐시)는 라이브 계산이라 **재계산 코드가
아예 필요 없다.** 남는 작업은 best-effort 정리 2건(Storage 사진, stale 알림)뿐.

**소프트 삭제(deleted_at) 기각 근거**:
- 재계산 회피 효과 없음 — 집계가 라이브라 오히려 **모든 조회 표면**(피드·프로필·
  크루 피드·검색·통계·기록·kudos 게이트·track·상세 등 15+ 지점)에 `deleted 제외`
  필터를 심어야 하고, **한 곳이라도 누락하면 "지운 run이 보이는" 프라이버시 사고
  클래스**(우리 404-은닉 원칙과 최악 상성).
- "지웠는데 서버에 남아있다"는 신뢰 문제 + PRIVACY_DATA_MAP·계정삭제(즉시 파괴)
  정책과 불일치.
→ **하드 삭제 + best-effort 정리 2건**으로 확정 제안. 복구 없음(파괴 확정 —
2단 컨펌은 프론트 몫).

## 2. 계약

| 항목 | 값 |
|---|---|
| 엔드포인트 | **`DELETE /runs/{run_id}`** (기존 GET/PATCH와 같은 패턴 경로 — 순서 충돌 없음) |
| 권한 | **소유자 본인만.** 타인 run·없는 run·이미 삭제 → **404 은닉**(존재 숨김 표준) |
| 성공 | **204** |
| 재삭제(멱등성) | **404** — run은 "리소스 삭제"라 `DELETE /notifications/{id}`(없음/남의 것 404) 관례를 따름. (204 멱등은 follow/kudos 같은 "관계 해제"의 관례 — run엔 부적합) → §8 확인 1 |
| 복구 | **없음**(응답·문서에 명시) |

**프론트 소비 규칙(Ivan 컨펌 카피 정합)**: 캐스케이드 확정 = *"좋아요·댓글·**사진**이
함께 삭제돼요"* (사진 포함 권장). 크루 채팅에 공유했던 카드는 **남되 탭하면 '삭제된
러닝'(404)** — 컨펌 문구에 넣을지는 프론트 판단(서버 계약은 기존 그대로).

## 3. 삭제 흐름 (커밋 지점 최후 배치 원칙)

```
1. 소유 확인: runs에서 (id, user_id=본인) 조회 → 없으면 404 (타인/없음/기삭제 동일)
2. 정리 재료 스냅샷: photos 경로 배열 확보 (행 삭제 전에)
3. DELETE runs row  ← 커밋 지점 (kudos·댓글·track FK cascade 동시 소멸)
4. best-effort 정리 (실패해도 로그만 — CLAUDE.md 원칙):
   a. Storage: run-photos/{run_id}/* remove (선례 패턴 재사용)
   b. notifications: target_type='run' AND target_id={run_id} 삭제
      (run_kudoed·run_commented·pb_achieved — 수신자 무관 전부)
5. 204
```
- **트랜잭션 불요** — 원자성이 필요한 다단계가 아님: 3이 유일한 커밋 지점이고
  4는 실패해도 다음 상태가 무해(사진 고아는 private 버킷이라 접근 불가·재시도
  값어치 없음, stale 알림은 탭 404 — 기존 잔존물과 동급). RPC 불필요.
- **부분 실패 정합성**: 3 성공 + 4 실패 = run은 사라졌고 부스러기만 남음(로그
  경고). 3 실패 = 아무 일도 안 일어남(404/502). 중간 상태 없음.

## 4. 엣지 케이스

| 케이스 | 처리 |
|---|---|
| 동시 삭제 2발 | 1발 204, 2발 404(행 이미 없음 — DELETE where id+user 반환행 기준). 원자적, 잠금 불요 |
| 삭제와 동시 kudos/댓글 POST | 게이트가 run 재조회 → 404. 극미세 레이스(조회 통과 후 삭제)는 FK 23503이 백스톱 — 구현 시 23503을 404로 매핑(고아 생성 불가) |
| PB였던 run 삭제 | 라이브 계산이라 다음 `GET /me/records`가 차순위 자동 반영. **재계산 알림 재발송 없음**(과거 재계산이지 새 기록 아님 — 요구사항 확정) |
| 세션 태그런 삭제 | participant_count 라이브 감소. 상대가 남긴 세션은 카운트만 줄고, 혼자였으면 태그런 자체가 없어져 배지 미표시 — 빈 세션 청소 불요(session_key는 run 행 속성일 뿐 별도 테이블 없음) |
| 채팅 공유된 run | 스냅샷 잔존(기존 계약) — 회귀 테스트로 보증 |
| admin 삭제 필요 시 | **기존 admin REST로 충분**(시드 정리에서 검증된 경로 — cascade 동일). 별도 admin API 안 만듦 |

## 5. 스키마 변경
- **없음.** FK cascade 3종이 이미 있고(§0 실조회), 신규 컬럼·테이블 불요.
  `db/` SQL 페어 불필요 — "스키마 무변경" 명시.

## 6. 비요구 (발명 금지)
- 휴지통·복구·soft delete 없음. 일괄 삭제 없음(1건 단위). admin 전용 삭제 API
  없음(admin REST로 충분). 삭제 사유 수집 없음. 알림 재발송 없음.

## 7. 테스트 계획 (`tests/test_run_delete_integration.py` 신규)

1. **정상 삭제**: 본인 run(kudos 2·댓글 1·GPS트랙·사진 1장 부착) DELETE → 204 +
   **캐스케이드 전수 assert**: runs·run_kudos·run_comments·run_tracks 행 0 +
   Storage 파일 부재(list) + 관련 알림(run_kudoed 등) 0.
2. **404 은닉**: 타인 run DELETE → 404 + 행 불변. 없는 id → 404.
3. **재삭제**: 같은 id 재DELETE → 404 (§2 관례).
4. **PB 승계**: PB run 포함 2개 저장 → PB run 삭제 → `GET /me/records`가 차순위
   값으로 갱신 assert (재계산 코드 없이 라이브 확인).
5. **세션 카운트**: demo식 2인 태그런 중 1건 삭제 → 크루 피드
   `session_participant_count` 2→1 assert.
6. **통계 차감**: 삭제 전후 주간/월간 거리·횟수 감소 assert.
7. **챌린지 차감**: 태그 기간 내 run 삭제 → `achieved_km` 감소 assert.
8. **run_share 잔존 회귀**: 크루 채팅에 공유 → run 삭제 → 메시지 payload 스냅샷
   잔존 + `GET /runs/{id}` 404 (기존 계약 보증).
9. **레이스**: `asyncio.gather` 동시 DELETE 2발 → 정확히 [204, 404] + 행 0.
10. **회귀**: run 목록/피드/상세·kudos·comments·gps_track·session_l1·stats 기존
    테스트 전종(삭제 기능 추가로 기존 경로 불변 확인).

## 8. 잔여 판단 지점 (확답 필요)

1. **재삭제 404 확정**: §2 근거(리소스 삭제 관례 = notifications 선례)로 404 추천
   — 프론트는 404를 "이미 삭제됨"으로 무해 처리(연타 대비). 수용?
2. **알림 정리 범위**: run을 target으로 한 알림 전부(수신자 무관 — 타인이 받은
   run_kudoed 포함) 삭제 추천. 대안(방치)은 stale 404 탭 잔존. 수용?
3. **pb_achieved 알림도 삭제됨**(target=run이라 §3-4b에 포함) — "기록 경신 이력
   알림"이 사라지는 셈인데, 원본 run이 없는 알림은 무의미하므로 삭제가 정합.
   수용?
4. (메모) monthly_insights 동수 엣지(같은 달 삭제1+추가1 → run_count 동일 →
   AI 캐시 stale): 실질 무해(AI 문구만 미세 낡음) — 처리 안 함 명시.

## 9. 완료의 정의 (§A)
1. 신규 10케이스 + 회귀 전종 통과.
2. DB 부수효과 assert(§7-1 캐스케이드 전수·정리 2건).
3. SQL 없음(스키마 무변경) 명시.
4. API_GUIDE: run 절에 DELETE 계약 + 소비 규칙(컨펌 카피 재료 — 캐스케이드 목록,
   채팅 카드 잔존, 복구 없음) 추가.
5. 키 grep clean · 임시 데이터 정리 · 커밋+푸시 → (지시 시) 배포+스모크
   (생성→kudos→삭제→캐스케이드 확인 1사이클).
