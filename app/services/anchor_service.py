"""앵커 검색 층 (ANCHOR_EPIC 슬라이스 1, 2026-07-23).

⚠️ **오프라인 전용 — 아직 route_service에 배선되지 않음(Phase 0 설계 후 슬라이스).**
시작점 반경에서 실재 runnable 앵커(공원·수변·트레일)를 수집·랭킹해 Anchor 목록 반환.
좌표는 지도 제공자 것만(발명 0). 기존 자산 재사용: rank_places_for_keyword(대표성),
_in_position_band(위치 밴드), _GRID_RATIOS(거리 조준은 슬라이스 2에서).

설계: docs/ANCHOR_EPIC_DESIGN.md §1.
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
# non-runnable 부속시설 제외(슬라이스 1 실측: "공원" 키워드가 주차장·지하차도·아파트·
# 몰을 반환). 실명 공원은 유지, 부속·상업 파생만 제거(pitstop 대표성 필터와 동형).
_NON_RUNNABLE = re.compile(
    r"주차장|주차|지하차도|아파트|상가|프라자|플라자|몰|마트|주민센터|화장실|음수대|"
    r"관리사무소|매점|편의점|정류장|출입구|버스|지하철")
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
            if _NON_RUNNABLE.search(p.name):
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


def select_anchors(anchors: list[Anchor], target_radius_m: float, k: int,
                   excluded: set[int], variant: int = 0) -> list[Anchor]:
    """8 sector를 k개 각도 bin으로 나눠 각 bin에서 target_radius 근접·대표성 좋은
    앵커 → polar sort(각도 정렬). variant는 bin별 variant-th 후보 선택(풀 다양화 —
    variant 0=최선, 1=차선…). 밴드 내·non-dead-end·미제외만."""
    pool = [a for a in anchors if a.in_band and not a.dead_end and a.id not in excluded]
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


async def build_anchor_pool(start: Coordinate, anchors: list[Anchor], target_km: float,
                            park_coords: list[Coordinate] | None = None, variant: int = 0):
    """앵커 풀 — 9롤(K3/K4 혼합·반경 다양) 스냅 → 밴드 게이트 + tiebreak
    [park desc · longest_retrace_m asc(체감 스퍼) · |km−target| asc]. K-트레이드오프를
    풀 다양화로 구조 해결. 반환 (RouteResponse|None, meta)."""
    from app.services.route_service import _within_band, _spur_metrics, _park_coverage

    park_coords = park_coords or []
    cands = []
    for k, f in _POOL_ROLLS:
        picked = select_anchors(anchors, target_km * 1000 * f, k, set(), variant)
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
