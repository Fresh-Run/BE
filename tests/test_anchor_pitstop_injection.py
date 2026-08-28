"""
anchor 엔진 pitstop 주입 — place-only 요청 anchor 서빙 시 경유지 드롭 교정 (2026-08-28)

버그(A-2 잠복 갭): route_service `needs_pitstop=bool(req.pitstop_keyword)`가 keyword만
봐서, pitstop_place-only(카페 지정·keyword 없음) 요청 시 anchor 후보에 is_pitstop 슬롯
미예약 → anchor 서빙 route에 경유지 미주입(0곳). gen_meta.pitstop.source=user_place인데
waypoints is_pitstop=0. 청라 등 소유 밀집지는 dedup으로 anchor가 이겨 매번 0곳.
수정: `needs_pitstop=_has_pitstop_intent(req)` — place-only도 슬롯 예약.

커버(anchor 강제 — v87 전멸시켜 anchor만 서빙):
  A. place-only anchor → needs_pitstop=True·is_pitstop=1·더노벰버 주입·마커 좌표 정합
  B. keyword anchor → needs_pitstop=True(하위호환)·is_pitstop=1
  C. 무pitstop anchor → needs_pitstop=False·is_pitstop=0(하위호환)
  D. place v87(anchor 0) → 종전 주입 불변(하위호환)
DB 부수효과 assert. 임시 유저·생성분 즉삭. Run: python tests/test_anchor_pitstop_injection.py
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
from app.services import anchor_service, map_service, openai_service, route_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None
_passed = 0
START = KoreaCoordinate(lat=37.60, lng=127.20)
POI = PitstopPlace(name="더노벰버라운지 인천청라점", category_code="CE7",
                   coordinate=KoreaCoordinate(lat=START.lat + 0.008, lng=START.lng))  # ~888m in-band
CAFE = Place(name="검색카페", coordinate=Coordinate(lat=START.lat + 0.008, lng=START.lng),
             category="카페", category_code="CE7", address="주소")
_captured: dict = {}


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def hav_m(a, b):
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = math.radians(b.lat - a.lat), math.radians(b.lng - a.lng)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(x))


def _pit(r):
    return next((w for w in r.waypoints if w.is_pitstop), None)


# ── 파이프 seam mock ────────────────────────────────────────────────────
async def _boom(**kw):
    raise RuntimeError("v87 전멸 강제 — anchor만 서빙")


async def _snap(origin=None, destination=None, waypoints=None, **kw):
    pts = [origin, *(waypoints or []), destination]
    return PedestrianRoute(distance_m=5000.0, duration_s=3000.0,
                           path=[p for p in pts if p] or [START], provider="tmap", road_segments=[])


class _A:  # _make_anchor_route는 .name·.coord만 사용 — 경량 스탠드인
    def __init__(self, name, coord):
        self.name = name
        self.coord = coord


async def _collect(*a, **k):
    return [_A("공원A", Coordinate(lat=START.lat + 0.006, lng=START.lng + 0.004)),
            _A("공원B", Coordinate(lat=START.lat + 0.008, lng=START.lng)),
            _A("공원C", Coordinate(lat=START.lat + 0.004, lng=START.lng - 0.004))]


def _build(start, anchors, target_km, n, needs_pitstop=False, **kw):
    """실 슬롯 로직(_make_anchor_route) 재사용 — needs_pitstop True면 is_pitstop 슬롯 예약."""
    _captured["needs_pitstop"] = needs_pitstop
    picked = anchors[:3]
    return [anchor_service._make_anchor_route(start, picked, target_km, needs_pitstop)
            for _ in range(max(1, n))]


async def _search(query, *a, **k):
    return [CAFE] if query == "카페" else []


async def _apt(*a, **k):
    return (0, 0)


class _Patched:
    def __init__(self, anchor_on=True):
        self.anchor_on = anchor_on

    def __enter__(self):
        self._orig = (openai_service.generate_route, map_service.get_pedestrian_route,
                      map_service.search_places, map_service.count_apartment_signal,
                      anchor_service.collect_anchors, anchor_service.build_anchor_candidates,
                      settings.anchor_pool_n)
        openai_service.generate_route = _boom
        map_service.get_pedestrian_route = _snap
        map_service.search_places = _search
        map_service.count_apartment_signal = _apt
        anchor_service.collect_anchors = _collect
        anchor_service.build_anchor_candidates = _build
        settings.anchor_pool_n = 3 if self.anchor_on else 0
        _captured.clear()
        return self

    def __exit__(self, *e):
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.count_apartment_signal,
         anchor_service.collect_anchors, anchor_service.build_anchor_candidates,
         settings.anchor_pool_n) = self._orig


async def _gm(route_id):
    return get_supabase_admin().table("routes").select("gen_meta,waypoints").eq(
        "id", route_id).single().execute().data


async def main():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"anch-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]

    # A. place-only anchor → 슬롯 예약·주입·마커
    print("[A. place-only anchor — 슬롯 예약·주입·마커]")
    with _Patched():
        ra = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_place=POI), user_id=_uid)
    assert _captured["needs_pitstop"] is True, f"place-only인데 needs_pitstop={_captured['needs_pitstop']}"
    row = await _gm(ra.route_id)
    assert row["gen_meta"]["engine"] == "anchor", row["gen_meta"]["engine"]
    wa = _pit(ra)
    assert wa is not None and wa.name == POI.name, "anchor에 pitstop 미주입(0곳 버그 재발)"
    drift = hav_m(wa.coordinate, POI.coordinate)
    assert drift < 1.0, f"마커 드리프트 {drift:.0f}m"
    pit_wps = [w for w in row["waypoints"] if w.get("is_pitstop")]
    assert len(pit_wps) == 1 and pit_wps[0]["name"] == POI.name, pit_wps
    ok(f"place anchor: needs_pitstop=True·engine=anchor·is_pitstop=1('{wa.name}')·마커 {drift:.1f}m·DB 영속")

    # B. keyword anchor → 하위호환(needs_pitstop True 유지·주입)
    print("\n[B. keyword anchor — 하위호환]")
    with _Patched():
        rb = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_keyword="카페"), user_id=_uid)
    assert _captured["needs_pitstop"] is True
    wb = _pit(rb)
    assert wb is not None and wb.name == CAFE.name, "keyword anchor 주입 실패"
    ok(f"keyword anchor: needs_pitstop=True·is_pitstop=1('{wb.name}')")

    # C. 무pitstop anchor → 슬롯 미예약(하위호환)
    print("\n[C. 무pitstop anchor — 슬롯 미예약]")
    with _Patched():
        rc = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0), user_id=_uid)
    assert _captured["needs_pitstop"] is False, _captured["needs_pitstop"]
    assert _pit(rc) is None, "무pitstop인데 is_pitstop 존재"
    ok("무pitstop anchor: needs_pitstop=False·is_pitstop=0(하위호환)")

    # D. place v87(anchor 0) → 종전 주입 불변
    print("\n[D. place v87(anchor_pool_n=0) — 하위호환]")

    async def _v87_place(**kw):
        s = kw["start"]
        return RouteResponse(summary="v87", total_distance_km=5.0, waypoints=[
            Waypoint(name="출발", coordinate=s, is_pitstop=False),
            Waypoint(name="지점 1", coordinate=Coordinate(lat=s.lat + 0.006, lng=s.lng), is_pitstop=False),
            Waypoint(name="지점 2", coordinate=Coordinate(lat=s.lat + 0.008, lng=s.lng), is_pitstop=True),
            Waypoint(name="복귀", coordinate=s, is_pitstop=False)])
    with _Patched(anchor_on=False):
        openai_service.generate_route = _v87_place
        rd = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_place=POI), user_id=_uid)
    row_d = await _gm(rd.route_id)
    assert row_d["gen_meta"]["engine"] == "v87"
    wd = _pit(rd)
    assert wd is not None and wd.name == POI.name, "v87 place 주입 회귀"
    ok(f"v87 place: engine=v87·is_pitstop=1('{wd.name}')(하위호환 불변)")


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
