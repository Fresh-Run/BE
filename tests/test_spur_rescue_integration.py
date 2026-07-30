"""
Integration: in-band spur 구제(INBAND_SPUR_RESCUE_DESIGN, 오너 승인 2026-07-30)

U-1 트리거 미달(L≤800) — 미발동·원 후보 그대로 · U-2 플래그 OFF 미발동 ·
U-3 앵커 best 미발동(v87 한정) · U-4 ①0원 대체(Gemini 0콜 assert) ·
U-5 ②재추첨 개선 반영(hit·L 개선) · U-6 개선 실패/missed → 원 후보(비퇴행) ·
U-7 재추첨 예외 → 원 후보(비퇴행)
P-1 파이프라인 OFF — verdict hit·spur_rescue 키 부재·cand_quality L 병기(관측
    플래그 무관 발효) · P-2 ON stage-2 — hit_redraw·rescued·Gemini +5콜(요청당
    ≤17) · P-3 ON 무개선 — 200 서빙·kept_original(비퇴행) · P-4 ON 게이트 교차 —
    재추첨 산출물 IC 램프 오염 → 내부 폐기 → 원 후보 서빙(뒷문 없음)

Run: python tests/test_spur_rescue_integration.py
외부 콜 0(전부 mock) — Gemini·T-map·Kakao 미호출. DB는 임시 유저·routes만
(종료 시 잔여 0 assert).
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
from app.models.schemas import (  # noqa: E402
    Coordinate, KoreaCoordinate, PedestrianRoute, RouteRequest, RouteResponse,
    Waypoint,
)
from app.services import map_service, openai_service, route_service  # noqa: E402
from app.services.route_service import (  # noqa: E402
    _road_hit_m, _spur_metrics, _spur_rescue,
)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None
# 천곡 캐노니컬 진입점(_ACCESS_RADIUS_M 800) 밖 + motorway 무접촉인 앞바다 —
# 1층(캐노니컬) 선서빙을 피해 풀 경로를 결정적으로 태운다.
START = Coordinate(lat=37.51, lng=129.115)


def ok(m):
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def C(la, lo):
    return Coordinate(lat=la, lng=lo)


# ── 합성 폴리라인(동해 앞바다 — motorway 데이터 무접촉 전제, 아래서 assert) ──
def star_path():
    """편도 ~1.2km 나갔다 같은 점들로 복귀 — L>800 왕복 팔."""
    out = [C(37.51, 129.115 + i * 0.0005) for i in range(29)]
    return out + out[::-1][1:]


def clean_path():
    """사각 루프 — 되밟기 0(L=0). star와 같은 앞바다 권역(게이트 무접촉)."""
    return [C(37.510, 129.115), C(37.514, 129.115), C(37.514, 129.120),
            C(37.510, 129.120), C(37.510, 129.115)]


def _wp(la, lo):
    return Waypoint(name="x", coordinate=C(la, lo), is_pitstop=False)


def _mk_candidate(start: Coordinate) -> RouteResponse:
    """pre-gate(체인 aim×[0.75,1.25]) 통과 3점 체인 — road_gate 테스트와 동일."""
    a = C(start.lat + 0.011, start.lng)
    b = C(start.lat + 0.011, start.lng + 0.013)
    wps = [Waypoint(name="출발", coordinate=start, is_pitstop=False),
           Waypoint(name="지점 1", coordinate=a, is_pitstop=False),
           Waypoint(name="지점 2", coordinate=b, is_pitstop=False),
           Waypoint(name="복귀", coordinate=start, is_pitstop=False)]
    return RouteResponse(summary="mock", total_distance_km=5.0, waypoints=wps)


def _route(polyline, km=5.0):
    r = _mk_candidate(START)
    r.polyline = polyline
    r.total_distance_km = km
    return r


def _ped(path, km):
    return PedestrianRoute(distance_m=km * 1000, duration_s=km * 800, path=path,
                           provider="tmap", road_segments=[(21, "mock로", km * 1000)])


REQ = RouteRequest(start=KoreaCoordinate(lat=START.lat, lng=START.lng),
                   target_distance_km=5.0)
NOARGS = dict(avoid_tags=[], prefs=None, lang="ko", radius_center=None,
              start_end_km=None)


async def unit_tests():
    L_STAR = _spur_metrics(star_path())["longest_retrace_m"]
    assert L_STAR > 800, f"star 전제: L>800, got {L_STAR}"
    assert _spur_metrics(clean_path())["longest_retrace_m"] == 0
    assert _road_hit_m(star_path(), "hard")[0] < 100, "star가 실 motorway와 겹치면 좌표 재선정"
    assert _road_hit_m(clean_path(), "hard")[0] < 100
    ok(f"합성 전제 — star L={L_STAR}(>800)·게이트 무접촉, clean L=0")

    star = _route(star_path())
    clean = _route(clean_path(), 5.2)
    quals = {id(star): (0.0, 0, 0), id(clean): (0.0, 0, 5)}
    spur_of = {id(star): L_STAR, id(clean): 0}
    in_band = [(5.0, star), (5.2, clean)]
    eng = {id(star): "v87", id(clean): "v87"}

    orig_redraw = route_service._adaptive_redraw
    orig_gen = openai_service.generate_route

    async def forbid_redraw(*a, **k):
        raise AssertionError("Gemini 경로(_adaptive_redraw)가 호출되면 안 됨")

    async def forbid_gen(*a, **k):
        raise AssertionError("generate_route가 호출되면 안 됨")

    try:
        print("\n[U-1 트리거 미달(L≤800) — 미발동]")
        settings.spur_rescue_enabled = True
        route_service._adaptive_redraw = forbid_redraw
        openai_service.generate_route = forbid_gen
        b, k, resc, rd = await _spur_rescue(
            REQ, 5.0, [(5.2, clean)], clean, 5.2, quals, spur_of,
            [(5.2, clean)], eng, **NOARGS)
        assert b is clean and resc is None and rd is None
        ok("L=0 best → 구제 객체 None·원 후보 그대로")

        print("\n[U-2 플래그 OFF — 미발동]")
        settings.spur_rescue_enabled = False
        b, k, resc, rd = await _spur_rescue(
            REQ, 5.0, [(5.0, star)], star, 5.0, quals, spur_of,
            [(5.0, star)], eng, **NOARGS)
        assert b is star and resc is None
        ok("L>800이어도 플래그 OFF면 미발동")

        print("\n[U-3 앵커 best — 미발동(v87 한정, 오너 결정 ③)]")
        settings.spur_rescue_enabled = True
        eng_a = {id(star): "anchor"}
        b, k, resc, rd = await _spur_rescue(
            REQ, 5.0, [(5.0, star)], star, 5.0, quals, spur_of,
            [(5.0, star)], eng_a, **NOARGS)
        assert b is star and resc is None
        ok("앵커 engine best는 L>800이어도 트리거 미발동")

        print("\n[U-4 ①0원 대체 — Gemini 0콜]")
        b, k, resc, rd = await _spur_rescue(
            REQ, 5.0, in_band, star, 5.0, quals, spur_of, in_band, eng, **NOARGS)
        assert b is clean and k == 5.2, (b is clean, k)
        assert resc["mode"] == "substitute" and resc["rolls_used"] == 0
        assert resc["L_before"] == L_STAR and rd is None
        ok("같은 풀 L≤800 후보로 대체 — _adaptive_redraw·generate_route 미호출(forbid mock 통과)")
    finally:
        route_service._adaptive_redraw = orig_redraw
        openai_service.generate_route = orig_gen

    print("\n[U-5 ②재추첨 개선 반영 — hit·L 개선]")
    better = _route(clean_path(), 5.1)

    async def redraw_hit(*a, **k):
        assert k.get("pool_n") == settings.spur_rescue_pool_n, k
        return better, {"redraw_hit": True, "redraw_verdict": "hit"}

    route_service._adaptive_redraw = redraw_hit
    try:
        b, k, resc, rd = await _spur_rescue(
            REQ, 5.0, [(5.0, star)], star, 5.0, quals, spur_of,
            [(5.0, star)], eng, **NOARGS)
        assert b is better and k == 5.1
        assert resc["mode"] == "redraw" and resc["rolls_used"] == settings.spur_rescue_pool_n
        ok(f"재추첨 hit·L 0<{L_STAR} → 교체, rolls_used {resc['rolls_used']}")

        print("\n[U-6 재추첨 개선 실패 — 원 후보 유지(비퇴행)]")
        worse = _route(star_path() + star_path(), 5.0)  # L 더 김

        async def redraw_worse(*a, **kw):
            return worse, {"redraw_hit": True, "redraw_verdict": "hit"}
        route_service._adaptive_redraw = redraw_worse
        b, k, resc, rd = await _spur_rescue(
            REQ, 5.0, [(5.0, star)], star, 5.0, quals, spur_of,
            [(5.0, star)], eng, **NOARGS)
        assert b is star and resc["mode"] == "kept_original"
        ok("L 미개선 → 원 후보 유지")

        async def redraw_missed(*a, **kw):
            r = _route(clean_path(), 6.0)
            r.target_missed = True
            return r, {"redraw_hit": True, "redraw_verdict": "missed"}
        route_service._adaptive_redraw = redraw_missed
        b, k, resc, rd = await _spur_rescue(
            REQ, 5.0, [(5.0, star)], star, 5.0, quals, spur_of,
            [(5.0, star)], eng, **NOARGS)
        assert b is star and resc["mode"] == "kept_original"
        ok("redraw verdict=missed(밴드 밖) → L 좋아도 미채택·원 후보 유지")

        print("\n[U-7 재추첨 예외 — 원 후보 유지(비퇴행)]")

        async def redraw_boom(*a, **kw):
            raise RuntimeError("forced(test)")
        route_service._adaptive_redraw = redraw_boom
        b, k, resc, rd = await _spur_rescue(
            REQ, 5.0, [(5.0, star)], star, 5.0, quals, spur_of,
            [(5.0, star)], eng, **NOARGS)
        assert b is star and resc["mode"] == "kept_original"
        ok("재추첨 예외 삼킴 → 원 후보 서빙 경로 유지(raise 전파 0)")
    finally:
        route_service._adaptive_redraw = orig_redraw
        settings.spur_rescue_enabled = False


async def pipeline_tests():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"spur-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    sb = get_supabase_admin()

    orig = (openai_service.generate_route, map_service.get_pedestrian_route,
            map_service.search_places, map_service.count_apartment_signal,
            settings.anchor_pool_n, settings.spur_rescue_enabled)
    gen_calls = {"n": 0}
    snap_calls = {"n": 0}

    async def gen_mock(**kw):
        gen_calls["n"] += 1
        return _mk_candidate(kw["start"])

    async def parks_mock(*a, **k):
        return []

    async def apt_mock(*a, **k):
        return (0, 0)

    def snap_factory(first9, later):
        async def snap(origin, destination, waypoints=None):
            snap_calls["n"] += 1
            path = first9 if snap_calls["n"] <= 9 else later
            return _ped(path, 5.0)
        return snap

    def last_gm():
        rows = sb.table("routes").select("id,gen_meta,created_at") \
            .eq("user_id", _uid).order("created_at", desc=True).limit(1).execute().data
        return rows[0]["gen_meta"]

    openai_service.generate_route = gen_mock
    map_service.search_places = parks_mock
    map_service.count_apartment_signal = apt_mock
    settings.anchor_pool_n = 0   # 순수 v87 풀(결정적)
    try:
        print("\n[P-1 파이프라인 플래그 OFF — 기존 동작 + 관측만 발효]")
        settings.spur_rescue_enabled = False
        gen_calls["n"] = snap_calls["n"] = 0
        map_service.get_pedestrian_route = snap_factory(star_path(), star_path())
        route = await route_service.create_running_route(REQ, user_id=_uid)
        assert route.total_distance_km == 5.0
        gm = last_gm()
        p1_calls = gen_calls["n"]
        assert gm["verdict"] == "hit" and "spur_rescue" not in gm, gm.get("verdict")
        assert all("longest_retrace_m" in c for c in gm["cand_quality"]), gm["cand_quality"][0]
        assert gm["longest_retrace_m"] > 800
        ok(f"verdict hit·spur_rescue 키 부재·cand_quality 전원 L 병기(관측 발효)·Gemini {p1_calls}콜")

        print("\n[P-2 플래그 ON — stage-2 재추첨 구제(hit_redraw)]")
        settings.spur_rescue_enabled = True
        gen_calls["n"] = snap_calls["n"] = 0
        map_service.get_pedestrian_route = snap_factory(star_path(), clean_path())
        route = await route_service.create_running_route(REQ, user_id=_uid)
        gm = last_gm()
        assert gm["verdict"] == "hit_redraw", gm["verdict"]
        sr = gm["spur_rescue"]
        assert sr["attempted"] and sr["mode"] == "redraw", sr
        assert sr["rolls_used"] == settings.spur_rescue_pool_n
        assert sr["L_before"] > 800 and sr["L_after"] < sr["L_before"] and sr["rescued"], sr
        assert gm["longest_retrace_m"] == sr["L_after"] == 0
        delta = gen_calls["n"] - p1_calls
        assert delta == settings.spur_rescue_pool_n, (gen_calls["n"], p1_calls)
        assert gen_calls["n"] <= 17, gen_calls["n"]
        ok(f"hit_redraw·L {sr['L_before']}→{sr['L_after']}·rescued·Gemini +{delta}콜"
           f"(요청 총 {gen_calls['n']}≤17)")

        print("\n[P-3 플래그 ON — 재추첨 무개선 → 원 후보 서빙(비퇴행)]")
        gen_calls["n"] = snap_calls["n"] = 0
        map_service.get_pedestrian_route = snap_factory(star_path(), star_path())
        route = await route_service.create_running_route(REQ, user_id=_uid)
        assert route.total_distance_km == 5.0, "서빙 자체는 반드시 성립(비퇴행)"
        gm = last_gm()
        sr = gm["spur_rescue"]
        assert gm["verdict"] == "hit" and sr["mode"] == "kept_original", (gm["verdict"], sr)
        assert sr["rolls_used"] == settings.spur_rescue_pool_n and not sr["rescued"]
        ok("무개선 재추첨 → verdict hit 유지·kept_original·rescued False·200 서빙")

        print("\n[P-4 플래그 ON — 게이트 교차: 재추첨 산출물 IC 램프 오염 → 폐기]")
        ramp = [C(p[0], p[1]) for p in
                json.load(open(os.path.join(FIX, "road_gate_donghae_ramp.json")))["polyline"]]
        assert _road_hit_m(ramp, "hard")[0] >= 100, "램프 fixture는 게이트 차단 전제"
        gen_calls["n"] = snap_calls["n"] = 0
        map_service.get_pedestrian_route = snap_factory(star_path(), ramp)
        route = await route_service.create_running_route(REQ, user_id=_uid)
        assert route.total_distance_km == 5.0
        gm = last_gm()
        sr = gm["spur_rescue"]
        assert sr["mode"] == "kept_original" and not sr["rescued"], sr
        assert gm["longest_retrace_m"] > 800, "서빙분은 원 후보(star) — 램프 후보 아님"
        served = [(round(c.lat, 5), round(c.lng, 5)) for c in route.polyline[:3]]
        assert served != [(round(p.lat, 5), round(p.lng, 5)) for p in ramp[:3]], \
            "게이트 차단 대상 폴리라인이 서빙되면 뒷문"
        ok("램프 산출물은 _adaptive_redraw 내장 게이트서 폐기 → 원 후보 서빙(뒷문 없음)")
    finally:
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.count_apartment_signal,
         settings.anchor_pool_n, settings.spur_rescue_enabled) = orig


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
    print(f"\n[cleanup] routes {len(rows)}건 삭제·임시 유저 삭제·잔여 0")


if __name__ == "__main__":
    try:
        asyncio.run(unit_tests())
        asyncio.run(pipeline_tests())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
