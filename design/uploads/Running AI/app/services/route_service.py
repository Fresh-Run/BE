"""Orchestration: combine the OpenAI route generation with Map API data.

This is the business-logic glue the API layer calls. It asks OpenAI for a
candidate route, optionally resolves the pitstop against the real Map API,
and enriches the response with actual pedestrian routing geometry.
"""

from __future__ import annotations

from app.models.schemas import RouteRequest, RouteResponse
from app.services import map_service, openai_service


async def create_running_route(req: RouteRequest) -> RouteResponse:
    """Produce a running route for the given request.

    Steps:
      1. Ask OpenAI to design a route (structured via function calling).
      2. (Optional) Resolve the pitstop keyword to a real nearby place.
      3. (Optional) Fetch real pedestrian path geometry from the Map API.
    """
    route = await openai_service.generate_route(
        target_distance_km=req.target_distance_km,
        start=req.start,
        end=req.end,
        pitstop_keyword=req.pitstop_keyword,
        notes=req.notes,
    )

    # Step 2: snap the pitstop to a real place if a keyword was given.
    if req.pitstop_keyword:
        try:
            places = await map_service.search_places(req.pitstop_keyword, near=req.start)
            if places:
                nearest = places[0]
                for wp in route.waypoints:
                    if wp.is_pitstop:
                        wp.name = nearest.name
                        wp.coordinate = nearest.coordinate
                        wp.description = nearest.address
                        break
        except Exception:  # noqa: BLE001 - map enrichment is best-effort
            # If the Map API fails, keep the AI-suggested pitstop as-is.
            pass

    # Step 3: enrich with a real pedestrian path when we have >= 2 points.
    if len(route.waypoints) >= 2:
        try:
            via = [wp.coordinate for wp in route.waypoints[1:-1]] or None
            pedestrian = await map_service.get_pedestrian_route(
                origin=route.waypoints[0].coordinate,
                destination=route.waypoints[-1].coordinate,
                waypoints=via,
            )
            route.polyline = pedestrian.path
            route.total_distance_km = round(pedestrian.distance_m / 1000.0, 2)
            route.estimated_duration_min = round(pedestrian.duration_s / 60.0, 1)
        except Exception:  # noqa: BLE001 - keep AI estimates if routing fails
            pass

    return route
