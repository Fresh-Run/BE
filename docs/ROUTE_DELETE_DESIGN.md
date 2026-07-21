# ROUTE_DELETE_DESIGN — 코스 삭제 (DELETE /routes/{id})

> 작성 2026-07-21. 상태: **구현 완료(배포 대기)**. run-delete(DELETE /runs)의 단순
> 동생 — 계약 관성 그대로(소유자만·404 은닉·204·재삭제 404·하드 삭제·복구 없음).
> Ivan 클라 어포던스(스와이프/⋯ 삭제 + 파괴 컨펌) 대기.

## 0. 캐스케이드 실사 (실증 — 임시 route 생성물로, 기존 데이터 무접촉)

`pg_constraint` 직접 조회는 PostgREST로 불가 → 임시 유저·route에 참조를 걸고
admin REST로 삭제해 on-delete 동작을 관찰(cascade_probe, 2026-07-21).

| 참조 | 실측 on-delete | 삭제 시 |
|---|---|---|
| `route_bookmarks.route_id` | **cascade** | DB 자동 소멸 |
| `route_likes.route_id` | **cascade** | DB 자동 소멸 |
| `route_comments.route_id` | **cascade** | DB 자동 소멸 |
| `coach_scripts.route_id`(PK) | **cascade** | DB 자동 소멸(오디오 코치 캐시) |
| `runs.route_id` | **set null** | **러닝 기록 잔존**, route_id만 null(기록은 독립 자산) |
| `routes.copied_from`(자기참조) | **set null** | **복사본 코스 잔존**, copied_from만 null |
| **알림**(`route_liked`·`route_commented`) | FK 없음(polymorphic, target_id=route_id) | **명시 정리 필요** — 방치 시 stale 404 탭(run-delete 선례) |
| 피드 route_summary | 라이브(runs.route_id JOIN routes.summary) | route_id null → 자동 null. 코스 피드는 routes 직접 조회라 그냥 빠짐 |
| 채팅 공유 스냅샷 | **해당 없음** — `run_share`(run 대상)만 존재, route 공유 기능 없음 | 무관 |
| Storage | **해당 없음** — 코스엔 자산 없음(이미지는 크루 전용) | 사진 정리 불필요 |

## 1. 핵심 — 하드 삭제, 재계산 코드 0

run-delete와 동일: 파생(북마크·좋아요·댓글·코치)은 전부 FK cascade, 코스는
어떤 집계에도 안 들어감(PB·통계·챌린지는 run 기반). **재계산 로직 불필요**.
남는 앱 작업은 best-effort 정리 1건(route 대상 알림)뿐 — Storage조차 없음.

set null 선택(cascade 아님)의 근거: 러닝 기록은 코스가 지워져도 남아야 할
독립 자산(뛴 사실은 코스 존재와 무관), 복사본은 이미 남의 소유. 둘 다
"연결만 끊고 본체 보존"이 맞다.

## 2. 계약

| 항목 | 값 |
|---|---|
| 엔드포인트 | **`DELETE /routes/{route_id}`** (기존 GET/PATCH `/routes/{route_id}`와 같은 패턴-경로 가족 — 순서 충돌 없음) |
| 권한 | **소유자 본인만.** 타인·없음·기삭제 → **404 은닉** |
| 성공 | **204** |
| 재삭제 | **404** (run-delete 관성 — "리소스 삭제") |
| 복구 | **없음**(하드) |
| 레이스 | 동시 2발 → `.delete().eq(user_id)` 반환행으로 승자 판정, 패자 404 (L8 패턴) |

## 3. 소비 규칙(프론트)
내 코스 목록(저장한 코스·프로필)에서 스와이프 or ⋯ → 2단 파괴 컨펌.
카피: "북마크·좋아요·댓글이 함께 삭제돼요"(연결된 러닝 기록은 남음). 연타 시
404를 "이미 삭제됨"으로 무해 처리(기존 계약).

## 4. 테스트 (tests/test_route_delete_integration.py — 전 케이스 통과)
cascade 4종 소멸 + run/복사본 set-null 잔존 실증 / 재삭제·타인·없음 404 /
알림 정리(route 대상 소멸+무관 잔존) / 레이스 [204,404] / is_one_way 필드(D).
회귀: bookmarks·comments·copy_count 통합 전부 통과.
