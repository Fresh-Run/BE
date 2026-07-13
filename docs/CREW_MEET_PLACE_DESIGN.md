# CREW_MEET_PLACE_DESIGN — 크루 상설 집결지 (meet_place)

> 작성 2026-07-14. 상태: **구현 완료(배포 대기)** — SQL 적용됨(사용자 실행,
> `db/2026-07-14_crew_meet_place.sql`), 코드·테스트 완료. §8-1 확정:
> **meet_place_name ≤100자**(공지 place_name과 동일 — 규칙 복제 원칙 우선).
> ⚠️ 배포 순서: 서버 배포 후 Ivan에게 "meet_* 전송 가능" 신호(forbid 422 방지).
> 요청: Ivan(프론트) — 캔버스 카드 "서울숲 공원 정문 · 성수동 · 매주 화·목 06:00"의
> **장소 부분**. 공지의 일회성 집결지와 별개로 크루 자체의 상설 집결지.
> 스케줄은 기존 `active_days`/`active_time` 재사용(신규 없음).

## 0. 진단 결과 (실조회, 2026-07-14)

| # | 확인 항목 | 결과 |
|---|---|---|
| 1 | crews에 place 관련 컬럼 | **없음**(실컬럼 23개 조회 — Ivan 주장 검증됨) |
| 2 | 크루 PATCH 권한 게이트 | `ensure_permission(crew_id, caller, "edit_crew")` (`crew_service.py:1434`) — **owner 또는 edit_crew 권한 admin**. v1의 "owner only" docstring은 낡은 주석 |
| 3 | 공지 place 검증 규칙 | `place_name` **max_length=100** · `place_lat` ge=33/le=39 · `place_lng` ge=124/le=132 (`schemas.py:1636-1640`) — bbox 그대로 복제 가능. ⚠️ 길이는 아래 §8-1 플래그(요청서의 50자 추정과 다름) |
| 4 | CrewResponse 소비처 | 라우트 10곳(생성·browse·mine·검색·상세·preview·join·수정·transfer 등)이 전부 같은 모델. 조립은 `_to_response`의 **`**crew` 스프레드** — DB 컬럼 추가 후 CrewResponse에 동명 Optional 필드만 추가하면 전 경로 자동 노출. additive nullable → 하위호환 |

## 1. 요구 / 비요구 (스코프 경계 — 발명 금지)

**요구**
- `crews`에 additive 컬럼 3개: `meet_place_name`(text null) · `meet_lat`/`meet_lng`
  (double precision null, 한국 bbox).
- `CrewCreate`(생성 시 설정)·`CrewUpdate`(수정) 세 필드 추가.
- `CrewUpdate`는 **명시 null=삭제** — 기존 `_NULL_DELETABLE`(sido/sigungu/lat/lng)에
  3필드 추가(region 패턴 그대로).
- `CrewResponse`에 세 필드 노출(null이면 프론트가 카드 장소 라인 숨김).
- 권한: **기존 PATCH 게이트 그대로 상속**(edit_crew — 별도 게이트 없음. sido/sigungu와
  같은 경로·같은 성격).

**비요구 (발명 금지)**
- 집결지 **1개만**(여러 개·이력 없음).
- 지도 검색/지오코딩 **서버 미제공** — 프론트 카카오 SDK 몫(region·run.area 분업 선례).
  서버는 저장·서빙만.
- 공지(place_*)와의 **동기화/연동 없음** — 완전 독립 필드(공지는 일회성, 이건 상설).
- 스케줄 필드 신규 없음(`active_days`/`active_time` 재사용).
- 크루 검색/둘러보기의 거리 계산(`distance_km`)은 기존 `lat`/`lng`(대표 좌표) 유지 —
  meet 좌표로 대체하지 않음(대표 좌표와 집결 좌표는 다른 개념).

## 2. 스키마 (DDL 방향 — SQL은 승인 후 세트 별도)

```
alter table public.crews
  add column if not exists meet_place_name text,             -- 표시명 (길이는 앱 검증)
  add column if not exists meet_lat  double precision,       -- bbox는 앱(Pydantic) 검증
  add column if not exists meet_lng  double precision;
```
- **전부 nullable, default 없음** — 기존 행 자동 null(백필 불필요), non-breaking.
- 길이·bbox는 **앱(Pydantic) 검증만**(공지 place_*와 동일 방침 — DB CHECK 없음).
- RLS는 기존 crews 테이블 설정 그대로(신규 테이블 아님 — enable 대상 아님).
- 승인 후 `db/2026-07-14_crew_meet_place.sql`에 [APPLY]/[ROLLBACK]/[확인쿼리] 세트.

## 3. 계약 (Pydantic·응답)

**CrewCreate / CrewUpdate (동일 3필드, 전부 optional)**
```python
meet_place_name: Optional[str] = Field(None, max_length=100)   # §8-1 확정 시 조정
meet_lat: Optional[float] = Field(None, ge=33.0, le=39.0)      # 공지 place_lat 동일
meet_lng: Optional[float] = Field(None, ge=124.0, le=132.0)    # 공지 place_lng 동일
```
- CrewUpdate 3분기: **생략=유지 / 명시 null=삭제 / 값=설정** — `update_crew`의
  `_NULL_DELETABLE` 화이트리스트에 `("meet_place_name","meet_lat","meet_lng")` 추가.
