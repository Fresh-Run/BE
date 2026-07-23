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

from app.models.schemas import Coordinate
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
