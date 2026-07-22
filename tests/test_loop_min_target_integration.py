"""
Integration test: 순환 최소거리 사전 게이트 (small-ask 후속, 2026-07-22)

루프(end 없음) target < 2.0km이면 생성 진입 전 422 loop_target_too_short +
min_target_km 힌트(one_way_end_too_far 미러). Gemini 0콜·쿼터 미소모.

케이스:
 1. 1.5km 루프 → 422 loop_target_too_short + min_target_km=2.0
 2. 1.9km 루프(경계 직전) → 422
 3. 2.0km 루프(경계) → 게이트 통과 → 200 (mock)
 4. 5.0km 루프 → 200 회귀
 5. one-way 짧은 target → loop 게이트 미간섭(loop_target_too_short 아님)

Run: python tests/test_loop_min_target_integration.py  (mock 8001 자동 기동)
"""
from __future__ import annotations

import os, subprocess, sys, time
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
B8001 = "http://localhost:8001"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys():
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):              anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}
TS = int(time.time())


def ok(m):  print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")


def sb_user(c, e):
    return c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                  json={"email": e, "password": "test1234", "email_confirm": True}).json()["id"]


def login(c, e):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": e, "password": "test1234"}).json()["access_token"]


def gen(c, tok, target, end=None):
    body = {"start": {"lat": 37.5445, "lng": 127.0374}, "target_distance_km": target}
    if end: body["end"] = end
    return c.post(f"{B8001}/api/routes/generate", headers={"Authorization": f"Bearer {tok}"}, json=body)


def scenario(c, seq, **extra):
    assert c.post(f"{B8001}/__mock/scenario", json={"seq": seq, **extra}).status_code == 200


def run_tests():
    c = httpx.Client(timeout=60)
    uid = None
    proc = None
    try:
        step("0. premium 유저 + mock 8001")
        uid = sb_user(c, f"loop-{TS}@test.com")
        tok = login(c, f"loop-{TS}@test.com")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.mock_route_app:app", "--port", "8001", "--log-level", "warning"],
            cwd=os.path.join(os.path.dirname(__file__), ".."))
        for _ in range(40):
            try:
                if c.get(f"{B8001}/health").status_code == 200: break
            except Exception: pass
            time.sleep(0.5)
        else:
            fail("mock 기동 실패")
        c.request("PATCH", f"{B8001}/api/me/profile", headers={"Authorization": f"Bearer {tok}"}, json={"nickname": f"LOOP{TS}"})
        c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{uid}", headers=_ADM, json={"tier": "premium"})
        ok("premium 유저 + mock up")

        step("1. 1.5km 루프 → 422 loop_target_too_short + min 힌트")
        r = gen(c, tok, 1.5)
        assert r.status_code == 422, f"1.5 루프 422, got {r.status_code}: {r.text[:120]}"
        d = r.json()["detail"]
        assert d["error"] == "loop_target_too_short" and d["min_target_km"] == 2.0, d
        assert "2.0km" in d["message"], d["message"]
        # Gemini 0콜 확인(게이트가 생성 전 차단)
        assert c.get(f"{B8001}/__mock/stats").json()["gemini_calls"] == 0, "게이트는 Gemini 0콜"
        ok("1.5 루프 → 422 loop_target_too_short · min_target_km=2.0 · Gemini 0콜")

        step("2. 1.9km(경계 직전) → 422 / 2.0km(경계) → 통과")
        assert gen(c, tok, 1.9).json()["detail"]["error"] == "loop_target_too_short", "1.9 게이트"
        scenario(c, [{"snap_km": 2.0}], pool_size=3)  # 2.0 band [1.7,2.5] hit
        r = gen(c, tok, 2.0)
        assert r.status_code == 200, f"2.0 경계는 통과(422 아님), got {r.status_code}: {r.text[:120]}"
        ok("1.9 → 422 · 2.0 경계 → 게이트 통과 200")

        step("3. 5.0km 루프 → 200 (회귀)")
        scenario(c, [{"snap_km": 5.0}], pool_size=3)
        assert gen(c, tok, 5.0).status_code == 200, "정상 5.0 무영향"
        ok("5.0 루프 정상 200")

        step("4. one-way 짧은 target → loop 게이트 미간섭")
        # end 근접(직선 ~0.9km ≤ 1.5×0.8=1.2) → one-way 게이트도 통과 → loop 게이트 무관
        scenario(c, [{"snap_km": 1.5}], pool_size=3)
        r = gen(c, tok, 1.5, end={"lat": 37.5445, "lng": 127.0374 + 0.010})
        assert r.status_code != 422 or r.json()["detail"]["error"] != "loop_target_too_short", \
            f"one-way는 loop 게이트에 안 걸려야, got {r.text[:120]}"
        ok(f"one-way target 1.5(end 근접) → loop_target_too_short 아님 (status {r.status_code})")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        if proc: proc.terminate()
        if uid:
            c.delete(f"{_SB}/rest/v1/routes?user_id=eq.{uid}", headers=_ADM)
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
