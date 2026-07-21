"""
Integration test: T-map 쿼터 소진 정직화 (2026-07-21 오너 승격, 백로그 c9855a0)

배경: 2026-07-21 v2.7 E2E가 실증 — T-map 429(QUOTA_EXCEEDED) 전패 시 nopath
폴백이 **폴리라인 없는 가짜 코스를 200으로 서빙**했다("앱은 거짓말하지 않는다"
위반). 수정: 스냅 실패의 지배 원인이 429면 nopath 폴백 금지 → 503
route_generation_unavailable. 진짜 no-path(지오 문제)만 기존 폴백 유지(보수적).

케이스(전부 mock — T-map 실호출 0):
 R. 회귀 — 정상 스냅 → 200 hit (무회귀 확인)
 1. 429 전패 → 503 route_generation_unavailable (nopath 폴백 금지)
 2. 부분 429 + 정상 스냅 1 → 200 hit (쿼터 비지배 → 정상 선택), gen_meta.snap_errors
 3. 진짜 no-path 지배 → 200 nopath 폴백 유지 (503 아님)
 4. 애매(429 1 + no-path 2, 과반 미달) → 보수적으로 기존 폴백(503 아님)

Run: python tests/test_quota_honesty_integration.py   (mock 8001 자동 기동)
"""
from __future__ import annotations

import os, subprocess, sys, time
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

B8001 = "http://localhost:8001"      # mock app (app.main + 패치)
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
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


def ok(m):         print(f"  ✓ {m}")
def fail(m, d=""):  print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):       print(f"\n[{t}]")


def sb_user(c, email):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": "test1234", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]


def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def gen(c, tok, target=5.0):
    return c.post(f"{B8001}/api/routes/generate",
                  headers={"Authorization": f"Bearer {tok}"},
                  json={"start": {"lat": 37.5445, "lng": 127.0374}, "target_distance_km": target})


def scenario(c, seq, **extra):
    assert c.post(f"{B8001}/__mock/scenario", json={"seq": seq, **extra}).status_code == 200


def stats(c):
    return c.get(f"{B8001}/__mock/stats").json()


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    proc = None
    try:
        step("0. premium 유저 + mock 8001")
        uids["u"] = sb_user(c, f"qh-u-{TS}@test.com")
        tok = sb_login(c, f"qh-u-{TS}@test.com")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.mock_route_app:app", "--port", "8001",
             "--log-level", "warning"],
            cwd=os.path.join(os.path.dirname(__file__), ".."))
        for _ in range(40):
            try:
                if c.get(f"{B8001}/health").status_code == 200: break
            except Exception: pass
            time.sleep(0.5)
        else:
            fail("mock 서버 기동 실패")
        assert c.request("PATCH", f"{B8001}/api/me/profile", headers={"Authorization": f"Bearer {tok}"},
                         json={"nickname": f"QH{TS}"}).status_code == 200
        c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{uids['u']}", headers=_ADM, json={"tier": "premium"})
        ok("premium 유저 + mock 8001 up")

        step("R. 회귀 — 정상 스냅 → 200 hit (무회귀)")
        scenario(c, [{"snap_km": 5.0}], pool_size=3)
        r = gen(c, tok)
        assert r.status_code == 200 and r.json()["total_distance_km"] == 5.0, r.text[:150]
        gm = stats(c)["last_gen_meta"]
        assert gm["verdict"] == "hit" and gm["snap_errors"] == {"quota": 0, "legnotroutable": 0, "other": 0}, gm
        ok("정상 200 hit · snap_errors 전 0 (무회귀)")

        step("1. 429 전패 → 503 route_generation_unavailable (nopath 폴백 금지)")
        scenario(c, [{"quota": True}], pool_size=3)  # 3 후보 전부 429
        r = gen(c, tok)
        assert r.status_code == 503, f"429 전패 → 503, got {r.status_code}: {r.text[:150]}"
        assert r.json()["detail"]["error"] == "route_generation_unavailable", r.json()
        assert "잠시 후" in r.json()["detail"]["message"], r.json()
        ok("429 전패 → 503 route_generation_unavailable (가짜 nopath 200 서빙 안 함)")

        step("2. 부분 429 + 정상 스냅 1 → 200 hit (쿼터 비지배 → 정상 선택)")
        scenario(c, [{"snap_km": 5.0}, {"quota": True}, {"quota": True}], pool_size=3)
        r = gen(c, tok)
        assert r.status_code == 200 and r.json()["total_distance_km"] == 5.0, r.text[:150]
        gm = stats(c)["last_gen_meta"]
        assert gm["verdict"] == "hit" and gm["snapped_count"] == 1, gm
        assert gm["snap_errors"] == {"quota": 2, "legnotroutable": 0, "other": 0}, \
            f"쿼터 2건 계측 남되 정상 서빙, got {gm['snap_errors']}"
        ok("정상 스냅 1개 있으면 429 2건 있어도 200 hit · snap_errors.quota=2 기록")

        step("3. 진짜 no-path 지배 → 200 nopath 폴백 유지 (503 아님)")
        scenario(c, [{"no_path": True}], pool_size=3)  # 전부 지오/장애(비쿼터)
        r = gen(c, tok)
        assert r.status_code == 200, f"진짜 no-path는 기존 폴백 유지(200), got {r.status_code}"
        gm = stats(c)["last_gen_meta"]
        assert gm["verdict"] == "nopath" and gm["snap_errors"]["quota"] == 0, gm
        assert gm["snap_errors"]["other"] == 3, f"other 3 기록, got {gm['snap_errors']}"
        ok("no-path 지배 → nopath 폴백 200 유지(쿼터 아님) · verdict=nopath")

        step("4. 애매(429 1 + no-path 2, 과반 미달) → 보수적으로 기존 폴백(503 아님)")
        scenario(c, [{"quota": True}, {"no_path": True}, {"no_path": True}], pool_size=3)
        r = gen(c, tok)
        assert r.status_code == 200, f"쿼터 과반 미달(1/3) → 기존 동작(200), got {r.status_code}: {r.text[:150]}"
        gm = stats(c)["last_gen_meta"]
        assert gm["verdict"] == "nopath" and gm["snap_errors"]["quota"] == 1, gm
        ok("429 1 + no-path 2 → 쿼터 비지배(1>2 거짓) → 기존 nopath 폴백(보수적)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        if proc: proc.terminate()
        c.delete(f"{_SB}/rest/v1/routes?user_id=eq.{uids.get('u','')}", headers=_ADM)
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (mock 서버 종료·코스·유저 삭제)")


if __name__ == "__main__":
    run_tests()
