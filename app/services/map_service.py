"""Map API integration for South Korea (Kakao / Naver).

This module provides boilerplate functions for:
  - keyword place search (to resolve pitstops like convenience stores)
  - pedestrian / walking routing between points

Both Kakao and Naver are stubbed with the correct endpoints, headers, and
request shapes. Fill in response parsing and error handling as needed.

For runners, T-map provides true sidewalk-level pedestrian routing and is the
recommended provider (MAP_PROVIDER=tmap). Kakao/Naver are driving-oriented.

API references:
  - Kakao Local (keyword search):
    https://developers.kakao.com/docs/latest/ko/local/dev-guide
  - Kakao Mobility (directions): https://developers.kakao.com/docs/latest/ko/kakaonavi/dev-guide
  - Naver Maps Directions (NCP):
    https://api.ncloud-docs.com/docs/ai-naver-mapsdirections
  - T-map Pedestrian (보행자 경로안내):
    https://tmapapi.sktelecom.com/main.html#webservice/docs/tmapRouteForPedestrian
"""

from __future__ import annotations

import logging
import math

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.core.json_util import loads_lenient
from app.models.schemas import Coordinate, PedestrianRoute, Place

# --- Endpoints ---------------------------------------------------------------

KAKAO_KEYWORD_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"

NAVER_GEOCODE_URL = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"
NAVER_DRIVING_URL = "https://maps.apigw.ntruss.com/map-direction/v1/driving"

# T-map pedestrian routing (POST, JSON body). Coordinates are lng/lat.
TMAP_PEDESTRIAN_URL = (
    "https://apis.openapi.sk.com/tmap/routes/pedestrian?version=1&format=json"
)

# Default request timeout for all outbound Map API calls.
_TIMEOUT = httpx.Timeout(10.0)

logger = logging.getLogger(__name__)


# --- Place search ------------------------------------------------------------


async def search_places(
    keyword: str,
    near: Coordinate | None = None,
    radius_m: int = 2000,
    limit: int = 5,
    sort: str = "distance",
) -> list[Place]:
    """Search for places (e.g. '편의점') near a coordinate, or nationwide.

    near=None이면 전국 정확도순(출발지 검색) — 카카오가 좌표 없는 keyword
    검색을 네이티브 지원하며, 그때 distance 정렬·radius는 불가(400)라
    파라미터를 통째로 뺀다. 좌표가 있으면 현행 거리순 그대로.
    Place (keyword) search always uses Kakao, independent of MAP_PROVIDER
    (which only selects the *routing* provider, e.g. T-map for walking).
    """
    return await _kakao_search_places(keyword, near, radius_m, limit, sort)


async def _kakao_search_places(
    keyword: str, near: Coordinate | None, radius_m: int, limit: int,
    sort: str = "distance",
) -> list[Place]:
    """Kakao Local keyword search. Kakao expects x=lng, y=lat.

    sort='distance'(기본, 근접) / 'accuracy'(관련도). 랜드마크형 pitstop은
    accuracy가 실제 공원을 상위로 올림(distance는 근접 상호가 실제 공원을 묻음 —
    청라 실측: distance는 밴드 내 공원 0, accuracy는 청라호수공원 포함 9개)."""
    if not settings.kakao_rest_api_key:
        raise RuntimeError(
            "Kakao place search is not configured. Set KAKAO_REST_API_KEY "
            "in your environment (see .env.example)."
        )

    headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}
    params = {"query": keyword, "size": limit}
    if near is not None:
        params.update({"x": near.lng, "y": near.lat,
                       "radius": radius_m, "sort": sort})
    else:
        params["sort"] = "accuracy"  # 좌표 없이 sort=distance는 카카오 400
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(KAKAO_KEYWORD_SEARCH_URL, headers=headers, params=params)
        resp.raise_for_status()
        data = loads_lenient(resp.text, context="kakao search")  # 제어문자 방어

    places: list[Place] = []
    for doc in data.get("documents", []):
        try:
            coordinate = Coordinate(lat=float(doc["y"]), lng=float(doc["x"]))
        except (KeyError, ValueError, ValidationError):
            # Skip results with missing/unparseable or out-of-range (non-Korea)
            # coordinates so one bad row doesn't fail the whole search.
            logger.debug("Skipping Kakao result with bad coordinate: %s", doc)
            continue
        places.append(
            Place(
                name=doc.get("place_name", keyword),
                coordinate=coordinate,
                category=doc.get("category_group_name") or None,
                category_code=doc.get("category_group_code") or None,
                address=doc.get("road_address_name") or doc.get("address_name"),
            )
        )
    return places


