"""
Integration test: 동적 탐색 반경 (코스 생성 자동 확장)
1) 결정론 8케이스 — generate_route/get_pedestrian_route를 mock.patch로 패치해
   재시도 루프를 in-process로 검증 (Gemini/T-map 호출 없음)
2) 실호출 1회 (본 서버 8000) — 정상 생성 + search_radius_km/quota 확인
Run: python tests/test_dynamic_radius_integration.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
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


def ok(m):
    print(f"  ✓ {m}")


def fail(m, d=""):
    print(f"  ✗ {m}" + (f": {d}" if d else ""))
    sys.exit(1)


def step(t):
    print(f"\n[{t}]")


def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201):
        fail("create user", r.text[:200])
    return r.json()["id"]


def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200:
        fail("login", r.text[:200])
    return r.json()["access_token"]


def sb_del_user(c, uid):
    c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)


def sb_del_in(c, table, col, vals):
    if not vals:
        return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})


# ═══ Phase 1: 결정론 (mock.patch, in-process) ═══════════════════════════════════

def phase1():
    from openai import APIError as OpenAIAPIError

    from app.models.schemas import (
        Coordinate,
        PedestrianRoute,
        RouteRequest,
        RouteResponse,
        Waypoint,
    )
    from app.services import route_service as rs
    from app.services.openai_service import _build_prompt

    START = Coordinate(lat=37.5445, lng=127.0374)
    REQ5 = RouteRequest(start={"lat": 37.5445, "lng": 127.0374}, target_distance_km=5)

    def mk_route(dist=5.0):
        return RouteResponse(summary="테스트 코스", total_distance_km=dist, waypoints=[
            Waypoint(name="s", coordinate=Coordinate(lat=37.5445, lng=127.0374), is_pitstop=False),
            Waypoint(name="m", coordinate=Coordinate(lat=37.55, lng=127.04), is_pitstop=False),
            Waypoint(name="e", coordinate=Coordinate(lat=37.545, lng=127.038), is_pitstop=False),
        ])

    def ped(km):
        return PedestrianRoute(distance_m=km * 1000, duration_s=km * 360, path=[START],
                               provider="tmap")

    class FakeAPIError(OpenAIAPIError):
        def __init__(self):  # noqa: super().__init__는 request 객체를 요구 — 우회
            Exception.__init__(self, "boom")

    def run_case(gen_side_effects, ped_side_effects, req=REQ5):
        """루프를 mock으로 실행 — (결과 route, generate mock, pedestrian mock)."""
        gen = AsyncMock(side_effect=gen_side_effects)
        pedm = AsyncMock(side_effect=ped_side_effects)
        with ExitStack() as st:
            st.enter_context(patch.object(rs.openai_service, "generate_route", gen))
            st.enter_context(patch.object(rs.map_service, "get_pedestrian_route", pedm))
            st.enter_context(patch.object(
                rs.feedback_service, "collect_avoidance_hints",
                AsyncMock(return_value=["사람많음"])))
            st.enter_context(patch.object(rs, "_save_route", AsyncMock()))
            route = asyncio.run(rs.create_running_route(req, user_id=None))
        return route, gen, pedm

    step("1-1. _radius_schedule 순수 함수")
    assert rs._radius_schedule(3) == [1.0, 2.0, 3.5, 8.0]
    assert rs._radius_schedule(5) == [1.2, 2.2, 3.7, 8.0]
    assert rs._radius_schedule(10) == [2.5, 3.5, 5.0, 8.0]
    assert rs._radius_schedule(20) == [5.0, 6.0, 7.5, 8.0]
    assert rs._radius_schedule(32) == [8.0], "r0가 상한이면 1시도만"
    ok("목표 비례 r0·점증·cap 8·dedupe ✓")

    step("1-2. 프롬프트에 반경 수치 주입")
    p = _build_prompt(5, START, None, None, None, radius_km=2.2)
    assert "within 2.2 km (straight-line)" in p and "near the start" not in p
    p = _build_prompt(5, START, None, None, None)  # radius 없으면 기존 문구
    assert "near the start" in p
    ok("radius 문구 교체 ✓ 레거시 문구 보존 ✓")

    step("1-3. 1시도 OK — 확장 없음")
    route, gen, _ = run_case([mk_route()], [ped(4.8)])  # 4.8 >= 3.0 OK
    assert gen.call_count == 1
    assert gen.call_args_list[0].kwargs["radius_km"] == 1.2
    assert route.search_radius_km == 1.2 and route.radius_expanded is False
    assert route.total_distance_km == 4.8
    ok("Gemini 1회 (radius 1.2) ✓ radius_expanded=False ✓")

    step("1-4. SHORT → 확장 → 2시도 OK")
    route, gen, _ = run_case([mk_route(), mk_route()], [ped(1.5), ped(5.2)])
    assert gen.call_count == 2
    radii = [c.kwargs["radius_km"] for c in gen.call_args_list]
    assert radii == [1.2, 2.2], radii
    assert route.search_radius_km == 2.2 and route.radius_expanded is True
    assert route.total_distance_km == 5.2
    ok("실측 1.5km(<3.0) → radius 2.2 재시도 → 채택 ✓")

    step("1-5. NO_PATH → 확장 → OK")
    route, gen, _ = run_case(
        [mk_route(), mk_route()],
        [RuntimeError("tmap down"), ped(5.0)])
    assert gen.call_count == 2
    assert route.search_radius_km == 2.2 and route.polyline is not None
    ok("경로 연결 실패 → 확장 → 성공 ✓")

    step("1-6. 전 시도 SHORT → |실측-목표| 최소 후보 반환")
    route, gen, _ = run_case(
        [mk_route() for _ in range(4)],  # 시도마다 독립 인스턴스 (같은 객체면 서로 덮어씀)
        [ped(1.0), ped(1.8), ped(2.5), ped(2.0)])
    assert gen.call_count == 4
    assert route.total_distance_km == 2.5, "목표 5km에 가장 가까운 후보(2.5)여야 함"
    assert route.search_radius_km == 3.7 and route.radius_expanded is True
    ok("4시도 소진 → best 후보(2.5km, radius 3.7) 반환 ✓")

    step("1-7. Gemini APIError — 첫 시도면 raise, 후보 있으면 후보로 마무리")
    try:
        run_case([FakeAPIError()], [])
        fail("첫 시도 APIError는 예외로 전파돼야 함")
    except OpenAIAPIError:
        pass
    route, gen, _ = run_case([mk_route(), FakeAPIError()], [ped(1.5)])
    assert gen.call_count == 2
    assert route.total_distance_km == 1.5, "SHORT 후보로 마무리해야 함"
    ok("1시도 APIError → 502 경로 ✓ 2시도 APIError → 기존 후보 반환 ✓")

    step("1-8. 파싱 실패(ValueError) → 다음 반경 진행 + 개인화 불변 전달")
    route, gen, _ = run_case(
        [ValueError("no tool call"), mk_route()], [ped(5.0)])
    assert gen.call_count == 2
    assert route.search_radius_km == 2.2 and route.radius_expanded is True
    # 매 시도 avoid_tags·prefs 동일 (루프 밖 1회 계산)
    kw0, kw1 = (c.kwargs for c in gen.call_args_list)
    assert kw0["avoid_tags"] == kw1["avoid_tags"] == ["사람많음"]
    assert kw0["prefs"] == kw1["prefs"] and kw0["prefs"] is not None
    assert kw0["target_distance_km"] == kw1["target_distance_km"] == 5
    ok("파싱 실패 흡수 ✓ avoid_tags/prefs/target 매 시도 동일 ✓")

    step("1-9. 전 시도 유효 응답 없음 → RouteGenerationFailed")
    try:
        run_case([ValueError("bad")] * 4, [])
        fail("후보가 없으면 RouteGenerationFailed여야 함")
    except rs.RouteGenerationFailed:
        ok("RouteGenerationFailed ✓ (API 레이어에서 구조화 502)")


# ═══ Phase 2: 실호출 1회 (본 서버 8000) ══════════════════════════════════════════

def phase2(c, tok):
    def api(method, path, **kw):
        return c.request(method, f"{BASE}{path}",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=120, **kw)

    step("2-1. 실호출: 정상 생성 → 새 필드 + 기존 필드 회귀")
    r = api("POST", "/routes/generate",
            json={"start": {"lat": 37.5445, "lng": 127.0374}, "target_distance_km": 5})
    assert r.status_code == 200, r.text[:400]
    d = r.json()
    assert d["summary"] and len(d["waypoints"]) >= 2 and d["total_distance_km"] > 0
    assert d["search_radius_km"] in (1.2, 2.2, 3.7, 8.0), d["search_radius_km"]
    assert isinstance(d["radius_expanded"], bool)
    ok(f"200 ✓ {d['total_distance_km']}km, radius {d['search_radius_km']}km "
       f"(expanded={d['radius_expanded']})")

    step("2-2. 쿼터: 재시도와 무관하게 요청당 1 차감")
    r = api("GET", "/me/quota")
    assert r.status_code == 200
    q = r.json()["ai_generation"]
    assert q["used"] == 1, f"요청 1번 = 차감 1이어야 함, got {q['used']}"
    ok("used=1 ✓")


def run():
    ts = int(time.time())
    pw = "TestPass123!"
    email = f"dr-u1-{ts}@t.l"
    uid = None
    with httpx.Client(timeout=30) as c:
        try:
            phase1()

            step("공용: 테스트 유저 생성")
            uid = sb_user(c, email, pw)
            tok = sb_login(c, email, pw)
            r = c.patch(f"{BASE}/me/profile",
                        headers={"Authorization": f"Bearer {tok}"},
                        json={"nickname": f"반경u1-{ts % 100000}"})
            assert r.status_code == 200, r.text[:200]
            ok(f"u1={uid[:8]}…")

            phase2(c, tok)

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            if uid:
                sb_del_in(c, "route_generations", "user_id", [uid])
                sb_del_in(c, "routes", "user_id", [uid])
                sb_del_in(c, "profiles", "user_id", [uid])
                sb_del_user(c, uid)
            ok("routes·quota·profiles·auth user 삭제")


if __name__ == "__main__":
    run()
