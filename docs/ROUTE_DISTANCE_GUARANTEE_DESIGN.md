# ROUTE_DISTANCE_GUARANTEE_DESIGN — AI 코스 목표 거리 보장 (v2.4)

> **v2.4 (2026-07-21, 오너 결정 — 하한 완화 + 계측 보강)**: 계측(v71 로그·저장분
> 43건)이 초과 편향을 실증 — dev>0:dev<0 = 34:8, median +0.70, 그리고 로그에서
> "4.84(−0.16)를 하한 −0.1 밖으로 버리고 5.38 서빙" 패턴 포착. 조치:
> ① **하한 −0.1 → −0.3** (밴드 [target−0.3, target+0.5], 폭 0.8) — 아깝게 미달한
>    코스를 건져 불필요한 초과 서빙을 줄인다. 전패 처리(미달 반환 금지·초과 최선·
>    둘 다 없으면 502)는 새 하한 기준으로 불변. **합격 코스가 −0.3까지 짧을 수
>    있으므로** 프론트 배너는 방향 중립(부호 분기 — API_GUIDE Ivan 노트).
> ② **gen_meta.snaps** — attempt별 스냅 배열(예 `[null, 4.84, 5.38]`, no_path·
>    untraversable은 null). 채택 attempt만 저장하던 gen_meta의 공백(버려진 후보
>    미관측)을 메워, 하한 완화 효과·미달 후보 비율을 사후 정량 가능.
> 비결정성 구조(코드 확인, 미수정): Gemini `temperature`/`seed` 미설정 = 기본
> 온도 샘플링이 지배적 — 같은 입력이 시점에 따라 성공/502로 갈리는 주원인.
> seed 고정은 다양성 상실이라 미채택, 밴드 완화로 502 빈도만 낮춘다.

> **v2.3 (2026-07-20, 배포됨 v68)** — 두 수술 묶음 (트리거: 실사용 3연속 비명중
> 5.7/5.7/502. 502 부검: 후보 7.71/6.45km 전부 캡 밖 — 원인 aim 3.9에 chain
> 5.57 등 Gemini 체인 비순응):
> **(A) 체인 순응도** — ① 프롬프트에 "chain MUST NOT exceed aim×1.15 — longer
> routes are invalid" 강제 ② 스냅 전 사전 게이트: 체인이 aim×[0.75,1.25] 밖이면
> T-map 없이 Gemini만 재추첨(attempt당 ≤2회), 소진 시 **aim 최근접 롤 salvage**
> (⚠️ 원지시 "소진=miss"에서 이탈 — E2E 부검에서 pre_miss가 attempt를 태워
> 잠실 3/4·일방 4/4 소실→502 양산. salvage는 T-map 상한 동일·후보만 보존.
> 판단 플래그). pre_reject 계측 추가, 502 경로에도 PERF 로그.
> ③ 구조화 출력 체인 자기보고 필드는 **미채택** — 체인은 좌표에서 결정론
> 계산 가능(자기보고는 스키마 비대+신뢰 불가. 판단 플래그).
> **(B) end-aware 기하 (일방통행 언락 선행)** — end 좌표 요청은: 탐색 원을
> corridor 중점 기준 max(r0, |s−e|/2+1.0)로, 초기 팽창비 1.25(직선형), aim에
> 물리 하한 |s−e|×1.05(체인은 직선거리보다 짧을 수 없음 — 하한 없인 전 롤
> pre-reject 전멸, E2E 실증).
> E2E 실측(3라운드 12건 실호출): 루프 9건 = 명중 3·초과서빙 1·502 5 /
> 일방 3건 = 전부 502 — **단 이 일방 케이스(직선 5km에 목표 5km)는 물리적
> 불가능 요청**(도로 팽창 1.2x+ → 최소 6km). 파이프라인 자체는 성립(aim 5.2·
> 순응·pre_reject 0). ⚠️ 일방 실행가능성 전제: |s−e| ≲ target×0.8 — 프론트
> 가이드 or 서버 422 여부는 오너 판단 대기.
> 비용 실측: gemini/gen 1~9회(구 1~4) — 재추첨 스파이크 관찰 필요, 평균은
> 지연 6~29s.

## (구) v2.2 헤더

