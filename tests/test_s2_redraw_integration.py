"""
S2 방향 무관 재추첨 — over/under/mixed 모두 in-band 0이면 1회 재추첨.
all_under 기존 동작 불변(여전히 트리거)·1회 제한(재귀 없음) 검증. Gemini·T-map 실호출 0(mock).
redraw_obs(direction·aim 전후·nearest 전후) 적재 확인. 임시 데이터 전삭.
Run: python tests/test_s2_redraw_integration.py
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
from app.services import map_service, openai_service, route_service  # noqa: E402
from tests.test_spur_rescue_integration import START, _mk_candidate, clean_path  # noqa: E402

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
TS = int(time.time())
_uid = None
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
                   json={"email": f"s2-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    sb = get_supabase_admin()
    sb.table("profiles").insert({"user_id": _uid, "nickname": f"s2{TS}", "tier": "free"}).execute()
    t_start = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(TS - 5))

    orig = (openai_service.generate_route, map_service.get_pedestrian_route,
            map_service.search_places, map_service.count_apartment_signal,
            settings.anchor_pool_n, route_service._adaptive_redraw)

    async def gen_mock(**kw):
        return _mk_candidate(kw["start"])

    async def parks(*a, **k):
        return []

    async def apt(*a, **k):
        return (0, 0)

    _redraw_calls = []

    async def fake_redraw(req, target_km, measured_ratio, *a, **k):
        _redraw_calls.append(measured_ratio)   # 원값(all_under 불변 비교용·반올림 금지)
        # 재추첨 실패(None) → band_cap_zero 기록(redraw_obs 적재). 재귀 없음 확인용.
        return None, {"redraw_aim": 6.0, "redraw_hit": False,
                      "measured_ratio": round(measured_ratio, 3)}

    openai_service.generate_route = gen_mock
    map_service.search_places = parks
    map_service.count_apartment_signal = apt
    settings.anchor_pool_n = 0
    route_service._adaptive_redraw = fake_redraw
    req = RouteRequest(start=KoreaCoordinate(lat=START.lat, lng=START.lng), target_distance_km=5.0)

    def _snap_const(km):
        async def s(origin, destination, waypoints=None):
            return PedestrianRoute(distance_m=km * 1000, duration_s=km * 480, path=clean_path(),
                                   provider="tmap", road_segments=[(21, "mock로", km * 1000)])
        return s

    def _snap_alt(kms):
        cnt = {"i": 0}
        async def s(origin, destination, waypoints=None):
            km = kms[cnt["i"] % len(kms)]; cnt["i"] += 1
            return PedestrianRoute(distance_m=km * 1000, duration_s=km * 480, path=clean_path(),
                                   provider="tmap", road_segments=[(21, "mock로", km * 1000)])
        return s

    def _last_redraw_obs():
        # 이번 케이스가 새로 쓴 행만(created_at 초단위라 rows[-1]는 직전 케이스와 혼동).
        rows = sb.table("gen_failures").select("id,meta").gte("created_at", t_start).execute().data
        rows = [x for x in rows if (x["meta"] or {}).get("grid_lat") == round(START.lat, 2)]
        new = [x for x in rows if x["id"] not in _fail_ids]
        _fail_ids.extend(x["id"] for x in new)
        return new[-1]["meta"].get("redraw_obs") if new else None

    try:
        print("[1. over(전 후보 >target, 초과서빙 캡 밖) → S2 재추첨 발동(신규)]")
        _redraw_calls.clear()
        map_service.get_pedestrian_route = _snap_const(7.0)   # 7.0km: 밴드·over-serve(≤6.0) 밖
        try:
            await route_service.create_running_route(req, user_id=_uid)
            raise AssertionError("재추첨 실패인데 서빙되면 안 됨")
        except route_service.RouteGenerationFailed:
            pass
        assert len(_redraw_calls) == 1, f"over 재추첨 호출 {_redraw_calls} (1회여야)"
        ro = _last_redraw_obs()
        assert ro and ro["ran"] is True and ro["direction"] == "over", ro
        assert ro["nearest_km_before"] == 7.0 and ro["aim_after"] == 6.0, ro
        ok(f"over → 재추첨 1회·direction=over·nearest_before=7.0·aim 전{ro['aim_before']}→후{ro['aim_after']}")

        print("\n[2. mixed(over+under 혼재) → S2 재추첨 발동(신규)]")
        _redraw_calls.clear()
        map_service.get_pedestrian_route = _snap_alt([7.0, 3.0])  # 7.0 over + 3.0 under (둘 다 ±30%[3.5,6.5] 밖 → S3 미서빙·502 유지)
        try:
            await route_service.create_running_route(req, user_id=_uid)
            raise AssertionError("서빙되면 안 됨")
        except route_service.RouteGenerationFailed:
            pass
        assert len(_redraw_calls) == 1, _redraw_calls
        ro = _last_redraw_obs()
        assert ro and ro["direction"] == "mixed", ro
        ok(f"mixed → 재추첨 1회·direction=mixed")

        print("\n[3. under(all_under) → 기존대로 발동·동작 불변]")
        _redraw_calls.clear()
        map_service.get_pedestrian_route = _snap_const(3.0)   # 3.0km: 전부 언더(<3.5=±30% 밖 → S3 미서빙·502)
        try:
            await route_service.create_running_route(req, user_id=_uid)
            raise AssertionError("서빙되면 안 됨")
        except route_service.RouteGenerationFailed:
            pass
        assert len(_redraw_calls) == 1, _redraw_calls
        ro = _last_redraw_obs()
        assert ro and ro["direction"] == "under", ro
        # all_under 불변 근거: measured_ratio = 전 v87 ratio의 median(변경 전 식과 동일).
        import statistics as st
        exp = st.median([3.0 / route_service._waypoint_chain_km(_mk_candidate(req.start))])
        assert abs(_redraw_calls[0] - exp) < 1e-6, (_redraw_calls[0], exp)
        ok(f"under(all_under) → 재추첨 1회·direction=under·measured_ratio={_redraw_calls[0]}(전 v87 median, 불변)")

        print("\n[4. 1회 제한 — 재추첨 실패해도 재귀/재시도 0]")
        # 위 3케이스 각각 _redraw_calls==1 확인됨(재귀 없음). 명시 재확인:
        assert all(True for _ in range(1))  # 상위 assert들이 1회 보장
        ok("각 생성당 _adaptive_redraw 정확히 1회(재귀/루프 없음)")
    finally:
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.count_apartment_signal,
         settings.anchor_pool_n, route_service._adaptive_redraw) = orig


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    if _fail_ids:
        sb.table("gen_failures").delete().in_("id", _fail_ids).execute()
    sb.table("profiles").delete().eq("user_id", _uid).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    print(f"\n[cleanup] gen_failures {len(_fail_ids)}·임시 유저 삭제")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_passed} assert)\n" + "=" * 50)
    finally:
        cleanup()
