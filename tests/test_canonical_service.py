"""Unit test: 캐노니컬 코스 매처 (슬라이스 1, 2026-07-24).

match_and_build — 진입권(800m)·거리 밴드(±0.6) 매칭 + 스티치 서빙, 미스 시 None(폴백).
canonical_courses 조회·T-map 진입 leg는 mock. 실호출 0.

Run: python tests/test_canonical_service.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import Coordinate, PedestrianRoute
from app.services import canonical_service as C
from app.services import map_service


def ok(m): print(f"  ✓ {m}")
def fail(m): print(f"  ✗ {m}"); sys.exit(1)


HOME = Coordinate(lat=37.53323, lng=126.63037)   # 오너 홈(청라) — 진입점서 ~190m
FAR = Coordinate(lat=37.5163, lng=127.0203)        # 신사 — 캐노니컬 미스

# 시드 코스(축약 polyline) — 진입점 4개 중 하나가 홈 인근
SEED = {
    "id": "c1", "name": "청라호수공원 순환", "region": "청라", "distance_km": 4.71,
    "polyline": [[37.5379, 126.6331], [37.5314, 126.6362], [37.5261, 126.6320], [37.5319, 126.6317]],
    "access_points": [[37.537896, 126.633095], [37.529958, 126.635667],
                      [37.526078, 126.631973], [37.531889, 126.631743]],  # 마지막이 홈서 ~190m
}


async def _mock_ped(origin, destination, waypoints=None):
    # 진입 leg — 홈↔access ~0.2km 스냅
    return PedestrianRoute(provider="tmap", distance_m=200.0, duration_s=120.0,
                           path=[origin, destination])


def run():
    print("[1. _hav_m + 진입점 최근접 — 홈이 진입권(800m) 내]")
    dists = [C._hav_m(HOME, Coordinate(lat=a[0], lng=a[1])) for a in SEED["access_points"]]
    assert min(dists) < 800, f"홈 최근접 진입점 {min(dists):.0f}m < 800m"
    assert min(dists) < 250, f"홈 최근접 ~190m 기대, got {min(dists):.0f}m"
    ok(f"홈→최근접 진입점 {min(dists):.0f}m (진입권 내)")

    print("\n[2. 매칭 서빙 — 홈 5km 요청 → 청라호수공원 순환(실명·engine=canonical)]")
    async def _t2():
        with patch.object(C, "_fetch_active", return_value=[SEED]), \
                patch.object(map_service, "get_pedestrian_route", _mock_ped):
            return await C.match_and_build(HOME, 5.0)
    res = asyncio.run(_t2())
    assert res is not None, "홈 5km는 캐노니컬 매칭돼야"
    route, meta = res
    assert route.summary == "청라호수공원 순환", f"카드 실명, got {route.summary}"
    assert meta["engine"] == "canonical" and meta["course_id"] == "c1", meta
    # 총거리 = 진입 왕복(0.2+0.2) + 코스 4.71 ≈ 5.1
    assert 4.9 <= route.total_distance_km <= 5.3, f"총거리 ~5.1, got {route.total_distance_km}"
    # 폴리라인 스티치: 진입 leg(2) + 코스(4) + 진입 leg(2) = 8점
    assert len(route.polyline) == 8, f"스티치 폴리라인, got {len(route.polyline)}"
    # waypoint 라벨은 중립(실명은 summary만)
    assert [w.name for w in route.waypoints] == ["출발", "지점 1", "복귀"], [w.name for w in route.waypoints]
    assert route.target_missed is False, "5.1 vs 5.0 → 밴드 내(0.5 미만)"
    ok(f"청라호수공원 순환 서빙 {route.total_distance_km}km · engine=canonical · waypoint 중립 라벨")

    print("\n[3. 폴백 — 신사(진입권 밖) → None(생성 폴백)]")
    async def _t3():
        with patch.object(C, "_fetch_active", return_value=[SEED]), \
                patch.object(map_service, "get_pedestrian_route", _mock_ped):
            return await C.match_and_build(FAR, 5.0)
    assert asyncio.run(_t3()) is None, "신사는 진입점 800m 밖 → None"
    ok("신사(캐노니컬 미스) → None → 생성 폴백")

    print("\n[4. 거리 밴드 미스 — 홈이나 target 10km(코스 4.71+진입≠10) → None]")
    async def _t4():
        with patch.object(C, "_fetch_active", return_value=[SEED]), \
                patch.object(map_service, "get_pedestrian_route", _mock_ped):
            return await C.match_and_build(HOME, 10.0)
    assert asyncio.run(_t4()) is None, "10km 요청은 4.71 코스와 밴드(±0.6) 밖 → None"
    ok("target 10km는 거리 밴드 밖 → None(1바퀴 코스 강매 안 함)")

    print("\n[5. best-effort — 조회 예외 시 None(생성 폴백, 생성 무중단)]")
    async def _t5():
        async def _boom(): raise RuntimeError("db down")
        with patch.object(C, "_fetch_active", side_effect=RuntimeError("db down")):
            return await C.match_and_build(HOME, 5.0)
    assert asyncio.run(_t5()) is None, "조회 예외 → None(삼킴)"
    ok("canonical_courses 조회 예외 → None(생성 폴백 보호)")

    print("\n[6. 빈 테이블 — 코스 0건 → None]")
    async def _t6():
        with patch.object(C, "_fetch_active", return_value=[]):
            return await C.match_and_build(HOME, 5.0)
    assert asyncio.run(_t6()) is None
    ok("코스 0건 → None")

    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)


if __name__ == "__main__":
    run()
