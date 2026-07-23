# PITSTOP_REPRESENTATIVENESS_DESIGN — "대중적 코스 우선" 설계 검토

> 작성 2026-07-22. **설계 문서만(코드 금지)**. 계기: 실사용 청라 리포트 —
> pitstop "공원"이 위치 밴드 정합(759m 초록공원)이나 **주민이 처음 듣는 무명 소공원**
> 채택, 지역 대표성 0. 목표: 출발지+목표거리 기준으로 **유명한/대중적 공원·코스** 우선.

---

## 0. 현재 Gemini 프롬프트 전문 (오너 직접 확인용)

### 시스템 메시지 (`openai_service.generate_route`)
```
You are a local running coach in South Korea. You design safe, runnable routes
(riversides, parks, sidewalks) and always respond by calling the
build_running_route function. Return ordered waypoint COORDINATES only — do NOT
invent place names, descriptions, or a title. The server assigns neutral display
labels and resolves any pitstop name from the map provider. Focus entirely on
realistic coordinates and the required geometry.
```

### 유저 메시지 (실제 — 청라 5km, pitstop "공원", radius 1.2km, aim 2.8km)
```
Design a running route in South Korea whose final on-road length is about 5.0 km.
Note: the route will be snapped to real pedestrian roads, which typically makes it
1.3-1.7x longer than the straight lines between waypoints. Therefore place the
waypoints so that the SUM OF STRAIGHT-LINE distances between consecutive waypoints
(including the return to start for loops) is about 2.8 km. The chain MUST NOT
exceed 3.2 km — longer routes are invalid. If unsure within that limit, err
slightly longer — a route a bit over 5.0 km is acceptable, but shorter is not.
Start at (37.5242, 126.6303) and return to the starting point (a loop route).
Include at least one pitstop matching the keyword '공원'. Keep every waypoint
within 1.2 km (straight-line) of the start point. Provide ordered waypoints with
realistic WGS84 coordinates, mark any pitstop with is_pitstop=true, and call
build_running_route with the result.
```
- **aim 계산**: `chain_aim = (target + 0.2) / est_ratio` = (5.0+0.2)/1.85 = **2.8km**,
  `chain_cap = aim × 1.15` = **3.2km**. (est_ratio 1.85 = 청라 격자값.)
- **주목**: 프롬프트는 **좌표만** 요구(중립 라벨 전환 후) — 지명·서사 창작 금지. pitstop
  실명은 서버가 Kakao로 해석. 즉 "유명한 곳"은 프롬프트가 아니라 **서버 pitstop 해석**에서
  다뤄야 함(Gemini는 실제 어느 공원이 유명한지 모름 = §3 축 B).

---

## 1. (가) 프롬프트로 "유명한 곳" 지시 — **기각**

제안: 프롬프트에 "prefer famous/popular parks" 추가.

**기각 논증 — 실패 이력 3건이 동일 패턴(Gemini는 지역 실측 지식이 없다)**:
| 이력 | 교훈 | 이 제안에 적용 |
|---|---|---|
| **v2.6 소프트 지시** | "aim for the middle" 소프트 거리 지시 → Gemini 무시, 미달 편향 악화 | "famous" 소프트 지시도 무시될 것 |
| **§3 축 C(공원 이탈)** | "공원 완주 선호" 추가 → 체류율 0.87→0.75 **악화** (실측) | 미학 소프트 지시가 오히려 해악 실증됨 |
| **라벨 hallucination** | Gemini가 "인천아시아드주경기장"을 6km 이격 좌표에 창작 | Gemini는 **어느 공원이 유명한지 모름** — "famous"라 해도 좌표를 창작하거나 무시 |

**근본**: 대표성은 **지역 실측 데이터**(Kakao 인기 신호·자체 run 밀도)에 있고 Gemini엔
없다. 프롬프트는 좌표만 뽑는 현행이 최적(중립 라벨 전환의 취지). → **프롬프트 불변.**

---

## 2. (나) Kakao 신호 기반 대표성 랭킹 — **채택 권장 (즉시, 저비용, 오프라인 검증됨)**

