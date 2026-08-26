"""
Integration: pitstop 실명 배선 — 최종 best 확정 후 단일 지점 적용 (2026-08-25)

버그(0c7b0f66 포렌식): pitstop 실명 writeback이 메인 스냅 직전 to_snap 후보에만
적용돼, _spur_rescue·_adaptive_redraw로 to_snap 밖에서 생성된 서빙 best(verdict=
hit_redraw)는 Gemini 중립 라벨 '지점 N'이 잔존. pitstop_obs.name엔 실명 기록됨.

수정: route_service._apply_pitstop_name(best, pitstop_pick)를 return 직전 단일
지점에서 호출 — 전 서빙 경로(hit·redraw) 커버. 이미 해석된 pick 재사용(추가 콜 0).

커버:
  A. 단위 — _apply_pitstop_name (redraw-sim·멱등·pick None·이름 원칙)
  B. hit(재추첨 없음) — 서빙 best pitstop 실명 + DB 영속 (pre-snap+end 멱등)
  C. hit_redraw(_spur_rescue 주입) — to_snap 밖 fresh best도 실명 + DB 영속
  D. 키워드 없음 — 실명 로직 미발동, 전 웨이포인트 중립 라벨 유지

Gemini·T-map·Kakao 실콜 0 (전 파이프 seam mock). 임시 유저 생성분 전량 정리.
Run: python tests/test_pitstop_realname_integration.py
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
    Coordinate, KoreaCoordinate, PedestrianRoute, Place, RouteRequest, RouteResponse, Waypoint,
)
from app.services import map_service, openai_service, route_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None

# 캐노니컬·on_course 미커버 원격 좌표(기존 v87 mock 테스트와 동일 — pre-gate 통과 실증)
START = KoreaCoordinate(lat=37.60, lng=127.20)
CAFE = Place(name="테스트카페 실명점",
             coordinate=Coordinate(lat=START.lat + 0.011, lng=START.lng + 0.013),
             category="카페", category_code="CE7", address="인천 서구 테스트로 1")
_passed = 0


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _cand(start, with_pitstop: bool):
    """mock 생성 후보 — 중립 라벨(§3 축B). with_pitstop이면 index2를 is_pitstop=True."""
    a = Coordinate(lat=start.lat + 0.011, lng=start.lng)
    b = Coordinate(lat=start.lat + 0.011, lng=start.lng + 0.013)
    wps = [Waypoint(name="출발", coordinate=start, is_pitstop=False),
           Waypoint(name="지점 1", coordinate=a, is_pitstop=False),
           Waypoint(name="지점 2", coordinate=b, is_pitstop=with_pitstop),
           Waypoint(name="복귀", coordinate=start, is_pitstop=False)]
    return RouteResponse(summary="mock", total_distance_km=5.0, waypoints=wps)


def _pitstop_wp(route: RouteResponse):
    return next((w for w in route.waypoints if w.is_pitstop), None)


# ───────────────────────── A. 단위 (_apply_pitstop_name) ─────────────────────
def unit_tests():
    print("[A. 단위 — _apply_pitstop_name]")

    # A-1 redraw-sim: 중립 pitstop → 실명 적용, 좌표 미변경
    r = _cand(START, with_pitstop=True)
    neutral_coord = _pitstop_wp(r).coordinate
    route_service._apply_pitstop_name(r, CAFE)
    assert _pitstop_wp(r).name == CAFE.name, _pitstop_wp(r).name
    assert _pitstop_wp(r).description == CAFE.address
    assert _pitstop_wp(r).coordinate == neutral_coord, "좌표는 미변경(폴리라인 정합)"
    ok("A-1 redraw-sim: 중립 '지점 2' → 실명, 좌표 보존")

    # A-2 멱등(non-redraw): 이미 실명이면 동일값 재적용
    r2 = _cand(START, with_pitstop=True)
    _pitstop_wp(r2).name = CAFE.name  # pre-snap이 이미 적용한 상태 모사
    route_service._apply_pitstop_name(r2, CAFE)
    assert _pitstop_wp(r2).name == CAFE.name
    ok("A-2 멱등: 이미 실명 → 동일 유지")

    # A-3 pick None(키워드 없음·해석 실패): 무동작 → 중립 유지
    r3 = _cand(START, with_pitstop=True)
    route_service._apply_pitstop_name(r3, None)
    assert _pitstop_wp(r3).name == "지점 2", "pick None인데 라벨 변경됨"
    ok("A-3 pick None: 중립 라벨 유지(미발동)")

    # A-4 이름 원칙: is_pitstop만 실명, 나머지 중립 불변
    r4 = _cand(START, with_pitstop=True)
    route_service._apply_pitstop_name(r4, CAFE)
    others = [w.name for w in r4.waypoints if not w.is_pitstop]
    assert others == ["출발", "지점 1", "복귀"], others
    ok("A-4 이름 원칙: 비-pitstop(발명 좌표) 중립 유지, 실 POI만 실명")


# ───────────────────────── 파이프 seam mock ──────────────────────────────────
async def _snap_mock(origin, destination, waypoints=None):
    pts = [Coordinate(lat=START.lat + 0.0001 * i, lng=START.lng) for i in range(60)]
    return PedestrianRoute(distance_m=5000, duration_s=4000, path=pts,
                           provider="tmap", road_segments=[])


async def _search_mock(query, *a, **k):
    return [CAFE] if query == (getattr(_search_mock, "kw", None) or "카페") else []


def _rank_mock(keyword, places, start=None, target_km=None, recent_pitstops=None):
    return list(places)


async def _apt_mock(*a, **k):
    return (0, 0)


class _Patched:
    """전 파이프 seam을 결정론 mock으로 — Gemini·T-map·Kakao 실콜 0."""
    def __init__(self, with_pitstop: bool, spur_inject: RouteResponse | None = None):
        self.with_pitstop = with_pitstop
        self.spur_inject = spur_inject

    async def _gen(self, **kw):
        return _cand(kw["start"], self.with_pitstop)

    async def _spur(self, req, target_km, in_band, best, best_km, *a, **k):
        # hit_redraw 강제 — to_snap 밖 fresh route(중립 pitstop)를 서빙 best로 주입.
        if self.spur_inject is None:
            return best, best_km, None, None
        fr = self.spur_inject
        return fr, fr.total_distance_km, {"mode": "redraw", "attempted": True}, \
            {"redraw_hit": True, "redraw_verdict": "hit"}

    def __enter__(self):
        self._orig = (openai_service.generate_route, map_service.get_pedestrian_route,
                      map_service.search_places, map_service.rank_places_for_keyword,
                      map_service.count_apartment_signal, route_service._spur_rescue)
        openai_service.generate_route = self._gen
        map_service.get_pedestrian_route = _snap_mock
        map_service.search_places = _search_mock
        map_service.rank_places_for_keyword = _rank_mock
        map_service.count_apartment_signal = _apt_mock
        route_service._spur_rescue = self._spur
        return self

    def __exit__(self, *exc):
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.rank_places_for_keyword,
         map_service.count_apartment_signal, route_service._spur_rescue) = self._orig


async def _assert_db_pitstop(route_id: str, expected_name: str, label: str):
    stored = await route_service.get_route(route_id, _uid)
    assert stored is not None, f"{label}: GET 조회 실패"
    wp = _pitstop_wp(stored)
    assert wp is not None, f"{label}: 저장 행에 is_pitstop 웨이포인트 부재"
    assert wp.name == expected_name, f"{label}: DB 영속 이름 {wp.name!r} != {expected_name!r}"
    ok(f"{label}: DB 영속 pitstop 실명='{wp.name}'")


async def main():
    global _uid
    unit_tests()

    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"pitstop-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]

    # B. hit(재추첨 없음) — 서빙 best pitstop 실명 + DB 영속
    print("\n[B. hit — 재추첨 없음(pre-snap+end 멱등)]")
    with _Patched(with_pitstop=True, spur_inject=None):
        rb = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_keyword="카페"),
            user_id=_uid)
    assert _pitstop_wp(rb) is not None and _pitstop_wp(rb).name == CAFE.name, \
        _pitstop_wp(rb).name if _pitstop_wp(rb) else "no pitstop"
    assert [w.name for w in rb.waypoints if not w.is_pitstop] == ["출발", "지점 1", "복귀"]
    ok(f"hit: 서빙 pitstop 실명='{_pitstop_wp(rb).name}', 나머지 중립")
    await _assert_db_pitstop(rb.route_id, CAFE.name, "hit")

    # C. hit_redraw — to_snap 밖 fresh best 주입, end-writeback이 실명 적용
    print("\n[C. hit_redraw — _spur_rescue 주입(to_snap 밖 fresh best)]")
    fresh = RouteResponse(
        summary="redraw-mock", total_distance_km=5.0,
        waypoints=[Waypoint(name="출발", coordinate=START, is_pitstop=False),
                   Waypoint(name="지점 7", coordinate=CAFE.coordinate, is_pitstop=True),
                   Waypoint(name="복귀", coordinate=START, is_pitstop=False)],
        polyline=[Coordinate(lat=START.lat + 0.0001 * i, lng=START.lng) for i in range(60)])
    assert _pitstop_wp(fresh).name == "지점 7", "주입 전 중립 라벨 확인"
    with _Patched(with_pitstop=True, spur_inject=fresh):
        rc = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_keyword="카페"),
            user_id=_uid)
    assert rc.summary == "5.0km 순환 코스" or "코스" in rc.summary  # 중립 제목 override
    assert _pitstop_wp(rc) is not None and _pitstop_wp(rc).name == CAFE.name, \
        f"redraw best 실명 미적용: {_pitstop_wp(rc).name if _pitstop_wp(rc) else None}"
    assert [w.name for w in rc.waypoints if not w.is_pitstop] == ["출발", "복귀"]
    ok(f"hit_redraw: fresh best '지점 7' → 실명='{_pitstop_wp(rc).name}'(end-writeback)")
    await _assert_db_pitstop(rc.route_id, CAFE.name, "hit_redraw")

    # D. 키워드 없음 — 실명 로직 미발동, 전 웨이포인트 중립
    print("\n[D. 키워드 없음 — 중립 라벨 유지(미발동)]")
    with _Patched(with_pitstop=False, spur_inject=None):
        rd = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0), user_id=_uid)
    assert all(not w.is_pitstop for w in rd.waypoints), "키워드 없음인데 is_pitstop 존재"
    assert CAFE.name not in [w.name for w in rd.waypoints], "실명 누출"
    assert set(w.name for w in rd.waypoints) <= {"출발", "지점 1", "지점 2", "복귀"}
    ok("키워드 없음: 전 웨이포인트 중립, 실명 미발동")
    stored_d = await route_service.get_route(rd.route_id, _uid)
    assert all(not w.is_pitstop for w in stored_d.waypoints)
    ok("키워드 없음: DB 영속분도 중립(부수효과 assert)")


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
