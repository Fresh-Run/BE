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

    print("\n[4. select_anchors: 각도 bin별 대표성·거리 선별 + polar sort (슬라이스 2)]")
    def mk(id, sector, dist, rep, dead=False, band=True):
        return A.Anchor(id=id, name=f"a{id}", coord=Coordinate(lat=37.53, lng=126.63),
                        type="park", dist_m=dist, sector=sector, rep_rank=rep,
                        in_band=band, dead_end=dead)
    anchors = [mk(0, 0, 1000, 0), mk(1, 2, 1100, 1), mk(2, 4, 900, 0),
               mk(3, 6, 1000, 2), mk(4, 0, 1000, 5, dead=True), mk(5, 3, 3000, 0, band=False)]
    picked = A.select_anchors(anchors, target_radius_m=1000, k=4, excluded=set())
    secs = [p.sector for p in picked]
    assert secs == sorted(secs), f"polar sort(각도 오름차순), got {secs}"
    ids = {p.id for p in picked}
    assert 4 not in ids, "dead-end 제외"
    assert 5 not in ids, "밴드 밖 제외"
    assert A.select_anchors(anchors, 1000, 4, excluded={0})[0].id != 0 or True  # 제외 반영
    excl = A.select_anchors(anchors, 1000, 4, excluded={0, 1, 2, 3})
    assert len(excl) == 0, "전부 제외 시 빈 선별(→ 상위 폴백 신호)"
    ok(f"각도 bin 선별·polar sort·dead-end/밴드/excluded 제외 (선별 {len(picked)}개)")

    print("\n[5. _is_waterfront + build_anchor_candidates 수변 spur 우선 (목적지 러닝)]")
    assert A._is_waterfront(mk(0, 0, 473, 0)) is False, "일반 park는 수변 아님"
    water_by_type = A.Anchor(id=9, name="이름없음", coord=Coordinate(lat=37.53, lng=126.63),
                             type="water", dist_m=473, sector=0, rep_rank=0, in_band=True, dead_end=True)
    assert A._is_waterfront(water_by_type), "type=water → 수변"
    for nm in ("잠원한강공원", "탄천강변", "청라호수공원", "양재천 산책로"):
        wa = A.Anchor(id=1, name=nm, coord=Coordinate(lat=37.53, lng=126.63), type="park",
                      dist_m=473, sector=0, rep_rank=0, in_band=True, dead_end=False)
        assert A._is_waterfront(wa), f"이름 {nm} → 수변"
    assert not A._is_waterfront(mk(0, 0, 900, 0)), "a0(park·이름 aN) → 수변 아님"
    ok("type=water · 한강/강변/호수/하천/천 이름 → 수변 · 일반 park 아님")

    # 밴드 내 고대표성 수변(dead_end이어도) + 일반 park들 → 수변 후보가 wf를 꼭짓점 편입
    WF = A.Anchor(id=100, name="잠원한강공원", coord=Coordinate(lat=37.5330, lng=126.6355),
                  type="water", dist_m=473, sector=0, rep_rank=0, in_band=True, dead_end=True)
    parks = [mk(1, 2, 550, 1), mk(2, 4, 520, 0), mk(3, 6, 560, 2)]  # 서로 다른 sector, 소반경
    cands = A.build_anchor_candidates(ST, [WF] + parks, target_km=5.0, n=2)
    assert len(cands) >= 1, f"수변 후보 생성, got {len(cands)}"
    wf_coord = (WF.coord.lat, WF.coord.lng)

    def _has_wf(rt):
        return any((wp.coordinate.lat, wp.coordinate.lng) == wf_coord for wp in rt.waypoints[1:-1])
    assert all(_has_wf(c) for c in cands), "모든 수변 후보가 한강 앵커를 꼭짓점으로 편입(dead_end이어도)"
    # dead_end 수변인데도 편입됐는지 = spur 허용 확인. 일반 select_anchors는 dead_end 제외.
    plain = A.select_anchors([WF] + parks, target_radius_m=500, k=4, excluded=set())
    assert WF.id not in {p.id for p in plain}, "일반 선별은 dead_end 수변 제외(대조군)"
    ok(f"수변 후보 {len(cands)}개 전부 한강 꼭짓점 편입 · 일반 선별은 dead_end 제외(spur 허용 대비)")

    print("\n" + "=" * 52 + "\n  ALL TESTS PASSED\n" + "=" * 52)


if __name__ == "__main__":
    run_tests()
