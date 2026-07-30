"""
Integration: 도로 등급 서빙 게이트(A) + nopath 정직화(B) — 2026-07-29 오너 승인 배치

A-1 동해 IC 램프 실폴리라인 차단 · A-2 잠원 trunk 병행 오탐 금지(회귀) ·
A-3 고속도로 횡단(짧은 접촉) 통과 · A-4 김포 motorway 본선 차단 ·
A-5 파이프라인: 오염 후보 폐기→클린 후보 서빙 + road_gate 키 ·
B-1 스냅 other 전패 → 502 + fail=no_path(가짜 카드 0) · B-2 quota 503·band_cap_zero 회귀

Run: python tests/test_road_gate_integration.py
외부 콜 0(전부 mock/정적 데이터) — Gemini·T-map·Kakao 미호출.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.models.schemas import Coordinate, KoreaCoordinate, PedestrianRoute, RouteRequest, RouteResponse, Waypoint  # noqa: E402
from app.services import map_service, openai_service, route_service  # noqa: E402
from app.services.route_service import (  # noqa: E402
    RouteGenerationFailed, RouteGenerationUnavailable, _load_road_grid, _road_hit_m,
)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None


def ok(m):
    print(f"  ✓ {m}")


def fx(name):
    return json.load(open(os.path.join(FIX, f"{name}.json")))["polyline"]


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _mk_candidate(start: Coordinate) -> RouteResponse:
    """pre-gate(체인 aim×[0.75,1.25]) 통과하는 3점 체인 후보 — target 5.0 기준."""
    a = Coordinate(lat=start.lat + 0.011, lng=start.lng)
    b = Coordinate(lat=start.lat + 0.011, lng=start.lng + 0.013)
    wps = [Waypoint(name="출발", coordinate=start, is_pitstop=False),
           Waypoint(name="지점 1", coordinate=a, is_pitstop=False),
           Waypoint(name="지점 2", coordinate=b, is_pitstop=False),
           Waypoint(name="복귀", coordinate=start, is_pitstop=False)]
    return RouteResponse(summary="mock", total_distance_km=5.0, waypoints=wps)


def _ped(path_pts, km):
    return PedestrianRoute(
        distance_m=km * 1000, duration_s=km * 800,
        path=[Coordinate(lat=p[0], lng=p[1]) for p in path_pts],
        provider="tmap", road_segments=[(21, "mock로", km * 1000)])


async def main():
    global _uid
    grid = _load_road_grid()
    assert grid["hard"][0] is not None, "정적 데이터 로드 실패 — data/motorways_kr.bin.gz 확인"

    print("[A-1 동해 IC 램프 — 하드 차단]")
    run, total = _road_hit_m(fx("road_gate_donghae_ramp"), "hard")
    assert run >= route_service._ROAD_GATE_BLOCK_M, run
    ok(f"longest {run:.0f}m ≥ 100m → 차단 (실측 longest_retrace 3003m 코스)")

    print("\n[A-2 잠원 trunk_link 병행 — 오탐 금지 회귀]")
    run2, _ = _road_hit_m(fx("road_gate_jamwon_ok"), "hard")
    assert run2 < route_service._ROAD_GATE_BLOCK_M, run2
    _, trunk_total = _road_hit_m(fx("road_gate_jamwon_ok"), "obs")
    assert trunk_total > 0, "trunk 관측축은 잠원 병행을 잡아야(관측만, 차단 없음)"
    ok(f"hard longest {run2:.0f}m → 통과 · trunk 관측 {trunk_total:.0f}m 기록(차단 없음)")

    print("\n[A-3 고속도로 횡단(교량/지하차도형) — 짧은 접촉 통과]")
    arr, _h = grid["hard"]
    # 존재 증명: 실 motorway를 가로지르는 횡단선(0 < 접촉 < 100m)이 게이트를
    # 통과한다 — 교량/지하차도 횡단 코스가 오차단되지 않는 성질. 표본 300점에서
    # 남북/동서 횡단선을 만들어 최소 양성 접촉을 찾는다(교차로 밀집부는 접촉이
    # 길어 자연 제외 — 그게 정상 동작).
    best_cross = None
    stride = ((len(arr) // 2) // 300) * 2 or 2
    for j in range(0, len(arr) - 1, stride):
        pla, plo = arr[j] / 1e5, arr[j + 1] / 1e5
        if not (33.5 <= pla <= 38.5 and 124.5 <= plo <= 129.6):   # 한국 경내만
            continue
        for cross in (
            [[pla - 0.0015 + 0.0001 * i, plo] for i in range(31)],   # 남북 횡단
            [[pla, plo - 0.0015 + 0.0001 * i] for i in range(31)],   # 동서 횡단
        ):
            c_run, _ = _road_hit_m(cross, "hard")
            if 0 < c_run < route_service._ROAD_GATE_BLOCK_M:
                best_cross = (c_run, pla, plo)
                break
        if best_cross:
            break
    assert best_cross, "접촉<100m 실횡단 표본 미발견 — 임계 과공격 신호"
    ok(f"실횡단 접촉 {best_cross[0]:.0f}m @({best_cross[1]:.4f},{best_cross[2]:.4f}) "
       f"< 100m → 통과(교량/지하차도 보호)")

    print("\n[A-4 motorway 본선 판정 — 김포 정밀 무죄 + 본선 주행 합성 차단]")
    # 김포 실서빙분: 광역 스캔(고정 스텝 카운트)은 165m 물림 의심이었으나 정밀
    # 게이트(실거리 적산·15m)는 짧은 접촉 — 지하차도/측도 수준으로 무죄 판정.
    # 스캔 방법의 과대계상을 게이트가 교정하는 케이스로 박제.
    run4, _ = _road_hit_m(fx("road_gate_gimpo_motorway"), "hard")
    assert 0 < run4 < route_service._ROAD_GATE_BLOCK_M, run4
    ok(f"김포 실코스 접촉 {run4:.0f}m < 100m → 통과(광역 스캔 165m는 계측 과대 — 정밀 무죄)")
    # 본선 주행 합성: 밀집 셀의 실 motorway 점들을 그대로 폴리라인으로(도로 위 주행)
    import collections as _c
    dense = _c.Counter(_h)
    hash_pick, cnt = max(dense.items(), key=lambda kv: kv[1])
    import bisect as _b
    lo_i, hi_i = _b.bisect_left(_h, hash_pick), _b.bisect_right(_h, hash_pick)
    cell_pts = sorted(([arr[2*j] / 1e5, arr[2*j+1] / 1e5] for j in range(lo_i, hi_i)),
                      key=lambda p: (p[1], p[0]))
    run4b, _ = _road_hit_m(cell_pts, "hard")
    assert run4b >= route_service._ROAD_GATE_BLOCK_M, (run4b, cnt)
    ok(f"본선 위 주행 합성({cnt}점 셀) longest {run4b:.0f}m → 차단")

    # ── 파이프라인 목킹 공통 ──
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"rg-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    # 129.12: 천곡 캐노니컬 진입점(_ACCESS_RADIUS_M 800) 밖 앞바다 — 배치5(07-28)
    # 시딩 후 129.10은 1층이 선서빙해 풀 경로에 도달 못 함(가로채임).
    START = Coordinate(lat=37.51, lng=129.12)
    req = RouteRequest(start=KoreaCoordinate(lat=START.lat, lng=START.lng),
                       target_distance_km=5.0)
    orig_gen = openai_service.generate_route
    orig_snap = map_service.get_pedestrian_route
    orig_parks = map_service.search_places
    orig_apt = map_service.count_apartment_signal

    async def gen_mock(**kw):
        return _mk_candidate(kw["start"])

    async def parks_mock(*a, **k):
        return []

    async def apt_mock(*a, **k):
        return (0, 0)

    openai_service.generate_route = gen_mock
    map_service.search_places = parks_mock
    map_service.count_apartment_signal = apt_mock
    sb = get_supabase_admin()
    t_start = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(TS - 5))
    try:
        print("\n[A-5 파이프라인 — 오염 후보 폐기·클린 서빙·gen_meta 키]")
        calls = {"n": 0}

        async def snap_mixed(origin, destination, waypoints=None):
            calls["n"] += 1
            if calls["n"] <= 2:                       # 앞 2후보는 램프 오염 경로
                return _ped(fx("road_gate_donghae_ramp"), 5.0)
            return _ped(fx("road_gate_jamwon_ok"), 5.0)  # 나머지는 클린(잠원)

        map_service.get_pedestrian_route = snap_mixed
        route = await route_service.create_running_route(req, user_id=_uid)
        rows = sb.table("routes").select("id,gen_meta").eq("user_id", _uid) \
            .gte("created_at", t_start).execute().data
        gm = rows[-1]["gen_meta"]
        assert route.total_distance_km == 5.0 and gm["verdict"] == "hit"
        assert gm.get("road_gate_rejected", 0) >= 1, gm
        assert gm.get("road_gate_worst_m", 0) >= 100, gm
        assert gm.get("trunk_hit_m", 0) > 0, "채택(잠원) 코스 trunk 관측 기록"
        assert gm.get("tmap_road_types"), "T-map roadType 관측 기록"
        ok(f"오염 {gm['road_gate_rejected']}건 폐기(worst {gm['road_gate_worst_m']}m) → "
           f"클린 서빙 + trunk_hit_m {gm['trunk_hit_m']} + tmap_road_types 기록")

        print("\n[B-1 스냅 other 전패 — 가짜 카드 0·502·fail=no_path]")
        async def snap_boom(*a, **k):
            raise RuntimeError("forced-other(test)")
        map_service.get_pedestrian_route = snap_boom
        before_routes = len(sb.table("routes").select("id").eq("user_id", _uid)
                            .gte("created_at", t_start).execute().data)
        try:
            await route_service.create_running_route(req, user_id=_uid)
            raise AssertionError("no_path 상황이 200 서빙되면 안 됨")
        except RouteGenerationFailed:
            pass
        after_routes = len(sb.table("routes").select("id").eq("user_id", _uid)
                           .gte("created_at", t_start).execute().data)
        assert after_routes == before_routes, "폴리라인 0 카드가 저장되면 안 됨"
        fails = sb.table("gen_failures").select("id,meta").gte("created_at", t_start).execute().data
        nps = [f for f in fails if (f["meta"] or {}).get("fail") == "no_path"]
        assert nps, "gen_failures fail=no_path 기록 필수"
        ok("502 + routes 무저장 + gen_failures fail=no_path")

        print("\n[B-2 회귀 — quota 503 · band_cap_zero 502 유지]")
        async def snap_quota(*a, **k):
            raise map_service.TmapQuotaExceeded()
        map_service.get_pedestrian_route = snap_quota
        try:
            await route_service.create_running_route(req, user_id=_uid)
            raise AssertionError("quota 지배는 503이어야")
        except RouteGenerationUnavailable:
            ok("quota 지배 → 503 유지")

        async def snap_under(origin, destination, waypoints=None):
            return _ped(fx("road_gate_jamwon_ok")[:40], 2.0)   # 전 후보 언더슈트
        map_service.get_pedestrian_route = snap_under
        try:
            await route_service.create_running_route(req, user_id=_uid)
            raise AssertionError("band_cap_zero는 502이어야")
        except RouteGenerationFailed:
            pass
        fails2 = sb.table("gen_failures").select("id,meta").gte("created_at", t_start).execute().data
        bcz = [f for f in fails2 if (f["meta"] or {}).get("fail") == "band_cap_zero"]
        assert bcz, "band_cap_zero 태그 유지"
        ok("전 후보 언더슈트(재추첨 포함 실패) → 502 + fail=band_cap_zero 유지")

        print("\n[A-6 재추첨 경로 게이트 — v112 스모크서 발견한 우회 구멍 회귀]")
        calls6 = {"n": 0}

        async def snap_redraw_ramp(origin, destination, waypoints=None):
            calls6["n"] += 1
            if calls6["n"] <= 9:                        # 메인 풀: 클린 언더슈트
                return _ped(fx("road_gate_jamwon_ok")[:40], 2.0)
            return _ped(fx("road_gate_donghae_ramp"), 5.0)   # 재추첨: 밴드 내 램프 오염

        map_service.get_pedestrian_route = snap_redraw_ramp
        try:
            await route_service.create_running_route(req, user_id=_uid)
            raise AssertionError("재추첨의 램프 오염 후보가 서빙되면 안 됨")
        except RouteGenerationFailed:
            pass
        fails3 = sb.table("gen_failures").select("id,meta").gte("created_at", t_start).execute().data
        rrg = [f for f in fails3
               if ((f["meta"] or {}).get("redraw") or {}).get("redraw_road_gate_rejected")]
        assert rrg, "재추첨 게이트 폐기 관측(redraw_road_gate_rejected) 기록 필수"
        ok("재추첨 밴드 내 램프 후보 폐기 → 502 + redraw_road_gate_rejected 기록")
    finally:
        openai_service.generate_route = orig_gen
        map_service.get_pedestrian_route = orig_snap
        map_service.search_places = orig_parks
        map_service.count_apartment_signal = orig_apt


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    rows = sb.table("routes").select("id").eq("user_id", _uid).execute().data
    if rows:
        sb.table("routes").delete().in_("id", [x["id"] for x in rows]).execute()
    fails = sb.table("gen_failures").select("id,meta") \
        .gte("created_at", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(TS - 5))).execute().data
    kill = [f["id"] for f in fails
            if (f["meta"] or {}).get("grid_lat") == 37.51 and (f["meta"] or {}).get("grid_lng") == 129.12]
    if kill:
        sb.table("gen_failures").delete().in_("id", kill).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    left = len(sb.table("routes").select("id").eq("user_id", _uid).execute().data)
    assert left == 0
    print(f"\n[cleanup] routes 0 · gen_failures {len(kill)}건 · 임시 유저 삭제")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