### 2.1 Kakao Place 응답의 대표성 프록시 (원시 필드 전수 — 청라 "공원" 실측)
| 필드 | 청라호수공원(유명) | 무명 소공원 | 대표성 프록시 가치 |
|---|---|---|---|
| **accuracy 정렬 순위** | **#1** (985m) | 하위 (222·478m 더 가까워도 뒤) | **★최강** — Kakao 관련도=인기 반영. 아래 검증 |
| `category_name` | "여행 > 공원 > **도시근린공원**"(3단, 정식 분류) | "여행 > 공원"(2단) | ★중 — 정식 분류(근린공원·시립 등)=established |
| `phone` | **"032-456-2749"**(관리 시설) | "" (없음) | ★중 — 전화=관리되는 공식 시설=유명 프록시 |
| `id` | 18475105 (8자리, 낮음) | 1370520825 (10자리) | △약 — 낮은 id≈먼저 등재(불확실) |
| `place_url` | 있음 | 있음 | ✗ 전부 있음(무차별) |
| `category_group_code` | "" | "" | ✗ 공원은 group 분류 밖 |

### 2.2 ★핵심 발견 — accuracy 정렬이 이미 대표성을 반영, **현 코드가 distance로 덮음**
- **실측**: 청라 "공원" `sort=accuracy` → **[0] 청라호수공원(985m)** > 문점공원(222m) >
  물방울공원(478m). **더 가까운 소공원보다 유명한 청라호수공원을 Kakao가 먼저 올림.**
- **그런데 현재 랭킹**(`rank_places_for_keyword`)이 `(적합도 desc, 위치밴드 desc,
  거리 asc)`라 — 밴드 내 동점(둘 다 실제 공원·in-band)에서 **거리 tiebreak**가 청라호수공원
  (986m)을 초록공원(759m)에게 지게 함. **accuracy가 준 대표성 순서를 거리가 뒤엎는 것.**

### 2.3 설계 — 랭킹에 "대표성 축" 추가 (tiebreak 교체)
```
현행:  key = (-adequacy, -in_band, distance)
제안:  key = (-adequacy, -in_band, accuracy_rank, distance)
              # accuracy_rank = Kakao accuracy 정렬에서의 원 인덱스(작을수록 대표)
```
- **1차 신호 = Kakao accuracy 순위**(원 인덱스 보존) — 무료(이미 accuracy로 검색 중),
  지역 인기 반영. 밴드 내 적합도 동점 park 중 **accuracy 상위 = 대표 park** 채택.
- **2차 보강(선택)**: accuracy 동률/약할 때 `category_name` 깊이(정식 분류 우대) +
  `phone` 존재(관리 시설) 가산. 단순 가중.
- **거리는 최종 tiebreak로 강등**(밴드 안이면 대표성이 거리보다 우선).

### 2.4 오프라인 검증 (필수 — 지시대로 실측)
- **청라 "공원" band-filtered accuracy 순서**: [청라호수공원(986m), 포리공원(1167m),
  소첨도공원(1376m), 정서진문화공원(1053m), 초록공원(759m), …]. **청라호수공원 = accuracy #1.**
- → 제안 랭킹(accuracy tiebreak)이면 **청라호수공원이 1위로 채택됨**(현행은 초록공원).
  **오너 요구("유명한 청라호수공원 우선") 정확히 달성.** 오프라인 확인 완료.

