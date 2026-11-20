"""
SQ1 모양 관측 적재 — 성공(gen_meta)·실패(candidate_obs) 양쪽에 retrace_ratio·branch_count
가 남는지 + 지표 예외 시 생성 결과 불변. Gemini·T-map 실호출 0(mock). 임시 데이터 전삭.
Run: python tests/test_sq1_shape_obs_integration.py
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
from app.models.schemas import KoreaCoordinate, PedestrianRoute, RouteRequest  # noqa: E402
from app.services import map_service, openai_service, route_service, shape_metrics  # noqa: E402
from tests.test_spur_rescue_integration import START, _mk_candidate, clean_path  # noqa: E402

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
TS = int(time.time())
_uid = None
_route_ids: list[str] = []
_fail_ids: list[str] = []
_passed = 0


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


async def main():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"sq1-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    sb = get_supabase_admin()
    sb.table("profiles").insert({"user_id": _uid, "nickname": f"sq1{TS}", "tier": "free"}).execute()
    t_start = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(TS - 5))

    orig = (openai_service.generate_route, map_service.get_pedestrian_route,
            map_service.search_places, map_service.count_apartment_signal,
            settings.anchor_pool_n, shape_metrics.shape_obs)

    async def gen_mock(**kw):
        return _mk_candidate(kw["start"])

    async def snap_in_band(origin, destination, waypoints=None):
        # 5.0km(밴드 [4.7,5.5] 내) + 깨끗한 폴리라인 → in-band 서빙
        return PedestrianRoute(distance_m=5000, duration_s=2400, path=clean_path(),
                               provider="tmap", road_segments=[(21, "mock로", 5000)])

    async def snap_under(origin, destination, waypoints=None):
        # 2.0km(밴드 밖 언더) 전부 → all_under → band_cap_zero
        return PedestrianRoute(distance_m=2000, duration_s=1600, path=clean_path(),
                               provider="tmap", road_segments=[(21, "mock로", 2000)])

    async def parks(*a, **k):
        return []

    async def apt(*a, **k):
        return (0, 0)

    openai_service.generate_route = gen_mock
    map_service.search_places = parks
    map_service.count_apartment_signal = apt
    settings.anchor_pool_n = 0
    req = RouteRequest(start=KoreaCoordinate(lat=START.lat, lng=START.lng), target_distance_km=5.0)

    def fresh_fails():
        rows = sb.table("gen_failures").select("id,meta").gte("created_at", t_start).execute().data
        return [x for x in rows if (x["meta"] or {}).get("grid_lat") == round(START.lat, 2)]

    try:
        print("[1. 성공 → gen_meta에 retrace_ratio·branch_count 적재]")
        map_service.get_pedestrian_route = snap_in_band
        route = await route_service.create_running_route(req, user_id=_uid)
        assert route.route_id, "서빙됐으나 저장 실패(route_id None)"
        _route_ids.append(route.route_id)
        gm = sb.table("routes").select("gen_meta").eq("id", route.route_id).single().execute().data["gen_meta"]
        assert "retrace_ratio" in gm and "branch_count" in gm, gm
        assert gm["branch_count"] is not None, gm   # clean_path(4점)=계산됨
        # 회랑 1단계 — friendly_ratio·retrace_friendly_m·retrace_road_m·branch_count_strict
        for ck in ("friendly_ratio", "retrace_friendly_m", "retrace_road_m", "branch_count_strict"):
            assert ck in gm, (ck, gm)
        # mock snap road_segments=[(21,...)] → roadType21=friendly → friendly_ratio=1.0
        assert gm["friendly_ratio"] == 1.0, gm
        ok(f"성공 gen_meta: retrace_ratio={gm['retrace_ratio']}·branch_count={gm['branch_count']} "
           f"·friendly_ratio={gm['friendly_ratio']}·branch_count_strict={gm['branch_count_strict']}")

        print("\n[2. 실패(band_cap_zero) → candidate_obs 각 후보에 두 지표 적재]")
        map_service.get_pedestrian_route = snap_under
        try:
            await route_service.create_running_route(req, user_id=_uid)
            raise AssertionError("언더슛인데 서빙되면 안 됨")
        except route_service.RouteGenerationFailed:
            pass
        rows = fresh_fails()
        assert rows, "실패행 미적재"
        _fail_ids.extend(x["id"] for x in rows)
        cobs = rows[-1]["meta"]["candidate_obs"]
        _keys = ("retrace_ratio", "branch_count", "friendly_ratio",
                 "retrace_friendly_m", "retrace_road_m", "branch_count_strict")
        assert cobs and all(all(k in c for k in _keys) for c in cobs), cobs
        ok(f"실패 candidate_obs {len(cobs)}건 각각 6지표 보유(SQ1 2 + 회랑 4) "
           f"(예: friendly_ratio={cobs[0]['friendly_ratio']}·branch_count_strict={cobs[0]['branch_count_strict']})")

        print("\n[3. 지표 예외 시 생성 결과 불변 — shape_obs가 raise해도 서빙 성공]")
        def _boom(_poly):
            raise RuntimeError("shape_obs boom")
        shape_metrics.shape_obs = _boom
        map_service.get_pedestrian_route = snap_in_band
        route2 = await route_service.create_running_route(req, user_id=_uid)
        assert route2.route_id, "지표 예외가 서빙/저장을 막음(불변 위반)"
        _route_ids.append(route2.route_id)
        gm2 = sb.table("routes").select("gen_meta").eq("id", route2.route_id).single().execute().data["gen_meta"]
        assert gm2.get("retrace_ratio") is None and gm2.get("branch_count") is None, gm2
        ok("shape_obs 예외 삼킴 → 서빙·저장 정상(route_id 有)·두 키 null")
    finally:
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.count_apartment_signal,
         settings.anchor_pool_n, shape_metrics.shape_obs) = orig


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    if _route_ids:
        sb.table("routes").delete().in_("id", _route_ids).execute()
    if _fail_ids:
        sb.table("gen_failures").delete().in_("id", _fail_ids).execute()
    sb.table("profiles").delete().eq("user_id", _uid).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    print(f"\n[cleanup] routes {len(_route_ids)}·gen_failures {len(_fail_ids)}·임시 유저 삭제")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_passed} assert)\n" + "=" * 50)
    finally:
        cleanup()
