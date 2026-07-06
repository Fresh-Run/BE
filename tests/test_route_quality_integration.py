"""
Integration test: 코스 생성 품질 (② 소수점 반올림, ③ 한국어 강제)
① 속도(reasoning_effort=none)는 before/after 계측 보고로 대체 — 여기선 미측정.
Run: python tests/test_route_quality_integration.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from unittest.mock import AsyncMock, patch

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys():
    anon = svc = ""
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                svc = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(m): print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")


def _hangul(s: str) -> bool:
    return any("가" <= ch <= "힣" for ch in (s or ""))


def phase_pure():
    from app.services import run_service as rs
    from app.services import route_service as rt
    from app.models.schemas import Coordinate, RouteRequest, RouteResponse, Waypoint, PedestrianRoute

    step("1. ② 결정론 — 통계 거리 1자리")
    rows = [{"distance_km": 5.12, "duration_sec": 1500},
            {"distance_km": 3.37, "duration_sec": 1100}]  # 합 8.49 → 8.5
    agg = rs._aggregate(rows, delta_distance_km=None)
    assert agg.total_distance_km == 8.5, f"1자리 반올림 기대 8.5, got {agg.total_distance_km}"
    assert agg.longest_run_km == 5.1, f"최장 1자리 5.1, got {agg.longest_run_km}"
    assert isinstance(agg.total_duration_sec, int)  # 시간은 정수 초
    ok("total_distance_km 8.49→8.5 ✓ longest 5.12→5.1 ✓ duration 정수초 ✓")

    step("2. ② 결정론 — 코스 생성 거리 1자리·소요시간 정수분 (mock)")
    def mk_route():
        return RouteResponse(summary="테스트 코스", total_distance_km=5.0, waypoints=[
            Waypoint(name="출발", coordinate=Coordinate(lat=37.5445, lng=127.0374), is_pitstop=False),
            Waypoint(name="반환", coordinate=Coordinate(lat=37.55, lng=127.04), is_pitstop=False)])
    # T-map이 5237m / 1583s 반환 → 5.2km, 26분(정수)이어야
    ped = PedestrianRoute(distance_m=5237.0, duration_s=1583.0,
                          path=[Coordinate(lat=37.5445, lng=127.0374)], provider="tmap")
    with patch.object(rt.openai_service, "generate_route", AsyncMock(return_value=mk_route())), \
         patch.object(rt.map_service, "get_pedestrian_route", AsyncMock(return_value=ped)), \
         patch.object(rt.feedback_service, "collect_avoidance_hints", AsyncMock(return_value=[])), \
         patch.object(rt, "_save_route", AsyncMock()):
        out = asyncio.run(rt.create_running_route(
            RouteRequest(start={"lat": 37.5445, "lng": 127.0374}, target_distance_km=5),
            user_id=None))
    assert out.total_distance_km == 5.2, f"거리 5237m→5.2km, got {out.total_distance_km}"
    assert out.estimated_duration_min == 26.0 and out.estimated_duration_min == int(out.estimated_duration_min), \
        f"소요시간 1583s→26분(정수), got {out.estimated_duration_min}"
    ok("거리 5237m→5.2km ✓ 소요시간 1583s→26분 정수 ✓")


def phase_real(c, tok):
    step("3. ③ 실호출 — 비한강 좌표에서 한국어 강제 (인천 아라뱃길)")
    r = c.post(f"{BASE}/routes/generate",
               headers={"Authorization": f"Bearer {tok}"}, timeout=90,
               json={"start": {"lat": 37.5665, "lng": 126.6737}, "target_distance_km": 6})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert _hangul(d["summary"]), f"요약이 한국어가 아님: {d['summary'][:60]}"
    for w in d["waypoints"]:
        assert _hangul(w["name"]), f"경유지명이 한국어가 아님: {w['name']}"
    # 소수점: 응답도 1자리·정수분
    assert round(d["total_distance_km"], 1) == d["total_distance_km"]
    dur = d.get("estimated_duration_min")
    assert dur is None or dur == int(dur)
    ok(f"요약·경유지 전부 한국어 ✓ {d['total_distance_km']}km {dur}분 — {d['summary'][:30]}…")


def run():
    ts = int(time.time())
    uid = None
    with httpx.Client(timeout=30) as c:
        try:
            phase_pure()
            step("공용: 유저")
            e = f"rq-{ts}@t.l"
            r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                       json={"email": e, "password": "TestPass123!", "email_confirm": True})
            uid = r.json()["id"]
            r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
                       headers={"apikey": _ANON, "Content-Type": "application/json"},
                       json={"email": e, "password": "TestPass123!"})
            tok = r.json()["access_token"]
            c.patch(f"{BASE}/me/profile", headers={"Authorization": f"Bearer {tok}"},
                    json={"nickname": f"품질u-{ts%100000}"})
            ok("유저 생성")
            phase_real(c, tok)
            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            if uid:
                c.delete(f"{_SB}/rest/v1/route_generations",
                         headers={**_ADM, "Prefer": "return=minimal"},
                         params={"user_id": f"eq.{uid}"})
                c.delete(f"{_SB}/rest/v1/routes",
                         headers={**_ADM, "Prefer": "return=minimal"},
                         params={"user_id": f"eq.{uid}"})
                c.delete(f"{_SB}/rest/v1/profiles",
                         headers={**_ADM, "Prefer": "return=minimal"},
                         params={"user_id": f"eq.{uid}"})
                c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
            ok("route_generations·routes·profiles·auth 삭제")


if __name__ == "__main__":
    run()
