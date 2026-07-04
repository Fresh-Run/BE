"""
Integration test: public route copy_count + sort=popular
Inserts test routes directly via Supabase REST (no AI call) for speed.
Run: python tests/test_copy_count_integration.py
"""
from __future__ import annotations

import os
import sys
import time

import httpx

BASE = "http://localhost:8000/api"
_SUPABASE_URL = "https://jlmmqnpddkokyintlawd.supabase.co"


def _load_keys() -> tuple[str, str]:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = service = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                service = line.split("=", 1)[1]
    return anon, service


_ANON, _SVC = _load_keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(msg: str) -> None:   print(f"  ✓ {msg}")
def fail(msg: str, d: str = "") -> None:
    print(f"  ✗ {msg}" + (f": {d}" if d else ""))
    sys.exit(1)
def step(t: str) -> None:   print(f"\n[{t}]")

def sb_create(c: httpx.Client, email: str, pw: str) -> str:
    r = c.post(f"{_SUPABASE_URL}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201): fail("create user", r.text[:200])
    return r.json()["id"]

def sb_login(c: httpx.Client, email: str, pw: str) -> str:
    r = c.post(f"{_SUPABASE_URL}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]

def sb_del_user(c: httpx.Client, uid: str) -> None:
    c.delete(f"{_SUPABASE_URL}/auth/v1/admin/users/{uid}", headers=_ADM)

def sb_del_in(c: httpx.Client, table: str, col: str, vals: list[str]) -> None:
    if not vals: return
    c.delete(f"{_SUPABASE_URL}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({',' .join(vals)})"})

def sb_insert_route(c: httpx.Client, uid: str, summary: str, is_public: bool) -> str:
    """Insert a minimal route row directly, bypassing AI generation."""
    r = c.post(f"{_SUPABASE_URL}/rest/v1/routes",
               headers={**_ADM, "Prefer": "return=representation"},
               json={
                   "user_id": uid,
                   "summary": summary,
                   "total_distance_km": 5.0,
                   "is_public": is_public,
                   "waypoints": [],
               })
    if r.status_code not in (200, 201): fail("insert route", r.text[:200])
    return r.json()[0]["id"]

def sb_del_routes(c: httpx.Client, route_ids: list[str]) -> None:
    sb_del_in(c, "routes", "id", route_ids)

def api(c: httpx.Client, method: str, path: str, tok: str, **kw) -> httpx.Response:
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


def run() -> None:
    ts = int(time.time())
    pw = "TestPass123!"
    emails = [f"cc-u1-{ts}@t.l", f"cc-u2-{ts}@t.l", f"cc-u3-{ts}@t.l"]
    uids: list[str] = []
    toks: list[str] = []
    all_route_ids: list[str] = []  # for cleanup

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 3명 ───────────────────────────────────────────────
            step("1. 유저 생성 + 로그인")
            for email in emails:
                uids.append(sb_create(c, email, pw))
                toks.append(sb_login(c, email, pw))
            uid1, uid2, uid3 = uids
            tok1, tok2, tok3 = toks
            ok(f"uid1={uid1[:8]}… uid2={uid2[:8]}… uid3={uid3[:8]}…")

            # ── 2. test1 공개 코스 2개(A, B) 직접 삽입 ───────────────────
            step("2. 공개 코스 A·B 삽입 (AI 없이 직접)")
            route_a = sb_insert_route(c, uid1, "테스트코스A - 인기있는 코스", is_public=True)
            route_b = sb_insert_route(c, uid1, "테스트코스B - 복사 안 된 코스", is_public=True)
            all_route_ids += [route_a, route_b]
            ok(f"route_a={route_a[:8]}… route_b={route_b[:8]}…")

            # ── 3. test2·test3가 코스 A 복사 ─────────────────────────────
            step("3. test2·test3 → 코스 A 복사")
            r2 = api(c, "POST", f"/routes/{route_a}/copy", tok2)
            if r2.status_code != 200: fail("copy by test2", r2.text[:200])
            copy1_id = r2.json()["id"]
            all_route_ids.append(copy1_id)

            r3 = api(c, "POST", f"/routes/{route_a}/copy", tok3)
            if r3.status_code != 200: fail("copy by test3", r3.text[:200])
            copy2_id = r3.json()["id"]
            all_route_ids.append(copy2_id)
            ok(f"copy1={copy1_id[:8]}… copy2={copy2_id[:8]}…")

            # ── 4. 피드(newest) → A copy_count=2, B copy_count=0 ─────────
            step("4. GET /routes/public?sort=newest → copy_count 확인")
            r = api(c, "GET", "/routes/public", tok1, params={"sort": "newest", "limit": 50})
            if r.status_code != 200: fail("GET public routes", r.text[:200])
            feed = r.json()
            by_id = {item["id"]: item for item in feed}

            assert route_a in by_id, "route_a 피드에 없음"
            assert route_b in by_id, "route_b 피드에 없음"
            ca = by_id[route_a]["copy_count"]
            cb = by_id[route_b]["copy_count"]
            print(f"  route_a copy_count={ca}, route_b copy_count={cb}")
            assert ca == 2, f"route_a copy_count 2 이어야 함, got {ca}"
            assert cb == 0, f"route_b copy_count 0 이어야 함, got {cb}"
            ok("copy_count: A=2 ✓  B=0 ✓")

            # ── 5. sort=popular → A가 B보다 앞에 ─────────────────────────
            step("5. GET /routes/public?sort=popular → A가 B보다 앞")
            r = api(c, "GET", "/routes/public", tok1, params={"sort": "popular", "limit": 50})
            if r.status_code != 200: fail("GET popular", r.text[:200])
            popular = r.json()
            ids_order = [item["id"] for item in popular]
            assert route_a in ids_order, "route_a not in popular feed"
            assert route_b in ids_order, "route_b not in popular feed"
            idx_a = ids_order.index(route_a)
            idx_b = ids_order.index(route_b)
            print(f"  route_a 순위={idx_a}, route_b 순위={idx_b}")
            assert idx_a < idx_b, f"인기순에서 A({idx_a})가 B({idx_b})보다 앞이어야 함"
            assert popular[idx_a]["copy_count"] == 2
            ok("인기순: A(2회) > B(0회) ✓")

            # ── 6. 복사본 하나 삭제 → copy_count 1로 감소 ────────────────
            step("6. copy1 삭제 → route_a copy_count=1 (실시간 반영)")
            sb_del_routes(c, [copy1_id])
            all_route_ids.remove(copy1_id)  # already deleted

            r = api(c, "GET", "/routes/public", tok1, params={"sort": "newest", "limit": 50})
            if r.status_code != 200: fail("GET after delete", r.text[:200])
            feed2 = {item["id"]: item for item in r.json()}
            ca2 = feed2[route_a]["copy_count"]
            print(f"  삭제 후 route_a copy_count={ca2}")
            assert ca2 == 1, f"삭제 후 copy_count 1 이어야 함, got {ca2}"
            ok("copy_count 실시간 반영: A=1 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)

        finally:
            step("Cleanup")
            sb_del_routes(c, all_route_ids)
            ok("routes 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")


if __name__ == "__main__":
    run()
