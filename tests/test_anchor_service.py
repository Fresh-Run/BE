"""
Unit test: 앵커 검색 층 (ANCHOR_EPIC 슬라이스 1, 2026-07-23)

_sector(방위각 8분할)·_NON_RUNNABLE(부속시설 제외) 순수 로직 + collect_anchors 집계
(Kakao/T-map mock). 실 호출 0.

Run: python tests/test_anchor_service.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import Coordinate, Place, PedestrianRoute
from app.services import anchor_service as A
from app.services import map_service


def ok(m): print(f"  ✓ {m}")


ST = Coordinate(lat=37.5300, lng=126.6300)


def run_tests():
    print("[1. _sector: 방위각 8분할 (0=E, 2=N, 4=W, 6=S 반시계)]")
    E = Coordinate(lat=37.5300, lng=126.6400)   # 동
    N = Coordinate(lat=37.5400, lng=126.6300)   # 북
    W = Coordinate(lat=37.5300, lng=126.6200)   # 서
    S = Coordinate(lat=37.5200, lng=126.6300)   # 남
    assert A._sector(ST, E) == 0, A._sector(ST, E)
    assert A._sector(ST, N) == 2, A._sector(ST, N)
    assert A._sector(ST, W) == 4, A._sector(ST, W)
    assert A._sector(ST, S) == 6, A._sector(ST, S)
    ok("E→0 · N→2 · W→4 · S→6 (각도 분산 입력)")

    print("\n[2. _NON_RUNNABLE: 부속시설·상업 제외, 실명 공원 유지]")
    for n in ("청라호수공원 대형주차장", "호수공원1지하차도", "청라호수공원한신더휴아파트",
              "호수공원프라자", "용산아이파크몰 더 가든"):
        assert A._NON_RUNNABLE.search(n), n
    for n in ("청라호수공원", "역삼문화공원", "이촌한강공원", "성수동구두테마공원"):
        assert not A._NON_RUNNABLE.search(n), n
    ok("주차장·지하차도·아파트·프라자·몰 제외 · 실명 공원 유지")

    print("\n[3. collect_anchors: 필터+dedup+밴드+sector+dead-end (mock)]")
    P = lambda name, la, lo: Place(name=name, coordinate=Coordinate(lat=la, lng=lo),
                                   category=None, category_code=None, address="x")
    # 실공원(밴드 내 ~440m) · 부속(주차장, 제외) · 중복(같은 공원 30m) · 원거리(밴드 밖 ~3km)
    PARK = P("큰공원", 37.5340, 126.6300)          # 북, ~445m
    LOT = P("큰공원 주차장", 37.5341, 126.6301)      # 부속 → 제외
    DUP = P("큰공원 정문", 37.5340, 126.6301)        # 30m 중복 → dedup
    FAR = P("먼공원", 37.5570, 126.6300)            # ~3km, 밴드 밖(target5×0.5=2.5km 초과)
    NEAR = P("코앞공원", 37.5302, 126.6300)         # ~22m, 밴드 밖(하한 200m 미만)
    canned = [PARK, LOT, DUP, FAR, NEAR]

    async def _mock_search(kw, near=None, radius_m=None, limit=None, sort=None):
        return list(canned)

    async def _mock_ped(origin, destination, waypoints=None):
        # 큰공원 목적지면 큰 갭(교량) → dead-end, 그 외 촘촘
        gap = 300.0 if abs(destination.lat - 37.5340) < 1e-4 else 20.0
        path = [origin, Coordinate(lat=(origin.lat + destination.lat) / 2 + gap / 111000,
                                   lng=origin.lng), destination]
        return PedestrianRoute(provider="tmap", distance_m=1000.0, duration_s=600.0, path=path)

    A._CACHE.clear()
    with patch.object(map_service, "search_places", _mock_search), \
            patch.object(map_service, "get_pedestrian_route", _mock_ped):
        anchors = asyncio.run(A.collect_anchors(ST, 5.0))
    names = [a.name for a in anchors]
    assert "큰공원 주차장" not in names, "부속 제외"
    assert names.count("큰공원") == 1 and "큰공원 정문" not in names, f"dedup, got {names}"
    big = next(a for a in anchors if a.name == "큰공원")
    assert big.in_band and big.sector == 2, f"밴드 내·북(sector2), got in_band={big.in_band} sec={big.sector}"
    assert big.dead_end is True, "큰공원 프로브 갭 300m>250 → dead-end"
    near = next(a for a in anchors if a.name == "코앞공원")
    assert near.in_band is False, "22m는 하한 200m 미만 → 밴드 밖"
    far = next(a for a in anchors if a.name == "먼공원")
    assert far.in_band is False and far.dead_end is None, "밴드 밖은 프로브 대상 아님(None)"
    ok(f"부속 제외·dedup·밴드·sector·dead-end 정합 (앵커 {len(anchors)}개)")

    print("\n" + "=" * 52 + "\n  ALL TESTS PASSED\n" + "=" * 52)


if __name__ == "__main__":
    run_tests()
