# CREW_FEED_FIXES_DESIGN — 크루 피드 2건 설계

> 작성 2026-07-13. 상태: **Part 2 구현·배포 완료** · **Part 1 구현 완료(배포 대기)**.
> 스키마 변경 없음(양 Part). Part 1·2 분리 배포.
> 전제(진단 완료, 실조회): `GET /crews/{id}/runs`는 크루원 전원의 non-private
> run 파이어호스(`crew_service.py:846-951`, crew_id 필터 없음) · 태그런 식별 =
> `crew_id NOT NULL`(session_key와 동치, DB 실측 3/37건) · 배지
> `is_crew_session`/`session_participant_count`(L1) · 건2는 `crew_service.py:1438`
> `exclude_none=True`가 명시 null을 삼키고 cover/icon 2필드만 `model_fields_set`
> 으로 되살림 · avatar_url 삭제 선례(`schemas.py:103`, profile_service).
>
> **Part 1·Part 2는 독립 배포·독립 롤백 가능.** 둘 다 스키마 변경 없음.

---

## Part 1 — `GET /crews/{id}/runs?session_only=true` (정기런 전용 뷰)

### 1.1 요구 / 비요구 (스코프 경계)

**요구**
- `GET /crews/{id}/runs`에 **쿼리 파라미터 `session_only`** 추가(기본 false).
- `session_only=true` → **이 크루로 태그된 정기런만** 반환:
  기존 WHERE에 `crew_id = {이 크루} AND session_key IS NOT NULL` 추가.
- `session_only` 생략/false → **현행 파이어호스 그대로**(크루원 전원 non-private run).
- 응답 shape·정렬(`ran_at DESC`)·페이지네이션(`limit`≤100·`offset`) **동일**.
- 배지 로직(`is_crew_session`·`session_participant_count`) **그대로**.

**비요구 (발명 금지)**
- 기본 동작 변경 없음(파이어호스 유지 — 계약·6개 테스트·시드 불변).
- 세션 상세("참여자 명단·기록 모아보기")는 **L2** — 이번 범위 밖.
- 새 응답 필드 없음(기존 CrewRunItem 그대로).
- 정렬/그룹핑 옵션 없음(session_key별 그룹핑은 L2).

### 1.2 엔드포인트 계약 변경

| method | 경로 | 파라미터 | 응답 | 상태 |
|---|---|---|---|---|
| GET | `/crews/{crew_id}/runs` | `limit`(≤100·기본20) · `offset` · **`session_only`(bool, 기본 false, 신규)** | `list[CrewRunItem]` | 200 (비크루원 403) |

**동작**
- `session_only` 미전송/false: 현행(크루원 전원 non-private run, 최신순).
- `session_only=true`: `user_id IN (현재 크루원) AND visibility != 'private'
  AND crew_id = {crew_id} AND session_key IS NOT NULL` + 차단 멤버 제외(기존과 동일).

**응답 예시 (session_only=true)**
```json
[
  { "run_id": "...", "user_id": "...", "nickname": "한강질주",
    "ran_at": "2026-07-13T21:03:00+09:00", "title": "여의도 정기런",
    "distance_km": 7.2, "duration_sec": 2400, "avg_pace_sec_per_km": 333,
    "is_crew_session": true, "session_participant_count": 4,
    "comment_count": 1, "route_summary": null, "photo_thumb": null }
]
```
→ **`session_only=true`면 반환된 모든 항목이 태그런이라 `is_crew_session`이 전부
`true`**다. 이는 **의도된 동작**(뷰 자체가 정기런 필터). 프론트는 이 뷰에서 배지를
생략하거나 "정기런" 헤더로 대체해도 됨.

### 1.3 엣지 케이스
- **태그런 0건**: `session_only=true`인데 이 크루 태그런이 없으면 **빈 배열**(정상,
  404 아님). DB 실측상 대부분 크루가 여기 해당(37 run 중 태그 3건).
