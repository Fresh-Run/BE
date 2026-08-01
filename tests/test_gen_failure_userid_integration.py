"""
Integration: gen_failures.meta.user_id 병기 (2026-08-01, additive 관측 전용)

1. 실패 적재 시 user_id 실림(band_cap_zero 경로) + 기존 필드 무영향
2. 미인증(user_id=None) → null 명시(키 존재)
3. 접근 경로 — anon 키 직조회 0행(RLS deny·서비스 전용) 실확인

Run: python tests/test_gen_failure_userid_integration.py
Gemini·T-map 실호출 0(mock). 생성 실패행·임시 유저 종료 시 전삭·잔여 0.
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
_uid: str | None = None
_fail_ids: list[str] = []


def ok(m):
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


async def main():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"gfu-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    sb = get_supabase_admin()
    t_start = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(TS - 5))

    orig = (openai_service.generate_route, map_service.get_pedestrian_route,
            map_service.search_places, map_service.count_apartment_signal,
            settings.anchor_pool_n)

    async def gen_mock(**kw):
        return _mk_candidate(kw["start"])

    async def snap_short(origin, destination, waypoints=None):
        # 전 후보 언더슛(2.0km — 밴드 4.9~5.5 밖) + 재추첨도 동일 → band_cap_zero
        return PedestrianRoute(distance_m=2000, duration_s=1600, path=clean_path(),
                               provider="tmap", road_segments=[(21, "mock로", 2000)])

    async def parks(*a, **k):
        return []

    async def apt(*a, **k):
        return (0, 0)

    openai_service.generate_route = gen_mock
    map_service.get_pedestrian_route = snap_short
    map_service.search_places = parks
    map_service.count_apartment_signal = apt
    settings.anchor_pool_n = 0
    req = RouteRequest(start=KoreaCoordinate(lat=START.lat, lng=START.lng),
                       target_distance_km=5.0)

    def fresh_fails():
        rows = sb.table("gen_failures").select("id,meta") \
            .gte("created_at", t_start).execute().data
        return [x for x in rows if (x["meta"] or {}).get("grid_lat") == round(START.lat, 2)]

    try:
        print("[1. 인증 실패 적재 — user_id 실림 + 기존 필드 무영향]")
        try:
            await route_service.create_running_route(req, user_id=_uid)
            raise AssertionError("전 후보 언더슛인데 서빙되면 안 됨")
        except route_service.RouteGenerationFailed:
            pass
        rows = fresh_fails()
        assert rows, "실패행 미적재"
        m = rows[-1]["meta"]
        _fail_ids.extend(x["id"] for x in rows)
        assert m.get("user_id") == _uid, m.get("user_id")
        for k in ("fail", "grid_lat", "grid_lng", "target_km", "snaps",
                  "one_way", "initial_ratio", "elapsed_s"):
            assert k in m, f"기존 필드 소실: {k}"
        assert m["fail"] == "band_cap_zero"
        ok(f"user_id 병기 ✓ 기존 8필드 무영향 ✓ fail={m['fail']}")

        print("\n[2. 미인증 — user_id null 명시]")
        try:
            await route_service.create_running_route(req, user_id=None)
            raise AssertionError("서빙되면 안 됨")
        except route_service.RouteGenerationFailed:
            pass
        rows = fresh_fails()
        new = [x for x in rows if x["id"] not in _fail_ids]
        _fail_ids.extend(x["id"] for x in new)
        m = new[-1]["meta"]
        assert "user_id" in m and m["user_id"] is None, m.get("user_id")
        ok("미인증 → user_id 키 존재 + null 명시")

        print("\n[3. 접근 경로 — anon 0행(서비스 전용)]")
        anon = settings.supabase_key
        r = httpx.get(f"{_SB}/rest/v1/gen_failures",
                      headers={"apikey": anon, "Authorization": f"Bearer {anon}"},
                      params={"select": "id", "limit": 3}, timeout=30)
        assert r.status_code == 200 and r.json() == [], (r.status_code, r.text[:80])
        svc_n = len(sb.table("gen_failures").select("id").limit(3).execute().data)
        assert svc_n > 0, "빈 테이블 위양성 방지 — 서비스 키는 행이 보여야"
        ok("anon 0행 · 서비스 키 조회 가능 — RLS deny 확정(클라 비노출)")
    finally:
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.count_apartment_signal,
         settings.anchor_pool_n) = orig


def cleanup():
    sb = get_supabase_admin()
    if _fail_ids:
        sb.table("gen_failures").delete().in_("id", _fail_ids).execute()
        left = sb.table("gen_failures").select("id").in_("id", _fail_ids).execute().data
        assert left == [], left
    if _uid:
        httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    print(f"\n[cleanup] gen_failures {len(_fail_ids)}건·임시 유저 삭제·잔여 0")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
