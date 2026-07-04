"""Pydantic schemas shared across the API and services.

Coordinate convention: South Korea uses WGS84 lat/lng. Note that Kakao's
REST API expects coordinates as `x=longitude, y=latitude`.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Coordinate(BaseModel):
    """A WGS84 geographic point."""

    lat: float = Field(..., description="Latitude (위도)", ge=33.0, le=39.0)
    lng: float = Field(..., description="Longitude (경도)", ge=124.0, le=132.0)


class RouteRequest(BaseModel):
    """Input from the client to generate a running route."""

    start: Coordinate = Field(..., description="Starting point")
    end: Optional[Coordinate] = Field(
        None,
        description="End point. If omitted, a loop back to start is assumed.",
    )
    target_distance_km: float = Field(
        ...,
        gt=0,
        le=100,
        description="Desired total running distance in kilometers.",
    )
    pitstop_keyword: Optional[str] = Field(
        None,
        description="Optional waypoint keyword, e.g. '편의점' (convenience store), '공원', 'cafe'.",
    )
    notes: Optional[str] = Field(
        None, description="Free-form preferences, e.g. 'avoid hills', 'riverside'."
    )


class Waypoint(BaseModel):
    """A single ordered point along the generated route."""

    name: str = Field(..., description="Human-readable label for this waypoint.")
    coordinate: Coordinate
    is_pitstop: bool = Field(
        False, description="True if this waypoint matches the requested pitstop keyword."
    )
    description: Optional[str] = Field(
        None, description="Why this point was chosen / what's here."
    )


class RouteResponse(BaseModel):
    """Structured running route returned to the client."""

    summary: str = Field(..., description="Short human-readable description of the route.")
    total_distance_km: float = Field(..., description="Estimated total distance.")
    estimated_duration_min: Optional[float] = Field(
        None, description="Estimated jogging duration in minutes."
    )
    waypoints: list[Waypoint] = Field(
        default_factory=list, description="Ordered waypoints from start to finish."
    )
    polyline: Optional[list[Coordinate]] = Field(
        None,
        description="Decoded path geometry (from the Map API) for drawing on a map.",
    )


class PedestrianRoute(BaseModel):
    """Normalized result returned by the Map service routing functions."""

    distance_m: float = Field(..., description="Total walking distance in meters.")
    duration_s: float = Field(..., description="Estimated walking duration in seconds.")
    path: list[Coordinate] = Field(
        default_factory=list, description="Ordered coordinates of the walking path."
    )
    provider: str = Field(..., description="'kakao' or 'naver'.")


class Place(BaseModel):
    """A point of interest returned by a keyword/place search."""

    name: str
    coordinate: Coordinate
    category: Optional[str] = None
    address: Optional[str] = None
