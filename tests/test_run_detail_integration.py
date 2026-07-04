"""
Integration test: run detail (GET /runs/{run_id}, 본인 것만)
Run: python tests/test_run_detail_integration.py
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"
_NOBODY = "00000000-0000-4000-8000-000000000000"

def _keys() -> tuple[str, str]:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):             anon = line.split("=",1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=",1)[1]
    return anon, svc

_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}

def ok(m):   print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")

def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200,201): fail("create user", r.text[:200])
    return r.json()["id"]

def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type":"application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]

def sb_del_user(c, uid): c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)

def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer":"return=minimal"},
             params={col: f"in.({',' .join(vals)})"})

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"rd-u{i}-{ts}@t.l" for i in range(1,3)]
    uids: list[str] = []
    toks: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            step("1. 유저 2명 생성")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2 = uids; tok1, tok2 = toks
            ok(f"u1={uid1[:8]}… u2={uid2[:8]}…")

            step("2. u1 러닝 기록 저장 (POST /runs)")
            r = api(c, "POST", "/runs", tok1,
                    json={"distance_km": 5.2, "duration_sec": 1800,
                          "avg_pace_sec_per_km": 346, "notes": "단건조회 테스트"})
            assert r.status_code in (200, 201), r.text[:200]
            run_id = r.json()["id"]
            ok(f"run={run_id[:8]}…")

            step("3. 본인 단건 조회 → 200 + 필드 일치")
            r = api(c, "GET", f"/runs/{run_id}", tok1)
            assert r.status_code == 200, r.text[:200]
            d = r.json()
            assert d["id"] == run_id and d["user_id"] == uid1
            assert d["distance_km"] == 5.2 and d["duration_sec"] == 1800
            assert d["avg_pace_sec_per_km"] == 346 and d["notes"] == "단건조회 테스트"
            assert d["ran_at"], "ran_at 존재해야 함"
            ok("본인 조회 200 ✓ 필드 일치 ✓")

            step("4. 남의 기록 조회 → 404")
            r = api(c, "GET", f"/runs/{run_id}", tok2)
            assert r.status_code == 404, f"남의 run → 404, got {r.status_code}"
            ok("타인 404 ✓")

            step("5. 없는 id → 404")
            r = api(c, "GET", f"/runs/{_NOBODY}", tok1)
            assert r.status_code == 404, f"없는 run → 404, got {r.status_code}"
            ok("없는 id 404 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "runs", "user_id", [u for u in uids if u])
            ok("runs 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