# ── pitstop 의도 존중 재랭킹 (2026-07-22, 백로그 (b)) ─────────────────────────
# 실사용 부검: pitstop "공원"이 category 무필터 텍스트+거리순이라 "…청라호수공원점"
# 상호를 가진 음식점이 실제 공원을 밀어냄. 랜드마크형 키워드는 상업 카테고리를
# 제외하고 적합도로 재랭킹, 상업형 키워드는 그 카테고리만, 미분류는 현행 유지.
_COMMERCIAL_CODES = {"FD6", "CE7", "CS2", "HP8", "PM9", "BK9", "OL7", "AD5"}  # 음식점·카페·편의점·병원·약국·은행·주유소·숙박
# 상업형 키워드 → include-only 코드(필터 반전)
_COMMERCIAL_KEYWORD_CODES = {"카페": "CE7", "커피": "CE7", "편의점": "CS2",
                             "음식점": "FD6", "식당": "FD6", "맛집": "FD6"}
# 랜드마크형 토큰(이 중 하나라도 키워드에 있으면 랜드마크 의도)
_LANDMARK_TOKENS = ("공원", "호수", "산", "천", "강변", "하천", "놀이터", "숲",
                    "해변", "저수지", "수목원", "둘레길", "생태")


def _keyword_intent(keyword: str) -> tuple[str, str | None]:
    """키워드→의도: (commercial, 코드) / (landmark, 토큰) / (unknown, None). 소규모
    매핑 — 미분류는 현행 무필터(과설계 금지)."""
    k = (keyword or "").strip()
    for kw, code in _COMMERCIAL_KEYWORD_CODES.items():
        if kw in k:
            return "commercial", code
    for t in _LANDMARK_TOKENS:
        if t in k:
            return "landmark", t
    return "unknown", None


def _adequacy(name: str, token: str) -> int:
    """이름 적합도 — 상호 차용(…공원점/캠퍼스) 최하, 실제 명칭(…공원) 우대."""
    if any(f"{token}{s}" in name for s in ("점", "캠퍼스", "지점", "타운")):
        return 0  # 랜드마크 상호 차용 — 실제 그곳이 아님
    if name.endswith(token):
        return 2  # 실제 명칭(예: 모래성공원)
    if token in name:
        return 1
    return 0


# 위치 밴드(루프 자연 지점, 2026-07-22 (b)): pitstop이 시작점 코앞(84m)이면 5km
# 루프 기하가 핀치돼 overshoot→502(청라 실사용 검증). 상한은 target×0.5, **하한은 절대
# 200m**(2026-07-22 좌표민감도 부검: target×0.15=750m 하한이 랜드마크 근접 출발점에서
# 대표 park(청라호수공원 354m)를 잘라내 소공원이 뽑히던 것 교정. 핀치는 target 무관 절대
# 기하라 절대 하한이 맞다 — 200m 미만만 핀치 보호로 제외). 밴드 내 0이면 적합도·최근접 폴백.
_POS_BAND_LO_M = 200.0          # 절대 하한(핀치 보호) — 200m 미만만 제외
_POS_BAND_HI_FACTOR = 0.50      # 상한은 target 비례 유지


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 great-circle 거리(m) — pitstop 위치 밴드용."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(x))


