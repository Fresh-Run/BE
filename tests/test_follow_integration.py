"""
Integration test: user follows
(POST/DELETE /users/{id}/follow, GET followers/following, GET /users/{id}/profile)
Run: python tests/test_follow_integration.py
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"
_NOBODY = "00000000-0000-4000-8000-000000000000"  # never-existing user id

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

def get_profile(c, tok, uid):
    r = api(c, "GET", f"/users/{uid}/profile", tok)
    if r.status_code != 200: fail("GET profile", r.text[:200])
    return r.json()


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"fl-u{i}-{ts}@t.l" for i in range(1,4)]
    uids: list[str] = []
    toks: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 3명 + 프로필 생성 ────────────────────────────────
            step("1. 유저 생성 + 로그인 + 프로필 생성")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2, uid3 = uids; tok1, tok2, tok3 = toks
            for i, tok in enumerate(toks, start=1):
                r = api(c, "PATCH", "/me/profile", tok,
                        json={"nickname": f"팔로우u{i}-{ts%100000}", "bio": f"러너{i}"})
                assert r.status_code == 200, f"프로필 생성 → 200 이어야 함, got {r.status_code}"
            ok(f"u1={uid1[:8]}… u2={uid2[:8]}… u3={uid3[:8]}… (프로필 3개)")

            # ── 2. u2·u3 → u1 팔로우 ─────────────────────────────────────
            step("2. u2·u3 → u1 팔로우 → 204")
            for tok, name in [(tok2,"u2"), (tok3,"u3")]:
                r = api(c, "POST", f"/users/{uid1}/follow", tok)
                assert r.status_code == 204, f"{name} follow → 204 이어야 함, got {r.status_code}"
            ok("u2·u3 팔로우 204 ✓")

            # ── 3. u1 공개 프로필 (u2 시점) ──────────────────────────────
            step("3. u1 프로필: follower_count=2, is_following=True, email 미노출")
            p = get_profile(c, tok2, uid1)
            assert p["follower_count"] == 2,  f"follower_count 2 이어야 함, got {p['follower_count']}"
            assert p["following_count"] == 0, f"following_count 0 이어야 함, got {p['following_count']}"
            assert p["is_following"] is True,   "u2는 u1을 팔로우 중이어야 함"
            assert p["is_followed_by"] is False, "u1은 아직 u2를 팔로우하지 않아야 함"
            assert p["nickname"] == f"팔로우u1-{ts%100000}"
            assert p["bio"] == "러너1"
            assert "email" not in p, "공개 프로필에 email이 노출되면 안 됨"
            ok("follower_count=2 ✓ is_following=True ✓ email 미노출 ✓")

            # ── 4. 더블탭(중복 팔로우) → 204, 카운트 유지 ────────────────
            step("4. u2 더블탭 → 204, follower_count=2 유지")
            r = api(c, "POST", f"/users/{uid1}/follow", tok2)
            assert r.status_code == 204, f"더블탭 → 204 이어야 함, got {r.status_code}"
            p = get_profile(c, tok2, uid1)
            assert p["follower_count"] == 2, f"더블탭 후 2 유지여야 함, got {p['follower_count']}"
            ok("더블탭 204 ✓ 카운트 유지 ✓")

            # ── 5. 자기 자신 팔로우 → 400 ────────────────────────────────
            step("5. u1 → u1 자기 팔로우 → 400")
            r = api(c, "POST", f"/users/{uid1}/follow", tok1)
            assert r.status_code == 400, f"자기 팔로우 → 400 이어야 함, got {r.status_code}"
            ok("자기 팔로우 400 ✓")

            # ── 6. 없는 유저 팔로우/프로필 → 404 ─────────────────────────
            step("6. 없는 유저 → 404")
            r = api(c, "POST", f"/users/{_NOBODY}/follow", tok1)
            assert r.status_code == 404, f"없는 유저 follow → 404, got {r.status_code}"
            r = api(c, "GET", f"/users/{_NOBODY}/profile", tok1)
            assert r.status_code == 404, f"없는 유저 profile → 404, got {r.status_code}"
            r = api(c, "GET", f"/users/{_NOBODY}/followers", tok1)
            assert r.status_code == 404, f"없는 유저 followers → 404, got {r.status_code}"
            ok("follow·profile·followers 모두 404 ✓")

            # ── 7. 맞팔: u1 → u2 팔로우 ──────────────────────────────────
            step("7. u1 → u2 팔로우 후 맞팔 표시")
            r = api(c, "POST", f"/users/{uid2}/follow", tok1)
            assert r.status_code == 204
            p = get_profile(c, tok1, uid2)   # u1이 보는 u2
            assert p["is_following"] is True,  "u1은 u2를 팔로우 중이어야 함"
            assert p["is_followed_by"] is True, "u2도 u1을 팔로우 중(맞팔)이어야 함"
            p = get_profile(c, tok2, uid1)   # u2가 보는 u1
            assert p["is_followed_by"] is True, "u1이 u2를 팔로우하므로 is_followed_by=True"
            assert p["following_count"] == 1, f"u1 following_count 1 이어야 함, got {p['following_count']}"
            ok("양방향 is_following/is_followed_by ✓")

            # ── 8. 팔로워 목록: 최신순 + 항목별 is_following ─────────────
            step("8. u1 팔로워 목록 (u1 시점): [u3, u2] + is_following")
            r = api(c, "GET", f"/users/{uid1}/followers", tok1)
            assert r.status_code == 200, r.text[:200]
            items = r.json()
            assert [i["user_id"] for i in items] == [uid3, uid2], \
                f"최신순 [u3, u2] 이어야 함, got {[i['user_id'][:8] for i in items]}"
            by_id = {i["user_id"]: i for i in items}
            assert by_id[uid2]["is_following"] is True,  "u1은 u2를 팔로우 → 항목 is_following=True"
            assert by_id[uid3]["is_following"] is False, "u1은 u3를 팔로우 안 함 → False"
            assert by_id[uid2]["nickname"] == f"팔로우u2-{ts%100000}"
            assert all("followed_at" in i for i in items)
            ok("최신순 ✓ 항목별 is_following ✓ 닉네임 배치 ✓")

            # ── 9. 팔로잉 목록 (제3자 시점) ──────────────────────────────
            step("9. u2 팔로잉 목록 (u3 시점): [u1], is_following=True")
            r = api(c, "GET", f"/users/{uid2}/following", tok3)
            assert r.status_code == 200, r.text[:200]
            items = r.json()
            assert [i["user_id"] for i in items] == [uid1]
            assert items[0]["is_following"] is True, "u3도 u1을 팔로우 중 → True"
            ok("팔로잉 목록 ✓ 제3자 시점 is_following ✓")

            # ── 10. limit+offset 페이지네이션 ────────────────────────────
            step("10. u1 팔로워 limit=1 페이지네이션")
            r1 = api(c, "GET", f"/users/{uid1}/followers", tok1, params={"limit":1,"offset":0})
            r2 = api(c, "GET", f"/users/{uid1}/followers", tok1, params={"limit":1,"offset":1})
            p1, p2 = r1.json(), r2.json()
            assert len(p1) == 1 and len(p2) == 1
            assert p1[0]["user_id"] == uid3 and p2[0]["user_id"] == uid2, \
                "offset=0→u3, offset=1→u2 이어야 함"
            r3 = api(c, "GET", f"/users/{uid1}/followers", tok1, params={"limit":1,"offset":2})
            assert r3.json() == [], "offset=2는 빈 목록이어야 함"
            ok("limit=1 페이지 분할 ✓ 범위 밖 빈 목록 ✓")

            # ── 11. user_followed 알림 ───────────────────────────────────
            step("11. u1 알림에 user_followed (actor=u2·u3, 닉네임 포함)")
            r = api(c, "GET", "/notifications", tok1)
            assert r.status_code == 200, r.text[:200]
            follows_notis = [n for n in r.json() if n["type"] == "user_followed"]
            actors = {n["actor_id"] for n in follows_notis}
            assert {uid2, uid3} <= actors, f"u2·u3의 팔로우 알림이 있어야 함, got {len(follows_notis)}건"
            sample = next(n for n in follows_notis if n["actor_id"] == uid2)
            assert sample["target_type"] == "user"
            assert sample["target_id"] == uid2, "target_id는 팔로워(actor)의 user_id"
            assert sample["actor_nickname"] == f"팔로우u2-{ts%100000}"
            # 더블탭(4단계)에도 u2 알림은 1건이어야 함
            assert sum(1 for n in follows_notis if n["actor_id"] == uid2) == 1, \
                "더블탭 시 알림이 중복 생성되면 안 됨"
            ok("user_followed 알림 ✓ 더블탭 중복 알림 없음 ✓")

            # ── 12. 언팔로우 + 멱등 ──────────────────────────────────────
            step("12. u2 언팔로우 → 카운트 감소, 재언팔로우 204")
            r = api(c, "DELETE", f"/users/{uid1}/follow", tok2)
            assert r.status_code == 204, f"unfollow → 204, got {r.status_code}"
            p = get_profile(c, tok2, uid1)
            assert p["follower_count"] == 1, f"언팔 후 follower_count 1, got {p['follower_count']}"
            assert p["is_following"] is False, "언팔 후 is_following=False"
            r = api(c, "DELETE", f"/users/{uid1}/follow", tok2)
            assert r.status_code == 204, f"재언팔로우 → 204 (멱등), got {r.status_code}"
            follower_ids = [i["user_id"] for i in api(c, "GET", f"/users/{uid1}/followers", tok1).json()]
            assert uid2 not in follower_ids, "언팔 후 팔로워 목록에서 빠져야 함"
            ok("언팔로우 ✓ 멱등 ✓ 목록 반영 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "follows", "follower_id", [u for u in uids if u])
            sb_del_in(c, "follows", "following_id", [u for u in uids if u])
            ok("follows 삭제")
            sb_del_in(c, "notifications", "user_id", [u for u in uids if u])
            sb_del_in(c, "notifications", "actor_id", [u for u in uids if u])
            ok("notifications 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