- **차단 멤버·private**: 기존 필터 그대로 적용(별도 분기 없음).
- **탈퇴 멤버의 태그런**: 현재 파이어호스가 `user_id IN (현재 크루원)`으로 거르므로,
  탈퇴한 멤버가 남긴 태그런은 **목록에서 빠진다**. 반면 `session_participant_count`
  는 session_key 기준 전역 집계(탈퇴·차단 포함). → **"카운트는 전역, 목록은
  현재 멤버"** 비대칭이 이미 v3.6 계약(숫자 전역·명단 필터). session_only도 이
  기존 비대칭을 **그대로 상속**(신규 이슈 아님). ⚠️ 아래 1.6 플래그.
- **경로 순서**: 기존 엔드포인트에 파라미터만 추가 — 경로 등록·순서 변화 없음.

### 1.4 스키마 변경
- **없음.** 쿼리에 조건 2개(`eq(crew_id)`·`not.is(session_key,null)`) 추가뿐.

### 1.5 하위호환
- 순수 additive. `session_only` 기본 false → 기존 호출자(파라미터 미전송)는 동작
  **완전 불변**. CrewRunItem 스키마 무변경. 기존 6개 테스트·시드 영향 0.

### 1.6 판단 필요 지점 (플래그)
**탈퇴 멤버의 태그런을 `session_only` 뷰에 포함할지.**
- 현행 상속(현재 멤버만) = 목록엔 안 뜨지만 참여자 수엔 카운트(v3.6 비대칭 일관).
- 대안: session_only에서만 `user_id IN 멤버` 필터를 빼고 **crew_id 기준 순수 태그런**
  (탈퇴자 포함) — 세션 뷰의 "그 날 그 세션 전원" 의미엔 더 맞음. 단 목록·카운트
  정합은 좋아지나 "탈퇴자 run이 크루 피드에 계속 노출"되는 프라이버시 고려 발생.
- **추천**: 1차는 **현행 상속(현재 멤버만)** — 기존 비대칭과 일관, 구현·회귀 최소.
  세션 전원 노출은 L2에서 재검토. → 승인 시 확인.

---

## Part 2 — 크루 PATCH `null` 삭제 버그 수정

### 2.1 요구 / 비요구 (스코프 경계)

**요구**
- `update_crew`의 dict 구성을 `exclude_none=True` 일괄 제거 → **`model_fields_set`
  기반 선별 포함**으로 교체(avatar_url 삭제 선례 확장).
- **null-삭제 화이트리스트 = `sido`, `sigungu`, `lat`, `lng` (4개만)**:
  명시 null이면 `data[field] = None`으로 DB null 기록.
- 그 외 필드는 **"생략=유지, 값=갱신, 명시 null=무시(유지)"** 유지.

**비요구 (발명 금지)**
- 스키마 변경 없음(컬럼 이미 nullable, Pydantic 이미 Optional).
- `tags`는 화이트리스트 **제외** — null-삭제 안 함, `[]`로 비우기(배열 컨벤션).
- `name` 등 필수 필드 삭제 불가(화이트리스트 제외).
- `cover_url`·`icon_url`은 **기존 삭제 동작 그대로**(회귀 방어 — 건드리지 않음).
- 새 검증 규칙 추가 없음(sido enum·lat/lng bbox·sigungu 길이 검증은 값이 있을 때만
  기존대로 발동, null엔 미발동).

### 2.2 근본 수정 (single-source 패턴)
현재(`crew_service.py:1438`):
```python
data = req.model_dump(mode="json", exclude_none=True)   # ← 모든 None 삼킴
# 이후 cover_url/icon_url만 model_fields_set으로 되살림(1442-1445)
```
설계(패턴 통일):
```python
data = req.model_dump(mode="json", exclude_none=True)   # 값 있는 필드만
_NULL_DELETABLE = ("sido", "sigungu", "lat", "lng")     # 화이트리스트
for field in _NULL_DELETABLE:
    if field in req.model_fields_set and getattr(req, field) is None:
        data[field] = None                               # 명시 null → DB null
# cover_url/icon_url 기존 블록은 그대로(삭제+Storage 정리, 회귀 방어)
```
→ avatar_url(`schemas.py:103`) / cover·icon(`crew_service.py:1443`)과 **동일 패턴**.
"생략 vs 명시 null" 구분은 `model_fields_set`이 유일 판별자.

