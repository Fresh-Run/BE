"""Tests for T-map pedestrian routing parsing in app/services/map_service.py.

These mock the outbound httpx call with a recorded T-map GeoJSON response
(tests/fixtures/tmap_pedestrian.json) so we can lock down:
  - summary totals (distance/time) parsing,
  - LineString geometry concatenation + lng/lat -> lat/lng mapping,
  - provider dispatch via settings.map_provider,
  - passList construction for waypoints.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.schemas import Coordinate
from app.services import map_service

FIXTURE = Path(__file__).parent / "fixtures" / "tmap_pedestrian.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient that records the POST and returns a fixture."""

    def __init__(self, payload: dict, capture: dict):
        self._payload = payload
        self._capture = capture

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_args) -> bool:
        return False

    async def post(self, url, headers=None, json=None):  # noqa: A002 - mirror httpx kwarg
        self._capture["url"] = url
        self._capture["headers"] = headers
        self._capture["body"] = json
        return _FakeResponse(self._payload)


@pytest.fixture
def patch_tmap(monkeypatch):
    """Patch httpx.AsyncClient and force MAP_PROVIDER=tmap; yields the capture dict."""
    capture: dict = {}
    payload = load_fixture()

    monkeypatch.setattr(map_service.settings, "map_provider", "tmap")
    monkeypatch.setattr(map_service.settings, "tmap_app_key", "test-key")
    monkeypatch.setattr(
        map_service.httpx,
        "AsyncClient",
        lambda *a, **k: _FakeAsyncClient(payload, capture),
    )
    return capture


ORIGIN = Coordinate(lat=37.56635, lng=126.97793)
DESTINATION = Coordinate(lat=37.56944, lng=126.98115)


async def test_parses_summary_totals(patch_tmap):
    route = await map_service.get_pedestrian_route(ORIGIN, DESTINATION)

    assert route.provider == "tmap"
    assert route.distance_m == 1284.0
    assert route.duration_s == 925.0


async def test_concatenates_linestring_geometries(patch_tmap):
    route = await map_service.get_pedestrian_route(ORIGIN, DESTINATION)

    # Two LineString features with 3 coords each -> 6 path points.
    assert len(route.path) == 6
    # Points are returned as Coordinate(lat, lng) — response order is [lng, lat].
    first = route.path[0]
    assert first.lat == pytest.approx(37.56635)
    assert first.lng == pytest.approx(126.97793)
    last = route.path[-1]
    assert last.lat == pytest.approx(37.56944)
    assert last.lng == pytest.approx(126.98115)


async def test_request_body_uses_wgs84_and_lnglat(patch_tmap):
    await map_service.get_pedestrian_route(ORIGIN, DESTINATION)

    body = patch_tmap["body"]
    assert body["startX"] == ORIGIN.lng
    assert body["startY"] == ORIGIN.lat
    assert body["endX"] == DESTINATION.lng
    assert body["endY"] == DESTINATION.lat
    assert body["reqCoordType"] == "WGS84GEO"
    assert body["resCoordType"] == "WGS84GEO"
    assert patch_tmap["headers"]["appKey"] == "test-key"
    # No waypoints -> no passList key.
    assert "passList" not in body


async def test_waypoints_build_passlist(patch_tmap):
    waypoints = [
        Coordinate(lat=37.56702, lng=126.97850),
        Coordinate(lat=37.56850, lng=126.98010),
    ]
    await map_service.get_pedestrian_route(ORIGIN, DESTINATION, waypoints=waypoints)

    body = patch_tmap["body"]
    assert body["passList"] == "126.9785,37.56702_126.9801,37.5685"


async def test_passlist_caps_at_five_waypoints(patch_tmap):
    waypoints = [Coordinate(lat=37.5663 + i * 0.001, lng=126.9779) for i in range(8)]
    await map_service.get_pedestrian_route(ORIGIN, DESTINATION, waypoints=waypoints)

    body = patch_tmap["body"]
    # T-map allows at most 5 intermediate points.
    assert len(body["passList"].split("_")) == 5
