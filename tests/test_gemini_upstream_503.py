"""
Integration: Gemini 업스트림 에러 503 세분 (2026-07-30 오너 승인)

전 롤 429/오버로드 → 503 route_generation_unavailable + 쿼터 환급 /
혼합 실패 → 기존 502 유지 / 기존 에러 계약 회귀. in-process ASGI + 실 DB.

Run: python tests/test_gemini_upstream_503.py  (Gemini·T-map 실콜 0 — 전부 mock)
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
from app.services import map_service, openai_service  # noqa: E402

TS = int(time.time())
_SB = settings.supabase_url
_uid: str | None = None


def ok(m):
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _mk_exc(cls):
    req = httpx.Request("POST", "https://gemini.test/v1")
    resp = httpx.Response(429 if cls is openai.RateLimitError else 500, request=req)
    return cls("upstream(test)", response=resp, body=None)


async def main():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"g503-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    tok = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                     headers={"apikey": settings.supabase_key, "Content-Type": "application/json"},
                     json={"email": f"g503-{TS}@test.com", "password": "test1234"},
                     timeout=30).json()["access_token"]
    H = {"Authorization": f"Bearer {tok}"}
    sb = get_supabase_admin()
    body = {"start": {"lat": 37.60, "lng": 127.20}, "target_distance_km": 5.0}
    orig = openai_service.generate_route

    def quota_rows():
        return len(sb.table("route_generations").select("id").eq("user_id", _uid).execute().data)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        for name, cls in (("RateLimitError", openai.RateLimitError),
                          ("InternalServerError", openai.InternalServerError)):
            print(f"[전 롤 {name} → 503]")

            async def boom(**kw):
                raise _mk_exc(cls)

            openai_service.generate_route = boom
            try:
                resp = await c.post("/api/routes/generate", headers=H, json=body)
            finally:
                openai_service.generate_route = orig
            b = resp.json()
            assert resp.status_code == 503, (resp.status_code, b)
            assert b["detail"]["error"] == "route_generation_unavailable" == b["error_code"], b
            assert "혼잡" in b["detail"]["message"]
            assert quota_rows() == 0, "쿼터 환급(예약 해제) 보장"
            ok(f"503 + route_generation_unavailable + 쿼터 잔여 0")

        print("[혼합 실패(429 일부 + 기타 일부) → 기존 502 유지]")
        calls = {"n": 0}

        async def mixed(**kw):
            calls["n"] += 1
            if calls["n"] % 2:
                raise _mk_exc(openai.RateLimitError)
            raise ValueError("parse-fail(test)")

        openai_service.generate_route = mixed
        try:
            resp = await c.post("/api/routes/generate", headers=H, json=body)
        finally:
            openai_service.generate_route = orig
        b = resp.json()
        assert resp.status_code == 502 and b["error_code"] == "route_generation_failed", b
        assert quota_rows() == 0
        ok("혼합 → 502 route_generation_failed(원인 단정 불가 — 지배 원칙) + 환급")

        print("[회귀 — 422·T-map 쿼터 503·언더슈트 502]")
        r422 = await c.post("/api/routes/generate", headers=H,
                            json={"start": {"lat": 37.60, "lng": 127.20}, "target_distance_km": 1.0})
        assert r422.status_code == 422 and r422.json()["error_code"] == "loop_target_too_short"

        from app.models.schemas import Coordinate, PedestrianRoute, RouteResponse, Waypoint

        def _cand(start):
            a = Coordinate(lat=start.lat + 0.011, lng=start.lng)
            bpt = Coordinate(lat=start.lat + 0.011, lng=start.lng + 0.013)
            return RouteResponse(summary="m", total_distance_km=5.0, waypoints=[
                Waypoint(name="출발", coordinate=start, is_pitstop=False),
                Waypoint(name="1", coordinate=a, is_pitstop=False),
                Waypoint(name="2", coordinate=bpt, is_pitstop=False),
                Waypoint(name="복귀", coordinate=start, is_pitstop=False)])

        async def gen_ok(**kw):
            return _cand(kw["start"])

        async def snap_quota(*a, **k):
            raise map_service.TmapQuotaExceeded()

        orig_snap = map_service.get_pedestrian_route
        openai_service.generate_route = gen_ok
        map_service.get_pedestrian_route = snap_quota
        try:
            rq = await c.post("/api/routes/generate", headers=H, json=body)
        finally:
            openai_service.generate_route = orig
            map_service.get_pedestrian_route = orig_snap
        assert rq.status_code == 503 and rq.json()["detail"]["error"] == "route_generation_unavailable"

        async def snap_under(origin, destination, waypoints=None):
            pts = [Coordinate(lat=37.60 + 0.0001 * i, lng=127.20) for i in range(30)]
            return PedestrianRoute(distance_m=2000, duration_s=1500, path=pts,
                                   provider="tmap", road_segments=[])

        openai_service.generate_route = gen_ok
        map_service.get_pedestrian_route = snap_under
        try:
            ru = await c.post("/api/routes/generate", headers=H, json=body)
        finally:
            openai_service.generate_route = orig
            map_service.get_pedestrian_route = orig_snap
        assert ru.status_code == 502 and ru.json()["error_code"] == "route_generation_failed"
        assert quota_rows() == 0
        ok("422 계약 · T-map 쿼터 503 · 언더슈트 502 전부 불변 + 환급")


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    for t, col in (("route_generations", "user_id"), ("routes", "user_id"), ("profiles", "user_id")):
        sb.table(t).delete().eq(col, _uid).execute()
    fails = sb.table("gen_failures").select("id,meta") \
        .gte("created_at", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(TS - 5))).execute().data
    kill = [f["id"] for f in fails
            if (f["meta"] or {}).get("grid_lat") == 37.6 and (f["meta"] or {}).get("grid_lng") == 127.2]
    if kill:
        sb.table("gen_failures").delete().in_("id", kill).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    print(f"\n[cleanup] 임시 유저·gen_failures {len(kill)}건 정리")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
