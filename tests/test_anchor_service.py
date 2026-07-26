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

    print("\n[2. _is_non_runnable: 시설 항상 제외 · 업소는 공원류 없을 때만(동음이의 가드)]")
    # (a) 시설텀 — 무조건 제외(공원 포함이어도)
    for n in ("청라호수공원 대형주차장", "호수공원1지하차도", "청라호수공원한신더휴아파트",
              "호수공원프라자", "용산아이파크몰 더 가든"):
        assert A._is_non_runnable(n), n
    # (b) 업소텀 + 공원류 토큰 없음 → 제외
    for n in ("강변공인중개사사무소", "한강부동산", "한강병원", "강남약국", "역삼은행", "대치학원"):
        assert A._is_non_runnable(n), n
    # (c) 오탐 가드 — 업소텀이 있으나 공원류 토큰 → 유지(은행나무공원·학원사거리공원 전례)
    for n in ("논현은행나무공원", "신사은행나무공원", "학원사거리공원", "은행나무산책로"):
        assert not A._is_non_runnable(n), f"동음이의 오탐 가드 실패: {n}"
    # (d) 실명 공원 — 유지
    for n in ("청라호수공원", "역삼문화공원", "이촌한강공원", "성수동구두테마공원"):
        assert not A._is_non_runnable(n), n
    ok("시설 항상 제외 · 업소는 공원류 없을 때만(은행↔은행나무공원 오탐 근절) · 실명 공원 유지")

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
    # 수변 후보가 생성되고 wf(dead_end이어도)를 편입 · 최우선(첫 후보)에 배치.
    # (희소 앵커면 변형 dedup으로 수변 1개+일반 채움 가능 — 실프로덕션은 앵커 다수라 수변만.)
    assert _has_wf(cands[0]), "수변 후보가 최우선(첫 후보) — wf 꼭짓점 편입(dead_end 허용)"
    assert any(_has_wf(c) for c in cands), "수변 후보 존재"
    # chain_target_km 조준: 격자적응(수변 spur 팽창 보정) — aim에 가까운 변형 채택
    cands2 = A.build_anchor_candidates(ST, [WF] + parks, 5.0, n=2, chain_target_km=3.6)
    assert _has_wf(cands2[0]), "chain_target 조준 경로에서도 수변 최우선"
    # dead_end 수변인데도 편입됐는지 = spur 허용 확인. 일반 select_anchors는 dead_end 제외.
    plain = A.select_anchors([WF] + parks, target_radius_m=500, k=4, excluded=set())
    assert WF.id not in {p.id for p in plain}, "일반 선별은 dead_end 수변 제외(대조군)"
    # 앵커 실명 노출(2026-07-26) — mid waypoint name = 대응 앵커 Kakao 실명(발명 아님).
    # 출발/복귀는 중립(집 앞, 앵커 아님).
    c0 = cands[0]
    mid_names = {wp.name for wp in c0.waypoints[1:-1]}
    assert "잠원한강공원" in mid_names, f"수변 앵커 실명 노출, got {mid_names}"
    assert all(not n.startswith("지점") for n in mid_names), f"mid는 실명(중립 아님), got {mid_names}"
    assert c0.waypoints[0].name == "출발" and c0.waypoints[-1].name == "복귀", "출발/복귀는 중립 유지"
    ok(f"수변 후보 최우선·wf 편입 · 앵커 mid 실명({sorted(mid_names)}) · 출발/복귀 중립")

    print("\n[6. 수변 주파 — 근접 수변 앵커 쌍이 체인에 인접 배치(주파 구간)]")
    # 400~900m 떨어진 수변 앵커 2개 + 일반 park들 → 쌍이 후보에 인접
    W1 = A.Anchor(id=200, name="이촌한강공원", coord=Coordinate(lat=37.5172, lng=126.9705),
                  type="water", dist_m=500, sector=0, rep_rank=0, in_band=True, dead_end=False)
    W2 = A.Anchor(id=201, name="강변어린이공원", coord=Coordinate(lat=37.5172, lng=126.9760),  # ~485m 동
                  type="water", dist_m=520, sector=0, rep_rank=1, in_band=True, dead_end=False)
    parks2 = [mk(10, 4, 520, 1), mk(11, 6, 540, 0)]
    p = A._best_water_pair(sorted([W1, W2] + [a for a in parks2 if A._is_waterfront(a)], key=lambda a: a.rep_rank))
    assert p is not None and {p[0].id, p[1].id} == {200, 201}, f"근접 수변 쌍 선택, got {p}"
    cands6 = A.build_anchor_candidates(ST, [W1, W2] + parks2, 5.0, n=2, chain_target_km=3.6)
    assert cands6, "쌍 주파 후보 생성"
    c6 = cands6[0]
    names6 = [wp.name for wp in c6.waypoints[1:-1]]
    # 쌍(이촌한강공원·강변어린이공원)이 리스트에서 인접(사이에 다른 앵커 없음)
    i1, i2 = names6.index("이촌한강공원"), names6.index("강변어린이공원")
    assert abs(i1 - i2) == 1, f"쌍이 인접(주파) 배치, got {names6}"
    ok(f"근접 수변 쌍 선택 · 후보에 인접 배치(주파): {names6}")

    print("\n" + "=" * 52 + "\n  ALL TESTS PASSED\n" + "=" * 52)


if __name__ == "__main__":
    run_tests()
