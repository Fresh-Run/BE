# PITSTOP_POI_SPEC.md — 경유지 POI 계약 (A-2) 서버 스펙 초안

> **설계만 — 구현·스키마 변경 없음.** 이반 클라 대응 합의 **선행** 후 구현
> (이반 "want to spec that field?" 응답). 계약 확정 시 `docs/API_GUIDE.md` 반영.
> A축(실명 writeback)은 이미 수정 완료(커밋 ca050ec) — 이 문서는 **별개의 계약 갭**
> (유저가 찍은 그 POI 유실)만 다룬다.

## 1. 유실 지점 — 정확히 어디서 사라지나

현 요청 계약(`app/models/schemas.py:588`):
```python
class RouteRequest(BaseModel):
    pitstop_keyword: Optional[str] = None   # "카페" 같은 키워드 문자열뿐
```
**유저가 앱에서 탭한 특정 POI(예: "스타벅스 광교점", 좌표)는 요청에 실리지 않는다** —
키워드 문자열만 전송. 서버는 그 키워드로 **Kakao를 재검색**한다:
```
route_service.py:1161  pitstop_places = search_places(req.pitstop_keyword, near=req.start, …)
route_service.py:1166  ranked = rank_places_for_keyword(req.pitstop_keyword, pitstop_places, …)
             pick = ranked[0]      # ← 서버가 자기 랭킹의 1위를 채택
```
→ **유실 지점 = 클라→서버 요청 경계.** 유저가 고른 POI 정체(place_id·좌표·정확한 이름)가
전달되지 않아, 서버가 **재검색 top-랭킹으로 대체**. 오너 실사례: "카페" 재검색에서
유저가 탭한 카페가 아닌 **acc_rank 8(8번째 카페)** 채택. A축 writeback(`_apply_pitstop_name`,
route_service.py:1512)은 "서버가 고른 pick"의 이름을 정확히 쓰지만, **그 pick 자체가
유저 지정과 다름** — A축으로 못 고치는 계약 문제.

## 2. 신 필드 설계 (additive — 하위호환)

`RouteRequest`에 유저 지정 POI 필드 추가. **있으면 재검색 우회, 없으면 keyword 폴백.**

```python
class PitstopPlace(BaseModel):
    name: str                              # 실 POI 표시명(이름 원칙 — 실명 그대로)
    coordinate: KoreaCoordinate            # 유저 지정 좌표(한국 밖 자동 거부)
    place_id: Optional[str] = None         # Kakao place id(선택 — dedup·분석·재조회)
    category_code: Optional[str] = None    # 선택(관측 — FD6/CE7 등)

class RouteRequest(BaseModel):
    # ...기존...
    pitstop_keyword: Optional[str] = None          # 유지(폴백·라벨)
    pitstop_place: Optional[PitstopPlace] = None    # 신규(유저 지정 POI 직접 전달)
```
- **additive**: 기존 keyword-only 요청·pitstop 없는 요청 **무영향**(`pitstop_place` 미전송
  = None → 종전 경로). `KoreaCoordinate` 재사용(입구 차단·한국 경계 검증 기존 로직).
- `Coordinate`/`KoreaCoordinate`(schemas.py:57/67)·`Place`(701) 기존 스키마 재사용 —
  `PitstopPlace`는 요청 전용 경량 모델(응답 `Place`와 구분).

## 3. 서버 로직 설계 (재검색 우회)

route_service 현 pitstop 블록(1160~1194)에 분기 추가 — **A축 파이프 그대로 재사용**:
```
if req.pitstop_place is not None:
    # 재검색 스킵 — 유저 지정을 pick으로 합성
    pick = Place(name=req.pitstop_place.name,
                 coordinate=req.pitstop_place.coordinate,
                 category_code=req.pitstop_place.category_code, address=None)
    # 좌표 유효성: KoreaCoordinate(경계) + 시작점 근접 밴드(경로 편입 가능성)
    #   기존 _in_position_band(start, pick, target)로 판정 — 밴드 밖이면 §5 엣지 처리
    pitstop_pick = pick
    # via 스냅·writeback은 기존 경로 동일: wp.coordinate=pick.coordinate,
    #   _apply_pitstop_name(best, pitstop_pick)가 name 적용(A축 재사용)
else:
    # 현행: keyword 재검색(search_places → rank_places_for_keyword) — 무변경
```
- **핵심**: `pitstop_place` 수신 시 **Kakao 재검색·랭킹 전면 스킵** → 지정 좌표를 pitstop
  via로 스냅, 지정 name을 실명 writeback(A축 `_apply_pitstop_name` 그대로). **신규 코드
  최소**(pick 합성 분기 하나 + 재검색 우회).
