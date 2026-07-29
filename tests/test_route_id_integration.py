"""
Integration: RouteResponse.route_id additive (2026-07-29, 07/09 파킹 항목 트리거)

주요 서빙 분기 전수(§10): 캐노니컬 훅 / on_course / v87 메인(mock) / dedup
last-resort 재매치 — 응답 route_id 존재 + GET 조회 일치. 임시 유저 정리 포함.

Run: python tests/test_route_id_integration.py
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
from app.models.schemas import Coordinate, PedestrianRoute, RouteRequest, RouteResponse, Waypoint  # noqa: E402
from app.services import map_service, openai_service, route_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None


def ok(m):
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


async def _assert_id(route, label):
    assert route.route_id, f"{label}: route_id 부재"
    stored = await route_service.get_route(route.route_id, _uid)
    assert stored is not None, f"{label}: GET 조회 실패"
    assert abs(stored.total_distance_km - route.total_distance_km) < 0.05, \
        (label, stored.total_distance_km, route.total_distance_km)
    ok(f"{label}: route_id={route.route_id[:8]}… → GET 일치({stored.total_distance_km}km)")
    return route.route_id


async def main():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"rid-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    sb = get_supabase_admin()

    print("[1. 캐노니컬 훅 분기 — 청라]")
    req_c = RouteRequest(start=Coordinate(lat=37.528678, lng=126.635812),
                         target_distance_km=4.5)
    r1 = await route_service.create_running_route(req_c, user_id=_uid)
    id1 = await _assert_id(r1, "canonical")

    print("\n[2. on_course 분기 — 아시아드 플라자]")
    r2 = await route_service.create_running_route(
        RouteRequest(start=Coordinate(lat=37.544532, lng=126.66425),
                     target_distance_km=2.0), user_id=_uid)
    await _assert_id(r2, "on_course")

    print("\n[3. v87 메인 분기 — mock 파이프라인]")
    START = Coordinate(lat=37.60, lng=127.20)   # 캐노니컬 미커버 좌표

    def _cand(start):
        a = Coordinate(lat=start.lat + 0.011, lng=start.lng)
        b = Coordinate(lat=start.lat + 0.011, lng=start.lng + 0.013)
        wps = [Waypoint(name="출발", coordinate=start, is_pitstop=False),
               Waypoint(name="지점 1", coordinate=a, is_pitstop=False),
               Waypoint(name="지점 2", coordinate=b, is_pitstop=False),
               Waypoint(name="복귀", coordinate=start, is_pitstop=False)]
        return RouteResponse(summary="mock", total_distance_km=5.0, waypoints=wps)

    async def gen_mock(**kw):
        return _cand(kw["start"])

    async def snap_mock(origin, destination, waypoints=None):
        pts = [Coordinate(lat=START.lat + 0.0001 * i, lng=START.lng) for i in range(50)]
        return PedestrianRoute(distance_m=5000, duration_s=4000, path=pts,
                               provider="tmap", road_segments=[])

    async def parks_mock(*a, **k):
        return []

    async def apt_mock(*a, **k):
        return (0, 0)

    orig = (openai_service.generate_route, map_service.get_pedestrian_route,
            map_service.search_places, map_service.count_apartment_signal)
    openai_service.generate_route = gen_mock
    map_service.get_pedestrian_route = snap_mock
    map_service.search_places = parks_mock
    map_service.count_apartment_signal = apt_mock
    try:
        r3 = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0), user_id=_uid)
        await _assert_id(r3, "v87(mock)")

        print("\n[4. dedup last-resort 재매치 분기 — 청라 소유 + 생성 전패]")
        async def boom(**kw):
            raise RuntimeError("forced")
        openai_service.generate_route = boom
        r4 = await route_service.create_running_route(req_c, user_id=_uid)  # 청라 재요청
        assert (r4.summary == "청라호수공원 순환"), r4.summary
        id4 = await _assert_id(r4, "dedup_exhausted 재서빙")
        assert id4 != id1, "재서빙도 새 행 — id 상이해야"
    finally:
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.count_apartment_signal) = orig


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    rows = sb.table("routes").select("id").eq("user_id", _uid).execute().data
    if rows:
        sb.table("routes").delete().in_("id", [x["id"] for x in rows]).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    left = len(sb.table("routes").select("id").eq("user_id", _uid).execute().data)
    assert left == 0
    print(f"\n[cleanup] routes {len(rows)}행·임시 유저 삭제(잔여 0)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