- `meet_lat`/`meet_lng`는 **함께 전송 권장**(반쪽 좌표 방지 — 서버는 독립 허용,
  region lat/lng와 동일 계약. API_GUIDE에 명시).
- **forbid와의 배포 순서(중요)**: CrewCreate·CrewUpdate는 `extra="forbid"` —
  **서버가 먼저 배포되기 전에 프론트가 meet_* 필드를 보내면 422**로 크루
  생성/수정이 깨진다. → **서버 배포 완료 후 Ivan에게 "meet_* 전송 가능" 신호**
  (이 순서를 릴리스 노트·보고에 명시).

**CrewResponse**
```python
meet_place_name: Optional[str] = None   # null → 프론트 카드 장소 라인 숨김
meet_lat: Optional[float] = None
meet_lng: Optional[float] = None
```
- `_to_response`가 `**crew` 스프레드라 필드 선언만으로 **10개 소비 경로 전부 자동
  노출**(browse·mine·상세·preview-by-code·join 등). 구현 시 crews를 명시 컬럼
  select하는 경로가 없는지 재확인(현재 `_crew_row(crew_id, "*")` 등 `*` 조회).
- **소비 규칙(프론트)**: 카드 장소 라인 = `meet_place_name` (+ 지도 진입은
  `meet_lat/lng`). 셋 다 null이면 라인 숨김. 스케줄 라인은 기존
  `active_days`/`active_time` 조합("매주 화·목 06:00").

## 4. 권한 (진단 확정)
- 별도 게이트 없음 — 크루 PATCH의 **`edit_crew` 게이트 그대로 상속**
  (owner 전권 암묵 + edit_crew 부여 admin). sido/sigungu도 같은 경로라 정합.
- 권한 없는 admin/member는 기존과 동일 **403**, 비멤버/없는 크루 404(기존 불변).

## 5. 하위호환 — 순수 additive
- 컬럼 3개 nullable 추가(기존 행 null) + 응답 Optional 필드(기본 null) + 요청
  optional 필드. **기존 계약·동작 전부 불변.**
- 프론트 구버전: meet_*를 안 보내면 아무 영향 없음, 응답의 새 필드는 무시하면 그만.

## 6. 테스트 계획 (`tests/test_crew_meet_place_integration.py` 신규)

1. **생성 시 설정**: CrewCreate에 meet_* 3필드 → 생성 200/201 + DB 저장 + 응답 노출.
2. **PATCH 설정/수정**: 값 전송 → 200 + DB 반영. 일부만(place_name만) → 그 필드만.
3. **null=clear**: `{meet_place_name:null}` → 삭제(DB null) + 생략 필드 유지.
   3필드 각각 + 혼합(clear+set 동시).
4. **bbox 422**: meet_lat 10.0 / meet_lng 200.0 → 422.
5. **길이 422**: place_name 초과(§8-1 확정 길이+1) → 422.
6. **권한**: member PATCH → 403 / edit_crew admin PATCH → 200(상속 확인) /
   없는 크루 404.
7. **응답 노출**: 상세·mine·browse(둘러보기)에서 meet_* 노출 + 미설정 크루 null.
8. **forbid 공존**: 오타 `meet_place_nam` → 422(기존 forbid 회귀) + 유효 meet_* 통과.
9. **회귀**: `test_crew_patch_null_delete`(기존 화이트리스트 4필드 불변),
   `test_crew_extra_forbid`, `test_crew_manage`, `test_crew_browse`.

DB 부수효과는 admin REST로 crews row 직접 assert.

## 7. 완료의 정의 (§A)
1. 신규 + 회귀 전부 통과(실패 시 자가 수정).
2. DB 부수효과 assert(설정/삭제/유지).
3. `db/2026-07-14_crew_meet_place.sql` [APPLY]/[ROLLBACK]/[확인쿼리] — 사용자 실행.
4. API_GUIDE: 크루 생성/수정 행(§198)에 meet_* 3필드 + null=clear + lat/lng 함께
   전송 권장 + 카드 소비 규칙(장소 라인=meet_place_name, null이면 숨김) 명시.
5. 키 grep clean · 임시 데이터 정리.
6. 커밋+푸시 → (지시 시) fly deploy + 스모크(설정→조회→clear 1사이클) →
   **배포 후 Ivan에게 전송 가능 신호**(forbid 순서).

## 8. 잔여 판단 지점 (확답 필요)

1. **meet_place_name 길이 — 50 vs 100**: 요청서는 "≤50자(공지와 동일 규칙 확인)"
   이었으나 실조회 결과 **공지 place_name은 100자**다. 두 의도가 충돌:
   - (i) **100자** — "공지와 동일 규칙 복제" 원칙 우선(추천: 장소명은 "서울숲
     공원 정문 앞 세븐일레븐 옆" 같이 길어질 수 있고, 공지와 규칙이 갈리면
     프론트가 입력 UI 제한을 두 벌 관리).
   - (ii) 50자 — 카드 한 줄 표시 고려(단 표시 잘림은 프론트 ellipsis 몫).
   → **추천 (i) 100자.** 확정해 달라.
2. **생성 화면 노출 여부(참고)**: CrewCreate에 넣어도 프론트가 생성 화면에서 안
   쓰면 무해(optional). Ivan 캔버스가 설정(수정) 화면 기준이면 생성 쪽은 계약만
   존재 — 별도 확답 불요, 참고만.
