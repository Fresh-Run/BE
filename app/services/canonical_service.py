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
import re

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
_ON_COURSE_M = 30.0               # 코스 위 시작 판정(폴리라인 최근접) — 진입 leg 생략
                                  # 가드(_build_served ≤30m)와 임계 통일(규칙 단일화)
_MAX_LAPS = 3                     # 바퀴수 배수 매칭 상한(석촌호수 2.5km×2=5km 류). 밴드가 실제 n 결정.
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


# 진입점 실명용 랜드마크 패턴(실재 장소만 채택 — 발명 금지)
_ACCESS_LANDMARK = re.compile(r"공원|광장|프라자|다리|둘레길|호수|한강|하천|산책|데크|마당|무대|나루")


async def _access_name(coord: Coordinate) -> str | None:
    """진입점 인근 실 POI명(발명 금지 — 실재 랜드마크만). best-effort → 없으면 None(중립).

    ⚠️ 랜드마크-borrow 배제(2026-08-26, P1 치킨마루 실사용 버그): 이름이 랜드마크
    정규식에 맞아도 **상업 카테고리(FD6 음식점·CE7 카페 등)면 무효** — "치킨마루
    청라5단지호수공원점"(FD6, 상호에 '호수공원' 차용)이 진입점명으로 채택돼 라이브
    오표시. pitstop 경로의 상업 제외(_COMMERCIAL_CODES)를 canonical access-naming에도
    적용(§C 함정). 상업이면 다음 후보 → 없으면 None(중립 진입점).
    """
    try:
        ps = await map_service.search_places("공원", near=coord, sort="distance",
                                             radius_m=120, limit=4)
    except Exception:  # noqa: BLE001 — 실명은 부가, 실패 시 중립
        return None
    for p in ps:
        if (_hav_m(coord, p.coordinate) <= 90 and _ACCESS_LANDMARK.search(p.name)
                and p.category_code not in map_service._COMMERCIAL_CODES):
            return p.name
    return None


async def _fetch_active() -> list[dict]:
    sb = get_supabase_admin()

    def _q():
        return (sb.table("canonical_courses")
                .select("id,name,region,distance_km,polyline,access_points")
                .eq("active", True).execute())

    resp = await asyncio.to_thread(_q)
    return resp.data or []


