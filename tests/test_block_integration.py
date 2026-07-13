"""
Integration test: 차단 v3 (docs/PRIVATE_PROFILE_DESIGN.md §3)

차단 전/후 가시성(프로필 404·run 404·검색 제외·공개탭 빈) + 양방향 팔로우
4행 정리 + 크루 공존(can_see_user 차단이 크루 뚫음, 랭킹/피드는 v3.5라 잔존) +
차단 해제 후 팔로우 미복구 + 중복 차단 멱등 + kudos 차단 404 우선 + 탈퇴 cascade.

Run: python tests/test_block_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timezone
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
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


def follow_count(c, table, col, uid, other_col=None, other=None):
    p = {col: f"eq.{uid}", "select": "*", "limit": 1}
    if other_col:
        p[other_col] = f"eq.{other}"
    r = c.get(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "count=exact"}, params=p)
    return int(r.headers.get("content-range", "?/0").split("/")[-1])


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. A(차단 주체)·B(차단 대상, 맞팔) + B의 public run·route")
        for k in ("a", "b"):
            uids[k] = sb_user(c, f"blk-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"blk-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"BLK{k}{TS}"}).status_code == 200
        # 맞팔
        assert api(c, "POST", f"/users/{uids['b']}/follow", tk["a"]).status_code == 204
        assert api(c, "POST", f"/users/{uids['a']}/follow", tk["b"]).status_code == 204
        now = datetime.now(timezone.utc)
        track = [{"lat": 37.5445 + i * 0.0002, "lng": 127.0374, "t": (TS - 7200) * 1000 + i * 8000,
                  "acc": 5.0} for i in range(20)]
        run = api(c, "POST", "/runs", tk["b"], json={
            "distance_km": 2.0, "duration_sec": 720, "visibility": "public",
            "gps_track": track}).json()["id"]
        summ = f"BLK코스{TS}"
        c.post(f"{_SB}/rest/v1/routes", headers=_ADM, json={
            "user_id": uids["b"], "summary": summ, "target_distance_km": 3.0,
            "total_distance_km": 3.0, "estimated_duration_min": 20, "waypoints": [],
            "polyline": [], "start_lat": 37.5, "start_lng": 127.0, "is_public": True})
        ok("A·B 맞팔 + B public run·route")

        step("1. 차단 전 — A는 B의 public run·프로필 정상 접근")
        assert api(c, "GET", f"/runs/{run}", tk["a"]).status_code == 200
        assert api(c, "GET", f"/users/{uids['b']}/profile", tk["a"]).json()["locked"] is False
        ok("차단 전 정상 노출")

        step("2. A가 B 차단 → 양방향 404 + 팔로우 4행 정리")
        assert api(c, "POST", f"/users/{uids['b']}/block", tk["a"]).status_code == 204
        # 양방향 프로필 404 (존재 은닉)
        assert api(c, "GET", f"/users/{uids['b']}/profile", tk["a"]).status_code == 404
        assert api(c, "GET", f"/users/{uids['a']}/profile", tk["b"]).status_code == 404
        # 양방향 run 404
        assert api(c, "GET", f"/runs/{run}", tk["a"]).status_code == 404
        # 팔로우 양방향 삭제 (A→B, B→A 둘 다 0)
        assert follow_count(c, "follows", "follower_id", uids["a"], "following_id", uids["b"]) == 0
        assert follow_count(c, "follows", "follower_id", uids["b"], "following_id", uids["a"]) == 0
        ok("양방향 프로필·run 404 + 팔로우 4행(맞팔 2) 정리")

        step("3. 검색·공개 프로필 탭 제외")
        res = api(c, "GET", f"/routes/search?q=BLK코스{TS}", tk["a"]).json()
        assert not any(r["summary"] == summ for r in res), "차단 대상 코스 검색 제외"
        assert api(c, "GET", f"/users/{uids['b']}/runs", tk["a"]).json() == [], "공개 탭 빈"
        ok("검색 제외·공개 프로필 탭 빈 목록")

        step("4. kudos·댓글 — 차단 404 (설정 403보다 은닉 우선)")
        r = api(c, "POST", f"/runs/{run}/kudos", tk["a"])
        assert r.status_code == 404, f"차단 kudos 404, got {r.status_code}"
        r = api(c, "POST", f"/runs/{run}/comments", tk["a"], json={"content": "막힘"})
        assert r.status_code == 404
        ok("차단 kudos·댓글 404 (은닉 우선)")

        step("5. 중복 차단 멱등 + self-block 400")
        assert api(c, "POST", f"/users/{uids['b']}/block", tk["a"]).status_code == 204  # 멱등
        assert api(c, "POST", f"/users/{uids['a']}/block", tk["a"]).status_code == 400  # self
        blocks = api(c, "GET", "/me/blocks", tk["a"]).json()
        assert len(blocks) == 1 and blocks[0]["user_id"] == uids["b"], blocks
        ok("중복 차단 멱등·self 400·차단 목록 1건")

        step("6. 크루 공존 — can_see_user 경로는 차단, 크루 자체 유지")
        crew = api(c, "POST", "/crews", tk["a"], json={"name": f"BLK크루{TS}"}).json()["id"]
        assert api(c, "POST", f"/crews/{crew}/join", tk["b"]).status_code == 200
        # 크루원이어도 차단 상대 run 상세는 404 (can_see_user 차단 최우선)
        assert api(c, "GET", f"/runs/{run}", tk["a"]).status_code == 404, "크루원이어도 차단 우선"
        # 단 크루 멤버십 자체는 유지 (강퇴 아님)
        members = api(c, "GET", f"/crews/{crew}/members", tk["a"]).json()
        assert any(m["user_id"] == uids["b"] for m in members), "차단해도 크루 멤버십 유지"
        ok("크루원 차단 run 404(can_see_user 우선)·멤버십 유지(v3.5 전 랭킹/피드 잔존)")

        step("7. 차단 해제 — 노출 복구, 팔로우는 미복구")
        assert api(c, "DELETE", f"/users/{uids['b']}/block", tk["a"]).status_code == 204
        assert api(c, "GET", f"/runs/{run}", tk["a"]).status_code == 200, "해제 후 run 복구"
        p = api(c, "GET", f"/users/{uids['b']}/profile", tk["a"]).json()
        assert p["locked"] is False and p["is_following"] is False, "팔로우는 미복구(재팔로우 필요)"
        assert api(c, "DELETE", f"/users/{uids['b']}/block", tk["a"]).status_code == 204  # 멱등
        ok("해제 후 run 200·프로필 복구·팔로우 미복구·해제 멱등")

        step("8. 탈퇴 cascade — blocks 소멸")
        assert api(c, "POST", f"/users/{uids['b']}/block", tk["a"]).status_code == 204
        assert api(c, "DELETE", f"/crews/{crew}", tk["a"]).status_code == 204
        assert api(c, "DELETE", "/me", tk["a"]).status_code == 204
        left = follow_count(c, "blocks", "blocker_id", uids["a"])
        assert left == 0, f"탈퇴 후 blocks 잔존: {left}"
        uids.pop("a")
        ok("탈퇴 시 blocks cascade 소멸")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
