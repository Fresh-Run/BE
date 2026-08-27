"""
far-POI best-effort 서빙 — 먼 pitstop_place 502 금지 (A-2 계약 ⓓ, 2026-08-27)

버그(이반 실측): pitstop_place 지정 POI가 경로에 비해 멀면(위치밴드 target×0.5 밖)
via 편입 시 경로가 target+1.0km·왕복팔 800m를 넘어 _serveable_over_cap 전멸 →
502 route_generation_failed(6초). 계약 ⓓ는 best-effort 편입 + target_missed:true.

수정: far pitstop이면 over-cap/retrace 게이트 완화 — 최소 초과 편입 후보를
target_missed=true로 서빙(502 금지). 마커·폴리라인은 지정 POI로 정합(overwrite_coord).

커버:
  A. far pitstop_place(3.1km) → 502 아님·서빙·target_missed·far_served·마커==POI
  B. near pitstop_place(0.8km, 밴드 내) → 종전 편입(far 아님)·서빙
  C. 무pitstop → far 로직 미발동
Gemini·T-map·Kakao 실콜 0(seam mock). 임시 유저 생성분 전량 정리.
Run: python tests/test_pitstop_far_besteffort.py
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.models.schemas import (  # noqa: E402
    Coordinate, KoreaCoordinate, PedestrianRoute, PitstopPlace,
    RouteRequest, RouteResponse, Waypoint,
)
from app.services import map_service, openai_service, route_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None
_passed = 0
TARGET = 3.0
START = KoreaCoordinate(lat=37.5446, lng=127.0559)  # 이반 성수
FAR = PitstopPlace(name="먼 유저POI", category_code="CE7",
                   coordinate=KoreaCoordinate(lat=START.lat + 0.028, lng=START.lng))   # ~3.1km
NEAR = PitstopPlace(name="가까운 유저POI", category_code="CE7",
                    coordinate=KoreaCoordinate(lat=START.lat + 0.007, lng=START.lng))  # ~0.78km(밴드 내)


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def hav_km(a, b):
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = math.radians(b.lat - a.lat), math.radians(b.lng - a.lng)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


async def _snap(origin, destination, waypoints=None):
    pts = [origin] + (waypoints or []) + [destination]
    dm = sum(hav_km(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) * 1000
    path = []
    for i in range(len(pts) - 1):
        for t in range(20):
            f = t / 20
            path.append(Coordinate(lat=pts[i].lat + (pts[i + 1].lat - pts[i].lat) * f,
                                   lng=pts[i].lng + (pts[i + 1].lng - pts[i].lng) * f))
    path.append(destination)
    return PedestrianRoute(distance_m=dm, duration_s=dm, path=path, provider="tmap", road_segments=[])


async def _search(q, *a, **k):
    return []


def _rank(kw, places, start=None, target_km=None, recent_pitstops=None):
    return list(places)


async def _apt(*a, **k):
    return (0, 0)


def _cand(start, with_pitstop=True):
    wp1 = Coordinate(lat=start.lat + 0.011, lng=start.lng + 0.009)  # 루프 크기(무pitstop 밴드 내)
    slot = Coordinate(lat=start.lat + 0.006, lng=start.lng + 0.005)  # writeback이 POI로 덮음
    return RouteResponse(summary="mock", total_distance_km=TARGET, waypoints=[
        Waypoint(name="출발", coordinate=start, is_pitstop=False),
        Waypoint(name="지점 1", coordinate=wp1, is_pitstop=False),
        Waypoint(name="지점 2", coordinate=slot, is_pitstop=with_pitstop),
        Waypoint(name="복귀", coordinate=start, is_pitstop=False)])


class _Patched:
    def __init__(self, with_pitstop=True):
        self.wp = with_pitstop

    async def _gen(self, **kw):
        return _cand(kw["start"], self.wp)

    def __enter__(self):
        self._orig = (openai_service.generate_route, map_service.get_pedestrian_route,
                      map_service.search_places, map_service.rank_places_for_keyword,
                      map_service.count_apartment_signal)
        openai_service.generate_route = self._gen
        map_service.get_pedestrian_route = _snap
        map_service.search_places = _search
        map_service.rank_places_for_keyword = _rank
        map_service.count_apartment_signal = _apt
        return self

    def __exit__(self, *e):
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.rank_places_for_keyword,
         map_service.count_apartment_signal) = self._orig


def _pit(r):
    return next((w for w in r.waypoints if w.is_pitstop), None)


async def _gm(route_id):
    sb = get_supabase_admin()
    row = sb.table("routes").select("gen_meta").eq("id", route_id).single().execute().data
    return row


async def main():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"far-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]

    # A. far pitstop_place → 502 아님·서빙·target_missed·far_served·마커==POI
    print("[A. far pitstop_place(3.1km) — best-effort 서빙]")
    print(f"   start→FAR = {hav_km(START, FAR.coordinate):.2f} km")
    with _Patched():
        try:
            ra = await route_service.create_running_route(
                RouteRequest(start=START, target_distance_km=TARGET, pitstop_place=FAR), user_id=_uid)
        except route_service.RouteGenerationFailed:
            raise AssertionError("far pitstop이 여전히 502 — best-effort 미발동")
    assert ra.target_missed is True, f"target_missed={ra.target_missed}"
    assert ra.total_distance_km > TARGET, f"편입인데 target 이하? {ra.total_distance_km}"
    wa = _pit(ra)
    assert wa is not None and wa.name == FAR.name, wa.name if wa else "no pitstop"
    drift = hav_km(wa.coordinate, FAR.coordinate) * 1000
    assert drift < 1.0, f"마커 드리프트 {drift:.0f}m"
    ok(f"far: 502 아님·서빙 {ra.total_distance_km}km·target_missed=True·마커==POI({drift:.1f}m)")

    row = await _gm(ra.route_id)
    gm = row["gen_meta"] or {}
    assert gm.get("verdict") == "far_pitstop_missed", gm.get("verdict")
    assert (gm.get("pitstop") or {}).get("far_served") is True, gm.get("pitstop")
    ok(f"far DB 부수효과: verdict=far_pitstop_missed·pitstop.far_served=True 영속")

    # B. near pitstop_place(밴드 내) → 종전 편입(far 아님)
    print("\n[B. near pitstop_place(0.8km, 밴드 내) — 종전 편입]")
    print(f"   start→NEAR = {hav_km(START, NEAR.coordinate):.2f} km")
    with _Patched():
        rb = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=TARGET, pitstop_place=NEAR), user_id=_uid)
    wb = _pit(rb)
    assert wb is not None and wb.name == NEAR.name
    gmb = (await _gm(rb.route_id))["gen_meta"] or {}
    assert gmb.get("verdict") != "far_pitstop_missed", gmb.get("verdict")
    assert not (gmb.get("pitstop") or {}).get("far_served"), "near인데 far_served"
    assert not (gmb.get("pitstop") or {}).get("far"), "near인데 far=True"
    ok(f"near: 종전 편입(verdict={gmb.get('verdict')})·far 미발동·마커=='{wb.name}'")

    # C. 무pitstop → far 로직 미발동
    print("\n[C. 무pitstop — far 로직 미발동]")
    with _Patched(with_pitstop=False):
        rc = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=TARGET), user_id=_uid)
    assert all(not w.is_pitstop for w in rc.waypoints)
    gmc = (await _gm(rc.route_id))["gen_meta"] or {}
    assert gmc.get("verdict") != "far_pitstop_missed"
    ok("무pitstop: 종전 서빙·far 로직 미발동")


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