async def match_and_build(start: Coordinate, target_km: float,
                          lang: str = "ko",
                          exclude_course_ids: set | None = None,
                          dedup_obs: dict | None = None) -> tuple[RouteResponse, dict] | None:
    """loop 요청서 시작점이 캐노니컬 코스 진입권 & 거리 밴드 내면 그 코스 서빙.
    미스/장애 시 None → 상위가 현행 생성 폴백. best-effort(예외 삼킴 — 캐노니컬이
    생성을 막지 않는다).

    exclude_course_ids(반복 생성 dedup, 2026-07-27 오너 정책): 유저가 이미 가진 코스
    id는 자격(반경·밴드) 판정을 **통과해도 후보에서 제외** — 뽑아놓고 막기 아님. 같은
    course_id의 다른 바퀴수도 함께 제외(같은 트랙 = 사실상 같은 코스). 제외된 코스 수는
    dedup_obs["skipped"]에 기록(미스 시 상위의 생성 gen_meta·바닥 규칙 판단용)."""
    try:
        courses = await _fetch_active()
    except Exception as exc:  # noqa: BLE001 — 조회 실패는 생성 폴백
        # 미시딩(테이블 부재) 롤아웃 창에도 매 생성 traceback로 Sentry 오염 안 되게
        # 한 줄 warning(exc_info 없이). 캐노니컬은 부가 레이어 — 생성이 진실.
        logger.warning("canonical_courses 조회 실패(%s) — 생성 폴백", type(exc).__name__)
        return None

    # 진입점 우선순위: access_points[0]=큐레이션 우선진입점(관대 밴드·최우선). 나머지는
    # 자동(표준 밴드). **바퀴수 배수 매칭**: 짧은 코스(석촌호수 2.5km)는 n바퀴(course×n)로
    # 밴드 진입 — n을 1..MAX 순회. 후보 key=(우선순위 0/1, diff) 최소 채택.
    best: tuple[tuple[int, float], dict, Coordinate, float, int | None, int] | None = None
    excluded_hit: set = set()   # dedup 제외로 빠진 자격 통과 코스 id(관측·바닥 판단)
    for c in courses:
        try:
            aps = _coords(c["access_points"])
            dist_km = float(c["distance_km"])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        # 코스 위 시작(오너 확정 2026-07-27): 폴리라인 최근접 ≤30m(진입 leg 생략 가드와
        # 동일 임계)면 우선진입점 경유 없이 그 지점에서 바로 시작 — "러너는 서 있는
        # 지점부터 뛴다"(배치4 플라자 실측: 경유 2.6km vs 제자리 2.0km). key=(-1,·)로
        # rank0보다 우선, 진입 왕복 0이라 diff=|코스×바퀴−target|. 밴드는 관대(1.0) —
        # 아는 코스 위에 서 있다는 신호가 큐레이션 입구 지정만큼 강함.
        try:
            poly = _coords(c["polyline"])
        except (KeyError, TypeError, ValueError, IndexError):
            poly = []
        if poly:
            # bbox 사전 필터(±~1.1km) — 원거리 코스 폴리라인 전수 스캔 회피
            if (min(p.lat for p in poly) - 0.01 <= start.lat <= max(p.lat for p in poly) + 0.01
                    and min(p.lng for p in poly) - 0.01 <= start.lng <= max(p.lng for p in poly) + 0.01):
                near_pt = min(poly, key=lambda p: _hav_m(start, p))
                d_poly = _hav_m(start, near_pt)
                if d_poly <= _ON_COURSE_M:
                    for laps in range(1, _MAX_LAPS + 1):
                        diff = abs(dist_km * laps - target_km)
                        if diff > _CANONICAL_PRIMARY_BAND_KM:
                            continue
                        if exclude_course_ids and c.get("id") in exclude_course_ids:
                            excluded_hit.add(c.get("id"))
                            continue
                        key = (-1, diff)
                        if best is None or key < best[0]:
                            best = (key, c, near_pt, d_poly, None, laps)
        for rank, ap in enumerate(aps):
            d = _hav_m(start, ap)
            if d > _ACCESS_RADIUS_M:
                continue
            access_rt = 2 * d / 1000.0 * _ACCESS_INFLATION   # 진입 왕복 추정(직선×스냅팽창)
            band = _CANONICAL_PRIMARY_BAND_KM if rank == 0 else _CANONICAL_BAND_KM
            for laps in range(1, _MAX_LAPS + 1):
                diff = abs(dist_km * laps + access_rt - target_km)
                if diff > band:
                    continue
                if exclude_course_ids and c.get("id") in exclude_course_ids:
                    excluded_hit.add(c.get("id"))            # 자격은 되나 소유 — 제외
                    continue
                key = (0 if rank == 0 else 1, diff)          # 우선진입점 최우선, 그다음 diff
                if best is None or key < best[0]:
                    best = (key, c, ap, d, rank, laps)

    if dedup_obs is not None:
        dedup_obs["skipped"] = len(excluded_hit)
    if best is None:
        return None
    _key, course, access, access_d, access_rank, laps = best
    try:
        route = await _build_served(start, access, course, target_km, lang, laps)
    except Exception:  # noqa: BLE001 — 스티치/스냅 실패는 생성 폴백
        logger.warning("canonical 코스 서빙 스티치 실패 — 생성 폴백", exc_info=True)
        return None
    meta = {"engine": "canonical", "verdict": "canonical",
            "course_id": course.get("id"), "course_name": course.get("name"),
            "region": course.get("region"), "access_dist_m": round(access_d),
            "access_rank": access_rank,  # 0=큐레이션 우선진입점 채택 · None=코스 위 시작
            "laps": laps,                # 바퀴수(배수 매칭 — n바퀴)
            "course_km": round(float(course["distance_km"]), 2)}
    if access_rank is None:
        meta["on_course_start"] = True  # 코스 위 제자리 시작(진입 leg 0) — additive 관측
    if excluded_hit:
        meta["dedup_skipped_canonical"] = len(excluded_hit)  # 차선 캐노니컬로 회피 서빙
    return route, meta


