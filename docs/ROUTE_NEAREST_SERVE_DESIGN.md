# 가까운 코스 서빙 (Nearest-Serve) 설계

> 상태: **S1+S2+S3 구현 완료**(2026-11-20). S2·S3 함께 배포(S2 단독 배포 안 함). 오너 결정 6건 확정(§4).
> **S3 완료**: 재추첨도 밴드 실패 시 **±30%(_S3_DEV=0.30) 내 품질통과(비앵커·longest_retrace≤800)
> 최근접 서빙**(`_nearest_quality_serve`, verdict `nearest_served`). 응답 additive
> `requested_distance_km`·`actual_distance_km`·`distance_reason`(target_missed 재사용). ±30% 밖/
> 품질통과 0이면 502(reason `no_quality_candidate`/`unroutable_area`), **suggested_target_km 발신
> 중단**(스키마 필드 아님—계약 무변). nearest_served는 **주간 무료 한도 미차감**(예약 해제). 밴드 안
> 서빙 불변. 회랑 완화는 4·5단계 몫(미포함). 과거 실패 재생·효과·프론트 요약: §9·§10.
> **S2 완료(2026-11-20)**: in-band 0이면 over/under/mixed 무관 1회 재추첨(종전 all_under만 →
> `_v87`로 확장). all_under 결과 불변(chains=전 v87 동일). redraw_obs에 direction·aim 전후·
> nearest 전후 additive. 재추첨 추가 호출 ≈Gemini 8·T-map ≤8레그, 지연 ≈+4~5s. 효과: §9.
> 진실의 원천: `app/services/route_service.py` 서빙 판정 흐름, `docs/API_GUIDE.md` §에러규약.

## 1. 배경 · 제품 원칙 (오너 결정, 2026-11)

코스 생성 실패 조사에서 최근 실패 다수가 **후보가 허용 밴드를 벗어나 코스 없이 502**
(band_cap_zero/no_path)로 떨어졌다. 예: 요청 5km, 후보 6.8/6.1/6.5/6.4km → 실패 +
"6.0km로 줄여볼까요?" 안내. 오너 제품 원칙:

- 유저가 요청한 대로 코스를 만드는 것이 기본.
- 정확히 못 맞추면 **요청에 가장 가까운 코스를 주고 실제 거리를 안내**한다.
- 실패는 **코스 품질이 실제로 나쁘거나(retrace·spur 등 게이트 탈락) 경로가 없을 때만**.
- 현 "추천 거리만 보내고 코스는 안 주는"(`suggested_target_km`) 방식은 이 원칙으로 대체.

## 2. 현재 서빙 판정 흐름 (파일:행 근거)

| 상수 | 값 | 행 |
|---|---|---|
| 합격 밴드 `_within_band` | **[target−0.3, target+0.5]** | route_service.py:370-376 (175·176) |
| 초과서빙 창 `_OVER_SERVE_CAP_KM` | 1.0 → (target, target+1.0] | 187, `_serveable_over_cap` 574-582 |
| 초과서빙 retrace 상한 `_OVER_SERVE_MAX_SPUR_M` | 800 | 191 |
| 단독후보 품질바닥 `_FLOOR_SPUR_M` | 1200 | 195 |
| pre-gate `_PRE_GATE_BAND`/`_PRE_GATE_UNDERSHOOT` | (0.75,1.25)/0.50 | 208·214 |

판정 순서(`create_running_route` 1413~1560): in_band 있으면 tiebreak 서빙(verdict hit) →
없으면 `_serveable_over_cap`(비앵커·retrace≤800) missed 서빙 → quota 503 → far-pitstop →
**적응 재추첨(`all_under`=v87 전부 언더슈트일 때만)** → 실패 시 band_cap_zero/no_path →
502(`suggested_target_km=int(best_km−0.5)`, routes.py:857-878). 오늘 서빙 거리 구간 =
**[target−0.3, target+1.0]**. 오버슈트는 `all_under` False라 **재추첨조차 없이** 502.

## 3. 새 흐름 설계안 (S2·S3)

- **a. 밴드 내 → 그대로 서빙**(현행 유지).
- **b. 밴드 없음 → 방향 무관 재추첨**: `all_under` 제약 제거, `median(snap_km/chain_km)`로
  aim 재계산(오버슈트면 낮추고 언더슈트면 높임). 혼합(target bracket)이면 재추첨 1회로 밴드
  진입 확률↑, 실패 시 c로 폴백. 요청당 재추첨 1회 상한(비용·지연).
- **c. 그래도 없음 → 품질 게이트 통과 후보 중 요청 최근접 서빙**. additive 응답 필드
  `requested_distance_km`·`actual_distance_km`·`distance_reason(nearest_served)`. `target_missed`
  재사용(부호로 "길/짧은 코스" 배너). 초과서빙 retrace 컷을 전 방향·전 거리로 일반화한
  `_nearest_quality_serve`.
