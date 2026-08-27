"""
마커 드리프트 수정 — user_place(A-2) 지정 POI는 마커 좌표까지 정확 (2026-08-27)

버그(이반 피커 스테이지 블로커): pitstop_place(유저가 앱에서 직접 탭한 POI) 요청이
redraw/rescue로 서빙되면 waypoint.name은 실명이나 waypoint.coordinate가 재추첨
슬롯(폴리라인 스냅점)에 남아 지정 POI에서 밀렸다(성수 898m 실측). _apply_pitstop_name이
name-only writeback이라 좌표는 폴리라인 정합만 유지한 탓.

수정: source=user_place면 _apply_pitstop_name이 마커 좌표도 지정값으로 덮고 폴리라인이
그 좌표를 지나게 보장. keyword 재검색(source=keyword_search)은 종전대로 name-only
(서버가 고른 POI라 좌표 정확성 보장 못 함 → 폴리라인 정합이 맞음).

커버:
  A. 단위 — _apply_pitstop_name(overwrite_coord) + _ensure_polyline_through
  B. redraw 재현 — user_place가 to_snap 밖 fresh best로 서빙돼도 마커==지정 POI(0m)
  C. keyword 무영향 — source=keyword_search는 좌표 미변경(폴리라인 정합 유지)
Gemini·T-map·Kakao 실콜 0(seam mock). 임시 유저 생성분 전량 정리.
Run: python tests/test_pitstop_marker_coord.py
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
    Coordinate, KoreaCoordinate, PedestrianRoute, Place, PitstopPlace,
    RouteRequest, RouteResponse, Waypoint,
)
from app.services import map_service, openai_service, route_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None
_passed = 0

START = KoreaCoordinate(lat=37.5446, lng=127.0559)  # 이반 성수
POI = PitstopPlace(name="유저지정 카페 실명점",
                   coordinate=KoreaCoordinate(lat=START.lat + 0.009, lng=START.lng + 0.006),
                   category_code="CE7")
# 재추첨이 만든 드리프트 pitstop 좌표(POI에서 ~750m 밀린 지점)
DRIFT = Coordinate(lat=START.lat + 0.003, lng=START.lng + 0.010)
# keyword 경로용 검색 POI
CAFE = Place(name="검색카페 실명점",
             coordinate=Coordinate(lat=START.lat + 0.011, lng=START.lng + 0.013),
             category="카페", category_code="CE7", address="서울 성동구 테스트로 1")


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def hav_m(a: Coordinate, b: Coordinate) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = math.radians(b.lat - a.lat), math.radians(b.lng - a.lng)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(x))


def _pit(route: RouteResponse):
    return next((w for w in route.waypoints if w.is_pitstop), None)


# ───────────────────────── A. 단위 ──────────────────────────────────────
def unit_tests():
    print("[A. 단위 — overwrite_coord + _ensure_polyline_through]")

    # A-1: overwrite_coord=True(user_place) → 마커 좌표 덮어쓰기 + 이름
    r = RouteResponse(summary="m", total_distance_km=5.0, waypoints=[
        Waypoint(name="출발", coordinate=START, is_pitstop=False),
        Waypoint(name="지점 2", coordinate=DRIFT, is_pitstop=True),
        Waypoint(name="복귀", coordinate=START, is_pitstop=False)],
        polyline=[Coordinate(lat=POI.coordinate.lat + 0.0002, lng=POI.coordinate.lng)])  # POI 22m
    pick = Place(name=POI.name, coordinate=POI.coordinate, category_code="CE7", address=None)
    route_service._apply_pitstop_name(r, pick, overwrite_coord=True)
    assert _pit(r).name == POI.name
    assert hav_m(_pit(r).coordinate, POI.coordinate) < 0.5, hav_m(_pit(r).coordinate, POI.coordinate)
    ok(f"A-1 user_place: 마커 좌표 == 지정 POI(0m)·이름 실명")

    # A-2: overwrite_coord=False(keyword) → 좌표 미변경(폴리라인 정합)
    r2 = RouteResponse(summary="m", total_distance_km=5.0, waypoints=[
        Waypoint(name="지점 2", coordinate=DRIFT, is_pitstop=True)])
    route_service._apply_pitstop_name(r2, CAFE, overwrite_coord=False)
    assert _pit(r2).name == CAFE.name
    assert _pit(r2).coordinate == DRIFT, "keyword인데 좌표 변경됨"
    ok("A-2 keyword: 이름만 실명·좌표 미변경(폴리라인 정합 유지)")

    # A-3: 폴리라인 근접(≤40m) → 삽입 안 함
    poly_near = [Coordinate(lat=POI.coordinate.lat + 0.0002, lng=POI.coordinate.lng),  # ~22m
                 Coordinate(lat=POI.coordinate.lat + 0.01, lng=POI.coordinate.lng)]
    n0 = len(poly_near)
    route_service._ensure_polyline_through(poly_near, POI.coordinate)
    assert len(poly_near) == n0, "근접인데 삽입됨"
    ok("A-3 폴리라인 근접(≤40m) → 삽입 없음(이반 32m 케이스)")

    # A-4: 폴리라인 밖(>40m) → 삽입해 선이 마커 통과
    poly_far = [Coordinate(lat=POI.coordinate.lat + 0.02, lng=POI.coordinate.lng + 0.02),
                Coordinate(lat=POI.coordinate.lat + 0.03, lng=POI.coordinate.lng + 0.03)]
    route_service._ensure_polyline_through(poly_far, POI.coordinate)
    assert min(hav_m(p, POI.coordinate) for p in poly_far) < 0.5, "삽입 후에도 선 밖"
    ok("A-4 폴리라인 밖(>40m) → 지정 좌표 삽입(마커 부유 방지)")


# ───────────────────────── 파이프 seam mock ────────────────────────────
async def _snap(origin, destination, waypoints=None):
    pts = [Coordinate(lat=START.lat + 0.0001 * i, lng=START.lng) for i in range(60)]
    return PedestrianRoute(distance_m=5000, duration_s=4000, path=pts,
                           provider="tmap", road_segments=[])


async def _search(query, *a, **k):
    return [CAFE] if query == "카페" else []


def _rank(keyword, places, start=None, target_km=None, recent_pitstops=None):
    return list(places)


async def _apt(*a, **k):
    return (0, 0)


def _cand(start, with_pitstop=True):
    a = Coordinate(lat=start.lat + 0.011, lng=start.lng)
    b = Coordinate(lat=start.lat + 0.011, lng=start.lng + 0.013)
    return RouteResponse(summary="mock", total_distance_km=5.0, waypoints=[
        Waypoint(name="출발", coordinate=start, is_pitstop=False),
        Waypoint(name="지점 1", coordinate=a, is_pitstop=False),
        Waypoint(name="지점 2", coordinate=b, is_pitstop=with_pitstop),
        Waypoint(name="복귀", coordinate=start, is_pitstop=False)])


class _Patched:
    """to_snap 밖 fresh redraw best를 _spur_rescue로 주입 — pitstop 슬롯을 DRIFT로."""
    async def _gen(self, **kw):
        return _cand(kw["start"], True)

    async def _spur(self, req, target_km, in_band, best, best_km, *a, **k):
        # POI 근처(22m)를 지나는 폴리라인 + is_pitstop 좌표는 DRIFT(밀림)
        poly = [Coordinate(lat=START.lat + 0.001 * i, lng=START.lng + 0.0007 * i) for i in range(13)]
        poly.append(Coordinate(lat=POI.coordinate.lat + 0.0002, lng=POI.coordinate.lng))
        fr = RouteResponse(summary="redraw", total_distance_km=5.0, waypoints=[
            Waypoint(name="출발", coordinate=req.start, is_pitstop=False),
            Waypoint(name="지점 7", coordinate=DRIFT, is_pitstop=True),
            Waypoint(name="복귀", coordinate=req.start, is_pitstop=False)], polyline=poly)
        return fr, fr.total_distance_km, {"mode": "redraw", "attempted": True}, \
            {"redraw_hit": True, "redraw_verdict": "hit"}

    def __enter__(self):
        self._orig = (openai_service.generate_route, map_service.get_pedestrian_route,
                      map_service.search_places, map_service.rank_places_for_keyword,
                      map_service.count_apartment_signal, route_service._spur_rescue)
        openai_service.generate_route = self._gen
        map_service.get_pedestrian_route = _snap
        map_service.search_places = _search
        map_service.rank_places_for_keyword = _rank
        map_service.count_apartment_signal = _apt
        route_service._spur_rescue = self._spur
        return self

    def __exit__(self, *e):
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.rank_places_for_keyword,
         map_service.count_apartment_signal, route_service._spur_rescue) = self._orig


async def main():
    global _uid
    unit_tests()

    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"marker-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]

    # B. redraw 재현 — user_place가 to_snap 밖 fresh best로 서빙돼도 마커 == 지정 POI
    print("\n[B. redraw 서빙 — user_place 마커 좌표 정확]")
    with _Patched():
        rb = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_place=POI), user_id=_uid)
    wp = _pit(rb)
    assert wp is not None and wp.name == POI.name, wp.name if wp else "no pitstop"
    drift_m = hav_m(wp.coordinate, POI.coordinate)
    assert drift_m < 1.0, f"마커가 지정 POI에서 {drift_m:.0f}m 밀림(0이어야)"
    near = min(hav_m(p, POI.coordinate) for p in rb.polyline)
    assert near <= route_service._MARKER_ON_LINE_M + 1, f"마커가 폴리라인 밖({near:.0f}m)"
    ok(f"redraw user_place: 마커 좌표 == 지정 POI({drift_m:.1f}m)·폴리라인 근접({near:.0f}m)")

    # DB 부수효과 — 저장 행의 pitstop 좌표도 지정 POI
    stored = await route_service.get_route(rb.route_id, _uid)
    swp = _pit(stored)
    assert swp and hav_m(swp.coordinate, POI.coordinate) < 1.0, \
        f"DB 영속 좌표 밀림: {hav_m(swp.coordinate, POI.coordinate):.0f}m"
    ok(f"DB 부수효과: 저장 pitstop 좌표 == 지정 POI(0m)·이름='{swp.name}'")

    # C. keyword 무영향 — source=keyword_search는 좌표 미변경(폴리라인 정합)
    print("\n[C. keyword 무영향 — 좌표 미변경]")
    with _Patched():
        rc = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_keyword="카페"), user_id=_uid)
    wc = _pit(rc)
    assert wc is not None and wc.name == CAFE.name, wc.name if wc else "no pitstop"
    # keyword 서빙 best는 fresh(DRIFT) — 좌표는 재추첨 슬롯 유지(덮어쓰기 안 함)
    assert hav_m(wc.coordinate, DRIFT) < 1.0, \
        f"keyword인데 좌표가 DRIFT에서 벗어남({hav_m(wc.coordinate, DRIFT):.0f}m) — 덮어쓰기 오발동"
    ok("keyword: 이름만 실명·좌표는 폴리라인 정합(DRIFT 슬롯) 유지 — 덮어쓰기 미발동")


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
