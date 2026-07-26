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


async def _no_access_name(coord):  # 라우트빌드 테스트 call-free·결정론(중립 진입명)
    return None


def run():
    _orig_access = C._access_name       # 원본 백업(진입 실명 로직 전용 테스트용)
    C._access_name = _no_access_name    # 라우트빌드 테스트 call-free(진입 실명은 #11서)
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
    # 폴리라인 스티치: 진입 leg(2) + 회전 코스(4+접점복귀 1=5) + 진입 leg(2) = 9점
    assert len(route.polyline) == 9, f"스티치 폴리라인, got {len(route.polyline)}"
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

    print("\n[4. 거리 밴드 미스 — target 8.0(1바퀴 5~6·2바퀴 9~11 갭) → None]")
    async def _t4():
        with patch.object(C, "_fetch_active", return_value=[SEED]), \
                patch.object(map_service, "get_pedestrian_route", _mock_ped):
            return await C.match_and_build(HOME, 8.0)  # 4.71×1·×2 + 진입 어느 것도 8.0 밴드 밖
    assert asyncio.run(_t4()) is None, "8.0km는 4.71 코스의 1·2바퀴 갭 → None"
    ok("target 8.0은 배수 매칭 갭 → None(강매 안 함)")

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

    print("\n[7. 큐레이션 우선진입점 — access_points[0]이 최근접보다 우선 채택]")
    # 우선진입점(디지털아트프라자 입구, 홈서 멂)이 access_points[0]. 최근접(홈 코앞)은 [3].
    HOME2 = Coordinate(lat=37.53094, lng=126.63851)   # 청라더샵레이크파크(오너 홈)
    ENTRANCE = [37.528678, 126.635812]                 # 디지털아트프라자 입구(우선)
    NEAR = [37.531000, 126.638000]                     # 홈 코앞(더 가까움, 비우선)
    SEED2 = {**SEED, "access_points": [ENTRANCE, NEAR]}  # [0]=우선진입점

    async def _t7():
        with patch.object(C, "_fetch_active", return_value=[SEED2]), \
                patch.object(map_service, "get_pedestrian_route", _mock_ped):
            return await C.match_and_build(HOME2, 5.0)
    res7 = asyncio.run(_t7())
    assert res7 is not None, "우선진입점이 반경·관대밴드 내면 서빙"
    _r7, meta7 = res7
    assert meta7["access_rank"] == 0, f"큐레이션 우선진입점(rank0) 채택, got rank {meta7['access_rank']}"
    d_entrance = C._hav_m(HOME2, Coordinate(lat=ENTRANCE[0], lng=ENTRANCE[1]))
    d_near = C._hav_m(HOME2, Coordinate(lat=NEAR[0], lng=NEAR[1]))
    assert d_near < d_entrance, "대조: NEAR가 물리적으로 더 가까움(그런데도 우선진입점 채택)"
    ok(f"우선진입점(rank0, {round(d_entrance)}m) 채택 · 최근접(NEAR {round(d_near)}m) 아님 — 큐레이션 존중")

    print("\n[8. 우선진입점 관대 밴드 — 자동 밴드(0.6) 초과라도 우선 밴드(1.0) 내면 서빙]")
    # 진입 왕복이 커 diff~0.7(자동밴드 밖)이나 우선진입점이라 서빙
    async def _t8():
        with patch.object(C, "_fetch_active", return_value=[{**SEED, "access_points": [ENTRANCE]}]), \
                patch.object(map_service, "get_pedestrian_route", _mock_ped):
            return await C.match_and_build(HOME2, 5.0)
    r8 = asyncio.run(_t8())
    assert r8 is not None, "우선진입점 단독도 관대밴드로 서빙"
    ok("우선진입점 단독 서빙(관대 밴드 1.0)")

    print("\n[9. 루프 회전 — 진입 접점 기준 회전으로 호수 관통 현 제거]")
    import math as _m
    def _gap(a, b):
        R=6371000.0;p1,p2=_m.radians(a.lat),_m.radians(b.lat)
        dp=_m.radians(b.lat-a.lat);dl=_m.radians(b.lng-a.lng)
        return 2*R*_m.asin(_m.sqrt(_m.sin(dp/2)**2+_m.cos(p1)*_m.cos(p2)*_m.sin(dl/2)**2))
    # 사각 루프(각 변 ~1km), idx0=북서. 진입점은 남동(idx2 인근) — idx0서 멀다.
    LOOP = [Coordinate(lat=37.540, lng=126.630), Coordinate(lat=37.540, lng=126.640),
            Coordinate(lat=37.531, lng=126.640), Coordinate(lat=37.531, lng=126.630),
            Coordinate(lat=37.540, lng=126.630)]  # 닫힘
    acc = Coordinate(lat=37.531, lng=126.640)  # 남동 꼭짓점(idx2)
    rot = C._rotate_loop(LOOP, acc)
    assert _gap(rot[0], acc) < 5.0, f"회전 시작이 진입 접점, got {_gap(rot[0],acc):.0f}m"
    assert _gap(rot[0], rot[-1]) < 5.0, "회전 후에도 닫힌 루프"
    # 회전 전: 스티칭하면 access→idx0 현(진입점 남동 → idx0 북서 = ~1.3km 갭) 발생
    chord = _gap(acc, LOOP[0])
    assert chord > 1000, f"미회전 시 현 {chord:.0f}m(호수 관통)"
    # 회전 후 인접 최대 갭은 변 길이(~1km)뿐, 새 현 없음 — 회전본 인접 갭 검사
    maxgap_rot = max(_gap(rot[i], rot[i+1]) for i in range(len(rot)-1))
    assert maxgap_rot <= chord + 1, "회전본 인접 갭이 원 변 길이 내(새 현 없음)"
    ok(f"회전 시작=진입점(0m) · 닫힘 유지 · 미회전 현 {chord:.0f}m 제거")

    # match_and_build 경유 스티치 — 회전으로 접점 이음(mock 진입 leg는 access서 끝)
    async def _t9():
        seed9 = {**SEED, "polyline": [[c.lat, c.lng] for c in LOOP],
                 "access_points": [[acc.lat, acc.lng]]}
        with patch.object(C, "_fetch_active", return_value=[seed9]), \
                patch.object(map_service, "get_pedestrian_route", _mock_ped):
            return await C.match_and_build(acc, 4.0)
    res9 = asyncio.run(_t9())
    if res9:  # 밴드 맞으면 스티치 검사
        r9, _ = res9
        # 코스 구간(진입 leg 2점 제외)의 시작이 access와 이어짐 — 큰 새 현 없음
        course_seg = r9.polyline[1:-1]
        big = [i for i in range(len(course_seg)-1) if _gap(course_seg[i], course_seg[i+1]) > chord+1]
        assert not big, f"스티치에 호수 관통 현(큰 갭) {len(big)}건 — 회전 실패"
        ok("match_and_build 스티치 — 호수 관통 현 0(회전 적용)")

    print("\n[10. 바퀴수 배수 매칭 — 2.5km 코스 target 5.0 → 2바퀴 서빙·카드 'N바퀴']")
    SMALL = {**SEED, "name": "석촌호수 순환", "distance_km": 2.5,
             "polyline": [[37.5100, 127.1000], [37.5120, 127.1010], [37.5110, 127.1030], [37.5095, 127.1015], [37.5100, 127.1000]],
             "access_points": [[37.5100, 127.1000]]}
    HOME3 = Coordinate(lat=37.5102, lng=127.1002)  # 진입점 코앞

    async def _t10(tgt):
        with patch.object(C, "_fetch_active", return_value=[SMALL]), \
                patch.object(map_service, "get_pedestrian_route", _mock_ped):
            return await C.match_and_build(HOME3, tgt)
    res10 = asyncio.run(_t10(5.0))
    assert res10 is not None, "2.5km 코스 target5.0 → 2바퀴 매칭"
    r10, meta10 = res10
    assert meta10["laps"] == 2, f"2바퀴 매칭(2.5×2=5.0), got laps {meta10['laps']}"
    assert "2바퀴" in r10.summary, f"카드에 '2바퀴' 표기, got '{r10.summary}'"
    assert 4.9 <= r10.total_distance_km <= 5.6, f"2바퀴 총거리 ~5.0+진입, got {r10.total_distance_km}"
    # 폴리라인이 루프 2회 반복(접점 이음) — 코스 구간 길이 ~2× 단일
    ok(f"2.5km 코스 → 2바퀴 서빙 '{r10.summary}' {r10.total_distance_km}km · laps={meta10['laps']}")
    # target 2.5 근처면 1바퀴
    res1 = asyncio.run(_t10(2.7))
    assert res1 and res1[1]["laps"] == 1 and "바퀴" not in res1[0].summary, "target2.7 → 1바퀴(표기 없음)"
    ok("target 2.7 → 1바퀴(단일, '바퀴' 표기 없음)")

    print("\n[11. 진입점 실명 — 인근 실 랜드마크만(발명 금지) · 없으면 중립]")
    from app.models.schemas import Place
    def _pl(nm, dlat): return Place(name=nm, coordinate=Coordinate(lat=HOME.lat+dlat, lng=HOME.lng),
                                    category=None, category_code=None, address="x")
    # 44m 랜드마크(디지털아트프라자) + 44m 카페(비랜드마크) + 222m 랜드마크(거리 초과)
    async def _search(kw, near=None, sort=None, radius_m=None, limit=None):
        return [_pl("스타벅스", 0.0004), _pl("청라중앙호수공원 디지털아트프라자", 0.0004), _pl("반포한강공원", 0.002)]
    async def _t11():
        with patch.object(map_service, "search_places", _search):
            return await _orig_access(HOME)      # 원본 _access_name 로직
    nm = asyncio.run(_t11())
    assert nm == "청라중앙호수공원 디지털아트프라자", f"인근 랜드마크 실명(카페 스킵), got {nm}"
    assert not C._ACCESS_LANDMARK.search("스타벅스"), "카페는 랜드마크 아님(발명 금지 필터)"
    # 실 POI 없으면 None(중립)
    async def _t11b():
        async def _empty(*a, **k): return []
        with patch.object(map_service, "search_places", _empty):
            return await _orig_access(HOME)
    assert asyncio.run(_t11b()) is None, "인근 실 POI 없으면 None(중립 폴백)"
    ok("인근 실 랜드마크만 실명(카페 제외·90m 초과 제외) · 없으면 None(중립)")

    print("\n[12. _build_served 진입 실명 반영 — _access_name 있으면 waypoint[1]에]")
    async def _named(coord): return "청라중앙호수공원 디지털아트프라자"
    async def _t12():
        C._access_name = _named
        try:
            with patch.object(map_service, "get_pedestrian_route", _mock_ped):
                return await C.match_and_build(HOME, 5.0)
        finally:
            C._access_name = _no_access_name
    r12, _ = asyncio.run(_t12())
    assert r12.waypoints[1].name == "청라중앙호수공원 디지털아트프라자", f"진입 waypoint 실명, got {r12.waypoints[1].name}"
    assert r12.waypoints[0].name == "출발" and r12.waypoints[2].name == "복귀", "출발·복귀는 중립 유지"
    ok(f"진입 waypoint 실명 '{r12.waypoints[1].name}' · 출발/복귀 중립 유지")

    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)


if __name__ == "__main__":
    run()
