# 코스 모양 품질(shape quality) 설계 — 왕복·가지·매듭·지그재그

> 상태: **조사·설계만**(2026-11-20). 코드·DB·테스트 무변경. DB 읽기 전용.
> 실측 도구: `scripts/measure_hill_shape.py`. 언덕은 `docs/HILL_AVOID_DESIGN.md`.

## 0. 문제 (실측 사례)

성북동(37.5966,126.9967) 5.0km 요청 → **4.8km 순환(route 27acb82e, 2026-11-20 13:00)** 서빙.
한 코스에 ① 출발 구간 왕복 ② 경유점1 막다른 가지 왕복 ③ 경유점2 근처 작은 고리(매듭)
④ 경유점3 골목 지그재그가 모두 있었다. **현재 품질 게이트가 이를 못 걸러 서빙됨**(아래 §3).

## 1. 현재 품질 판정이 보는 지표 (file:line)

| 지표 | 함수·위치 | 측정 | 서빙 사용 |
|---|---|---|---|
| **longest_retrace_m**(주력) | `_spur_metrics` `route_service.py:574` | 최장 **연속** 이중주행 회랑(m) | **게이트**: `_OVER_SERVE_MAX_SPUR_M=800`(:191)·`_FLOOR_SPUR_M=1200`(:195) |
| long_spur_count / micro_reversals | `_spur_metrics` `:574`(long_m=100·micro_m=50) | >100m 스퍼 수 / <50m 반전 수 | 관측(cand_quality) |
| retrace(레거시) | `_polyline_retrace` `:555`(near=`_RETRACE_NEAR_M=20` :545) | 반전 선분 **개수** | tiebreak 3순위(`_best_in_band`) |
| zigzag_score | `_zigzag_score` `:511` | 웨이포인트 체인 >120° 반전 수 | tiebreak 2순위 |
| park_coverage | `_park_coverage` `:530`(radius 300m) | 중간 wp의 공원 300m 근접 비율 | tiebreak 1순위 |
| max_gap_m | `_polyline_max_gap_m` `:547` | 인접점 최대 간격 | 관측 전용 |
| crossing_count | `map_service.py:630` | 횡단보도 수 | tiebreak 4순위 |
| self_intersections | (factory 전용) | 그래프 순환 자기교차 | **서빙 미사용**(CLAUDE.md §C: T-map 실경로엔 과다카운트, 육안이 기준) |

**tiebreak 순서**(`_best_in_band`): park desc → zigzag asc → retrace asc → crossing asc → 거리근접.
**핵심 공백**: 서빙 **게이트는 `longest_retrace_m`(단일 최장 스퍼) 하나**뿐. "작은 가지 여러 개·총 왕복 비율·매듭"은 게이트에 없음 → §3처럼 다수 가지가 통과.

## 2. 제안 모양 지표 (polyline만으로 계산)

`scripts/measure_hill_shape.py`에 구현(실측·분포에 사용):
- **retrace_ratio_pct**: 경로 길이 중 비인접 구간의 20m 내로 되돌아오는 비율(%) — "총 왕복 비중". longest_retrace(단일)가 못 보는 **누적 왕복**을 포착.
- **retrace_m**: 왕복 총 길이(m).
- **n_branches_gt50m**: 50m 초과 연속 왕복 run 수 ≈ **막다른 가지 개수**.
- **sharp_turns_per_km**: 꼭짓점 회전각 >100° 빈도/km ≈ **골목 지그재그**.
- **self_cross**(참고·비신뢰): 비인접 선분 교차 수 ≈ 매듭. ⚠️ **현 구현은 밀집 polyline에서 과다카운트**(아래 실측서 평지 루프도 18–25) — CLAUDE.md §C의 self_intersections 경고와 동일. **육안/스무딩 전처리 전까지 게이트 금지, 관측만**.

## 3. 최근 서빙 코스 분포 + 성북동 위치 (읽기 전용, n=60 순환)

`python scripts/measure_hill_shape.py --dist 60`:

| 지표 | median | p75 | p90 | max | **성북동(27acb82e)** |
|---|---|---|---|---|---|
| retrace_ratio_pct | 29.3 | **42.7** | 62.6 | 86.3 | **43.3 ≈ p75** |
| longest_retrace_m | 434 | 754 | 1127 | 4200 | **446 ≈ median** |
| n_branches_gt50m | 8 | **10** | 12 | 18 | **10 = p75** |
| sharp_turns_per_km | 0.5 | 0.7 | 1.0 | 4.9 | 0.4(<median) |

**판정**: 성북동은 retrace 비율·가지 수에서 **p75**(중앙값보다 나쁨)지만, **단일 최장 스퍼(446m)는 median**이라 **현 게이트(longest_retrace>800/1200)를 전부 통과** → 그래서 서빙됨. **전체 분포 자체가 모양-노이즈가 큼**(median 왕복 29%·가지 8개) — 현 단일-스퍼 게이트가 "다수 가지·누적 왕복"을 방치. (sharp_turns는 내 >100° 임계가 "골목 지그재그"를 덜 잡음 — 스냅 detail 레벨 필요, 지표 보정 대상.)

## 4. 경유점이 순환선 밖에 찍혀 가지가 생기는 원인 (코드)

