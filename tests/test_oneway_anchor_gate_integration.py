"""
Integration: 앵커 one-way 게이트 (2026-08-08, P2 a8905a40 실증 수정)

전례: Gemini 전멸(크레딧 소진 8/6) 시 루프 전용 앵커 롤이 편도 요청에
"편도" 제목 루프를 서빙(engine=anchor·폐합 0m) + 정직 503을 502로 위장.
수정: req.end 지정 시 anchor_n=0.

G-1 one-way + 전 롤 429 + anchor_pool_n=2 → **503 정직화**(앵커 미편입 —
    collect_anchors 호출 0 assert) + 쿼터 환급
G-2 loop + 전 롤 429 + 앵커 제공 → 앵커 서빙 불변(engine=anchor — 기존 동작)
G-3 one-way + v87 정상 → 편도 서빙 불변("편도" 제목·"복귀" 라벨 부재 =
    라벨 모순 소멸 픽스처)
Gemini·T-map 실콜 0(전부 mock)·실 DB — 생성 행·유저 종료 시 전삭 잔여 0.

Run: python tests/test_oneway_anchor_gate_integration.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
import openai  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.main import app  # noqa: E402
from app.models.schemas import (  # noqa: E402
    Coordinate, PedestrianRoute, RouteResponse, Waypoint)
from app.services import anchor_service, map_service, openai_service  # noqa: E402

TS = int(time.time())
_SB = settings.supabase_url
_uid: str | None = None
START = {"lat": 37.60, "lng": 127.20}
END = {"lat": 37.612, "lng": 127.21}   # 직선 ~1.6km — one_way_end_too_far 비발동(target 5)


def ok(m):
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _mk_429():
    req = httpx.Request("POST", "https://gemini.test/v1")
    return openai.RateLimitError("upstream(test)",
                                 response=httpx.Response(429, request=req), body=None)


def _loop_cand(start: Coordinate) -> RouteResponse:
    a = Coordinate(lat=start.lat + 0.011, lng=start.lng)
    b = Coordinate(lat=start.lat + 0.011, lng=start.lng + 0.013)
    return RouteResponse(summary="anchor-loop", total_distance_km=5.0, waypoints=[
        Waypoint(name="출발", coordinate=start, is_pitstop=False),
        Waypoint(name="공원A", coordinate=a, is_pitstop=False),
        Waypoint(name="공원B", coordinate=b, is_pitstop=False),
        Waypoint(name="복귀", coordinate=start, is_pitstop=False)])


def _oneway_cand(start: Coordinate, end: Coordinate) -> RouteResponse:
    mid = Coordinate(lat=(start.lat + end.lat) / 2, lng=(start.lng + end.lng) / 2 + 0.01)
    return RouteResponse(summary="v87-oneway", total_distance_km=5.0, waypoints=[
        Waypoint(name="출발", coordinate=start, is_pitstop=False),
        Waypoint(name="중간", coordinate=mid, is_pitstop=False),
        Waypoint(name="도착", coordinate=end, is_pitstop=False)])


async def _snap_5km(origin=None, destination=None, waypoints=None, **kw):
    pts = [origin, *(waypoints or []), destination]
    return PedestrianRoute(distance_m=5000.0, duration_s=3000.0,
                           path=[p for p in pts if p], provider="tmap")


async def main():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"owg-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    tok = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                     headers={"apikey": settings.supabase_key,
                              "Content-Type": "application/json"},
                     json={"email": f"owg-{TS}@test.com", "password": "test1234"},
                     timeout=30).json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}
    sb = get_supabase_admin()

    orig = (openai_service.generate_route, map_service.get_pedestrian_route,
            anchor_service.collect_anchors, anchor_service.build_anchor_candidates,
            settings.anchor_pool_n)
    anchor_calls = {"n": 0}

    async def boom(**kw):
        raise _mk_429()

    async def collect_counting(*a, **k):
        anchor_calls["n"] += 1
        return ["fake-anchor"]

    def build_loops(start, anchors, target_km, n, **kw):
        return [_loop_cand(start) for _ in range(n)]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        try:
            settings.anchor_pool_n = 2
            anchor_service.collect_anchors = collect_counting
            anchor_service.build_anchor_candidates = build_loops
            map_service.get_pedestrian_route = _snap_5km

            print("[G-1 one-way + 전 롤 429 + 앵커 가용 → 503 정직화]")
            openai_service.generate_route = boom
            resp = await c.post("/api/routes/generate", headers=H,
                                json={"start": START, "end": END,
                                      "target_distance_km": 5.0})
            b = resp.json()
            assert resp.status_code == 503, (resp.status_code, b)
            assert b["error_code"] == "route_generation_unavailable", b
            assert anchor_calls["n"] == 0, "one-way면 앵커 수집 자체가 없어야(게이트)"
            q = sb.table("route_generations").select("id").eq("user_id", _uid).execute().data
            assert q == [], "쿼터 환급"
            ok("503 + 앵커 미편입(collect 0회) + 쿼터 환급 — 502/루프 위장 소멸")

            print("[G-2 loop + 전 롤 429 + 앵커 가용 → 앵커 서빙(기존 불변)]")
            resp = await c.post("/api/routes/generate", headers=H,
                                json={"start": START, "target_distance_km": 5.0})
            b = resp.json()
            assert resp.status_code == 200, (resp.status_code, b)
            assert anchor_calls["n"] == 1, "loop는 앵커 편입 종전대로"
            row = sb.table("routes").select("id,gen_meta,is_one_way") \
                .eq("id", b["route_id"]).execute().data[0]
            assert row["gen_meta"]["engine"] == "anchor" and row["is_one_way"] is False
            ok("loop 앵커 서빙·engine=anchor·one_way false — 게이트 무영향")

            print("[G-3 one-way + v87 정상 → 편도 서빙 불변 + 라벨 모순 소멸]")
            async def gen_oneway(**kw):
                return _oneway_cand(kw["start"], kw["end"])
            openai_service.generate_route = gen_oneway
            resp = await c.post("/api/routes/generate", headers=H,
                                json={"start": START, "end": END,
                                      "target_distance_km": 5.0})
            b = resp.json()
            assert resp.status_code == 200, (resp.status_code, b)
            assert "편도" in b["summary"], b["summary"]
            names = [w["name"] for w in b["waypoints"]]
            assert "복귀" not in names, f"편도 서빙에 복귀 라벨 금지: {names}"
            row = sb.table("routes").select("is_one_way,gen_meta") \
                .eq("id", b["route_id"]).execute().data[0]
            assert row["is_one_way"] is True and row["gen_meta"]["engine"] != "anchor"
            ok(f'편도 제목 ✓ 라벨 {names}(복귀 무) ✓ engine {row["gen_meta"]["engine"]} ✓')
        finally:
            (openai_service.generate_route, map_service.get_pedestrian_route,
             anchor_service.collect_anchors, anchor_service.build_anchor_candidates,
             settings.anchor_pool_n) = orig


def cleanup():
    sb = get_supabase_admin()
    if _uid:
        sb.table("routes").delete().eq("user_id", _uid).execute()
        sb.table("route_generations").delete().eq("user_id", _uid).execute()
        httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
        left = sb.table("routes").select("id").eq("user_id", _uid).execute().data
        assert left == [], left
    print("\n[cleanup] 생성 route·쿼터 행·유저 삭제 — 잔여 0")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