> **v2.2 (2026-07-20 긴급 재보정, 배포 대기)**: v2.1 배포(v66) 직후 실전 명중률
> 0 (연속 전패 3건 — 5.7/5.9/6.3 전부 초과+missed). 계측 13건 분석: ratio
> 중앙값 1.58·평균 1.61·범위 1.09~2.11 → 판정 **(c) 둘 다** — 상수 1.45가 실측
> 중심보다 낮아 초과 편향(전 miss가 초과) + 분산(σ≈0.27)이 커 어떤 고정
> 상수로도 폭 0.6 밴드 1회 명중 불가. 조치 3종:
> ① **적응형 팽창비** — attempt N 실측 ratio(클램프 [1.1, 2.2])를 N+1 체인
>    목표에 피드백(`chain=(target+0.2)/est_ratio`). 초기 상수 1.45→**1.6**
>    (실측 중앙값 — 표본이 서울·5km 편중인 점은 플래그).
> ② **전패 초과 서빙 캡 +1.0km** — 그 밖이면 502("6.3km는 5km의 답이 아니다").
>    캡 값 1.0은 판단 플래그.
> ③ **예상 시간 러닝 환산** — T-map 도보 시간 폐기, 거리 × 6'30"/km
>    (오너 확정. 기존 저장 코스는 backfill 필요 — 별도 SQL, 미실행).
> E2E 첫 실측(2건): 5.4km 밴드 내 명중 1 + 502 정직 실패 1 — v2.1의 0/4 대비
> 방향 개선(표본 적음 인지). attempt 로그에 aim 필드 추가(재보정 재료).
>
> **v2.1 (2026-07-20 최종 룰링 — Ivan 절충안, v66 배포됨)**: 합격 밴드
> **[target−0.1, target+0.5]** (폭 0.6 — 명중률 확보). 전패 시 **미달 후보 반환
> 금지**: 초과 최선만 target_missed=true로 서빙, 초과 0이면 **502
> route_generation_failed**(기존 실패 계약 재사용·쿼터 미소모 — 프론트 "다시
> 설정" 유도). 프롬프트 조준점 밴드 중심 `(target+0.2)/1.45` + "err slightly
> longer". (중간안 v2 [target, target+0.3]·전패 미달 최장 서빙은 같은 날 폐기.)
> 계기: TF 실기기 사례(낙산 5km→3.0km 7/18, 안양천 5km→3.9km 7/19 — 둘 다 전패
> 후 최선+missed 경로로 판정. attempt 로그 링버퍼 소실이라 간접 판정, 우회
> 코드 패스 없음은 확인).
> ⚠️ 관찰: target_missed·502 빈도, 시도 수 분포 — 계측 20건 축적 시
> _SNAP_INFLATION 재보정과 함께 리뷰.
>
> v1: 작성 2026-07-14, 배포 완료(v59~) — §10 확정: E2E는 "±0.5 이내
> 또는 target_missed=true" 계약 검증 / _SHORT_RATIO 완전 삭제(±0.5 일원화).
> ⚠️ 배포 후 route_gen 로그 20건 축적 시 _SNAP_INFLATION 재보정(§3 트리거).
> 진단 확정(실측 3건 + 코드 추적): 주범 = ⑴ Gemini 과소 기하(4km 요청에 직선
> 체인 2.2~2.8km — "avoid overshooting" 지시의 역효과) ⑵ T-map 스냅 팽창비
> 출렁임(1.13~1.74×, 보정 로직 없음) ⑶ 게이트가 하한 60%뿐(`_SHORT_RATIO=0.6`,
> 상한 없음 — "4km→2.5km"도 즉시 합격). 수정 방향 ①프롬프트 보정+②게이트
> 강화 결합 승인됨.

## 1. 요구 / 비요구

**요구**
- `POST /routes/generate` 결과가 **|total − target| ≤ 0.5km** 안에 들도록 게이트.
- 4회 전패 시 **|오차| 최소 후보 채택 + 응답에 플래그**(반려 안 함 — 최선+정직한 표시).
- 시도별 계측 로그(팽창비 재보정 재료 축적).
- 하위호환: 응답 additive 필드 1개, 기존 필드·에러 계약 불변.

**비요구 (발명 금지)**
- ③ 기하 후처리(waypoint 방사 확장/단축 후 T-map 재스냅) 안 함 — **후속 후보로만
  메모**(①+② 배포 후에도 미달률 유의미하면 v2).
- 팽창비 자동학습 안 함 — 로그 기반 **수동 재보정**(아래 §3 트리거).
- 반경 스케줄(`_radius_schedule`)·cap 4회·NO_PATH 폴백 구조 변경 없음.
- 스키마(DB) 변경 없음 — routes 테이블 그대로(플래그는 응답 전용, 저장 안 함).

## 2. ① 프롬프트 보정 (openai_service.py `_build_prompt` diff)

**보정 계수 도입**: `_SNAP_INFLATION = 1.45` (§3). 프롬프트에 주입할 직선 체인
목표 = `chain_target = round(target_distance_km / _SNAP_INFLATION, 1)`.

```diff
     # 탐색 반경: 수치가 오면 "near the start"를 명시적 반경 제약으로 교체.
     if radius_km is not None:
         area_text = (
             f"Keep every waypoint within {radius_km} km (straight-line) of the "
-            "start point, and design the route so its total length closely "
-            "matches the target distance (avoid overshooting). Provide ordered "
-            "waypoints with realistic WGS84 coordinates, "
+            "start point. Provide ordered waypoints with realistic WGS84 "
+            "coordinates, "
         )
     else:
         area_text = (
             "Provide ordered waypoints with realistic WGS84 coordinates near the start, "
         )
+
+    # ±500m 보장(ROUTE_DISTANCE_GUARANTEE): 도보 스냅 팽창을 프롬프트가 선보정.
+    # 직선 체인을 target/1.45로 뽑게 해 스냅 후 target 근처에 떨어지게 한다.
+    chain_target = round(target_distance_km / _SNAP_INFLATION, 1)
+    distance_text = (
+        f"Design a running route in South Korea whose final on-road length is "
+        f"about {target_distance_km} km. Note: the route will be snapped to "
+        f"real pedestrian roads, which typically makes it 1.3-1.7x longer than "
+        f"the straight lines between waypoints. Therefore place the waypoints so "
+        f"that the SUM OF STRAIGHT-LINE distances between consecutive waypoints "
+        f"(including return to start for loops) is about {chain_target} km. "
+    )

     return (
-        f"Design a running route in South Korea of about {target_distance_km} km. "
+        f"{distance_text}"
         f"Start at ({start.lat}, {start.lng}) and {end_text}. "
```
- **"avoid overshooting" 제거** — 과소 기하 유도 문구 삭제.
- 팽창 맥락("1.3-1.7x longer") + **직선 체인 목표 수치**를 명시 — 모델이 어림하지
  않고 계산 가능한 목표를 갖게.

## 3. 팽창비 확정 — `_SNAP_INFLATION = 1.45`

- 실측 3건: 1.13(뚝섬) / 1.50(여의도) / 1.74(서울숲) — 중앙값 1.50.
- **1.45 채택 근거**: 중앙값에서 소폭 하향 — 격자 도로망(저팽창 1.1x대)에서
  체인이 과하게 짧아지는 쪽(=버그로 리포트된 미달 방향)을 덜 만들도록 보수 조정.
  고팽창 지역의 오버슈트는 게이트+재시도가 잡는다.
- **⚠️ 표본 3건 한계 명시** — 지역·도로망 편향 가능. 상수는 `openai_service.py`
  상단에 근거 주석과 함께 두고 하드코딩 매직넘버 금지.
- **재보정 트리거(수동)**: §5 로그가 **20건 이상** 쌓이면 팽창비 중앙값을 재산정해
  상수 갱신(1줄 수정). 배포 보고에 리마인드 기재.

## 4. ② 게이트 강화 (route_service.py 반경 루프)

```
_TOLERANCE_KM = 0.5    # |actual − target| ≤ 0.5 → 합격 (기존 _SHORT_RATIO=0.6 대체)
```
**시도별 흐름** (기존 루프 구조·반경 스케줄·cap 4 유지):
1. Gemini → T-map 스냅 → `actual_km`.
2. `|actual − target| ≤ 0.5` → **즉시 채택(현행 OK와 동일한 조기 종료)**.
3. 밖이면 **후보 보관**(`(actual, route)` — 현행 SHORT 후보 보관 로직을 미달·초과
   양쪽으로 일반화) → 다음 반경 시도. (반경 확장은 미달 케이스에 유효, 초과
   케이스도 스케줄 그대로 진행 — 프롬프트가 체인 목표를 고정하므로 반경이 커져도
   오버슈트를 키우지 않고 시도 다양성만 확보.)
4. **4회 전패** → `best = min(candidates, key=|actual − target|)` 채택 +
   **`target_missed=True`**.
5. NO_PATH(웨이포인트<2·T-map 실패) 폴백은 **현행 그대로**(AI 추정 폴백 — 이
   경로로 채택되면 target_missed는 |오차| 기준으로 동일 판정).

에러 계약 불변: 전 시도 실패(후보 0)면 기존 `RouteGenerationFailed` 그대로.

## 5. 계측 로그 (재보정 재료)

시도마다 `logger.info` 1줄 (키·쿼리스트링 없음 — httpx 로그 함정 무관):
```
route_gen attempt=2 radius=2.0 chain_km=2.71 snapped_km=4.13 ratio=1.52 target=4.0 verdict=ok
```
- `chain_km` = Gemini 웨이포인트 직선 체인(코드에서 haversine 합 계산 — 진단
  스크립트와 동일 공식, 헬퍼 1개).
- 좌표·유저 id는 로그에 안 남김(위치 프라이버시). ratio 분포만 필요.

## 6. 응답 계약 — additive 플래그 1개

`RouteResponse`에 추가:
```python
target_missed: bool = Field(False, description="목표 ±0.5km 못 맞춘 최선 후보임 — 프론트는 '요청 거리와 달라요' 안내.")
```
- **`radius_expanded: bool` 선례와 대칭**(같은 응답의 기존 bool 플래그) — additive,
  기본 False라 기존 프론트 무영향.
- 오차 수치 필드는 **추가 안 함**: 프론트가 `total_distance_km − 요청 target`으로
  계산 가능(요청값을 이미 안다) — 필드 발명 회피.
- **소비 규칙**: `target_missed=true`면 결과 화면에 "요청 거리(4km)와 조금 달라요
  (4.8km)" 류 안내 배너. false면 표시 없음.

## 7. 테스트 계획 (Gemini 실호출 최소화)

**`tests/test_route_distance_guarantee_integration.py` (신규)** — mock 전수 + 실호출 1~2건:
- **mock 방식**: `test_push_notification`의 선례(패치 서버를 8001 포트에 별도 기동)
  재사용 — `openai_service.generate_route`·`map_service.get_pedestrian_route`를
  스크립트된 시퀀스로 패치.
  1. 1시도 합격: 스냅 4.2km(target 4.0) → 즉시 채택·`target_missed=false`·시도 1회.
  2. 미달 후 재시도 합격: [2.5, 3.7] 시퀀스 → 2시도 채택·false·Gemini mock 2회 호출 assert(비용 검증).
  3. 초과도 불합격: [4.8, 4.3] → 4.8 반려·4.3 채택 (**상한 게이트 신설 검증**).
  4. 4회 전패 → 최소오차 채택+플래그: [2.5, 2.7, 5.2, 3.2] → 3.2 채택·`target_missed=true`.
  5. NO_PATH 폴백 회귀: T-map 실패 시퀀스 → 기존 AI 추정 폴백 동작 유지.
  6. 프롬프트 단위 검증(호출 0회): `_build_prompt(4.0, …)` 문자열에 `about 2.8 km`
     (=4.0/1.45 반올림)·"1.3-1.7x" 포함 + "avoid overshooting" 부재.
- **실호출 E2E 1~2건**(회당 ~2원): 4km 생성 → `|total−4| ≤ 0.5` 또는
  `target_missed=true` 둘 중 하나 성립(비결정론 수용 어서션) + 로그 라인 형식 확인.
- **회귀**: `test_route*` 기존 스위트(생성 쿼터·free 429·RouteResponse shape).
  생성 코스는 테스트 후 삭제.

## 8. 비용 영향 요약
- **worst 불변**: Gemini cap 4회 그대로(게이트만 교체 — 시도 상한 추가 없음).
- **평균 중립~절감 논거**: 현행은 첫 시도가 60% 게이트를 거의 항상 통과(3/3 실측
  전부 1시도 종료)하지만 **오답을 통과**시키던 것. 신규는 ①이 첫 시도 명중률을
  올려(체인 목표 명시) 재시도 수요 자체를 줄인다 — 실측 기준 팽창 1.3~1.7 구간은
  1.45 보정 시 4km 목표에서 3.6~4.7km에 착지, 절반 이상이 1~2시도 내 합격 예상.
  전패해도 4회에서 멈추고 최선 후보 반환(추가 비용 없음).
- 크레딧 소진·spend cap(429→502) 리스크는 현행과 동일 — 시도 수 로그로 배포 후
  평균 시도 수 관찰.

## 9. 완료의 정의 (§A)
1. 신규 mock 6케이스 + E2E 1~2건 + route 회귀 통과.
2. DB 부수효과: 없음(routes 저장 로직 불변) — 응답 필드·로그 assert로 대체.
3. SQL 없음(스키마 무변경) 명시.
4. API_GUIDE: AI 코스 생성 행에 **±0.5km 보장 + `target_missed` 소비 규칙**(true면
   안내 배너) 추가.
5. 키 grep clean · 생성 코스 정리 · 커밋+푸시 → (지시 시) 배포+실생성 스모크
   1~2건 → **로그 20건 축적 후 팽창비 재보정 리마인드**.

## 10. 잔여 판단 지점 (확답 필요)
1. **E2E 실호출 어서션의 비결정론 수용**: "±0.5 이내 **또는** target_missed=true"
   로 어느 쪽이든 계약이 지켜졌는지만 검증(모델 비결정성 때문에 '반드시 ±0.5 명중'
   을 CI성 테스트로 강제하면 flaky). 이 방식 수용하는지.
2. **`_SHORT_RATIO` 완전 대체 확인**: 0.6 하한 게이트는 삭제되고 ±0.5 게이트로
   일원화된다(60% 미달이어도 후보 보관은 동일). 반경 확장 트리거가 "SHORT"에서
   "불합격 전반"으로 바뀌는 것 수용하는지 — 동작상 미달 케이스는 현행과 동일하게
   반경이 늘고, 초과 케이스만 새로 재시도가 생긴다.
