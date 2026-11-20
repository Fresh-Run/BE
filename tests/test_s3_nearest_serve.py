"""
S3 최근접 품질 서빙 — ±30% 내 품질통과 최근접 서빙, 응답 필드, 무차감, 실패 시 suggested
미발신, 밴드 안 불변. Gemini·T-map 실호출 0(mock). 임시 데이터 전삭.
Run: python tests/test_s3_nearest_serve.py
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
from app.models.schemas import (CurrentUser, KoreaCoordinate, PedestrianRoute,  # noqa: E402
                                RouteRequest, RouteResponse)
from app.services import map_service, openai_service, route_service, quota_service  # noqa: E402
from app.api import routes as api_routes  # noqa: E402
from tests.test_spur_rescue_integration import START, _mk_candidate, clean_path  # noqa: E402

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
TS = int(time.time())
_uid = None
_route_ids: list[str] = []
_passed = 0


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


class _R:
    def __init__(s, poly=None):
        s.polyline = poly or [{"lat": 37.5, "lng": 127.0}, {"lat": 37.51, "lng": 127.0}]


def _pure():
    rs = route_service
    print("[A. _nearest_quality_serve — ±30% 경계·품질·동률]")

    def mk(cases, target=5.0):
        scored, eng, spur = [], {}, {}
        for km, e, rt in cases:
            r = _R(); scored.append((km, r)); eng[id(r)] = e; spur[id(r)] = rt
        return rs._nearest_quality_serve(scored, target, eng, spur)

    assert mk([(6.8, "v87", 100), (6.1, "v87", 100), (6.5, "v87", 100)])[0] == 6.1
    ok("이준 사례(6.8/6.1/6.5) → 6.1(±30% 내 최근접, 6.8 제외)")
    assert mk([(6.5, "v87", 100), (6.6, "v87", 100)])[0] == 6.5
    assert mk([(3.5, "v87", 100), (3.4, "v87", 100)])[0] == 3.5
    ok("경계 6.5(=1.3x)·3.5(=0.7x) 포함 / 6.6·3.4 제외")
    assert mk([(5.6, "anchor", 100)]) is None
    ok("일반 앵커 제외 → None")
    assert mk([(5.6, "v87", 900)]) is None
    ok("longest_retrace 900>800 제외 → None")
    assert mk([(3.4, "v87", 100), (7.7, "v87", 100), (8.4, "v87", 100)]) is None
    ok("±30% 밖만 → None(이준 10건 중 1 실패 케이스)")
    # 동률: target 5, 4.5와 5.5 동거리 → min이 안정(첫 요소)
    tie = mk([(5.5, "v87", 100), (4.5, "v87", 100)])
    assert tie[0] in (4.5, 5.5)
    ok(f"동률(4.5·5.5 |Δ|=0.5 동일) → 안정 선택({tie[0]})")


async def main():
    global _uid
    _pure()

    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"s3-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    sb = get_supabase_admin()
    sb.table("profiles").insert({"user_id": _uid, "nickname": f"s3{TS}", "tier": "free"}).execute()

    orig = (openai_service.generate_route, map_service.get_pedestrian_route,
            map_service.search_places, map_service.count_apartment_signal,
            settings.anchor_pool_n, route_service._adaptive_redraw)

    async def gen_mock(**kw):
        return _mk_candidate(kw["start"])

    async def parks(*a, **k):
        return []

    async def apt(*a, **k):
        return (0, 0)

    async def fail_redraw(*a, **k):
        return None, {"redraw_aim": 6.0, "redraw_hit": False, "measured_ratio": 1.0}

    def snap(km):
        async def s(origin, destination, waypoints=None):
            return PedestrianRoute(distance_m=km * 1000, duration_s=km * 480, path=clean_path(),
                                   provider="tmap", road_segments=[(21, "m", km * 1000)])
        return s

    openai_service.generate_route = gen_mock
    map_service.search_places = parks
    map_service.count_apartment_signal = apt
    settings.anchor_pool_n = 0
    route_service._adaptive_redraw = fail_redraw
    req = RouteRequest(start=KoreaCoordinate(lat=START.lat, lng=START.lng), target_distance_km=5.0)

    try:
        print("\n[B. nearest_served 서빙 — 응답 필드]")
        map_service.get_pedestrian_route = snap(6.5)   # 밴드·over-serve(≤6.0) 밖, ±30% 내
        route = await route_service.create_running_route(req, user_id=_uid)
        if route.route_id:
            _route_ids.append(route.route_id)
        assert route.distance_reason == "nearest_served", route.distance_reason
        assert route.requested_distance_km == 5.0 and route.actual_distance_km == route.total_distance_km
        assert route.target_missed is True
        ok(f"6.5km 서빙 → distance_reason=nearest_served·requested=5.0·actual={route.actual_distance_km}·target_missed=True")

        print("\n[C. 밴드 안 서빙 불변 — distance_reason None]")
        route_service._adaptive_redraw = orig[5]  # 원복(밴드 안은 재추첨 무관)
        map_service.get_pedestrian_route = snap(5.0)   # 밴드 내
        r2 = await route_service.create_running_route(req, user_id=_uid)
        if r2.route_id:
            _route_ids.append(r2.route_id)
        assert r2.distance_reason is None and r2.requested_distance_km is None, r2.distance_reason
        assert 4.7 <= r2.total_distance_km <= 5.5
        ok(f"밴드 내 5.0 서빙 → distance_reason=None·requested=None(기존 동작 불변)")

        print("\n[D. 엔드포인트 — nearest_served 무차감 / 실패 시 suggested 미발신]")
        # 무차감: nearest_served 반환 시 release 호출되는가
        _released = []
        _orig = (quota_service.get_tier, quota_service.reserve_ai_generation,
                 quota_service.release_ai_generation, route_service.create_running_route)

        async def _tier(uid):
            return "free"

        async def _reserve(uid, limit):
            return "resv-1"

        async def _release(rid):
            _released.append(rid)

        async def _crr_nearest(req, user_id=None):
            return RouteResponse(summary="s", total_distance_km=6.5, distance_reason="nearest_served",
                                 requested_distance_km=5.0, actual_distance_km=6.5, target_missed=True)
        quota_service.get_tier = _tier
        quota_service.reserve_ai_generation = _reserve
        quota_service.release_ai_generation = _release
        api_routes.quota_service.release_ai_generation = _release
        api_routes.quota_service.reserve_ai_generation = _reserve
        api_routes.quota_service.get_tier = _tier
        route_service.create_running_route = _crr_nearest
        user = CurrentUser(user_id=_uid, email=None)
        out = await api_routes.generate_route(req, user)
        assert out.distance_reason == "nearest_served" and _released == ["resv-1"], _released
        ok("nearest_served → release_ai_generation 호출(무차감)")

        # 실패 502: suggested_target_km 미발신 + reason=no_quality_candidate
        _released.clear()
        async def _crr_fail(req, user_id=None):
            raise route_service.RouteGenerationFailed(fail="band_cap_zero", best_km=6.0)
        route_service.create_running_route = _crr_fail
        try:
            await api_routes.generate_route(req, user)
            raise AssertionError("502여야 함")
        except api_routes.HTTPException as e:
            d = e.detail
            assert "suggested_target_km" not in d, d
            assert d.get("reason") == "no_quality_candidate", d
            assert _released == ["resv-1"], _released  # 실패도 예약 해제(무차감)
        ok("실패 502 → suggested_target_km 미발신·reason=no_quality_candidate·예약 해제")
        (quota_service.get_tier, quota_service.reserve_ai_generation,
         quota_service.release_ai_generation, route_service.create_running_route) = _orig
    finally:
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.count_apartment_signal,
         settings.anchor_pool_n, route_service._adaptive_redraw) = orig


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    if _route_ids:
        sb.table("routes").delete().in_("id", _route_ids).execute()
    sb.table("profiles").delete().eq("user_id", _uid).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    print(f"\n[cleanup] routes {len(_route_ids)}·임시 유저 삭제")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_passed} assert)\n" + "=" * 50)
    finally:
        cleanup()
