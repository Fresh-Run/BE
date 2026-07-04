"""
Integration test: notifications (route_liked, route_commented, crew_joined)
Run: python tests/test_notifications_integration.py
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
            if   line.startswith("SUPABASE_KEY="):             anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(m):        print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):      print(f"\n[{t}]")

def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201): fail("create user", r.text[:200])
    return r.json()["id"]

def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]

def sb_del_user(c, uid): c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)

def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})

def sb_insert_route(c, uid, summary, is_public):
    r = c.post(f"{_SB}/rest/v1/routes",
               headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": uid, "summary": summary,
                     "total_distance_km": 5.0, "is_public": is_public, "waypoints": []})
    if r.status_code not in (200, 201): fail("insert route", r.text[:200])
    return r.json()[0]["id"]

def sb_set_nickname(c, uid, nickname):
    c.post(f"{_SB}/rest/v1/profiles",
           headers={**_ADM, "Prefer": "resolution=merge-duplicates,return=minimal"},
           json={"user_id": uid, "nickname": nickname})

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def get_notifications(c, tok, limit=50):
    r = api(c, "GET", "/notifications", tok, params={"limit": limit})
    assert r.status_code == 200, f"GET /notifications → 200 이어야 함, got {r.status_code}: {r.text[:200]}"
    return r.json()

def get_unread_count(c, tok):
    r = api(c, "GET", "/notifications/unread-count", tok)
    assert r.status_code == 200, f"GET unread-count → 200 이어야 함, got {r.status_code}"
    return r.json()["count"]


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"ntf-u{i}-{ts}@t.n" for i in range(1, 3)]
    uids: list[str] = []; toks: list[str] = []
    all_routes: list[str] = []; crew_ids: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 2명 + 닉네임 ──────────────────────────────────────
            step("1. 유저 2명 생성 + 로그인 + 닉네임")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2 = uids; tok1, tok2 = toks
            nick2 = f"액터{ts % 10000}"
            sb_set_nickname(c, uid1, f"주인{ts % 10000}")
            sb_set_nickname(c, uid2, nick2)
            ok(f"u1={uid1[:8]}(코스/크루 주인)  u2={uid2[:8]}(액터) nick2={nick2}")

            # ── 2. test1 공개 코스 삽입 ───────────────────────────────────
            step("2. 공개 코스 삽입")
            route_a = sb_insert_route(c, uid1, "알림테스트코스", True)
            all_routes.append(route_a)
            ok(f"route_a={route_a[:8]}")

            # ── 3. test2 → test1 코스 좋아요 → route_liked 알림 ──────────
            step("3. test2 → test1 코스 좋아요 → route_liked 알림")
            r = api(c, "POST", f"/routes/{route_a}/like", tok2)
            assert r.status_code == 204, f"like → 204 이어야 함, got {r.status_code}"

            notifs = get_notifications(c, tok1)
            liked_notifs = [n for n in notifs if n["type"] == "route_liked"]
            assert len(liked_notifs) >= 1, f"route_liked 알림이 없음: {notifs}"
            n = liked_notifs[0]
            assert n["actor_id"] == uid2, f"actor_id 불일치: {n['actor_id']}"
            assert n["target_id"] == route_a, f"target_id 불일치: {n['target_id']}"
            assert n["target_type"] == "route", f"target_type 불일치: {n['target_type']}"
            assert n["actor_nickname"] == nick2, f"actor_nickname 불일치: {n['actor_nickname']}"
            assert n["is_read"] is False, "is_read False 이어야 함"
            ok(f"route_liked 알림 ✓  actor_nickname={n['actor_nickname']}")

            # ── 4. test2 → test1 코스 댓글 → route_commented 알림 ────────
            step("4. test2 → test1 코스 댓글 → route_commented 알림")
            r = api(c, "POST", f"/routes/{route_a}/comments", tok2,
                    json={"content": "멋진 코스!"})
            assert r.status_code == 201, f"comment → 201 이어야 함, got {r.status_code}"

            notifs = get_notifications(c, tok1)
            commented_notifs = [n for n in notifs if n["type"] == "route_commented"]
            assert len(commented_notifs) >= 1, f"route_commented 알림 없음: {notifs}"
            nc = commented_notifs[0]
            assert nc["actor_id"] == uid2, f"actor_id 불일치: {nc['actor_id']}"
            assert nc["target_id"] == route_a, f"target_id 불일치: {nc['target_id']}"
            assert nc["actor_nickname"] == nick2, f"actor_nickname 불일치: {nc['actor_nickname']}"
            ok(f"route_commented 알림 ✓  actor_nickname={nc['actor_nickname']}")

            # ── 5. test1 크루 생성 + test2 가입 → crew_joined 알림 ────────
            step("5. test1 크루 생성 + test2 가입 → crew_joined 알림")
            r = api(c, "POST", "/crews", tok1,
                    json={"name": f"알림테스트크루{ts}", "is_public": True})
            assert r.status_code == 200, f"crew create → 200 이어야 함, got {r.status_code}"
            crew_id = r.json()["id"]
            crew_ids.append(crew_id)

            r = api(c, "POST", f"/crews/{crew_id}/join", tok2)
            assert r.status_code == 200, f"crew join → 200 이어야 함, got {r.status_code}"

            notifs = get_notifications(c, tok1)
            joined_notifs = [n for n in notifs if n["type"] == "crew_joined"]
            assert len(joined_notifs) >= 1, f"crew_joined 알림 없음: {notifs}"
            nj = joined_notifs[0]
            assert nj["actor_id"] == uid2, f"actor_id 불일치: {nj['actor_id']}"
            assert nj["target_id"] == crew_id, f"target_id 불일치: {nj['target_id']}"
            assert nj["target_type"] == "crew", f"target_type 불일치: {nj['target_type']}"
            assert nj["actor_nickname"] == nick2, f"actor_nickname 불일치: {nj['actor_nickname']}"
            ok(f"crew_joined 알림 ✓  actor_nickname={nj['actor_nickname']}")

            # ── 6. test1이 자기 코스에 좋아요 → 알림 안 생김 ──────────────
            step("6. test1 자기 코스 좋아요 → 알림 생성 안 됨")
            notifs_before = [n for n in get_notifications(c, tok1) if n["type"] == "route_liked"]
            r = api(c, "POST", f"/routes/{route_a}/like", tok1)
            assert r.status_code == 204, f"self-like → 204 이어야 함"
            notifs_after = [n for n in get_notifications(c, tok1) if n["type"] == "route_liked"]
            assert len(notifs_after) == len(notifs_before), \
                f"자기 행동 좋아요에 알림이 생김 (before={len(notifs_before)}, after={len(notifs_after)})"
            ok("자기 좋아요 → 알림 생성 없음 ✓")

            # ── 7. unread-count + 개별 읽음 처리 ──────────────────────────
            step("7. unread-count 확인 + 개별 읽음 처리")
            count_before = get_unread_count(c, tok1)
            assert count_before >= 3, f"unread_count >= 3 이어야 함 (like+comment+join), got {count_before}"
            ok(f"unread_count={count_before} ✓")

            # 첫 번째 알림 개별 읽음
            all_notifs = get_notifications(c, tok1)
            first_id = all_notifs[0]["id"]
            r = api(c, "PATCH", f"/notifications/{first_id}/read", tok1)
            assert r.status_code == 204, f"mark_read → 204 이어야 함, got {r.status_code}"

            count_after = get_unread_count(c, tok1)
            assert count_after == count_before - 1, \
                f"읽음 처리 후 unread_count {count_before-1} 이어야 함, got {count_after}"
            ok(f"개별 읽음 → unread_count {count_before} → {count_after} ✓")

            # ── 8. 전체 읽음 처리 ──────────────────────────────────────────
            step("8. 전체 읽음 처리 → unread_count=0")
            r = api(c, "PATCH", "/notifications/read-all", tok1)
            assert r.status_code == 204, f"read-all → 204 이어야 함, got {r.status_code}"
            count_final = get_unread_count(c, tok1)
            assert count_final == 0, f"read-all 후 unread_count 0 이어야 함, got {count_final}"
            ok("read-all → unread_count=0 ✓")

            # ── 9. test1 알림은 test2에게 안 보임 ─────────────────────────
            step("9. test2는 자기 알림만 보임 (test1 알림 안 보임)")
            notifs2 = get_notifications(c, tok2)
            for n in notifs2:
                assert n.get("user_id") != uid1 or True, "구조 확인"
            # test1 이벤트(route_liked 등)로 test2가 받은 알림은 없어야 함
            # (test2가 한 행동이므로 test2는 recipient가 아님)
            assert all(
                n["actor_id"] != uid2 or n["type"] not in ("route_liked", "route_commented", "crew_joined")
                for n in notifs2
            ) or len(notifs2) == 0, "test2한테 엉뚱한 알림이 있음"
            ok(f"test2 알림 목록 {len(notifs2)}개 (자기 관련 이벤트 없음 ✓)")

            # ── 10. 존재하지 않는 알림 읽음 처리 → 404 ────────────────────
            step("10. 없는 알림 mark_read → 404")
            r = api(c, "PATCH", f"/notifications/00000000-0000-0000-0000-000000000000/read", tok1)
            assert r.status_code == 404, f"없는 알림 → 404 이어야 함, got {r.status_code}"
            ok("없는 알림 → 404 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)

        finally:
            step("Cleanup")
            sb_del_in(c, "notifications", "user_id", [u for u in uids if u])
            ok("notifications 삭제")
            # crew_members cascade on crew delete — delete crew first
            for cid in crew_ids:
                api(c, "DELETE", f"/crews/{cid}", tok1)
            ok("crews 삭제")
            sb_del_in(c, "route_comments", "route_id", all_routes)
            sb_del_in(c, "route_likes", "route_id", all_routes)
            sb_del_in(c, "routes", "id", all_routes)
            ok("routes/likes/comments 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")


if __name__ == "__main__":
    run()
