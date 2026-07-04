"""
Integration test: route likes (POST/DELETE /routes/{id}/like)
Run: python tests/test_likes_integration.py
"""
from __future__ import annotations

import os, sys, time
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

def sb_insert_route(c, uid, summary, is_public):
    r = c.post(f"{_SB}/rest/v1/routes",
               headers={**_ADM, "Prefer":"return=representation"},
               json={"user_id": uid, "summary": summary,
                     "total_distance_km": 5.0, "is_public": is_public, "waypoints": []})
    if r.status_code not in (200,201): fail("insert route", r.text[:200])
    return r.json()[0]["id"]

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def get_route_from_feed(c, tok, route_id, limit=50):
    r = api(c, "GET", "/routes/public", tok, params={"sort":"newest","limit":limit})
    if r.status_code != 200: fail("GET feed", r.text[:200])
    by_id = {item["id"]: item for item in r.json()}
    return by_id.get(route_id)


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"lk-u{i}-{ts}@t.l" for i in range(1,4)]
    uids: list[str] = []
    toks: list[str] = []
    all_routes: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 3명 ───────────────────────────────────────────────
            step("1. 유저 생성 + 로그인")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2, uid3 = uids; tok1, tok2, tok3 = toks
            ok(f"u1={uid1[:8]}… u2={uid2[:8]}… u3={uid3[:8]}…")

            # ── 2. 공개 코스 A, 비공개 코스 B 삽입 ──────────────────────
            step("2. 공개 코스 A + 비공개 코스 B 삽입")
            route_a = sb_insert_route(c, uid1, "좋아요테스트A", True)
            route_b = sb_insert_route(c, uid1, "좋아요테스트B-비공개", False)
            all_routes += [route_a, route_b]
            ok(f"route_a={route_a[:8]}… (공개)  route_b={route_b[:8]}… (비공개)")

            # ── 3. test2·test3 좋아요 → like_count=2 ─────────────────────
            step("3. test2·test3 → 코스 A 좋아요")
            for tok, name in [(tok2,"test2"), (tok3,"test3")]:
                r = api(c, "POST", f"/routes/{route_a}/like", tok)
                assert r.status_code == 204, f"{name} like → 204 이어야 함, got {r.status_code}"
            ok("test2·test3 좋아요 204 ✓")

            item = get_route_from_feed(c, tok1, route_a)
            assert item is not None, "route_a 피드에 없음"
            assert item["like_count"] == 2, f"like_count 2 이어야 함, got {item['like_count']}"
            ok(f"like_count=2 ✓")

            # ── 4. is_liked: test2=True, test1=False ─────────────────────
            step("4. is_liked 확인 (test2=True, test1=False)")
            item2 = get_route_from_feed(c, tok2, route_a)
            item1 = get_route_from_feed(c, tok1, route_a)
            assert item2["is_liked"] is True,  f"test2 is_liked True 이어야 함, got {item2['is_liked']}"
            assert item1["is_liked"] is False, f"test1 is_liked False 이어야 함, got {item1['is_liked']}"
            ok("test2 is_liked=True ✓  test1 is_liked=False ✓")

            # ── 5. test2 더블탭(중복 좋아요) → 204, like_count 여전히 2 ─
            step("5. test2 더블탭 → 204, like_count 유지")
            r = api(c, "POST", f"/routes/{route_a}/like", tok2)
            assert r.status_code == 204, f"더블탭 → 204 이어야 함, got {r.status_code}"
            item = get_route_from_feed(c, tok1, route_a)
            assert item["like_count"] == 2, f"더블탭 후 like_count 2 유지여야 함, got {item['like_count']}"
            ok("더블탭 204 ✓  like_count=2 유지 ✓")

            # ── 6. test2 좋아요 취소 → like_count=1 ─────────────────────
            step("6. test2 좋아요 취소 → like_count=1")
            r = api(c, "DELETE", f"/routes/{route_a}/like", tok2)
            assert r.status_code == 204, f"unlike → 204 이어야 함, got {r.status_code}"
            item = get_route_from_feed(c, tok1, route_a)
            assert item["like_count"] == 1, f"취소 후 like_count 1 이어야 함, got {item['like_count']}"
            assert item["is_liked"] is False or get_route_from_feed(c, tok2, route_a)["is_liked"] is False
            ok("unlike 204 ✓  like_count=1 ✓")

            # ── 7. test2 또 취소(이미 취소됨) → 204 멱등 ─────────────────
            step("7. 이미 취소된 좋아요 재취소 → 204 (멱등)")
            r = api(c, "DELETE", f"/routes/{route_a}/like", tok2)
            assert r.status_code == 204, f"재취소 → 204 이어야 함, got {r.status_code}"
            ok("재취소 204 ✓")

            # ── 8. 비공개 코스 좋아요 → 404 ──────────────────────────────
            step("8. 비공개 코스(B) 좋아요 → 404")
            r = api(c, "POST", f"/routes/{route_b}/like", tok2)
            assert r.status_code == 404, f"비공개 코스 좋아요 → 404 이어야 함, got {r.status_code}"
            ok("비공개 코스 좋아요 → 404 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "route_likes", "route_id", all_routes)
            ok("route_likes 삭제")
            sb_del_in(c, "routes", "id", all_routes)
            ok("routes 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
