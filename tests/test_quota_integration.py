"""
Integration test: premium tier + AI generation quota
(GET /me/quota, POST /routes/generate 429, tier self-upgrade block)
Run: python tests/test_quota_integration.py

Note: includes 1-2 REAL OpenAI/map generations (u1 consume path, u2 premium
path). The 429 path is verified cost-free by seeding route_generations rows.
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timezone
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"

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
def warn(m): print(f"  ⚠ {m}")
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

def sb_seed_generations(c, uid, n):
    if n <= 0: return
    r = c.post(f"{_SB}/rest/v1/route_generations",
               headers={**_ADM, "Prefer":"return=minimal"},
               json=[{"user_id": uid} for _ in range(n)])
    if r.status_code not in (200,201): fail("seed generations", r.text[:200])

def sb_set_tier(c, uid, tier):
    r = c.patch(f"{_SB}/rest/v1/profiles",
                headers={**_ADM, "Prefer":"return=minimal"},
                params={"user_id": f"eq.{uid}"}, json={"tier": tier})
    if r.status_code not in (200,204): fail("set tier", r.text[:200])

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def get_quota(c, tok):
    r = api(c, "GET", "/me/quota", tok)
    if r.status_code != 200: fail("GET /me/quota", r.text[:200])
    return r.json()

_GEN_BODY = {"start": {"lat": 37.5445, "lng": 127.0374}, "target_distance_km": 3.0}

def gen(c, tok):
    """POST /routes/generate with a long timeout (real OpenAI+map call)."""
    return api(c, "POST", "/routes/generate", tok, json=_GEN_BODY, timeout=150)


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"qt-u{i}-{ts}@t.l" for i in range(1,3)]
    uids: list[str] = []
    toks: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 2명 + 프로필 ─────────────────────────────────────
            step("1. 유저 생성 (u1=free, u2=premium 예정) + 프로필")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2 = uids; tok1, tok2 = toks
            for i, tok in enumerate(toks, start=1):
                r = api(c, "PATCH", "/me/profile", tok,
                        json={"nickname": f"쿼터u{i}-{ts%100000}"})
                assert r.status_code == 200, r.text[:200]
            ok(f"u1={uid1[:8]}… u2={uid2[:8]}…")

            # ── 2. 초기 쿼터: free 0/3 ───────────────────────────────────
            step("2. u1 초기 쿼터: free, 0/3, reset_at 존재")
            q = get_quota(c, tok1)
            assert q["tier"] == "free"
            ai = q["ai_generation"]
            assert ai["used"] == 0 and ai["limit"] == 3 and ai["remaining"] == 3
            assert ai["unlimited"] is False and ai["reset_at"]
            reset = datetime.fromisoformat(ai["reset_at"])
            assert reset > datetime.now(timezone.utc), "reset_at은 미래 시각이어야 함"
            ok("tier=free ✓ 0/3 ✓ reset_at 미래 ✓")

            # ── 3. tier 자가 승급 차단 ───────────────────────────────────
            step("3. PATCH /me/profile에 tier 끼워넣기 → 무시돼야 함")
            r = api(c, "PATCH", "/me/profile", tok1,
                    json={"nickname": f"쿼터u1-{ts%100000}", "tier": "premium"})
            assert r.status_code == 200, r.text[:200]
            assert get_quota(c, tok1)["tier"] == "free", "tier 자가 승급이 막혀야 함"
            r = api(c, "GET", "/me/profile", tok1)
            assert r.json()["tier"] == "free"
            ok("자가 승급 차단 ✓ /me/profile에 tier 노출 ✓")

            # ── 4. 실제 생성 1회 → used=1 (소모 기록 경로) ───────────────
            step("4. u1 실제 AI 생성 1회 → used 증가 (OpenAI 호출)")
            r = gen(c, tok1)
            if r.status_code == 200:
                used = get_quota(c, tok1)["ai_generation"]["used"]
                assert used == 1, f"생성 후 used 1 이어야 함, got {used}"
                ok("실제 생성 200 ✓ used=1 기록 ✓")
            else:
                warn(f"외부 API 불안정 (status {r.status_code}) — 시딩으로 대체")
                used_real = get_quota(c, tok1)["ai_generation"]["used"]
                assert used_real == 0, "생성 실패 시 쿼터 미소모여야 함"
                ok("생성 실패 시 쿼터 미소모 ✓")

            # ── 5. 잔여분 시딩 후 4번째 → 429 (OpenAI 호출 없음) ─────────
            step("5. used=3 채우고 초과 생성 → 429 + 바디")
            used = get_quota(c, tok1)["ai_generation"]["used"]
            sb_seed_generations(c, uid1, 3 - used)
            q = get_quota(c, tok1)["ai_generation"]
            assert q["used"] == 3 and q["remaining"] == 0
            t0 = time.time()
            r = gen(c, tok1)
            elapsed = time.time() - t0
            assert r.status_code == 429, f"초과 생성 → 429, got {r.status_code}"
            d = r.json()["detail"]
            assert d["error"] == "quota_exceeded" and d["limit"] == 3
            assert d["used"] == 3 and d["remaining"] == 0 and d["reset_at"]
            assert elapsed < 5, f"429는 OpenAI 호출 전 차단이라 즉시여야 함 ({elapsed:.1f}s)"
            ok(f"429 ✓ 바디(limit·used·remaining·reset_at) ✓ 즉시 차단({elapsed:.1f}s) ✓")

            # ── 6. premium 승급 (admin) → unlimited ──────────────────────
            step("6. u2 admin 승급 → 쿼터 unlimited")
            sb_set_tier(c, uid2, "premium")
            sb_seed_generations(c, uid2, 3)   # 3회 이미 썼어도
            q = get_quota(c, tok2)
            assert q["tier"] == "premium"
            ai = q["ai_generation"]
            assert ai["unlimited"] is True and ai["limit"] is None
            assert ai["remaining"] is None and ai["reset_at"] is None
            assert ai["used"] == 3, "used는 참고용으로 집계"
            ok("premium unlimited ✓ (used=3이어도 제한 없음)")

            # ── 7. premium 생성 → 429 아님 ───────────────────────────────
            step("7. u2 생성 시도 → 429가 아니어야 함 (실제 호출)")
            r = gen(c, tok2)
            assert r.status_code != 429, "premium은 쿼터 차단이 없어야 함"
            ok(f"premium 429 없음 ✓ (status {r.status_code})")

            # ── 8. 공개 프로필에 tier 배지 ───────────────────────────────
            step("8. 공개 프로필 tier: u2=premium, u1=free")
            r = api(c, "GET", f"/users/{uid2}/profile", tok1)
            assert r.status_code == 200 and r.json()["tier"] == "premium"
            r = api(c, "GET", f"/users/{uid1}/profile", tok2)
            assert r.json()["tier"] == "free"
            ok("공개 프로필 tier 노출 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "route_generations", "user_id", [u for u in uids if u])
            ok("route_generations 삭제")
            sb_del_in(c, "routes", "user_id", [u for u in uids if u])
            ok("routes(생성분) 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
