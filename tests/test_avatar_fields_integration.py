"""
Integration test: 응답 7종 avatar_url additive — 대표 3경로 + 탈퇴 작성자

댓글 목록(run·route)·크루 랭킹·알림에서: 아바타 있는 유저(값) / 없는 유저(null)
/ 탈퇴 작성자(공지 author_avatar_url null 보존) assert. 배치 조회(briefs)라
행 수와 무관하게 IN 1쿼리 — N+1 없음은 구현 계층에서 보장.

Run: python tests/test_avatar_fields_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timedelta, timezone
import httpx

BASE = "http://localhost:8000/api"
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
AVATAR = f"https://cdn.example/avatar-{TS}.png"


def ok(m):        print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
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
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {token}"}, **kw)


def _track(distance_km, pace=360):
    step_m = 22.24
    n = round(distance_km * 1000 / step_m) + 1
    t0 = (TS - 7200) * 1000
    return [{"lat": 37.5445 + i * 0.0002, "lng": 127.0374,
             "t": t0 + i * round(step_m * pace), "acc": 5.0} for i in range(n)]


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    try:
        step("0. A(아바타 있음)·B(아바타 없음) + 크루/run")
        for k in ("a", "b"):
            uids[k] = sb_user(c, f"avf-{k}-{TS}@test.com")
        tok_a, tok_b = sb_login(c, f"avf-a-{TS}@test.com"), sb_login(c, f"avf-b-{TS}@test.com")
        assert api(c, "PATCH", "/me/profile", tok_a,
                   json={"nickname": f"AVF-a{TS}", "avatar_url": AVATAR}).status_code == 200
        assert api(c, "PATCH", "/me/profile", tok_b,
                   json={"nickname": f"AVF-b{TS}"}).status_code == 200
        crew = api(c, "POST", "/crews", tok_a, json={"name": f"아바타크루{TS}"}).json()["id"]
        assert api(c, "POST", f"/crews/{crew}/join", tok_b).status_code == 200
        now = datetime.now(timezone.utc)
        run_b = api(c, "POST", "/runs", tok_b, json={
            "distance_km": 3.0, "duration_sec": 1200, "visibility": "public",
            "gps_track": _track(3.0), "ran_at": (now - timedelta(hours=2)).isoformat()
        }).json()["id"]
        api(c, "POST", "/runs", tok_a, json={
            "distance_km": 2.0, "duration_sec": 800, "visibility": "public",
            "gps_track": _track(2.0), "ran_at": (now - timedelta(hours=1)).isoformat()})
        ok("유저 2명(아바타 유/무) + 크루 + verified run 2개")

        step("1. run 댓글 목록 — 작성자별 avatar_url")
        assert api(c, "POST", f"/runs/{run_b}/comments", tok_a,
                   json={"content": "아바타 있는 A"}).status_code in (200, 201)
        assert api(c, "POST", f"/runs/{run_b}/comments", tok_b,
                   json={"content": "아바타 없는 B"}).status_code in (200, 201)
        rows = api(c, "GET", f"/runs/{run_b}/comments", tok_b).json()
        by = {r["user_id"]: r for r in rows}
        assert by[uids["a"]]["avatar_url"] == AVATAR, by[uids["a"]]
        assert by[uids["b"]]["avatar_url"] is None, "아바타 없는 유저는 null"
        ok("A=값 · B=null ✓")

        step("2. 크루 랭킹 + 멤버 목록 — avatar_url")
        rank = api(c, "GET", f"/crews/{crew}/ranking", tok_a).json()
        rby = {e["user_id"]: e for e in rank}
        assert rby[uids["a"]]["avatar_url"] == AVATAR and rby[uids["b"]]["avatar_url"] is None
        members = api(c, "GET", f"/crews/{crew}/members", tok_a).json()
        mby = {m["user_id"]: m for m in members}
        assert mby[uids["a"]]["avatar_url"] == AVATAR and mby[uids["b"]]["avatar_url"] is None
        ok("랭킹·멤버 목록 A=값 · B=null ✓")

        step("2b. 공개 코스 — owner_avatar_url (no-op 재발 방지)")
        route_row = {"summary": f"avf-route-{TS}", "target_distance_km": 3.0,
                     "total_distance_km": 3.0, "estimated_duration_min": 20,
                     "waypoints": [], "polyline": [], "start_lat": 37.5,
                     "start_lng": 127.0, "is_public": True, "user_id": uids["a"]}
        c.post(f"{_SB}/rest/v1/routes", headers=_ADM, json=route_row)
        pub = api(c, "GET", "/routes/public?sort=newest&limit=20", tok_b).json()
        mine_route = next(x for x in pub if x["summary"] == f"avf-route-{TS}")
        assert mine_route["owner_avatar_url"] == AVATAR, mine_route.get("owner_avatar_url")
        ok("공개 코스 owner_avatar_url ✓")

        step("3. 알림 — actor_avatar_url")
        assert api(c, "POST", f"/users/{uids['b']}/follow", tok_a).status_code == 204
        notifs = api(c, "GET", "/notifications", tok_b).json()
        n = next(x for x in notifs if x["type"] == "user_followed")
        assert n["actor_avatar_url"] == AVATAR, n
        ok("actor_avatar_url=A 아바타 ✓")

        step("4. 공지 author + 탈퇴 작성자 null 보존")
        ann = api(c, "POST", f"/crews/{crew}/announcements", tok_a,
                  json={"title": "아바타 공지", "body": "x"}).json()
        assert ann["author_avatar_url"] == AVATAR, ann.get("author_avatar_url")
        # A 탈퇴 (크루 위임 후) → author null 보존 케이스에서 avatar도 null
        assert api(c, "PATCH", f"/crews/{crew}/transfer", tok_a,
                   json={"new_owner_id": uids["b"]}).status_code == 200
        assert api(c, "DELETE", "/me", tok_a).status_code == 204
        uids.pop("a")
        anns = api(c, "GET", f"/crews/{crew}/announcements", tok_b).json()
        row = next(x for x in anns if x["id"] == ann["id"])
        assert row["author_nickname"] is None and row["author_avatar_url"] is None, row
        ok("작성 시 avatar ✓ → 탈퇴 후 author_nickname·avatar 모두 null ✓")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup: 탈퇴 cascade")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
