"""앵커 검색 층 + 기하 (ANCHOR_EPIC).

시작점 반경에서 실재 runnable 앵커(공원·수변·트레일)를 수집·랭킹(collect_anchors) +
각도 정렬 루프 기하(build_anchor_loop/build_anchor_candidates). 좌표는 지도 제공자
것만(발명 0). 기존 자산 재사용: rank_places_for_keyword(대표성)·_in_position_band.

⚠️ collect_anchors·build_anchor_loop·build_anchor_pool은 **오프라인 검증 전용**(§8.17
동결). **build_anchor_candidates만 route_service의 혼합 풀 기여자로 배선**(§9 부활,
플래그 ANCHOR_POOL_N). 설계: docs/ANCHOR_EPIC_DESIGN.md §1·§9.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass

from app.models.schemas import Coordinate, RouteResponse, Waypoint
from app.services import map_service

logger = logging.getLogger(__name__)

# 수집 키워드 (타입, 키워드) — 병렬 Kakao. 전부 landmark/unknown 의도라 상업 배제·거리순.
_ANCHOR_KEYWORDS: list[tuple[str, str]] = [
    ("park", "공원"), ("park", "근린공원"), ("park", "호수공원"),
    ("water", "한강공원"), ("water", "하천"), ("water", "강변"),
    ("trail", "산책로"), ("trail", "둘레길"),
]
# non-runnable 제외(슬라이스 1 실측: "공원" 키워드가 주차장·지하차도·아파트·몰을 반환).
# 실명 공원은 유지, 부속·상업 파생만 제거(pitstop 대표성 필터와 동형).
# 2분류 — 시설(항상 제외) vs 업소(공원류 이름이면 무효). 후자는 한국어 동음이의 오탐
# 방지(은행↔은행나무공원·학원↔학원사거리공원 전례, 2026-07-24 자책 회귀 부검):
# 업소텀은 이름에 공원류 토큰이 없을 때만 제외한다.
_FACILITY = re.compile(
    r"주차장|주차|지하차도|아파트|상가|프라자|플라자|몰|마트|주민센터|화장실|음수대|"
    r"관리사무소|매점|편의점|정류장|출입구|버스|지하철")
_BUSINESS = re.compile(r"공인중개사|중개사|부동산|사무소|병원|약국|학원|은행")
# 공원류 토큰 — 있으면 업소텀 무효(은행나무공원은 공원이지 은행이 아니다).
_GREENSPACE = re.compile(r"공원|산책로|둘레길|천|숲")


def _is_non_runnable(name: str) -> bool:
    """부속시설·업소 제외 판정. 시설텀은 무조건 제외, 업소텀은 공원류 토큰이 없을 때만."""
    if _FACILITY.search(name):
        return True
    if _BUSINESS.search(name) and not _GREENSPACE.search(name):
        return True
    return False
_DEDUP_M = 120.0          # 같은 앵커 중복 제거 반경(여러 키워드가 같은 공원 반환)
_DEAD_END_GAP_M = 250.0   # start→anchor 프로브 leg 최대갭 > 이 값이면 dead-end(교량/수변 신호)
_PROBE_TOP_N = 8          # dead-end 프로브 대상(in-band 상위 N — 비용 상한)

# 격자 셀 캐시(정적 앵커) — 슬라이스 1은 프로세스 로컬 stub. 실배선 시 TTL·격자키 확정.
_CACHE: dict = {}


@dataclass
class Anchor:
    id: int
    name: str
    coord: Coordinate
    type: str            # park | water | trail
    dist_m: float        # 시작 거리(m)
    sector: int          # 시작 기준 방위각 8분할(0=E, 반시계) — §3 각도 분산 입력
    rep_rank: int        # 소스 검색 내 대표성 순위(0=최상위, rank_places_for_keyword 결과 순)
    in_band: bool        # 위치 밴드 [200m, target×0.5] 내
    dead_end: bool | None  # start→anchor 프로브 교량 신호(in-band 상위 N만 판정, 그 외 None)


def _sector(start: Coordinate, c: Coordinate) -> int:
    """시작 기준 방위각 8분할(45°). 경도 스케일 보정."""
    dy = c.lat - start.lat
    dx = (c.lng - start.lng) * math.cos(math.radians(start.lat))
    ang = math.degrees(math.atan2(dy, dx)) % 360.0
    return int(ang // 45)


async def collect_anchors(start: Coordinate, target_km: float,
                          probe_dead_end: bool = True) -> list[Anchor]:
    """시작 반경에서 앵커 수집 → 병합·대표성·sector·밴드·dead-end 판정."""
    ckey = (round(start.lat, 3), round(start.lng, 3), round(target_km))
    if ckey in _CACHE:
        return _CACHE[ckey]

    radius_m = max(2000, round(target_km * map_service._POS_BAND_HI_FACTOR * 1000))

    async def _search(kw: str):
        try:
            return await map_service.search_places(kw, near=start, radius_m=radius_m,
                                                   limit=15, sort="accuracy")
        except Exception:  # noqa: BLE001 — 개별 키워드 실패는 스킵
            logger.warning("anchor 검색 실패 kw=%r", kw, exc_info=True)
            return []

    results = await asyncio.gather(*[_search(kw) for _, kw in _ANCHOR_KEYWORDS])

    # 타입·대표성 랭킹 후 근접 병합(최상 rep_rank 유지)
    anchors: list[Anchor] = []
    for (typ, kw), places in zip(_ANCHOR_KEYWORDS, results):
        ranked = map_service.rank_places_for_keyword(kw, places, start=start, target_km=target_km)
        for rank, p in enumerate(ranked):
            if _is_non_runnable(p.name):
                continue  # 부속시설·상업 파생(주차장·아파트·몰 등) — runnable 앵커 아님
            if any(map_service._haversine_m(a.coord.lat, a.coord.lng,
                                            p.coordinate.lat, p.coordinate.lng) <= _DEDUP_M
                   for a in anchors):
                continue  # 중복(이미 더 상위 소스/순위로 수집됨)
            d = map_service._haversine_m(start.lat, start.lng, p.coordinate.lat, p.coordinate.lng)
            anchors.append(Anchor(
                id=len(anchors), name=p.name, coord=p.coordinate, type=typ,
                dist_m=round(d), sector=_sector(start, p.coordinate), rep_rank=rank,
                in_band=map_service._in_position_band(start, p, target_km), dead_end=None))

    if probe_dead_end:
        from app.services.route_service import _polyline_max_gap_m
        targets = [a for a in anchors if a.in_band][:_PROBE_TOP_N]

        async def _probe(a: Anchor):
            try:
                pr = await map_service.get_pedestrian_route(
                    origin=start, destination=a.coord, waypoints=None)
                return _polyline_max_gap_m(pr.path) > _DEAD_END_GAP_M
            except Exception:  # noqa: BLE001 — 프로브 실패는 미판정(None)
                return None

        for a, flag in zip(targets, await asyncio.gather(*[_probe(a) for a in targets])):
            a.dead_end = flag

    _CACHE[ckey] = anchors
    return anchors


# ── 슬라이스 2: 앵커 → 기하 (각도 정렬 루프 + 스냅 + 거리 수선 + dead-end 우회) ──────
# 설계 docs/ANCHOR_EPIC_DESIGN.md §3. 원형성은 sector 각도 정렬로 구조적 보장 —
# 각 leg이 각도를 전진하므로 되돌기(out-and-back)가 불가.
# 거리 수선(슬라이스 2.5): 반복 스케일링(수렴 불안정, hit 61%) → 반경 그리드 서치.
# 각 그리드 반경에서 루프 생성 → 밴드 브래킷 후 target 최근접 선택.
# ⚠️ factor 재보정(기하): K-gon 루프 perimeter ≈ 8~9r·snap → 5km면 r≈540~610m
# = factor 0.10~0.13. 초기 0.16~0.34는 7km+ 오버슈트(hit 17%) 유발 → 0.08~0.22로 하향.
_R_GRID_FACTORS = [0.08, 0.10, 0.12, 0.15, 0.18, 0.22]
_DEAD_END_SWAP_CAP = 3     # dead-end 우회 스왑 상한(그리드 전역 공유)


# vertex 반경 상단(슬라이스 3 최종): 루프 꼭짓점은 0.35×target 내만 — far anchor
# (예: 목동 실개천 1565m=0.31)를 꼭짓점서 배제해 거리-강제 왕복 스퍼 제거(목동 2268m
# 부검). far anchor는 pitstop 용도로만(spur 명시, §8.14 through-path 정합). 위치 밴드
# 상단(0.5, pitstop용)과 별개 축.
_VERTEX_MAX_FACTOR = 0.35


def select_anchors(anchors: list[Anchor], target_radius_m: float, k: int,
                   excluded: set[int], variant: int = 0,
                   vertex_max_m: float | None = None) -> list[Anchor]:
    """8 sector를 k개 각도 bin으로 나눠 각 bin에서 target_radius 근접·대표성 좋은
    앵커 → polar sort(각도 정렬). variant는 bin별 variant-th 후보 선택(풀 다양화 —
    variant 0=최선, 1=차선…). vertex_max_m 있으면 far anchor 꼭짓점 배제(거리-강제 스퍼
    방지). 밴드 내·non-dead-end·미제외만."""
    pool = [a for a in anchors if a.in_band and not a.dead_end and a.id not in excluded
            and (vertex_max_m is None or a.dist_m <= vertex_max_m)]
    bins: dict[int, list[Anchor]] = {}
    for a in pool:
        bins.setdefault(int(a.sector / 8 * k), []).append(a)  # 0..k-1
    picked = []
    for lst in bins.values():
        lst.sort(key=lambda a: abs(a.dist_m - target_radius_m) + a.rep_rank * 40)
        picked.append(lst[variant % len(lst)])
    picked.sort(key=lambda a: a.sector)  # 각도 순 방문 → 원형 구조 보장
    return picked


# 앵커 풀(슬라이스 3): 9롤 = K3 4개 + K4 5개(밴드 적중은 K3, 스퍼 우위는 K4 경쟁).
# 반경 factor로 거리 다양화. 선택은 밴드 게이트 + tiebreak(park > longest_retrace > 거리).
_POOL_ROLLS = [(3, 0.10), (3, 0.12), (3, 0.14), (3, 0.16),
               (4, 0.09), (4, 0.11), (4, 0.13), (4, 0.15), (4, 0.17)]


# 혼합 풀 기여자용 앵커 롤 config(§9 부활) — Gemini 0콜 규칙 기반. K3/K4 믹스,
# factor 재보정(slice2.5: 5km는 r≈540~610m=0.10~0.13). variant로 다양화.
_CANDIDATE_CONFIGS = [(4, 0.11), (3, 0.13), (4, 0.12), (3, 0.11), (4, 0.13)]
# 수변 spur 후보(01:43 부검, "목적지 러닝") — 고대표성 한강/수변 앵커를 꼭짓점 편입 +
# 나머지 앵커 링을 작게(spur 왕복 거리를 반경 축소로 보정 → 밴드 진입). "좋은 왕복" 공식화.
# 한강·강변·호수 + 서울 하천명(양재천·탄천·중랑천·안양천…): "…천" 뒤 경계/산책/공원.
# "천호"처럼 천이 접두면 앞 글자 없어 미스매치(오탐 회피).
_WATERFRONT = re.compile(r"한강|강변|수변|호수|하천|천변|[가-힣]천(?=\s|$|산책|둔치|공원|길)")
# 수변 후보 내부 변형(others 수 × 소반경 factor) — 이 중 chain_target 최근접을 채택
# (밴드 적응 캘리브레이션, 2026-07-24: 청라 초과·미노스 미달 동시 교정. 고정 factor는
# 지역별 도로 팽창차로 밴드를 못 맞춤 — 청라 1.69 vs 미노스 1.35. chain_target은 격자
# 팽창을 역산하므로 chain≈chain_target 후보가 스냅 시 ≈target으로 착지).
# 수변 후보 내부 변형 — others=2 고정(others=1은 체인 과단→pre-gate 드롭), factor 스프레드.
_WATER_VARIANTS = [(2, f) for f in (0.06, 0.08, 0.10, 0.12)]
# 수변 후보 chain 조준 = chain_aim × 이 비율(수변 spur 도로 팽창이 격자보다 커 짧게 조준).
# 0.80: 미노스·목동 in-band 무회귀 실측(2026-07-24). 청라류 고팽창·희소앵커 지역은
# 팩터 무관 초과라 in-band 불가 — v87이 서빙(범위 밖, 앵커는 밴드 내만 기여).
_WATER_CHAIN_FRAC = 0.80


def _is_waterfront(a: Anchor) -> bool:
    return a.type == "water" or bool(_WATERFRONT.search(a.name))


def _hav_m(a: Coordinate, b: Coordinate) -> float:
    R = 6371000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi = math.radians(b.lat - a.lat)
    dl = math.radians(b.lng - a.lng)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def _chain_km(start: Coordinate, picked: list[Anchor]) -> float:
    """앵커 체인의 직선 길이(start→picked→start, km) — 사전게이트·밴드 조준용."""
    pts = [start] + [a.coord for a in picked] + [start]
    return sum(_hav_m(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) / 1000.0


def _make_anchor_route(start, picked, target_km, needs_pitstop):
    from app.services.openai_service import _neutral_label
    ntot = len(picked) + 2
    ps = len(picked) // 2 if needs_pitstop else -1
    # 앵커 실명 노출(2026-07-26 오너) — mid는 대응 앵커의 Kakao 실명(발명 아님, 이미 보유).
    # 이름 없으면 중립 폴백. pitstop 슬롯은 상위(route_service)가 실 pitstop명으로 덮음.
    mids = [Waypoint(name=(a.name or _neutral_label(j + 1, ntot, False, "ko")),
                     coordinate=a.coord, is_pitstop=(j == ps)) for j, a in enumerate(picked)]
    wps = ([Waypoint(name=_neutral_label(0, ntot, False, "ko"), coordinate=start, is_pitstop=False)]
           + mids
           + [Waypoint(name=_neutral_label(ntot - 1, ntot, False, "ko"), coordinate=start, is_pitstop=False)])
    return RouteResponse(summary="x", total_distance_km=round(target_km, 1),
                         waypoints=wps, polyline=None)


def build_anchor_candidates(start: Coordinate, anchors: list[Anchor], target_km: float,
                            n: int, needs_pitstop: bool = False,
                            chain_target_km: float | None = None) -> list[RouteResponse]:
    """혼합 풀 기여자 — 미스냅 앵커 체인 n개(각도 정렬, 중립 라벨). route_service가
    v87 롤과 함께 공통 스냅·선택. **수변 spur 후보 우선**(한강 등 고대표성 수변을 꼭짓점
    편입 — 01:43 한강 미접근 부검). needs_pitstop이면 앵커 1개를 is_pitstop 슬롯으로.

    chain_target_km(격자적응)이 오면 수변 내부 변형(others 수 × factor) 중 **chain이
    chain_target에 가장 가까운 것**을 채택 — 지역별 도로 팽창차를 흡수해 밴드 중앙 조준
    (2026-07-24 캘리브레이션: 청라 초과·미노스 미달 동시 교정). None이면 레거시(짧은 순)."""
    vertex_max = target_km * 1000 * _VERTEX_MAX_FACTOR
    out: list[RouteResponse] = []
    # 1) 수변 spur 후보 — 밴드 내 고대표성(rep≤3) 수변 앵커 있으면 우선 생성
    water = sorted([a for a in anchors if a.in_band and _is_waterfront(a) and a.rep_rank <= 3],
                   key=lambda a: a.rep_rank)
    if water and n > 0:
        wf = water[0]
        non_water = [a for a in anchors if a.id != wf.id and not _is_waterfront(a)]
        # 변형(others 수 × factor) 생성 후 chain 기준 선택. 수변 spur 팽창이 격자보다
        # 크므로 조준점은 chain_aim이 아니라 그보다 짧은 _WATER_CHAIN_FRAC×chain_aim
        # (2026-07-24 실측: chain_aim 직접 조준 시 미노스 5.6 초과 회귀). chain_target
        # 없으면 레거시(짧은 순).
        variants: list[tuple[float, list[Anchor]]] = []
        seen: set[float] = set()
        for vi, (ok, f) in enumerate(_WATER_VARIANTS):
            others = select_anchors(non_water, target_km * 1000 * f, ok, set(), vi, vertex_max)
            if len(others) < ok:
                continue
            combined = sorted(others + [wf], key=lambda a: a.sector)  # 각도 정렬(수변 포함)
            chain = _chain_km(start, combined)
            key = round(chain, 1)
            if key in seen:  # 동일 chain 변형 중복 제거
                continue
            seen.add(key)
            variants.append((chain, combined))
        aim = chain_target_km * _WATER_CHAIN_FRAC if chain_target_km else None
        variants.sort(key=lambda c: (abs(c[0] - aim) if aim else c[0]))
        for _chain, combined in variants[:min(2, n)]:
            out.append(_make_anchor_route(start, combined, target_km, needs_pitstop))
    # 2) 나머지는 일반 앵커 롤(다양성)
    for i, (k, f) in enumerate(_CANDIDATE_CONFIGS[:max(0, n - len(out))]):
        picked = select_anchors(anchors, target_km * 1000 * f, k, set(), i, vertex_max)
        if len(picked) < 3:
            continue
        out.append(_make_anchor_route(start, picked, target_km, needs_pitstop))
    return out[:n]


async def build_anchor_pool(start: Coordinate, anchors: list[Anchor], target_km: float,
                            park_coords: list[Coordinate] | None = None, variant: int = 0):
    """앵커 풀 — 9롤(K3/K4 혼합·반경 다양) 스냅 → 밴드 게이트 + tiebreak
    [park desc · longest_retrace_m asc(체감 스퍼) · |km−target| asc]. K-트레이드오프를
    풀 다양화로 구조 해결. 반환 (RouteResponse|None, meta)."""
    from app.services.route_service import _within_band, _spur_metrics, _park_coverage

    park_coords = park_coords or []
    vertex_max_m = target_km * 1000 * _VERTEX_MAX_FACTOR  # far anchor 꼭짓점 배제
    cands = []
    for k, f in _POOL_ROLLS:
        picked = select_anchors(anchors, target_km * 1000 * f, k, set(), variant, vertex_max_m)
        if len(picked) < 3:
            continue
        try:
            pr = await map_service.get_pedestrian_route(
                origin=start, destination=start, waypoints=[a.coord for a in picked])
        except Exception:  # noqa: BLE001 — 롤 실패는 스킵(풀이 흡수)
            continue
        km = pr.distance_m / 1000.0
        wps = ([Waypoint(name="출발", coordinate=start, is_pitstop=False)]
               + [Waypoint(name=a.name, coordinate=a.coord, is_pitstop=False) for a in picked]
               + [Waypoint(name="복귀", coordinate=start, is_pitstop=False)])
        route = RouteResponse(summary="x", total_distance_km=round(km, 1),
                              polyline=pr.path, waypoints=wps)
        sm = _spur_metrics(pr.path)
        cands.append({"route": route, "km": km, "k": k, "longest": sm["longest_retrace_m"],
                      "long_spur": sm["long_spur_count"], "micro": sm["micro_reversals"],
                      "park": _park_coverage(route, park_coords)})
    if not cands:
        return None, {"reason": "no_candidates", "rolls": len(_POOL_ROLLS)}
    in_band = [c for c in cands if _within_band(c["km"], target_km)]
    pool = in_band or cands
    # tiebreak: ⚠️ 오너 원안 [park > longest > 거리]는 park 우선이 long-spur high-park를
    # 뽑아 스퍼 목표를 배반(§8.13 재현, 실측 longest 971). 재프레임 가치가 "스퍼 반감"이라
    # **longest 우선**으로 교정(park는 차순위·앵커라 대개 1.0 유지). 실측 971→반감.
    best = min(pool, key=lambda c: (c["longest"], -c["park"], abs(c["km"] - target_km)))
    meta = {"pool_size": len(cands), "n_in_band": len(in_band), "k_sel": best["k"],
            "km": round(best["km"], 2), "hit": int(_within_band(best["km"], target_km)),
            "longest_retrace_m": best["longest"], "long_spur_count": best["long_spur"],
            "micro_reversals": best["micro"], "park": best["park"]}
    return best["route"], meta


def _anchor_near_gap(polyline: list, picked: list[Anchor]):
    """폴리라인 최대갭 지점에 가장 가까운 앵커 — dead-end leg 유발자 특정."""
    from app.services.route_service import _dist_km
    if len(polyline) < 2:
        return None
    gi = max(range(1, len(polyline)), key=lambda i: _dist_km(polyline[i - 1], polyline[i]))
    mid = polyline[gi]
    return min(picked, key=lambda a: _dist_km(a.coord, mid))


async def build_anchor_loop(start: Coordinate, anchors: list[Anchor],
                            target_km: float, k: int = 4):
    """앵커 각도 루프 생성 → T-map 스냅 → **반경 그리드 서치 거리 수선** + dead-end 우회.
    각 그리드 반경에서 루프 생성(dead-end 앵커는 전역 제외), 밴드 내 우선 target 최근접
    선택. 반환 (RouteResponse|None, meta). 앵커 부족 시 (None, reason) → 상위 v87 폴백."""
    from app.services.route_service import _polyline_max_gap_m, _within_band, _dist_km

    excluded: set[int] = set()
    meta = {"grid_tried": 0, "dead_end_swaps": 0}
    candidates: list[tuple[float, list, object]] = []  # (km, picked, pr)

    for f in _R_GRID_FACTORS:
        r = target_km * 1000 * f
        picked = pr = None
        for _ in range(_DEAD_END_SWAP_CAP):
            picked = select_anchors(anchors, r, k, excluded)
            if len(picked) < 3:
                break
            via = [a.coord for a in picked]
            pr = await map_service.get_pedestrian_route(origin=start, destination=start, waypoints=via)
            if _polyline_max_gap_m(pr.path) > _DEAD_END_GAP_M:
                bad = _anchor_near_gap(pr.path, picked)
                if bad is not None:
                    excluded.add(bad.id)  # 그리드 전역 제외(재발 방지)
                    meta["dead_end_swaps"] += 1
                    pr = None
                    continue
            break
        meta["grid_tried"] += 1
        if picked and len(picked) >= 3 and pr is not None:
            candidates.append((pr.distance_m / 1000.0, picked, pr))

    if not candidates:
        return None, {**meta, "reason": "insufficient_anchors"}
    # 밴드 내 우선(있으면 그중 target 최근접), 없으면 전체 target 최근접
    in_band = [c for c in candidates if _within_band(c[0], target_km)]
    km, picked, pr = min(in_band or candidates, key=lambda c: abs(c[0] - target_km))

    wps = ([Waypoint(name="출발", coordinate=start, is_pitstop=False)]
           + [Waypoint(name=a.name, coordinate=a.coord, is_pitstop=False) for a in picked]
           + [Waypoint(name="복귀", coordinate=start, is_pitstop=False)])
    route = RouteResponse(summary="x", total_distance_km=round(km, 1),
                          polyline=pr.path, waypoints=wps)
    meta.update({"km": round(km, 2), "max_gap": _polyline_max_gap_m(pr.path),
                 "closure_m": round(_dist_km(pr.path[0], pr.path[-1]) * 1000, 1) if pr.path else None,
                 "n_anchors": len(picked), "hit": int(_within_band(km, target_km))})
    return route, meta