def _in_position_band(start: Coordinate, place: Place, target_km: float) -> bool:
    """pitstop이 루프 자연 지점(시작 거리 [절대 200m, target×0.5]) 안인가.
    하한 절대 200m: 핀치(코앞 pitstop→overshoot)만 제외, 300~700m 대표 park는 통과."""
    d_m = _haversine_m(start.lat, start.lng, place.coordinate.lat, place.coordinate.lng)
    return _POS_BAND_LO_M <= d_m <= target_km * _POS_BAND_HI_FACTOR * 1000.0


def rank_places_for_keyword(
    keyword: str, places: list[Place],
    start: Coordinate | None = None, target_km: float | None = None,
) -> list[Place]:
    """pitstop 의도 존중 재랭킹/필터. 통과 후보 리스트(빈 리스트면 상위가 폴백).

    - unknown 의도: 원본(거리순) 그대로 — 현행 동작 보존.
    - commercial 의도: 그 카테고리 코드만 남김(거리순 유지).
    - landmark 의도: 상업 카테고리 제외 후 [적합도 desc, **위치밴드 desc**, **대표성**,
      시작거리 asc] 안정 정렬. **대표성 = Kakao accuracy 순위**(places는 accuracy 정렬로
      들어옴 → 원 인덱스가 순위, 작을수록 대표). ★밴드 내에서만 대표성 tiebreak(오너 C) —
      밴드 밖은 기존 거리순. 청라 실측: accuracy가 청라호수공원을 밴드 내 #1로 올림.
    """
    intent, param = _keyword_intent(keyword)
    if intent == "unknown":
        return places
    if intent == "commercial":
        return [p for p in places if p.category_code == param]
    kept = [p for p in places if p.category_code not in _COMMERCIAL_CODES]
    if not kept:
        return []
    has_band = start is not None and target_km is not None
    acc_rank = {id(p): i for i, p in enumerate(places)}  # accuracy 정렬 원 순위

    def _key(p: Place):
        adeq = _adequacy(p.name, param)
        if has_band:
            d = _haversine_m(start.lat, start.lng,
                             p.coordinate.lat, p.coordinate.lng) / 1000.0
            in_band = _in_position_band(start, p, target_km)
        else:
            d, in_band = 0.0, False
        # 적합도 → 위치밴드 → (밴드 내면 accuracy 순위=대표성, 밴드 밖이면 거리 상수)
        # → 최종 거리. 밴드 내에서만 대표성이 거리를 이긴다(오너 C).
        rep = acc_rank[id(p)] if in_band else 10 ** 9
        return (-adeq, -int(in_band), rep, d)

    return sorted(kept, key=_key)


async def _naver_search_places(
    keyword: str, near: Coordinate, radius_m: int, limit: int
) -> list[Place]:
    """Naver place search stub.

    Naver's place/local search lives behind the NAVER Search API (separate
    credentials from Maps). Implement against your chosen endpoint here.
    """
    raise NotImplementedError(
        "Naver place search is not implemented. Use MAP_PROVIDER=kakao, "
        "or wire up the NAVER Search (Local) API here."
    )


# --- Pedestrian routing ------------------------------------------------------


class LegNotRoutable(Exception):
    """T-map이 이 leg(두 점 사이)의 실보행 경로를 못 찾음 — 200이지만 빈 경로.

    강 위·철로 등 보행 불가 구간의 양안 웨이포인트를 이을 때 발생. HTTP/네트워크
    장애(raise_for_status)와 구분해 상위(route_service)가 이 후보를 traversability
    실패로 폐기하게 한다 — 그냥 두면 그 leg가 폴리라인에서 누락돼 렌더 시 인접
    구간이 물 위를 직선 횡단하게 보인다(Ivan 리포트 A). 좌표 미기록(프라이버시)."""


class TmapQuotaExceeded(Exception):
    """T-map 무료 쿼터 소진 — HTTP 429 QUOTA_EXCEEDED (일시적 인프라 한계).

    LegNotRoutable(지오 문제, 후보 자체 결함)과 **반드시 구분**한다: 이건 후보가
    아니라 우리 쪽 일일 콜 예산이 바닥난 것 — 상위(route_service)가 AI추정 nopath
    폴백(폴리라인 없는 가짜 코스)을 서빙하는 대신 503으로 정직하게 실패하게 한다
    ("앱은 거짓말하지 않는다", 2026-07-21 E2E 실증: 429 전패가 5/5 nopath 200 서빙).
    무료 티어는 자정(KST) 리셋. 좌표 미기록(프라이버시)."""


