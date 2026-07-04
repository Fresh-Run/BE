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

import httpx
from pydantic import ValidationError

from app.core.config import settings
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
    near: Coordinate,
    radius_m: int = 2000,
    limit: int = 5,
) -> list[Place]:
    """Search for places (e.g. '편의점') near a coordinate.

    Place (keyword) search always uses Kakao, independent of MAP_PROVIDER
    (which only selects the *routing* provider, e.g. T-map for walking).
    Returns a normalized list of Places.
    """
    return await _kakao_search_places(keyword, near, radius_m, limit)


async def _kakao_search_places(
    keyword: str, near: Coordinate, radius_m: int, limit: int
) -> list[Place]:
    """Kakao Local keyword search. Kakao expects x=lng, y=lat."""
    if not settings.kakao_rest_api_key:
        raise RuntimeError(
            "Kakao place search is not configured. Set KAKAO_REST_API_KEY "
            "in your environment (see .env.example)."
        )

    headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}
    params = {
        "query": keyword,
        "x": near.lng,
        "y": near.lat,
        "radius": radius_m,
        "size": limit,
        "sort": "distance",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(KAKAO_KEYWORD_SEARCH_URL, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

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
                address=doc.get("road_address_name") or doc.get("address_name"),
            )
        )
    return places


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
        data = resp.json()

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
        data = resp.json()

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
    resp.raise_for_status()
    data = resp.json()

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

    return distance_m, duration_s, path
