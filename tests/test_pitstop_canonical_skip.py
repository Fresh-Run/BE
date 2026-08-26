"""
Integration: pitstop 의도 시 canonical 스킵 (P2, 오너 결정 a, 2026-08-26)

경유지 요청(pitstop_keyword or pitstop_place)이 있으면 canonical(경유지 없는 고정
코스) 우선 서빙을 스킵하고 생성 경로로 → pitstop 주입(is_pitstop=1, UI "1곳" 일치).
무pitstop 요청은 canonical 우선(현행 불변). 생성 전멸 시 canonical last-resort 폴백.
Gemini/T-map/Kakao/canonical 실콜 0(seam mock). 임시 유저 생성분 즉삭.

Run: python tests/test_pitstop_canonical_skip.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.models.schemas import (  # noqa: E402
    Coordinate, KoreaCoordinate, PedestrianRoute, Place, PitstopPlace,
    RouteRequest, RouteResponse, Waypoint,
)
from app.services import canonical_service, map_service, openai_service, route_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None
START = KoreaCoordinate(lat=37.60, lng=127.20)
CAFE = Place(name="검색카페", coordinate=Coordinate(lat=START.lat + 0.011, lng=START.lng + 0.013),
             category="카페", category_code="CE7", address="주소")
USER_POI = PitstopPlace(name="유저지정카페",
                        coordinate=KoreaCoordinate(lat=START.lat + 0.011, lng=START.lng + 0.013),
                        category_code="CE7")
_passed = 0
_canon_calls: list = []


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _cand(start, pit=True):
    a = Coordinate(lat=start.lat + 0.011, lng=start.lng)
    b = Coordinate(lat=start.lat + 0.011, lng=start.lng + 0.013)
    return RouteResponse(summary="mock", total_distance_km=5.0, waypoints=[
        Waypoint(name="출발", coordinate=start, is_pitstop=False),
        Waypoint(name="지점 1", coordinate=a, is_pitstop=False),
        Waypoint(name="지점 2", coordinate=b, is_pitstop=pit),
        Waypoint(name="복귀", coordinate=start, is_pitstop=False)])


def _pit_wp(r):
    return next((w for w in r.waypoints if w.is_pitstop), None)


async def _gen(**kw):
    return _cand(kw["start"], pit=True)


async def _snap(origin, destination, waypoints=None):
    return PedestrianRoute(distance_m=5000, duration_s=4000,
                           path=[Coordinate(lat=START.lat + 0.0001 * i, lng=START.lng) for i in range(60)],
                           provider="tmap", road_segments=[])


async def _search(query, *a, **k):
    return [CAFE] if query == "카페" else []


def _rank(keyword, places, start=None, target_km=None):
    return list(places)


async def _apt(*a, **k):
    return (0, 0)


async def _mock_canon(start, target_km, **k):
    """canonical 매칭 시뮬 — 호출 카운트. 매칭되면 canonical 코스 반환."""
    _canon_calls.append(1)
    croute = RouteResponse(summary="청라호수공원 순환", total_distance_km=4.5, waypoints=[
        Waypoint(name="출발", coordinate=Coordinate(lat=start.lat, lng=start.lng), is_pitstop=False),
        Waypoint(name="호수공원", coordinate=Coordinate(lat=start.lat + 0.01, lng=start.lng), is_pitstop=False),
        Waypoint(name="복귀", coordinate=Coordinate(lat=start.lat, lng=start.lng), is_pitstop=False)],
        polyline=[Coordinate(lat=start.lat + 0.0001 * i, lng=start.lng) for i in range(50)])
    return croute, {"engine": "canonical", "verdict": "canonical",
                    "course_id": "00000000-0000-4000-8000-0000000000cc", "course_name": "청라호수공원 순환"}


class _Patched:
    def __init__(self, gen=_gen):
        self.gen = gen

    def __enter__(self):
        _canon_calls.clear()
        self._orig = (openai_service.generate_route, map_service.get_pedestrian_route,
                      map_service.search_places, map_service.rank_places_for_keyword,
                      map_service.count_apartment_signal, canonical_service.match_and_build,
                      route_service.canonical_service.match_and_build)
        openai_service.generate_route = self.gen
        map_service.get_pedestrian_route = _snap
        map_service.search_places = _search
        map_service.rank_places_for_keyword = _rank
        map_service.count_apartment_signal = _apt
        canonical_service.match_and_build = _mock_canon
        route_service.canonical_service.match_and_build = _mock_canon
        return self

    def __exit__(self, *e):
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.rank_places_for_keyword,
         map_service.count_apartment_signal, canonical_service.match_and_build,
         route_service.canonical_service.match_and_build) = self._orig


async def main():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"p2-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]

    # A. pitstop_keyword → canonical 스킵, 생성+pitstop 주입, is_pitstop=1
    print("[A. pitstop_keyword — canonical 스킵]")
    with _Patched():
        ra = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_keyword="카페"), user_id=_uid)
    assert _canon_calls == [], f"pitstop인데 canonical 호출됨: {_canon_calls}"
    assert ra.summary != "청라호수공원 순환", ra.summary  # canonical 아님
    assert _pit_wp(ra) and _pit_wp(ra).name == "검색카페"
    ok(f"canonical 스킵(호출 0)·생성 서빙·is_pitstop=1('{_pit_wp(ra).name}')·카운트 일치")

    # B. 무pitstop → canonical 우선(현행 불변)
    print("\n[B. 무pitstop — canonical 우선]")
    with _Patched():
        rb = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0), user_id=_uid)
    assert _canon_calls and rb.summary == "청라호수공원 순환", (_canon_calls, rb.summary)
    assert _pit_wp(rb) is None
    ok("canonical 서빙(호출≥1·실명 summary)·is_pitstop 없음(하위호환)")

    # C. pitstop_place-only → canonical 스킵, place 주입
    print("\n[C. pitstop_place-only — canonical 스킵]")
    with _Patched():
        rc = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_place=USER_POI), user_id=_uid)
    assert _canon_calls == [] and _pit_wp(rc).name == USER_POI.name
    ok(f"place-only도 canonical 스킵·place 주입('{_pit_wp(rc).name}')")

    # D. pitstop인데 생성 전멸 → canonical last-resort 폴백(빈손 502 금지)
    print("\n[D. 생성 전멸 + pitstop — canonical 폴백]")
    async def _boom(**kw):
        raise RuntimeError("forced gen fail")
    with _Patched(gen=_boom):
        rd = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_keyword="카페"), user_id=_uid)
    assert rd.summary == "청라호수공원 순환", rd.summary   # last-resort canonical
    assert _canon_calls, "폴백 canonical 미호출"
    ok("생성 전멸 시 canonical last-resort 폴백(경유지 없지만 코스 서빙·502 아님)")


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    rows = sb.table("routes").select("id").eq("user_id", _uid).execute().data
    if rows:
        sb.table("routes").delete().in_("id", [x["id"] for x in rows]).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    assert len(sb.table("routes").select("id").eq("user_id", _uid).execute().data) == 0
    print(f"\n[cleanup] routes {len(rows)}행·임시 유저 삭제(잔여 0)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_passed} assert)\n" + "=" * 50)
    finally:
        cleanup()
