# 언덕 피하기(avoid_hills) 실효화 설계 — 고도 데이터 기반

> 상태: **조사·설계만**(2026-11-20). 코드·DB·테스트 무변경. 유료 API·키 발급 없음.
> 실측 도구: `scripts/measure_hill_shape.py`(읽기 전용). 모양 품질은 별도
> `docs/ROUTE_SHAPE_QUALITY_DESIGN.md`.

## 0. 문제

한남동(grid 37.54, 127.00)에서 5.0km + `avoid_hills=true` 요청 → 5.6km 순환이 서빙됐고
경로가 남산 자락(그랜드 하얏트·국립극장 방면) 급경사를 통과했다. 원인: `avoid_hills`가
**Gemini 프롬프트 문구로만** 반영되고, 서버에 고도 조회·후보 필터가 없다(아래 §1).

## 1. 현황 추적 (file:line)

### 1.1 avoid_hills 흐름 — **프롬프트 문구 전용, 데이터 필터 0**
- 스키마: `app/models/schemas.py:194`(`AiCourseSettings.avoid_hills`)·`:296`(patch)·`:604`(RouteRequest 오버라이드)·`:31`(avoid 태그 `오르막많음`).
- 선호 병합: `app/services/route_service.py:135-158` `_resolve_course_prefs`(body>설정>기본), `:152` avoid_hills 병합, `:156-157` `avoid_hills and terrain=='hill' → terrain='mixed'`.
- 충돌 태그 제거: `route_service.py:889-902` `_filter_conflicting_avoid_tags`(terrain='hill'이면 `오르막많음` 태그 drop).
- 프롬프트화: `app/services/openai_service.py:140-147` `AVOIDANCE_INSTRUCTIONS`(`오르막많음`→"prefer flat terrain and avoid steep hills")·`:150-173` `_prefs_text`(`:163-164` `avoid_hills → "avoid steep hills"`)·`:194-312` `_build_prompt`(SOFT PREFERENCES 주입).
- 생성→스냅→점수→서빙: `route_service.py:1198-1200`(후보)·`:1340-1392`(T-map 스냅)·`:1415-1461`(점수·in-band 선택). **고도 지표 0.**
- 관측 전용: `route_service.py:1442-1445` gen_meta.prefs에 avoid_hills 기록(비기능).
→ **결론: avoid_hills는 프롬프트 문구만. 서버 측 고도 기반 필터·점수 전무(확인됨).**

### 1.2 저장소의 고도 코드·데이터 유무
- **러닝 기록엔 고도 있음(단 기기 GPS 전용)**: `db/2026-07-06_gps_tracks.sql:30` `splits.elev_gain_m`; `app/services/track_service.py:12-13,33`(`ELEV_HYSTERESIS_M=3`, 기압계 없는 폰 ±5m 노이즈)·`:270-289`(기기 alt 누적)·`:316-320`(polyline에 `alt` 보존 — **주석: "avoid_hills 실효 측정 소스"**, Ivan 계약). **순수 계산, 외부 API 0.**
- **T-map 보행자 응답엔 고도 없음**: `app/services/map_service.py:712-725`(geometry를 `[lng,lat]`만 파싱, z/alt 미추출); `Coordinate`(schemas.py)는 lat/lng만.
- **생성 코스엔 고도 없음**: Gemini 좌표·T-map 2D. DEM/SRTM/외부 고도 API **전무**(app/·scripts/·db/ 전수 grep 0).
→ **결론: 생성·서빙 경로에 고도 데이터 0. 유일한 고도는 "이미 달린 기록"의 노이즈 많은 기기 GPS(생성엔 무용).** 즉 avoid_hills 실효화엔 **외부 고도 소스 신규 도입이 필수.**

## 2. 고도 데이터 소스 비교 (공식 문서 기준)

| 소스 | 비용 | 호출 한도 | 한국 해상도 | 지연 | 상업 약관 | 운영 부담 |
|---|---|---|---|---|---|---|
| **Open-Meteo Elevation** | 무료(비상용)·상용 유료키 | 비상용 <10k/일·5k/시·600/분, 100좌표/콜 | Copernicus DEM GLO-90 **90m** | API 왕복(수십~수백 ms, SLA 없음) | **비상용만 무료**(상용은 `customer-` 유료) — FreshRun은 상용이라 **무료 사용 불가**(함정, CLAUDE.md §C) | 낮음(외부 의존) |
| **OpenTopoData(공개)** | 무료 | 100좌표/req·**1 req/s·1000/일** | SRTM **30m**(±60°)·Copernicus·ASTER 선택 | API 왕복 | 공개 호스트 약관 모호 | 낮으나 1k/일 한도 |
| **OpenTopoData(자가호스트)** | **$0(오픈소스)** | 무제한(자기 서버) | SRTM 30m / Copernicus GLO-30 / NGII 등 래스터 탑재 가능 | **<10ms(로컬 래스터)** | 오픈소스 라이선스 + 데이터셋 라이선스 각각 확인 | 중(래스터 번들·서버 상주) |
| **Google Elevation API** | **$5/1k**(월 5k 무료, 볼륨할인) | 512좌표/콜 | 보간(수십 m급) | API 왕복 | 상용 허용(유료) | 낮음(외부 의존·과금) |
| **자가 DEM 번들(서울 bbox)** | **$0 상시**(1회 구축) | 무제한 | **NGII 5m**(항공) 또는 GLO-30 30m, 서울만 보관 | **<10ms(인메모리/타일)** | NGII 90m=공공데이터 개방(이용제한 없음)·5m는 라이선스 개별 확인(일부 CC BY-NC-ND) | 중(타일 보관·갱신) |