### 2.3 필드별 처리 표 (전수)

| 필드 | 생략(fields_set 없음) | 명시 null | 값 전송 |
|---|---|---|---|
| **`sido`** | 유지 | **삭제(→null)** | 저장(Sido enum 검증) |
| **`sigungu`** | 유지 | **삭제(→null)** | 저장(길이 검증) |
| **`lat`** | 유지 | **삭제(→null)** | 저장(bbox 검증) |
| **`lng`** | 유지 | **삭제(→null)** | 저장(bbox 검증) |
| `tags` | 유지 | **무시(유지)** — 삭제 안 함 | 저장(≤5); 비우려면 `[]` |
| `name` | 유지 | 무시(유지) — 필수라 삭제 불가 | 저장 |
| `description`·`area`·`sport`·`active_time`·`color` 등 | 유지 | 무시(유지) | 저장 |
| `cover_url` | 유지 | **삭제(→null)+Storage 정리** (기존) | 저장(경로 검증) |
| `icon_url` | 유지 | **삭제(→null)+Storage 정리** (기존) | 저장(경로 검증) |

> "무시(유지)"= 현행 동작 유지(exclude_none이 떨궈 update dict에 안 실림). 화이트
> 리스트 밖 필드의 명시 null은 **삭제로 해석하지 않는다**(의도적 — 필수·배열 필드
> 보호). 프론트가 그 필드를 비우려면 각 규칙(`name` 불가, `tags`는 `[]`)을 따름.

### 2.4 스키마 변경
- **없음.** `crews.sido/sigungu/lat/lng`는 이미 nullable(진단 실측: 각 7·7·8·8건
  null 존재). Pydantic `CrewUpdate` 필드도 이미 `Optional`. DDL·마이그레이션 불필요.

### 2.5 하위호환 (회귀 방어가 핵심)
- 이건 **버그 수정** — 기존 "정상 동작"을 깨지 않는 게 최우선:
  - **생략=유지**: 화이트리스트 필드도 미전송이면 절대 건드리지 않음(기존 유지).
  - **값 전송=갱신**: 검증·저장 경로 불변.
  - **cover/icon 삭제**: 기존 블록 그대로 — 회귀 테스트로 재확인.
  - 화이트리스트 밖 필드의 명시 null: 기존처럼 무시(유지) — 동작 변화 없음.
- 유일한 **동작 변화**는 `sido/sigungu/lat/lng` 명시 null이 이제 **삭제**된다는 것
  (= 버그 수정, 의도). 프론트가 실수로 null을 보내던 게 없었는지 확인 권장(아래 2.6).

### 2.6 판단 필요 지점 (플래그)
1. **lat/lng 페어링**: 좌표는 쌍이라 `lat`만 null·`lng`는 값이면 반쪽 좌표가 됨
   (DB 실측상 lat/lng는 항상 동반 9/8건). 코드에서 **독립 삭제 허용**(단순)하되
   프론트가 "둘 다 지우기"를 계약으로 지킬지, 아니면 서버가 **쌍 강제**(하나만
   null이면 둘 다 null 또는 422)할지. **추천**: 서버는 독립 허용(단순), API_GUIDE에
   "지역 좌표는 lat·lng를 함께 보내라" 명시. → 승인 시 확인.
2. **기존 프론트가 null을 보내고 있었나**: 수정 전엔 null이 무시됐으므로, 프론트가
   무심코 `{"sido": null}`을 보내던 코드가 있으면 수정 후 **의도치 않은 삭제**가
   발생할 수 있음. 배포 전 프론트 팀에 "sido/sigungu/lat/lng 명시 null=삭제로
   바뀜" 공지 필요(계약 강화류 — 회귀 범위 확대 원칙).

---

## 테스트 계획 (완료의 정의 §A 풀세트)

### Part 1 — `tests/test_crew_session_only_integration.py` (신규)
1. **파이어호스 불변**: `session_only` 미전송 → 기존과 동일(태그·비태그 run 모두
   포함) — 기존 계약 회귀.
