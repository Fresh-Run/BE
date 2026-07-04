"""HTTP route handlers for the running route API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import Coordinate, Place, RouteRequest, RouteResponse
from app.services import map_service, route_service

router = APIRouter(prefix="/api", tags=["routes"])


@router.post(
    "/routes/generate",
    response_model=RouteResponse,
    summary="Generate a running route",
)
async def generate_route(req: RouteRequest) -> RouteResponse:
    """Generate an AI running route, enriched with real Map API data."""
    try:
        return await route_service.create_running_route(req)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to generate route: {exc}")


@router.get("/places", response_model=list[Place], summary="Search nearby places")
async def search_places(
    keyword: str,
    lat: float,
    lng: float,
    radius_m: int = 2000,
    limit: int = 5,
) -> list[Place]:
    """Search for pitstop candidates (e.g. '편의점') near a coordinate."""
    try:
        return await map_service.search_places(
            keyword=keyword,
            near=Coordinate(lat=lat, lng=lng),
            radius_m=radius_m,
            limit=limit,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Place search failed: {exc}")