def _rotate_loop(poly: list[Coordinate], access: Coordinate) -> list[Coordinate]:
    """폴리라인 루프를 진입 접점(access 최근접 인덱스) 기준으로 회전 — 스티칭 시 진입
    leg 끝(access)과 루프 시작이 이어지게. 회전 없으면 access→idx0 현(호수 관통 직선)
    이 생김(2026-07-26 오너 실기기 부검). 닫힌 루프면 끝 중복 제거 후 접점 복귀로 재닫기."""
    if len(poly) < 3:
        return list(poly)
    core = poly[:-1] if _hav_m(poly[0], poly[-1]) < 5.0 else list(poly)
    idx = min(range(len(core)), key=lambda i: _hav_m(access, core[i]))
    rotated = core[idx:] + core[:idx]
    rotated.append(rotated[0])  # 접점 복귀(닫기)
    return rotated


async def _build_served(start: Coordinate, access: Coordinate, course: dict,
                        target_km: float, lang: str, laps: int = 1) -> RouteResponse:
    """진입 leg(home↔access) T-map 스냅 + 코스 polyline 스티치. 카드 제목=실명.
    루프는 진입 접점 기준 회전 후 스티치(access→idx0 현 방지). laps>1이면 회전 루프를
    n회 반복(접점→접점 이음, 0갭) + 카드에 'N바퀴' 표기."""
    loop = _rotate_loop(_coords(course["polyline"]), access)
    poly = loop * max(1, laps)                     # n바퀴 반복(접점서 이어져 0갭)
    # 진입 leg 스냅 — 단, 시작이 진입점에 거의 붙어 있으면(≤30m) leg가 ~0m라 T-map 400
    # (start==end). 그 경우 진입 leg 생략(러너가 이미 입구에 있음) — 로버스트니스.
    if _hav_m(start, access) <= 30.0:
        in_path, out_path, leg_km = [], [], 0.0
    else:
        leg_in = await map_service.get_pedestrian_route(origin=start, destination=access)
        leg_out = await map_service.get_pedestrian_route(origin=access, destination=start)
        in_path, out_path = leg_in.path, leg_out.path
        leg_km = (leg_in.distance_m + leg_out.distance_m) / 1000.0
    stitched = in_path + poly + out_path
    total_km = round(leg_km + float(course["distance_km"]) * laps, 1)
    _nl = openai_service._neutral_label
    aname = await _access_name(access)             # 진입점 실명(실재 POI만, best-effort)
    wps = [Waypoint(name=_nl(0, 3, False, lang), coordinate=start, is_pitstop=False),
           Waypoint(name=(aname or _nl(1, 3, False, lang)), coordinate=access, is_pitstop=False),
           Waypoint(name=_nl(2, 3, False, lang), coordinate=start, is_pitstop=False)]
    name = str(course["name"])
    if laps > 1:                                    # 바퀴수 표기(실명 + N바퀴/N laps)
        name += f" {laps}바퀴" if (lang or "ko") != "en" else f" x{laps}"
    route = RouteResponse(
        summary=name,                               # 실명 카드 제목(DB — 발명 아님)
        total_distance_km=total_km,
        estimated_duration_min=round(total_km * _RUN_PACE_MIN_PER_KM),
        waypoints=wps, polyline=stitched)
    route.is_one_way = False
    route.target_missed = abs(total_km - target_km) > 0.5   # 정직 — 카드 실명이 있어 사용자 앎
    return route