2. **session_only=false** 명시 → 파이어호스(1과 동일).
3. **session_only=true** → 태그런만: 응답의 모든 항목이 `crew_id==this` 태그런
   (비태그 run **부재 assert**), `is_crew_session` **전부 true assert**.
4. **빈 결과**: 태그런 0인 크루 → `session_only=true` 시 **빈 배열**(200).
5. **배지**: `session_only=true` 항목의 `session_participant_count`가 파이어호스
   때와 동일 값(집계 로직 불변 확인).
6. **필터 상속**: private run 제외·차단 멤버 제외가 session_only에도 적용.
7. **정렬·페이지네이션**: `ran_at DESC`·`limit`/`offset` 동작 확인.

### Part 2 — `tests/test_crew_patch_null_delete_integration.py` (신규, 매트릭스)
필드 × 케이스 전수:
1. `sido/sigungu/lat/lng` 각각 **명시 null → DB null 저장 assert**.
2. `sido/sigungu/lat/lng` 각각 **생략 → 기존 값 유지 assert**(덮어쓰기 없음).
3. `sido/sigungu/lat/lng` 각각 **값 전송 → 저장 assert**(+검증: 잘못된 sido enum
   422, bbox 밖 lat/lng 422 — 값 경로 불변).
4. `tags` **명시 null → 유지(무시) assert**(삭제 안 됨) + `[]` → 비워짐 assert.
5. `name` 명시 null → 유지(삭제 안 됨) assert.
6. **회귀 — cover/icon**: 명시 null → 삭제(→null)+Storage 정리 assert(기존 동작).
7. **혼합 PATCH**: `{"sido": null, "sigungu": "성수동", "name": "새이름"}` → sido
   삭제·sigungu 갱신·name 갱신·나머지 유지 동시 검증.

### 회귀 재실행 목록
- Part 1: `test_crew_runs_integration`·`test_crew_run_session_l1_integration`·
  `test_run_visibility_integration`·`test_decision_a_prime_v35_integration`(차단)·
  `test_crew_admin_area_integration`.
- Part 2: `test_crew_admin_area_integration`(sido/sigungu/lat/lng 저장)·크루
  이미지 삭제 관련 테스트.

### 테스트 규율
- DB 부수효과 직접 assert(크루 row의 컬럼 null/값). 임시 크루·유저 생성 후 정리.
- 권한: 비크루원 403(기존)·edit_crew 권한 게이트 회귀. Gemini 무관(실호출 0).

---

## 완료의 정의 (이 작업의 §A 체크리스트)
1. 신규 2파일 + 회귀 목록 전부 통과(실패 시 자가 수정 후 재실행).
2. DB 부수효과 assert: Part1 태그런만/파이어호스 구분, Part2 컬럼 null/값/유지.
3. `db/`: **양 Part 모두 SQL 없음**(스키마 무변경) — 문서에 명시.
4. `docs/API_GUIDE.md` 갱신:
   - §217 `GET /crews/{id}/runs`에 `session_only` 파라미터 + 소비 규칙(true면
     태그런만·is_crew_session 전부 true) 추가.
   - §197 크루 PATCH에 `sido/sigungu/lat/lng` **명시 null=삭제** 계약 명시
     (cover/icon과 동일 규칙, tags는 `[]`·name 불가).
5. 커밋 전 키 패턴 grep clean.
6. 임시 데이터 정리, 키·값 화면 출력 0.
7. 스테이징: 크루 피드·PATCH 영향 → `fly deploy` + `/health` + (session_only
   조회 / sido null 삭제) 스모크 1사이클.
8. 보고: 통과 목록 / 변경 파일 표 / 판단 플래그 / 실패 원인 1줄.

---

## 승인 전 확답 필요 (2건)
1. **Part 1.6** — `session_only` 뷰에 탈퇴 멤버의 태그런 포함? (추천: 현행 상속=현재
   멤버만, 카운트-목록 비대칭은 v3.6과 일관)
2. **Part 2.6** — lat/lng 독립 삭제 허용 vs 서버 쌍 강제? (추천: 독립 허용 +
   API_GUIDE에 "함께 전송" 명시) / 프론트에 "명시 null=삭제" 계약 강화 공지.