- **랜드마크 필터 우회**: 유저가 명시 선택했으므로 상업 카테고리 제외 필터(FD6/CE7)를
  **적용하지 않음** — 유저 의도 존중(현 필터는 keyword 재검색 오탐 방지용, 명시 선택엔 불요).
- 관측: gen_meta.pitstop에 `source:"user_place"` vs `"keyword_search"` 구분 기록(additive).

## 4. 하위호환 (assert 설계)

| 요청 형태 | 동작 | 검증 |
|---|---|---|
| `pitstop_place` 있음 | 재검색 우회·지정 POI 사용 | 신 경로 |
| `pitstop_keyword`만(place 없음) | **종전 재검색·랭킹 그대로** | 무영향 assert |
| pitstop 없음 | 종전 무pitstop 생성 | 무영향 assert |
- **이름 원칙 정합**: 유저 지정 실 POI = `name` 그대로 실명 노출(발명 0). A축과 동일 원칙.
- 테스트(구현 시): ① place 지정 → 그 좌표·이름이 서빙 waypoint에 정확 반영(Kakao 미호출
  assert — 재검색 스킵) ② keyword-only → 기존 rank_places 경로·결과 불변 ③ pitstop 없음
  → 무영향. §E 매트릭스(place 유·keyword 유·무 × 좌표).

## 5. 이반 협의 항목 (확정 필요)

1. **클라 shape**: `place_id` 포함 여부(dedup/분석엔 유용, 라우팅엔 불요) · 좌표 정밀도
   (6자리 권장) · `name`은 Kakao 원문 그대로.
2. **place ↔ keyword 병존 정책**: 둘 다 오면 **place 우선**(keyword는 라벨/폴백)? 아니면
   place 있으면 keyword 무시? 권고 = place 우선 + keyword 무시(명시 선택이 강함).
3. **엣지 — 지정 POI가 경로에서 너무 먼 경우**(시작점서 밴드 밖·target 초과 유발):
   ⓐ 그대로 편입(overshoot 감수) ⓑ 422 거부("경유지가 너무 멉니다") ⓒ keyword 폴백
   재검색 ⓓ best-effort 편입 + `target_missed` 플래그. **권고 = ⓓ**(서빙률 우선, 정직 배너).
   → **이반/오너 확정 필요**.
4. **좌표 유효성 실패**(한국 밖 등): KoreaCoordinate가 422 — 클라가 사전 검증할지.
5. **category_code 전송 여부**: 관측용(선택). 없어도 라우팅 무관.
6. **place_id 재조회**: 좌표 신뢰 vs place_id로 서버가 Kakao 재조회(최신 좌표)? 권고 =
   **클라 좌표 신뢰**(재조회는 콜 증가·불필요) — place_id는 관측만.

## 6. 구현 순서

- **이반 합의 선행**(클라가 보낼 shape 확정) → 구현. A축(실명 writeback)은 이미 배포됨.
- 구현 범위(합의 후): `PitstopPlace` 모델 + `RouteRequest.pitstop_place` additive +
  route_service pitstop 블록 분기(재검색 우회) + gen_meta source 관측 + 테스트 매트릭스.
- **SQL·스키마 변경 0**(요청 계약만 — DB 무접촉). `docs/API_GUIDE.md` pitstop 소비 규칙
  표 갱신(place 필드 + place↔keyword 우선순위).
- ⚠️ **계약 변경 규칙(§C)**: `pitstop_keyword` 기대 기존 테스트 전수 grep — additive라
  깨지진 않으나 place 경로 테스트 신설 필수.