async def get_pedestrian_route(
    origin: Coordinate,
    destination: Coordinate,
    waypoints: list[Coordinate] | None = None,
) -> PedestrianRoute:
    """Fetch a walking/pedestrian route between two points (optionally via waypoints).

    Returns a normalized PedestrianRoute. Uses the configured MAP_PROVIDER.

    Note: Kakao Mobility and Naver Directions are primarily *driving* APIs.
    For true sidewalk-accurate pedestrian routing in Korea, prefer the T-map
    Pedestrian API (MAP_PROVIDER=tmap).
    """
    if settings.map_provider == "tmap":
        return await _tmap_pedestrian_route(origin, destination, waypoints)
    if settings.map_provider == "kakao":
        return await _kakao_route(origin, destination, waypoints)
    return await _naver_route(origin, destination, waypoints)


async def _kakao_route(
    origin: Coordinate,
    destination: Coordinate,
    waypoints: list[Coordinate] | None,
) -> PedestrianRoute:
    """Kakao Mobility directions. Coordinates are "lng,lat" strings."""
    headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}
    params: dict[str, str] = {
        "origin": f"{origin.lng},{origin.lat}",
        "destination": f"{destination.lng},{destination.lat}",
        "priority": "RECOMMEND",
    }
    if waypoints:
        params["waypoints"] = "|".join(f"{w.lng},{w.lat}" for w in waypoints)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(KAKAO_DIRECTIONS_URL, headers=headers, params=params)
        resp.raise_for_status()
        data = loads_lenient(resp.text, context="kakao directions")  # 제어문자 방어

    # Parse the first route's summary + geometry.
    route = data["routes"][0]
    summary = route["summary"]
    path: list[Coordinate] = []
    for section in route.get("sections", []):
        for road in section.get("roads", []):
            verts = road.get("vertexes", [])
            # vertexes are a flat [lng, lat, lng, lat, ...] array.
            for i in range(0, len(verts) - 1, 2):
                path.append(Coordinate(lat=verts[i + 1], lng=verts[i]))

    return PedestrianRoute(
        distance_m=float(summary["distance"]),
        duration_s=float(summary["duration"]),
        path=path,
        provider="kakao",
    )


async def _naver_route(
    origin: Coordinate,
    destination: Coordinate,
    waypoints: list[Coordinate] | None,
) -> PedestrianRoute:
    """Naver Directions (NCP). Coordinates are "lng,lat" strings."""
    headers = {
        "x-ncp-apigw-api-key-id": settings.naver_map_client_id,
        "x-ncp-apigw-api-key": settings.naver_map_client_secret,
    }
    params: dict[str, str] = {
        "start": f"{origin.lng},{origin.lat}",
        "goal": f"{destination.lng},{destination.lat}",
    }
    if waypoints:
        params["waypoints"] = "|".join(f"{w.lng},{w.lat}" for w in waypoints)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(NAVER_DRIVING_URL, headers=headers, params=params)
        resp.raise_for_status()
        data = loads_lenient(resp.text, context="naver driving")  # 제어문자 방어

    route = data["route"]["traoptimal"][0]
    summary = route["summary"]
    path = [Coordinate(lat=pt[1], lng=pt[0]) for pt in route.get("path", [])]

    return PedestrianRoute(
        distance_m=float(summary["distance"]),
        duration_s=float(summary["duration"]) / 1000.0,  # naver returns ms
        path=path,
        provider="naver",
    )