### 2.5 트레이드오프
- accuracy는 Kakao 문서상 "정확도"(관련도)로 명시 — "인기"라 못박진 않으나 **실측상
  유명 park를 상위로**(청라호수공원 #1). 이름 매치도 섞이나 랜드마크 키워드에선 실제 park
  surface. **타 좌표 일반화는 gen_meta pitstop 관측(v82~)으로 사후 검증** 필요.
- 위치 밴드 유지: 대표성 tiebreak는 **밴드 내에서만** 작동(밴드 밖 대표 park는 여전히 후순위)
  — overshoot 방지(핀치)와 대표성을 **둘 다** 만족.

---

## 3. (다) 자체 run 데이터 기반 인기 코스 (중기) — **베타 데이터 트리거 대기**

### 3.1 개념
유저 `run_tracks.points`를 **격자(~200m 셀)로 집계**해 "이 동네 사람들이 실제 뛰는 구역"
히트맵 → pitstop/웨이포인트를 고밀도 셀로 우대. Kakao(어디가 공식 park)와 다른 축 —
**실제 러너가 선택한 코스**(진짜 대중성).

### 3.2 프라이버시 설계 (필수)
- **집계만 노출**: 격자 셀별 밀도(카운트)만. **개별 트랙 절대 미노출.**
- **최소 표본 임계(k-익명)**: 셀당 **≥5명 서로 다른 유저**가 지난 뒤에만 그 셀을 신호로 사용
  (1~2명 트랙으로 개인 동선 역추적 차단).
- **격자 라운딩**: gen_failures 격자(소수 2자리≈1.1km)보다 촘촘한 200m 셀이나, 노출은
  밀도 등급(상/중/하)만 — 원좌표 미노출.
- **집계 갱신은 배치**(일 1회 등), 실시간 개별 반영 없음.

### 3.3 트리거·규모
- **전제**: 활성 지역당 run 트랙 축적(수백+). 베타 초기엔 표본 부족 → **무효**.
- **트리거**: 특정 지역 run_tracks가 **≥임계(예 지역당 50트랙·20유저)** 도달 → 그 지역만 활성.
- **규모**: 격자 집계 테이블(지역×셀×밀도), 야간 배치. RLS enable(집계 전용).
- **결정 유보**: 지금은 데이터 없음 → **(나) 선행 후 베타 축적 보며 착수 판단.**

---

## 4. 권고 조합 + 확답 지점

### 권고
1. **즉시: (나) Kakao accuracy 대표성 tiebreak** — 저비용·오프라인 검증됨(청라호수공원 1위).
   distance tiebreak → accuracy 순위 tiebreak 교체 (+선택적 category_depth·phone 보강).
2. **(가) 프롬프트 기각** — 실패 이력 3건, Gemini 지역 무지.
3. **(다) run 히트맵 = 중기** — 베타 run 축적 트리거 대기, 프라이버시 설계 확정 후.
4. **관측 활용**: v82 pitstop 필드(name·in_band)에 **채택 pitstop의 accuracy 순위·대표성
   신호도 기록**하면 (나) 효과를 실사용에서 자동 검증.

### 확답 지점 (오너 결정)
| # | 결정 | 옵션 | 추천 |
|---|---|---|---|
| A | (나) 채택? | 예(accuracy tiebreak) / 아니오 | **예** — 오프라인 검증됨 |
| B | (나) 신호 범위 | accuracy만 / +category_depth·phone 보강 | **accuracy만 시작**(단순·검증됨), 보강은 관측 후 |
| C | 대표성 vs 위치밴드 우선순위 | 밴드 내 대표성 tiebreak(권고) / 대표성이 밴드도 무시 | **밴드 내 tiebreak**(overshoot 방지 유지) |
| D | (다) run 히트맵 | 지금 설계 착수 / 베타 트리거 대기 | **트리거 대기**(데이터 전무) |
| E | pitstop 관측에 accuracy 순위 추가? | 예 / 아니오 | **예**(소형, (나) 효과 자동 검증) |

---

## 6지역 일반화 검증 (2026-07-22) — "공원" 키워드 채택표

(나) 구현 후 6개 격자 지역(est_ratio 그리드)에서 실 Kakao로 pitstop 해석
(landmark 의도 → sort=accuracy → 상업 제외·적합도·위치밴드·대표성) 결과. target 5.0km.

| 지역 | 채택 pitstop | cat | raw→rank | 밴드 | acc순위 | 거리 | fallback |
|---|---|---|---|---|---|---|---|
| 뚝섬 | 삼성해맞이공원 | (실명) | 15→15 | 내 | 0 | 571m | ✗ |
| 성수 | 응봉산인공암벽공원 | (실명) | 15→15 | 내 | 1 | 734m | ✗ |
| 여의도 | 여의도한강공원 | (실명) | 15→15 | 내 | 0 | 312m | ✗ |
| 청라 | 청라호수공원 | (실명) | 15→15 | 내 | 0 | 354m | ✗ |
| 목동 | 오목공원 | (실명) | 15→15 | 내 | 0 | 1013m | ✗ |
| 강남 | 역삼문화공원 | (실명) | 15→15 | 내 | 0 | 456m | ✗ |

**결론**: **6/6 실명 공원 채택**(상업 "…공원점"·음식점 0), **6/6 위치밴드 내**
(overshoot 핀치 없음), fallback 0. sort=accuracy가 실제 공원을 상위로 올려
raw→rank 15→15(상업 제외가 발동조차 안 함 — accuracy가 이미 park-first).
성수만 acc 1(1위가 밴드 밖이거나 비대표라 대표성 tiebreak가 acc#1 실공원 채택).
**(나) 일반화 확인** — 청라 단일 검증이 6지역으로 확장됨.
⚠️ 상업 제외 필터는 이 셋에선 미발동(안전망) — distance-sort 경로(상업형 키워드)나
공원 희소 지역에서만 발동하므로 `test_pitstop_intent.py`(mock)가 그 경로를 커버.