1. 경유점 좌표 결정: `route_service.py:1276-1291`(유저 POI) 또는 `:1292-1322`(Kakao 검색·랭킹).
2. 웨이포인트에 **좌표 덮어쓰기**: `:1323-1330`(`wp.coordinate = pick.coordinate`, is_pitstop) — AI 체인과 동떨어진 실 POI 좌표로 교체.
3. T-map에 via로 전달: `:1338`(중간 wp 전부).
4. **T-map 보행자 API는 경유점 제약 미지원** → `map_service.py:586-618` **leg별 분리 라우팅**(start→wp→…→end 각각 최단). 경유점이 순환선 밖이면 **"거기까지 갔다 되돌아오는" 막다른 가지(out-and-back) 발생**.
5. **가지 잘라내기(trim) 없음**: `_spur_metrics`로 **측정만**, polyline에서 가지를 제거하는 코드 없음. 임계 초과 시 **재추첨(regenerate)뿐**(`_spur_rescue` `:1018-1061`·floor redraw `:1471-1492`) — 이번 가지를 고치는 게 아니라 운에 맡겨 새로 뽑음. `_ensure_polyline_through` `:447-463`은 마커를 경로 40m 내로 끌어올 뿐 trim 아님.

**줄이는 방법 비교**:
- **(a) 경유점 위치밴드 강화**: `map_service._in_position_band`(현 [200m, target×0.5])를 **순환선 근접(경로 예상 회랑 내)**으로 조여 off-loop POI 채택↓. 생성 전 차단·단순. 단 밴드 내 POI 없으면 폴백.
- **(b) 가지 잘라내기 후처리**: 서빙 전 polyline에서 out-and-back run을 **감지·절단**(start/end 왕복, 경유점 왕복). 효과 직접적이나 경유점을 "지나되 가지 없이"는 기하적으로 불가할 때가 있어 **경유점을 경로 위 최근접으로 이동**(마커 정합) 필요. 중간 복잡도.
- **(c) 모양 점수 게이트**(아래 §5): 재추첨 유도를 longest_retrace 단일이 아니라 retrace_ratio·가지수로 확장 → 가지 많은 후보를 자연 탈락·재추첨. S3 품질축과 정합.
- **권고**: **(c)+(a) 병행**(게이트로 거르고 밴드로 예방), (b)는 후속(정밀 trim).

## 5. 서빙 판정 기준 초안 + 실패 증가 추정 (임계 미정=오너)

현 게이트에 **모양 축 추가**(S3 품질 게이트에 합류):
- `retrace_ratio_pct > T_r`(초안 ~45–50, median 29·p75 43 기준) → 품질 벌점/재추첨.
- `n_branches_gt50m > T_b`(초안 ~10–12) → 벌점/재추첨.
- longest_retrace 게이트는 유지. self_cross는 **관측만**(지표 비신뢰).

**실패 증가 추정**(n=60 분포 기준, 순수 탈락 가정 시):
- `retrace>45 OR branches>11` 컷 → 약 **p75~p80 초과분(~20–25%)**이 1차 탈락 대상. 단 S3는 탈락이 아니라 **"품질 통과 최근접 서빙"**이라, 재추첨으로 더 나은 후보를 찾으면 실패가 아니라 **재추첨 비용**(Gemini 콜↑). **순수 502 증가는 "전 후보가 컷 초과 + 재추첨도 실패"인 경우만** — 분포상 소수(한남동 같은 지형 제약 지역). **정확 추정은 H1/S1식 관측 선행 필요**(현재는 거리/고도처럼 모양도 gen_meta에 미기록).
- → **측정 먼저**: 서빙 코스의 retrace_ratio·branches를 gen_meta에 기록(관측)해 컷 임계별 탈락률을 실측한 뒤 확정. 임계 **전부 미정**.

## 6. ROUTE_NEAREST_SERVE / HILL_AVOID와 맞물림·순서
- S1 candidate_obs(이미 구현)에 **모양 지표(retrace_ratio·branches) 추가 기록** = "측정 먼저"(거리·고도와 동형). → **SQ1(관측)**.
- S3 품질 게이트에 모양 축 + §4(a) 밴드 강화. → **SQ2(서빙)**.
- §4(b) 정밀 trim은 후속. → **SQ3**.
순서: SQ1(관측, 독립) → SQ2(S3 동반) → SQ3.

## 7. 오너 결정 필요 (각 1줄 추천)
1. **모양 축 게이트 임계(retrace_ratio/branches)**: 미정 — 추천 **SQ1 관측 분포로 확정**(예 p80). 이유: 추측 컷은 실패율 미지(§B).
2. **벌점 vs 탈락 vs trim**: 미정 — 추천 **(c)게이트 벌점+(a)밴드, trim 후속**. 이유: nearest-serve 정합·단순.
3. **self_cross 게이트화 여부**: 미정 — 추천 **관측만(게이트 금지)**. 이유: 현 구현 과다카운트(§2·CLAUDE.md §C).
4. **sharp_turns 임계·정의**: 미정 — 추천 **스냅 detail 레벨 재정의 후**. 이유: 현 >100°가 골목 지그재그를 덜 잡음.
5. **경유점 밴드 조이기 강도**: 미정 — 추천 **순환 회랑 근접 우선, 밴드 내 0이면 현행 폴백**. 이유: 가지 예방 vs 가용성 균형.

## 결정 이력·재검토 조건
- **결정(2026-11-20)**: 현 서빙 게이트가 단일 longest_retrace만 봐 다수 가지·누적 왕복을 방치(성북동 p75인데 통과). 모양 축 추가 + 측정 선행 방향.
- **근거**: n=60 분포에서 성북동 retrace 43%(p75)·가지 10(p75)이나 longest 446m(median)이라 전 게이트 통과(실측).
- **재검토 조건**: ① SQ1 관측으로 컷 임계·실패율 확정 ② sharp_turns·self_cross 지표 신뢰도 개선 후 게이트 편입 ③ T-map 경유점 제약 미지원이 해소되면 §4 재설계.
