# 가까운 코스 서빙 (Nearest-Serve) 설계

> 상태: **설계 + S1(관측) 구현**. S2·S3는 오너 결정 6건 확정 후 착수.
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

## 4. 오너 결정 필요 (전부 **미정**)

1. **허용 편차 한도**: ±30% / ±50% / 없음 (거리별 비대칭 가능). — **미정**
2. **한도 밖 처리**: 실패(502) vs 무조건 최근접 서빙. — **미정**
3. **앵커 후보를 최근접 서빙 대상에 포함?** (현 초과서빙은 앵커 제외). — **미정**
4. **품질 게이트 서빙 상한**: retrace 컷 현 800 유지 / 상향 / 거리별 차등. — **미정**
5. **무료 주간 한도 차감 여부**: near-serve도 1회 차감(원칙) vs 밴드 밖은 미차감. — **미정**
6. **`suggested_target_km` 제거 시점**: 즉시 발신중단만 vs N빌드 후 필드 제거. — **미정**

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

## 결정 이력 · 재검토 조건

- **결정**(2026-11, 오너): 밴드 밖 실패 → 가까운 코스 서빙으로 대체. 품질/no_path만 실패.
- **근거**: 저밀도·장거리 실패 다수가 "쓸 만한 후보 있는데 거리 밴드로 버림"(조사 실측).
- **재검토 조건**: ① S1 관측 1~2주 축적 후 reject 사유 분포로 허용 한도(결정1) 확정 ②
  near-serve 품질 불만(retrace 큰 코스 서빙) 리포트 시 결정4 상향 재검 ③ 무료 차감 불만(결정5).
