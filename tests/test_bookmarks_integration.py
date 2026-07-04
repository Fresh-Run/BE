"""
Integration test: route bookmarks
(POST/DELETE /routes/{id}/bookmark, GET /routes/bookmarked)
Run: python tests/test_bookmarks_integration.py
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

def sb_set_public(c, route_id, is_public):
    r = c.patch(f"{_SB}/rest/v1/routes",
                headers={**_ADM, "Prefer":"return=minimal"},
                params={"id": f"eq.{route_id}"}, json={"is_public": is_public})
    if r.status_code not in (200,204): fail("set is_public", r.text[:200])

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def get_bookmarked(c, tok, **params):
    r = api(c, "GET", "/routes/bookmarked", tok, params=params)
    if r.status_code != 200: fail("GET /routes/bookmarked", r.text[:200])
    return r.json()


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"bm-u{i}-{ts}@t.l" for i in range(1,3)]
    uids: list[str] = []
    toks: list[str] = []
    all_routes: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            step("1. 유저 2명 + u2 프로필")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2 = uids; tok1, tok2 = toks
            r = api(c, "PATCH", "/me/profile", tok2,
                    json={"nickname": f"북마크u2-{ts%100000}"})
            assert r.status_code == 200
            ok(f"u1={uid1[:8]}… u2={uid2[:8]}…")

            step("2. u2 코스: 공개A·비공개B·공개C")
            route_a = sb_insert_route(c, uid2, "북마크테스트A", True)
            route_b = sb_insert_route(c, uid2, "북마크테스트B-비공개", False)
            route_c = sb_insert_route(c, uid2, "북마크테스트C", True)
            all_routes += [route_a, route_b, route_c]
            ok("A·B·C 삽입")

            step("3. 북마크: A 저장 + 더블탭 멱등, 비공개 B → 404")
            r = api(c, "POST", f"/routes/{route_a}/bookmark", tok1)
            assert r.status_code == 204, f"bookmark → 204, got {r.status_code}"
            r = api(c, "POST", f"/routes/{route_a}/bookmark", tok1)
            assert r.status_code == 204, f"더블탭 → 204 (멱등), got {r.status_code}"
            r = api(c, "POST", f"/routes/{route_b}/bookmark", tok1)
            assert r.status_code == 404, f"비공개 북마크 → 404, got {r.status_code}"
            ok("저장 204 ✓ 멱등 ✓ 비공개 404 ✓")

            step("4. C도 저장 → 목록 [C, A] 최신 저장순 + enrich 필드")
            r = api(c, "POST", f"/routes/{route_c}/bookmark", tok1)
            assert r.status_code == 204
            items = get_bookmarked(c, tok1)
            assert [i["id"] for i in items] == [route_c, route_a], \
                f"[C, A] 순이어야 함, got {len(items)}건"
            item = items[1]
            assert item["owner_nickname"] == f"북마크u2-{ts%100000}"
            assert item["is_mine"] is False
            for k in ("like_count", "comment_count", "copy_count", "is_liked"):
                assert k in item, f"{k} 필드 누락"
            assert get_bookmarked(c, tok2) == [], "u2 목록은 비어 있어야 함 (본인 것만)"
            ok("최신 저장순 ✓ enrich 필드 ✓ 유저 격리 ✓")

            step("5. limit+offset 페이지네이션")
            p1 = get_bookmarked(c, tok1, limit=1, offset=0)
            p2 = get_bookmarked(c, tok1, limit=1, offset=1)
            assert [i["id"] for i in p1] == [route_c]
            assert [i["id"] for i in p2] == [route_a]
            assert get_bookmarked(c, tok1, limit=1, offset=2) == []
            ok("offset=0→C, 1→A, 2→[] ✓")

            step("6. 저장 후 비공개 전환 → 목록에서 숨김, 재공개 → 복귀")
            sb_set_public(c, route_a, False)
            assert [i["id"] for i in get_bookmarked(c, tok1)] == [route_c], \
                "비공개 전환된 A는 숨겨져야 함"
            sb_set_public(c, route_a, True)
            assert [i["id"] for i in get_bookmarked(c, tok1)] == [route_c, route_a], \
                "재공개 시 북마크 유지된 채 복귀해야 함"
            ok("비공개 숨김 ✓ 재공개 복귀 (북마크 보존) ✓")

            step("7. 해제 + 멱등")
            r = api(c, "DELETE", f"/routes/{route_c}/bookmark", tok1)
            assert r.status_code == 204
            r = api(c, "DELETE", f"/routes/{route_c}/bookmark", tok1)
            assert r.status_code == 204, "재해제도 204 (멱등)"
            assert [i["id"] for i in get_bookmarked(c, tok1)] == [route_a]
            ok("해제 ✓ 멱등 ✓ 목록 반영 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "route_bookmarks", "route_id", all_routes)
            ok("route_bookmarks 삭제")
            sb_del_in(c, "routes", "id", all_routes)
            ok("routes 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