async def _tmap_pedestrian_route(
    origin: Coordinate,
    destination: Coordinate,
    waypoints: list[Coordinate] | None,
) -> PedestrianRoute:
    """T-map Pedestrian routing — sidewalk-accurate walking paths.

    The T-map *pedestrian* API only routes between a single start and end
    point (its `passList` waypoint support is unreliable for walking). To
    follow an arbitrary number of AI-generated waypoints in order, we split
    the ordered point list into adjacent pairs, route each leg separately,
    then stitch the legs back into one continuous path and sum the totals.

    This removes the old 5-waypoint cap: every point is honored.
    """
    # Full ordered itinerary: start -> each waypoint -> end.
    points: list[Coordinate] = [origin, *(waypoints or []), destination]

    total_distance_m = 0.0
    total_duration_s = 0.0
    path: list[Coordinate] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for leg_index in range(len(points) - 1):
            leg_start = points[leg_index]
            leg_end = points[leg_index + 1]
            distance_m, duration_s, leg_path = await _tmap_walk_leg(
                client, leg_start, leg_end
            )
            total_distance_m += distance_m
            total_duration_s += duration_s

            # Drop the first coordinate of every leg after the first so the
            # shared point between consecutive legs isn't duplicated.
            if path and leg_path:
                leg_path = leg_path[1:]
            path.extend(leg_path)

    return PedestrianRoute(
        distance_m=total_distance_m,
        duration_s=total_duration_s,
        path=path,
        provider="tmap",
    )


async def _tmap_walk_leg(
    client: httpx.AsyncClient,
    origin: Coordinate,
    destination: Coordinate,
) -> tuple[float, float, list[Coordinate]]:
    """Route a single start->end pedestrian leg via the T-map API.

    T-map is a POST with a JSON body and returns a GeoJSON FeatureCollection.
    Coordinates are WGS84 lng/lat. Returns (distance_m, duration_s, path).
    """
    headers = {
        "appKey": settings.tmap_app_key,
        "Content-Type": "application/json",
    }
    body: dict[str, object] = {
        "startX": origin.lng,
        "startY": origin.lat,
        "endX": destination.lng,
        "endY": destination.lat,
        "startName": "start",
        "endName": "end",
        "reqCoordType": "WGS84GEO",  # input coordinate system
        "resCoordType": "WGS84GEO",  # response coordinate system
        "searchOption": "0",  # 0=recommended, 4=shortest distance
    }

    resp = await client.post(TMAP_PEDESTRIAN_URL, headers=headers, json=body)
    # T-map 무료 쿼터 소진은 429 QUOTA_EXCEEDED — 일반 HTTP 장애와 구분해 전용
    # 예외로 승격(상위가 nopath 폴백 금지·503 정직화). 다른 4xx/5xx는 그대로 전파.
    if resp.status_code == 429:
        raise TmapQuotaExceeded()
    resp.raise_for_status()
    # T-map GeoJSON 응답의 도로/POI명에 간헐적 미이스케이프 제어문자 → E2E 성수
    # nopath의 실블로커(2026-07-22). 표준 resp.json() 대신 제어문자 방어 파싱.
    data = loads_lenient(resp.text, context="tmap pedestrian")

    # Totals live on the first (Point) feature's properties; the geometry is
    # the concatenation of all LineString features.
    distance_m = 0.0
    duration_s = 0.0
    path: list[Coordinate] = []

    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if "totalDistance" in props:
            distance_m = float(props["totalDistance"])
        if "totalTime" in props:
            duration_s = float(props["totalTime"])

        geometry = feature.get("geometry", {})
        if geometry.get("type") == "LineString":
            for lng, lat in geometry.get("coordinates", []):
                path.append(Coordinate(lat=lat, lng=lng))

    # T-map은 보행 불가 구간에 200 + 빈/무의미 응답을 준다(에러코드가 아님).
    # 유효 경로(거리>0·점 존재) 없으면 이 leg는 실보행 불가 — 조용히 distance=0,
    # path=[]로 통과시키면 폴리라인에 구멍이 나 물 위 직선 횡단이 생긴다(리포트 A).
    if not path or distance_m <= 0:
        raise LegNotRoutable()

    return distance_m, duration_s, path