- **d. 실패는 품질통과 후보 0개 OR no_path일 때만**(502, reason `no_quality_candidate`/`unroutable_area`).
- **e. `suggested_target_km` 폐기**: 발신 중단(스키마는 1~2 빌드 유지 후 제거 — §D 역방향).
  프론트 "줄여볼까요?" 배너 자연 비활성, 신 배너(actual≠requested) 활성.

## 4. 오너 결정 (확정, 2026-11-20)

1. **허용 편차 한도**: **±30%**. 벗어나면 **실패 처리 + 숫자 없는 안내**(reason만, suggested 없음).
2. **한도 밖 처리**: **실패(502)** — ±30% 밖이면 최근접 서빙하지 않고 숫자 없는 안내.
3. **앵커 후보**: **제외 유지**(현 초과서빙과 동일 — 최근접 서빙 대상에서 앵커 제외).
4. **품질 게이트 서빙 상한**: **longest_retrace 800m 기준 유지**.
5. **무료 주간 한도 차감**: **요청과 다른 거리 서빙 시 차감하지 않음**(near-serve는 무차감).
6. **`suggested_target_km`**: **발신 먼저 중단**, 필드 제거는 **나중에**(1~2 빌드 후).

> S3 재설계 반영: (a)밴드 내 서빙 (b)±30% 내 최근접 서빙(차감 없음) (c)±30% 밖은 실패+숫자
> 없는 안내. suggested_target_km 발신 중단. 앵커 제외·retrace 800m 유지.

## 5. 시뮬레이션 (거리 기준 · 실패 10건)

`|cand−req|/req ≤ D` 중 요청 최근접 서빙. no_path는 2d로 전 한도 실패.

| 요청 | 후보 | ±30% | ±50% | 없음 |
|---|---|---|---|---|
| 5 | 7.8,4.4,7.3 | 4.4 | 4.4 | 4.4 |
| 7 | 9.8,9.1,8.7,11.2,9.1,8.3 | 8.3 | 8.3 | 8.3 |
| 10 | 13.9,8,13.8 | 8 | 8 | 8 |
| 5 | 6.8,6.1,6.5,6.4 | 6.1 | 6.1 | 6.1 |
| 5 | 6.5,8.6,8.7,7.6,7.5 | 6.5 | 6.5 | 6.5 |
| 3 | 3.5,4.6,4.8 | 3.5 | 3.5 | 3.5 |
| 5 | 7.9,3.9 | 3.9 | 3.9 | 3.9 |
| 5 | 8.4,3.4,7.7 | 실패 | 3.4 | 3.4 |
| 5 | 7.2,12.6,9.1,5.6(no_path) | no_path | no_path | no_path |
| 5 | 7.8,3.9,3.1 | 3.9 | 3.9 | 3.9 |
| **서빙/실패** | | **8/2** | **9/1** | **9/1** |