**출처**: [Open-Meteo Elevation docs](https://open-meteo.com/en/docs/elevation-api) · [Open-Meteo pricing](https://open-meteo.com/en/pricing) · [Open-Meteo terms](https://open-meteo.com/en/terms) · [OpenTopoData SRTM](https://www.opentopodata.org/datasets/srtm/) · [OpenTopoData GitHub(자가호스트)](https://github.com/ajnisbet/opentopodata) · [Google Elevation 과금](https://developers.google.com/maps/documentation/elevation/usage-and-billing) · [NGII DEM(공공데이터포털)](https://www.data.go.kr/data/15059920/fileData.do) · [NGII 지도 다운로드](http://map.ngii.go.kr/).

**권고(미확정·§5)**: **자가 호스트 DEM**(서울 bbox만, SRTM/GLO-30 30m 또는 NGII) — 상시 $0·무한도·<10ms·한국 커버·외부 의존 0. 프로젝트 "그늘 인지 코스" 파킹의 자가호스트 GIS 선택과 동형(CLAUDE.md 파킹). **프로토타입/실측은 Open-Meteo(무료 비상용)로 하되 상용 서빙엔 쓰지 않는다.**

## 3. 실측 (무료 Open-Meteo, 소량 호출 — 연구용)

`scripts/measure_hill_shape.py`로 DB의 실제 서빙 코스 polyline을 읽어 샘플 간격별 측정:

| 코스 | 샘플 100m | 50m | 30m |
|---|---|---|---|
| **한남동(5.0→5.6km, 제보)** 누적상승 | **145m** | 180m | 221m |
| 〃 km당 상승 | **42m/km** | 45 | 47 |
| 〃 최대 구간경사 | **13.9%** | 27.3 | 36.7 |
| **여의도공원(평지 대조)** 누적상승 | **18m** | 91m | 94m |
| 〃 km당 상승 | **6m/km** | 24 | 23 |
| 〃 최대 구간경사 | **3.3%** | 28.0 | 30.0 |

**판정**: 한남동 vs 여의도 = **km당 상승 42 vs 6(7×)**, 최대경사 13.9% vs 3.3%. 명확히 분리.

**샘플 간격 민감도(중요)**: Copernicus GLO-90은 **90m 네이티브 해상도**라 30/50m 오버샘플은 DEM 보간·교량/지하차도 노이즈를 긁어 수치를 부풀린다 — 여의도 최대경사가 3.3%(100m)→30%(30m)로 **노이즈성 급등**(실제 여의도는 평지). 따라서 **① 샘플 간격은 DEM 해상도에 맞춰 ~90-100m** ② 더 촘촘히 보려면 `track_service.ELEV_HYSTERESIS_M=3` 같은 **히스테리시스 스무딩**으로 노이즈 억제. **누적상승보다 km당 상승이 간격에 덜 민감(한남동 42-47 일관)**해 1차 지표로 적합.

재현: `python scripts/measure_hill_shape.py`(고도+모양) · `--no-elevation`(모양만) · `--ids <uuid>…`.

## 4. 설계안

### 4.1 벌점(soft) vs 탈락(cutoff)
- **탈락(임계 초과 후보 제거)**: 깔끔하나 **산지(한남동)는 전 후보가 언덕→전멸→502**. ROUTE_NEAREST_SERVE 원칙("항상 서빙, 못 맞추면 가까운 것+안내")과 충돌.
- **벌점(점수 강등)**: `avoid_hills=true`일 때 오르막 지표를 **tiebreak/품질점수에 벌점**으로 → 가장 완만한 후보가 이김. 전부 언덕이면 **가장 완만한 것 + "이 지역은 언덕이 많아요" 안내** 서빙.
- **권고 = 하이브리드(벌점 우선)**: 평지 대안이 있으면 언덕 후보 강등(사실상 탈락), 전부 언덕이면 최완만 서빙. nearest-serve와 정합.

### 4.2 임계값 초안(실측 근거, 미정=§5)
- **1차 지표 = km당 상승(ascent_per_km)**: 평지 <15, 보통 15–30, 언덕 >30. 한남동 42, 여의도 6. **벌점 시작 ~20, 강한 벌점 ~35**(초안).
- **보조 = 최대 구간경사(max_grade, 100m 샘플)**: 평지 <8%, 한남동 14%. **주의 >10%**(초안).
- 전부 미정 — §5.

### 4.3 요청당 추가 호출·지연·월비용(자가호스트 기준)
- 고도는 **서빙 후보(in-band finalists, 보통 1–5개)만** 필요. 5km를 100m 샘플 = ~50점/후보 × 3 = ~150점.
- **자가호스트 DEM**: 외부 호출 **0회**, 인메모리 래스터 조회 ~150점 **<10ms**, **월 $0**.
- (대안)Open-Meteo/Google: 100–512좌표/콜 → 1–3콜/요청, **+300ms–1s**. Google은 ~2콜/생성 × 생성량; 월 1만 생성 가정 ≈ 2만콜 ≈ **$100/월**(5k 무료 차감). → 상용은 자가호스트 권고.

### 4.4 폴백(필수)
고도 조회 실패·타임아웃이면 **고도 벌점을 건너뛰고 기존 서빙 동작 그대로**(avoid_hills는 프롬프트 문구로만 남음). 자가호스트는 상주라 실패율 낮음. §C "외부 의존 실패가 코스 생성을 막지 않음" 원칙.

### 4.5 전부 언덕 지역(한남동) 동작 — 선택지
- **(A·권고)** 가장 완만한 후보 서빙 + additive 안내(`terrain_note: "hilly_area"`·`ascent_per_km` 실측치) → 클라 "이 지역은 언덕이 많아 완만한 코스로 드려요".
- **(B)** 실패(502 `area_too_hilly`) — nearest-serve 원칙 위배라 비권고.
- 미정 — §5.

### 4.6 생성 단계 경유점을 낮은 고도로 유도
- **(a)** 프롬프트 문구만(현행) — 실효 없음(제보가 증거).
- **(b·권고)** **후보 풀 생성 후 고도 점수화**(S2/S3 품질 게이트에 ascent 축 추가) — 가장 완만 후보 선택. 구현 단순·측정 선행 가능.
- **(c)** 고도 인지 경유점 시딩(낮은 고도 회랑으로 유도) — 복잡, 후속. riverside/저지대 회랑 사전목록 필요.

### 4.7 ROUTE_NEAREST_SERVE(S2·S3)와 맞물림 + 구현 순서
`docs/ROUTE_NEAREST_SERVE_DESIGN.md`의 S3 "품질 게이트 통과 후보 중 최근접 서빙"에 **오르막을 품질 축으로 추가**하면 자연 통합(retrace와 나란히). 순서:
1. **H1(관측 선행)**: 자가호스트 DEM 도입 + 후보별 `ascent_per_km`·`max_grade`를 **gen_meta/gen_failures에 기록만**(서빙 무변경). S1 candidate_obs 확장과 동형 — **측정 먼저**(§B).
2. **H2**: S2/S3 착수 시 `avoid_hills=true`면 S3 품질점수에 고도 벌점 합류 + 4.5 안내필드.
3. **H3(후속)**: 4.6(c) 고도 인지 시딩.
→ **H1은 S2/S3와 독립**(관측만)이라 먼저 가능. H2는 S3와 동반.

## 5. 오너 결정 필요 (각 1줄 추천)
1. **고도 소스**: 미정 — 추천 **자가호스트 DEM(서울 bbox)**. 이유: 상시 $0·<10ms·외부의존 0·상용 가능(Open-Meteo 무료는 상용 불가).
2. **DEM 데이터셋/해상도**: 미정 — 추천 **GLO-30 또는 NGII 30m 1차**(5m는 라이선스 확인 후). 이유: 러닝 경사 판정엔 30m로 충분, 5m는 용량·라이선스 부담.
3. **벌점 vs 탈락**: 미정 — 추천 **하이브리드(벌점 우선)**. 이유: 산지 전멸 502 방지(nearest-serve 정합).
4. **임계값(ascent_per_km / max_grade)**: 미정 — 추천 **벌점 시작 20·강벌점 35 / 주의 10%**(실측 근거, H1 분포로 보정).
5. **전부 언덕 지역 동작**: 미정 — 추천 **(A) 최완만 서빙 + 안내**. 이유: nearest-serve 원칙.
6. **경유점 유도 방식**: 미정 — 추천 **(b) 후보 풀 고도 점수화**. 이유: 단순·측정 선행·S3 정합.
7. **H1 관측 선도입 여부**: 미정 — 추천 **예(S2/S3 전 H1 먼저)**. 이유: 임계값을 추측 아닌 실측 분포로 정함(§B).

## 결정 이력·재검토 조건
- **결정(2026-11-20, 조사)**: avoid_hills 실효화엔 외부 고도 소스 필수(생성·서빙 경로 고도 0 확인). 벌점·nearest-serve 정합 방향.
- **근거**: 한남동 42m/km vs 여의도 6m/km 실측 분리; 프롬프트-only가 제보로 반증.
- **재검토 조건**: ① H1 관측 분포로 임계값 확정 ② 자가호스트 DEM 라이선스(NGII 5m) 실확인 ③ 상용 전환 시 Open-Meteo 무료 금지 재확인.
