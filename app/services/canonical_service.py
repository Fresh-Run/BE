"""캐노니컬 코스 레이어 — 큐레이션된 실코스를 생성보다 우선 서빙.

오너 통찰: "러너는 아는 코스를 뛴다. 집 앞 호수공원 4.8km를 두고 조립 루프를 주는 건
에바." loop 요청서 시작점이 코스 진입권 & 거리 밴드 내면 그 코스를 서빙(카드 실명 —
검증된 DB명이라 중립 라벨 원칙과 충돌 없음, 오너 룰링). 미스면 현행 생성 폴백.
상세는 docs/CANONICAL_COURSES_DESIGN.md.
"""
from __future__ import annotations

import asyncio
import logging
import math

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import Coordinate, RouteResponse, Waypoint
from app.services import map_service, openai_service

logger = logging.getLogger(__name__)

_ACCESS_RADIUS_M = 800.0          # 시작점이 진입점서 이 반경 내면 매칭 후보
_CANONICAL_BAND_KM = 0.6          # 자동(비우선) 진입점 — |코스km + 진입왕복 − target| ≤
# 큐레이션 우선진입점(access_points[0]) 밴드 — 오너가 "이 코스를 이 입구로" 지정한 것이라
# 관대(진입 왕복이 길어도 아는 코스 서빙 우선, 2026-07-26 오너 큐레이션). 우선진입점이
# 반경·이 밴드 내면 최근접보다 우선 채택.
_CANONICAL_PRIMARY_BAND_KM = 1.0
_ACCESS_INFLATION = 1.3           # 진입 직선 → 도보 팽창 추정(밴드 사전판정용)
_RUN_PACE_MIN_PER_KM = 6.0


def _hav_m(a: Coordinate, b: Coordinate) -> float:
    R = 6371000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi = math.radians(b.lat - a.lat)
    dl = math.radians(b.lng - a.lng)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def _coords(pairs: list) -> list[Coordinate]:
    return [Coordinate(lat=float(p[0]), lng=float(p[1])) for p in pairs]


async def _fetch_active() -> list[dict]:
    sb = get_supabase_admin()

    def _q():
        return (sb.table("canonical_courses")
                .select("id,name,region,distance_km,polyline,access_points")
                .eq("active", True).execute())

    resp = await asyncio.to_thread(_q)
    return resp.data or []


async def match_and_build(start: Coordinate, target_km: float,
                          lang: str = "ko") -> tuple[RouteResponse, dict] | None:
    """loop 요청서 시작점이 캐노니컬 코스 진입권 & 거리 밴드 내면 그 코스 서빙.
    미스/장애 시 None → 상위가 현행 생성 폴백. best-effort(예외 삼킴 — 캐노니컬이
    생성을 막지 않는다)."""
    try:
        courses = await _fetch_active()
    except Exception as exc:  # noqa: BLE001 — 조회 실패는 생성 폴백
        # 미시딩(테이블 부재) 롤아웃 창에도 매 생성 traceback로 Sentry 오염 안 되게
        # 한 줄 warning(exc_info 없이). 캐노니컬은 부가 레이어 — 생성이 진실.
        logger.warning("canonical_courses 조회 실패(%s) — 생성 폴백", type(exc).__name__)
        return None

    # 진입점 우선순위: access_points[0]=큐레이션 우선진입점(관대 밴드·최우선). 나머지는
    # 자동(표준 밴드). 후보 key=(우선순위 0/1, diff) 최소 채택 — 우선진입점이 조건 만족 시
    # 최근접보다 이김. 반경·밴드 밖이면 다음 진입점으로.
    best: tuple[tuple[int, float], dict, Coordinate, float, int] | None = None
    for c in courses:
        try:
            aps = _coords(c["access_points"])
            dist_km = float(c["distance_km"])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        for rank, ap in enumerate(aps):
            d = _hav_m(start, ap)
            if d > _ACCESS_RADIUS_M:
                continue
            access_rt = 2 * d / 1000.0 * _ACCESS_INFLATION   # 진입 왕복 추정(직선×스냅팽창)
            diff = abs(dist_km + access_rt - target_km)
            band = _CANONICAL_PRIMARY_BAND_KM if rank == 0 else _CANONICAL_BAND_KM
            if diff > band:
                continue
            key = (0 if rank == 0 else 1, diff)              # 우선진입점 최우선, 그다음 diff
            if best is None or key < best[0]:
                best = (key, c, ap, d, rank)

    if best is None:
        return None
    _key, course, access, access_d, access_rank = best
    try:
        route = await _build_served(start, access, course, target_km, lang)
    except Exception:  # noqa: BLE001 — 스티치/스냅 실패는 생성 폴백
        logger.warning("canonical 코스 서빙 스티치 실패 — 생성 폴백", exc_info=True)
        return None
    meta = {"engine": "canonical", "verdict": "canonical",
            "course_id": course.get("id"), "course_name": course.get("name"),
            "region": course.get("region"), "access_dist_m": round(access_d),
            "access_rank": access_rank,  # 0=큐레이션 우선진입점 채택
            "course_km": round(float(course["distance_km"]), 2)}
    return route, meta


async def _build_served(start: Coordinate, access: Coordinate, course: dict,
                        target_km: float, lang: str) -> RouteResponse:
    """진입 leg(home↔access) T-map 스냅 + 코스 polyline 스티치. 카드 제목=실명."""
    poly = _coords(course["polyline"])
    leg_in = await map_service.get_pedestrian_route(origin=start, destination=access)
    leg_out = await map_service.get_pedestrian_route(origin=access, destination=start)
    stitched = leg_in.path + poly + leg_out.path
    total_km = round((leg_in.distance_m + leg_out.distance_m) / 1000.0
                     + float(course["distance_km"]), 1)
    _nl = openai_service._neutral_label
    wps = [Waypoint(name=_nl(0, 3, False, lang), coordinate=start, is_pitstop=False),
           Waypoint(name=_nl(1, 3, False, lang), coordinate=access, is_pitstop=False),
           Waypoint(name=_nl(2, 3, False, lang), coordinate=start, is_pitstop=False)]
    route = RouteResponse(
        summary=str(course["name"]),               # 실명 카드 제목(DB — 발명 아님)
        total_distance_km=total_km,
        estimated_duration_min=round(total_km * _RUN_PACE_MIN_PER_KM),
        waypoints=wps, polyline=stitched)
    route.is_one_way = False
    route.target_missed = abs(total_km - target_km) > 0.5   # 정직 — 카드 실명이 있어 사용자 앎
    return route
