"""
Integration: 경유지 POI 계약(A-2) — pitstop_place 재검색 우회 (2026-08-26)

유저 지정 POI(pitstop_place)를 요청에 실으면 서버가 Kakao 재검색을 스킵하고 그
좌표·이름을 경유지로 직접 사용. place 우선(keyword 함께 와도 라우팅은 place),
keyword-only는 종전 재검색 경로 불변(하위호환), far-POI는 best-effort(422 아님),
redraw 경로에서도 실명 유지(A축 연계). Gemini/T-map/Kakao 실콜 0(seam mock).

Run: python tests/test_pitstop_poi_integration.py
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
from app.services import map_service, openai_service, route_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None

START = KoreaCoordinate(lat=37.60, lng=127.20)   # 캐노니컬 미커버
USER_POI = PitstopPlace(name="유저지정 스타벅스",
                        coordinate=KoreaCoordinate(lat=START.lat + 0.011, lng=START.lng + 0.013),
                        category_code="CE7")
# keyword 재검색이 반환할 (다른) 카페 — place 우선이면 이게 채택되면 안 됨
KW_CAFE = Place(name="검색결과 다른카페",
                coordinate=Coordinate(lat=START.lat + 0.005, lng=START.lng + 0.002),
                category="카페", category_code="CE7", address="검색 주소")
_passed = 0
_search_calls: list = []      # search_places 쿼리 기록
_rank_calls: list = []        # rank_places_for_keyword 호출 기록


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _cand(start, with_pitstop=True):
    a = Coordinate(lat=start.lat + 0.011, lng=start.lng)
    b = Coordinate(lat=start.lat + 0.011, lng=start.lng + 0.013)
    wps = [Waypoint(name="출발", coordinate=start, is_pitstop=False),
           Waypoint(name="지점 1", coordinate=a, is_pitstop=False),
           Waypoint(name="지점 2", coordinate=b, is_pitstop=with_pitstop),
           Waypoint(name="복귀", coordinate=start, is_pitstop=False)]
    return RouteResponse(summary="mock", total_distance_km=5.0, waypoints=wps)


def _pitstop_wp(route):
    return next((w for w in route.waypoints if w.is_pitstop), None)


async def _gen(**kw):
    return _cand(kw["start"], with_pitstop=True)


async def _snap(origin, destination, waypoints=None):
    pts = [Coordinate(lat=START.lat + 0.0001 * i, lng=START.lng) for i in range(60)]
    return PedestrianRoute(distance_m=5000, duration_s=4000, path=pts, provider="tmap",
                           road_segments=[])


async def _search(query, *a, **k):
    _search_calls.append(query)
    if query == "카페":
        return [KW_CAFE]
    return []   # 공원(park coverage) 등


def _rank(keyword, places, start=None, target_km=None, recent_pitstops=None):
    _rank_calls.append(keyword)
    return list(places)


async def _apt(*a, **k):
    return (0, 0)


class _Patched:
    def __init__(self, spur_inject=None):
        self.spur_inject = spur_inject

    async def _spur(self, req, target_km, in_band, best, best_km, *a, **k):
        if self.spur_inject is None:
            return best, best_km, None, None
        fr = self.spur_inject
        return fr, fr.total_distance_km, {"mode": "redraw", "attempted": True}, \
            {"redraw_hit": True, "redraw_verdict": "hit"}

    def __enter__(self):
        _search_calls.clear(); _rank_calls.clear()
        self._orig = (openai_service.generate_route, map_service.get_pedestrian_route,
                      map_service.search_places, map_service.rank_places_for_keyword,
                      map_service.count_apartment_signal, route_service._spur_rescue)
        openai_service.generate_route = _gen
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


async def _db_pitstop(route_id, label):
    stored = await route_service.get_route(route_id, _uid)
    return _pitstop_wp(stored)


async def main():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"poi-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]

    # A. place 지정 → 그 이름·좌표 서빙 + Kakao 재검색 0
    print("[A. place 지정 — 재검색 우회]")
    with _Patched():
        ra = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_place=USER_POI), user_id=_uid)
    wp = _pitstop_wp(ra)
    assert wp and wp.name == USER_POI.name, (wp.name if wp else None)
    assert "카페" not in _rank_calls and "카페" not in _search_calls, (_rank_calls, _search_calls)
    assert _rank_calls == [], f"place인데 rank 재검색 호출됨: {_rank_calls}"
    ok(f"place 이름 '{wp.name}' 서빙 · rank 재검색 0 · search에 pitstop 쿼리 없음(park만: {set(_search_calls)})")
    dbwp = await _db_pitstop(ra.route_id, "place")
    assert dbwp and dbwp.name == USER_POI.name
    ok("DB 영속 place 실명")

    # B. keyword-only(place 없음) → 종전 재검색 경로(하위호환)
    print("\n[B. keyword-only — 종전 재검색(하위호환)]")
    with _Patched():
        rb = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_keyword="카페"), user_id=_uid)
    assert "카페" in _rank_calls, "keyword-only인데 재검색 안 함"
    assert _pitstop_wp(rb).name == KW_CAFE.name, _pitstop_wp(rb).name
    ok(f"keyword 재검색 채택 '{_pitstop_wp(rb).name}' (종전 경로 불변)")

    # C. 공존(place+keyword) → place 우선(재검색 스킵)
    print("\n[C. place+keyword 공존 — place 우선]")
    with _Patched():
        rc = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0,
                         pitstop_place=USER_POI, pitstop_keyword="카페"), user_id=_uid)
    assert _pitstop_wp(rc).name == USER_POI.name, _pitstop_wp(rc).name
    assert _rank_calls == [], f"공존인데 keyword 재검색됨: {_rank_calls}"
    ok(f"공존: place '{_pitstop_wp(rc).name}' 우선 · keyword 재검색 0")

    # D. redraw 경로에서도 place 실명 유지(A축 연계)
    print("\n[D. redraw — place 실명 유지]")
    fresh = RouteResponse(summary="redraw", total_distance_km=5.0,
                          waypoints=[Waypoint(name="출발", coordinate=START, is_pitstop=False),
                                     Waypoint(name="지점 7", coordinate=USER_POI.coordinate, is_pitstop=True),
                                     Waypoint(name="복귀", coordinate=START, is_pitstop=False)],
                          polyline=[Coordinate(lat=START.lat + 0.0001 * i, lng=START.lng) for i in range(60)])
    with _Patched(spur_inject=fresh):
        rd = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_place=USER_POI), user_id=_uid)
    assert _pitstop_wp(rd).name == USER_POI.name, _pitstop_wp(rd).name
    ok(f"redraw best도 place 실명 '{_pitstop_wp(rd).name}'(A축)")

    # E. 하위호환 — 무pitstop 무영향
    print("\n[E. 무pitstop — 무영향]")
    async def _gen_np(**kw):
        return _cand(kw["start"], with_pitstop=False)
    with _Patched():
        openai_service.generate_route = _gen_np
        re_ = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0), user_id=_uid)
    assert all(not w.is_pitstop for w in re_.waypoints)
    assert USER_POI.name not in [w.name for w in re_.waypoints]
    ok("무pitstop: is_pitstop 없음·실명 누출 0")

    # F. KoreaCoordinate 422 백스탑 (한국 밖 좌표)
    print("\n[F. 좌표 검증 422]")
    try:
        PitstopPlace(name="해외", coordinate=KoreaCoordinate(lat=48.85, lng=2.35))
        assert False, "한국 밖 좌표 통과"
    except Exception as e:
        assert type(e).__name__ == "ValidationError"
    ok("한국 밖 pitstop_place 좌표 422(ValidationError)")


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
        print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_passed} assert)\n" + "=" * 50)
    finally:
        cleanup()