**한계**: 기록에 품질(retrace·engine·polyline)이 없어 **거리로만** 계산 → 서빙 건수는 **상한치**.
품질 필터로 실제는 줄 수 있음(#9 no_path가 그 예). → **S1 관측이 이 공백을 메움**(아래).

## 6. S1 — 관측 추가 (구현됨, 서빙 무변경)

`gen_failures.meta`에 스키마 변경 없이 additive로 후보별 상세 적재:
- **`candidate_obs`**(배열, 후보마다): `km`·`engine`·`longest_retrace_m`·`band`(in/over/under)·
  `reject`(out_of_band_under/out_of_band_over/retrace_over_cap/anchor_excluded/serveable_over/in_band).
- **`redraw_obs`**(요청 단위): `ran`(bool)·`skip_reason`(not_all_under/snap_errors_present/no_v87_chain/no_gen_cands/none).

서빙 판정·응답 **무변경** — 실패 기록 직전 관측만 부가(예외는 삼키고 로그). `no_gen_cands`
사이트는 `candidate_obs=[]`·`redraw_obs.skip_reason="no_gen_cands"`.

## 7. 위험 · 테스트 · 구현 단계

- **위험**: R1 품질저하 서빙(완화=품질게이트 유지) · R2 무료한도 소진 체감(오너 결정5) ·
  R3 재추첨 비용(1회 상한) · R4 응답계약(additive·Optional) · R5 far/one-way 상호작용.
- **테스트**: 시작좌표 3+ 매트릭스 · 거리 시뮬 유닛 · mock 통합(near-serve 200 + additive) ·
  회귀(기존 서빙 그린) · 쿼터 부수효과 · gen_failures 적재 assert.
- **구현 단계**: **S1 관측(본 커밋)** → S2 재추첨 확대 → S3 최근접 서빙+응답필드 → S4 필드 정리.

## 9. S2 효과 실측 (변경 전/후, 한남동·성북동 5km ×5, 2026-11-20)

`scripts/measure_s2_effect.py`로 변경 전(부모 커밋 워크트리)·후(S2) 각 5회:

| 지점 | **밴드 안 서빙** 전→후 | 502 전→후 | 밴드 밖 서빙 전→후 |
|---|---|---|---|
| 한남동(37.54,127.00) | **0/5 → 1/5** | 5 → 4 | 0 → 0 |
| 성북동(37.59,126.99) | **0/5 → 1/5** | 5 → **2** | 0 → **2**(missed 서빙) |

**해석**: 변경 전엔 두 지점 다 **전 후보가 over(요청보다 김) → all_under False → 재추첨 0 → 전부 502**
(gemini=9, redraw 0). S2 후엔 **over에도 재추첨 발동**(gemini=17=9풀+8재추첨, redraw 검출 한남1·성북2)
→ **밴드 안 서빙 0→1씩, 성북 502 5→2**(재추첨 hit 또는 missed 서빙으로 구제). 재추첨이 항상
in-band를 맞추진 않지만(aim 보정의 한계) **보장 502를 재추첨 기회로 전환**이 핵심 개선. Gemini
비결정성이라 N=5는 신호 수준(절대값 아님). **추가 호출**: 재추첨 시 Gemini +8·T-map ≤8레그,
**지연 +4~5s**(9.9s vs 4.7s). 임시 데이터(route 4·gen_failures 16) 전삭(잔존 0).

## 10. S3 — 과거 실패 재생·비율·프론트 요약 (2026-11-20)

**과거 실패 재생**(이준 2026-11-18~19 gen_failures 10건, Gemini/T-map 실호출 0 — snaps 거리
재생): S3 적용 시 **서빙 9 / 실패 1**. 실패 1 = target 5·후보 [3.4,7.7,8.4](±30% [3.5,6.5] 밖).
⚠️ 10건 모두 candidate_obs(품질) 없는 과거 기록이라 **거리 기준 상한치**(품질 탈락 반영 시 ≤9).

| target | 후보(snaps) | S3 결과 |
|---|---|---|
| 5 | 4.4,7.3,7.8 | 서빙 4.4 | | 7 | 8.3,8.7,9.1,9.1,9.8,11.2 | 서빙 8.3 | | 10 | 8,13.8,13.9 | 서빙 8 |
| 5 | 6.1,6.4,6.5,6.8 | 서빙 6.1 | | 5 | 6.5,7.5,7.6,8.6,8.7 | 서빙 6.5 | | 3 | 3.5,4.6,4.8 | 서빙 3.5 |
| 5 | 3.9,7.9 | 서빙 3.9 | | 5 | **3.4,7.7,8.4** | **실패(±30% 밖)** | | 5 | 5.6,7.2,9.1,12.6 | 서빙 5.6 |
| 5 | 3.1,3.9,7.8 | 서빙 3.9 | | | | |

**최근 14일 서빙 비율**(routes 읽기 전용, 순환 12건): **밴드 안 83%(10) · 밴드 밖 17%(2)**
(verdict: hit 7·hit_redraw 1·missed 4).

### §10.1 프론트 연동 요약 (RouteResponse additive, 2026-11)
| 필드 | 타입 | 의미 |
|---|---|---|
| `requested_distance_km` | `float \| null` | nearest_served일 때 유저 요청 거리. 그 외 null |
| `actual_distance_km` | `float \| null` | nearest_served일 때 실제 서빙 거리(=total_distance_km). 그 외 null |
| `distance_reason` | `string \| null` | `"nearest_served"`만(요청과 다른 거리 최근접 서빙). null=정상/missed |
| `target_missed`(기존 재사용) | `bool` | nearest_served는 항상 true. 부호(actual−requested)로 "N.Nkm 길/짧은 코스" 배너 |

**소비 규칙**: `distance_reason=="nearest_served"`면 "요청과 다른 거리의 코스예요"(actual/requested로
문구), 그 외 기존 그대로. **실패 502**: `detail.reason`이 `no_quality_candidate`(±30% 내 쓸 만한
후보 없음) / `unroutable_area`(경로 없음) — `suggested_target_km`은 **더 이상 안 옴**(S3가 가까운
코스를 주므로). 기존 필드·형식 불변.

**예시 — nearest_served 성공(200)**:
```json
{"route_id":"…","summary":"6.5km 순환 코스","total_distance_km":6.5,"target_missed":true,
 "requested_distance_km":5.0,"actual_distance_km":6.5,"distance_reason":"nearest_served",
 "waypoints":[…],"polyline":[…]}
```
**예시 — 실패(502)**:
```json
{"detail":{"error":"route_generation_failed","message":"코스 생성에 실패했어요. 잠시 후 다시 시도해 주세요.","reason":"no_quality_candidate"},"error_code":"route_generation_failed"}
```

## 결정 이력 · 재검토 조건

- **결정**(2026-11, 오너): 밴드 밖 실패 → 가까운 코스 서빙으로 대체. 품질/no_path만 실패.
- **근거**: 저밀도·장거리 실패 다수가 "쓸 만한 후보 있는데 거리 밴드로 버림"(조사 실측).
- **재검토 조건**: ① S1 관측 1~2주 축적 후 reject 사유 분포로 허용 한도(결정1) 확정 ②
  near-serve 품질 불만(retrace 큰 코스 서빙) 리포트 시 결정4 상향 재검 ③ 무료 차감 불만(결정5).
