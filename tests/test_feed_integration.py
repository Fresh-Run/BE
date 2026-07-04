"""
Integration test: following feed (GET /feed)
Run: python tests/test_feed_integration.py
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

def get_feed(c, tok, **params):
    r = api(c, "GET", "/feed", tok, params=params)
    if r.status_code != 200: fail("GET /feed", r.text[:200])
    return r.json()


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"fd-u{i}-{ts}@t.l" for i in range(1,4)]
    uids: list[str] = []
    toks: list[str] = []
    all_routes: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 3명 + 프로필 ─────────────────────────────────────
            step("1. 유저 생성 + 로그인 + 프로필")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2, uid3 = uids; tok1, tok2, tok3 = toks
            for i, tok in enumerate(toks, start=1):
                r = api(c, "PATCH", "/me/profile", tok,
                        json={"nickname": f"피드u{i}-{ts%100000}"})
                assert r.status_code == 200, r.text[:200]
            ok(f"u1={uid1[:8]}… u2={uid2[:8]}… u3={uid3[:8]}…")

            # ── 2. 코스: u2 공개A + 비공개B, u3 공개C ────────────────────
            step("2. 코스 삽입 (u2: 공개A·비공개B / u3: 공개C)")
            route_a = sb_insert_route(c, uid2, "피드테스트A", True)
            route_b = sb_insert_route(c, uid2, "피드테스트B-비공개", False)
            route_c = sb_insert_route(c, uid3, "피드테스트C", True)
            all_routes += [route_a, route_b, route_c]
            ok("A(공개)·B(비공개)·C(공개) 삽입")

            # ── 3. 팔로우 없는 유저 → 빈 피드 ────────────────────────────
            step("3. 팔로우 0명인 u2 → 빈 배열")
            assert get_feed(c, tok2) == [], "팔로우 없으면 빈 배열이어야 함"
            ok("빈 피드 ✓")

            # ── 4. u1 → u2 팔로우 → 피드에 A만 ───────────────────────────
            step("4. u1이 u2 팔로우 → 피드 [A] (비공개 B·미팔로우 C 제외)")
            r = api(c, "POST", f"/users/{uid2}/follow", tok1)
            assert r.status_code == 204
            feed = get_feed(c, tok1)
            ids = [f["id"] for f in feed]
            assert ids == [route_a], f"[A]만 나와야 함, got {len(ids)}건"
            assert feed[0]["owner_nickname"] == f"피드u2-{ts%100000}"
            assert feed[0]["owner_id"] == uid2
            assert feed[0]["is_mine"] is False
            ok("A만 노출 ✓ 비공개·미팔로우 제외 ✓ owner_nickname ✓")

            # ── 5. 소셜 카운트 (좋아요·댓글·복사) ────────────────────────
            step("5. 카운트: u3 좋아요+댓글, u1 좋아요 → is_liked")
            r = api(c, "POST", f"/routes/{route_a}/like", tok3)
            assert r.status_code == 204
            r = api(c, "POST", f"/routes/{route_a}/comments", tok3,
                    json={"content": "피드 테스트 댓글"})
            assert r.status_code in (200, 201), r.text[:200]
            feed = get_feed(c, tok1)
            item = feed[0]
            assert item["like_count"] == 1, f"like_count 1, got {item['like_count']}"
            assert item["comment_count"] == 1, f"comment_count 1, got {item['comment_count']}"
            assert item["is_liked"] is False, "u1은 아직 안 눌렀으니 False"
            r = api(c, "POST", f"/routes/{route_a}/like", tok1)
            assert r.status_code == 204
            item = get_feed(c, tok1)[0]
            assert item["like_count"] == 2 and item["is_liked"] is True
            assert "copy_count" in item
            ok("like_count·comment_count·is_liked·copy_count ✓")

            # ── 6. u1 → u3 추가 팔로우 → [C, A] 최신순 ───────────────────
            step("6. u1이 u3도 팔로우 → 피드 [C, A] 최신순")
            r = api(c, "POST", f"/users/{uid3}/follow", tok1)
            assert r.status_code == 204
            ids = [f["id"] for f in get_feed(c, tok1)]
            assert ids == [route_c, route_a], f"[C, A] 순이어야 함, got {len(ids)}건"
            ok("두 유저 코스 병합 + 최신순 ✓")

            # ── 7. limit+offset 페이지네이션 ─────────────────────────────
            step("7. limit=1 페이지네이션")
            p1 = get_feed(c, tok1, limit=1, offset=0)
            p2 = get_feed(c, tok1, limit=1, offset=1)
            p3 = get_feed(c, tok1, limit=1, offset=2)
            assert [f["id"] for f in p1] == [route_c]
            assert [f["id"] for f in p2] == [route_a]
            assert p3 == [], "범위 밖 offset은 빈 배열"
            ok("offset=0→C, 1→A, 2→[] ✓")

            # ── 8. 언팔로우 반영 ─────────────────────────────────────────
            step("8. u3 언팔로우 → 피드에서 C 제거")
            r = api(c, "DELETE", f"/users/{uid3}/follow", tok1)
            assert r.status_code == 204
            ids = [f["id"] for f in get_feed(c, tok1)]
            assert ids == [route_a], f"[A]만 남아야 함, got {len(ids)}건"
            ok("언팔로우 즉시 반영 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "route_comments", "route_id", all_routes)
            sb_del_in(c, "route_likes", "route_id", all_routes)
            ok("comments·likes 삭제")
            sb_del_in(c, "routes", "id", all_routes)
            ok("routes 삭제")
            sb_del_in(c, "follows", "follower_id", [u for u in uids if u])
            sb_del_in(c, "follows", "following_id", [u for u in uids if u])
            sb_del_in(c, "notifications", "user_id", [u for u in uids if u])
            sb_del_in(c, "notifications", "actor_id", [u for u in uids if u])
            ok("follows·notifications 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
