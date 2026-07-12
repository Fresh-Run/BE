"""
Integration test: item4 — 서버 검증 상한을 시안 확정값에 맞춤
  크루 max_members ≤100, radius_km ≤20, 챌린지 goal_km ≤100.
  경계값 통과 + 초과 422 + DB 부수효과(초과는 행 미생성).

Run: python tests/test_crew_limits_align_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timezone, timedelta
import httpx

BASE = "http://localhost:8000/api"
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


def ok(m):        print(f"  ✓ {m}")
def step(t):      print(f"\n[{t}]")


def sb_user(c, email):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": "test1234", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]


def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


def crew_count_with_name(c, name):
    r = c.get(f"{_SB}/rest/v1/crews", headers={**_ADM, "Prefer": "count=exact"},
              params={"name": f"eq.{name}", "select": "id", "limit": 1})
    return int(r.headers.get("content-range", "?/0").split("/")[-1])


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. 유저")
        uids["a"] = sb_user(c, f"lim-a-{TS}@test.com")
        tk = sb_login(c, f"lim-a-{TS}@test.com")
        assert api(c, "PATCH", "/me/profile", tk, json={"nickname": f"LIM{TS}"}).status_code == 200
        ok("유저 준비")

        step("1. max_members 경계 100 통과 / 101 → 422")
        n_ok = f"LIM인원OK{TS}"
        r = api(c, "POST", "/crews", tk, json={"name": n_ok, "max_members": 100})
        assert r.status_code == 200, f"100 통과 기대, got {r.status_code}: {r.text[:200]}"
        crew_ok = r.json()["id"]
        n_bad = f"LIM인원BAD{TS}"
        r = api(c, "POST", "/crews", tk, json={"name": n_bad, "max_members": 101})
        assert r.status_code == 422, f"101 → 422 기대, got {r.status_code}"
        assert crew_count_with_name(c, n_bad) == 0, "초과 크루는 행 미생성"
        ok("max_members 100 통과·101 거부·행 미생성")

        step("2. radius_km 경계 20 통과 / 21 → 422 (수정 경로도)")
        r = api(c, "PATCH", f"/crews/{crew_ok}", tk, json={"radius_km": 20})
        assert r.status_code == 200, f"radius 20 통과 기대, got {r.status_code}: {r.text[:200]}"
        assert r.json()["radius_km"] == 20
        r = api(c, "PATCH", f"/crews/{crew_ok}", tk, json={"radius_km": 21})
        assert r.status_code == 422, f"radius 21 → 422 기대, got {r.status_code}"
        # DB는 여전히 20 (거부되어 미반영)
        db = c.get(f"{_SB}/rest/v1/crews", headers=_ADM, params={"id": f"eq.{crew_ok}", "select": "radius_km"}).json()[0]
        assert db["radius_km"] == 20, f"거부되어 radius 20 유지, got {db}"
        ok("radius_km 20 통과·21 거부·DB 미반영")

        step("3. 챌린지 goal_km 경계 100 통과 / 101 → 422")
        now = datetime.now(timezone.utc)
        body = {"title": f"챌{TS}", "starts_at": (now - timedelta(hours=1)).isoformat(),
                "ends_at": (now + timedelta(days=3)).isoformat()}
        r = api(c, "POST", f"/crews/{crew_ok}/challenges", tk, json={**body, "goal_km": 100})
        assert r.status_code in (200, 201), f"goal 100 통과 기대, got {r.status_code}: {r.text[:200]}"
        # goal 101은 Pydantic 검증(le=100)이 핸들러 진입 전 422 — 크루 상태(활성
        # 챌린지 有)와 무관하게 거부되므로 별 크루 불필요. 422=DB write 도달 안 함.
        r = api(c, "POST", f"/crews/{crew_ok}/challenges", tk, json={**body, "goal_km": 101})
        assert r.status_code == 422, f"goal 101 → 422 기대, got {r.status_code}"
        ok("goal_km 100 통과·101 거부(검증층, DB 미도달)")
        api(c, "DELETE", f"/crews/{crew_ok}", tk)

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
