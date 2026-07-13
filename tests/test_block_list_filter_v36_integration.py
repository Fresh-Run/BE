"""
Integration test: v3.6 차단 목록 필터 (L-1 kudos·L-2 run댓글·L-3 route댓글)

3목록 각각: 차단 전 노출 → 차단 후 제외 → 해제 후 재노출. count는 전역 유지
(목록만 필터 — 정합 주석). 랭킹·명단은 예외(별 테스트).

Run: python tests/test_block_list_filter_v36_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timezone
import httpx

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys():
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
def step(t):      print(f"\n[{t}]")


def sb_user(c, email):
    return c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                  json={"email": email, "password": "test1234", "email_confirm": True}).json()["id"]


def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


def kudosers(c, run_id, token):
    return {u["user_id"] for u in api(c, "GET", f"/runs/{run_id}/kudos", token).json()}


def run_commenters(c, run_id, token):
    return {x["user_id"] for x in api(c, "GET", f"/runs/{run_id}/comments", token).json()}


def route_commenters(c, route_id, token):
    return {x["user_id"] for x in api(c, "GET", f"/routes/{route_id}/comments", token).json()}


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. A(뷰어·소유)·B(차단 대상)·F(대조) + A의 public run·route, B·F가 상호작용")
        for k in ("a", "b", "f"):
            uids[k] = sb_user(c, f"blf-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"blf-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"BLF{k}{TS}"}).status_code == 200
        now = datetime.now(timezone.utc)
        track = [{"lat": 37.5445 + i * 0.0002, "lng": 127.0374, "t": int(now.timestamp() * 1000) + i * 8000,
                  "acc": 5.0} for i in range(20)]
        run = api(c, "POST", "/runs", tk["a"], json={
            "distance_km": 2.0, "duration_sec": 720, "visibility": "public",
            "gps_track": track, "ran_at": now.isoformat()}).json()["id"]
        route = c.post(f"{_SB}/rest/v1/routes", headers={**_ADM, "Prefer": "return=representation"},
                       json={"user_id": uids["a"], "summary": f"BLF코스{TS}", "target_distance_km": 3.0,
                             "total_distance_km": 3.0, "estimated_duration_min": 20, "waypoints": [],
                             "polyline": [], "start_lat": 37.5, "start_lng": 127.0, "is_public": True}).json()[0]["id"]
        # B·F가 kudos·run댓글·route댓글
        for u in ("b", "f"):
            assert api(c, "POST", f"/runs/{run}/kudos", tk[u]).status_code == 204
            assert api(c, "POST", f"/runs/{run}/comments", tk[u], json={"content": f"{u}런댓글"}).status_code == 200
            assert api(c, "POST", f"/routes/{route}/comments", tk[u], json={"content": f"{u}코스댓글"}).status_code == 201
        ok("A public run·route + B·F가 kudos·댓글 2종")

        step("1. 차단 전 — 3목록에 B·F 모두 노출")
        assert kudosers(c, run, tk["a"]) == {uids["b"], uids["f"]}, "kudos 명단 B·F"
        assert run_commenters(c, run, tk["a"]) == {uids["b"], uids["f"]}, "run 댓글 B·F"
        assert route_commenters(c, route, tk["a"]) == {uids["b"], uids["f"]}, "route 댓글 B·F"
        # 전역 카운트 = 2
        detail = api(c, "GET", f"/runs/{run}", tk["a"]).json()
        assert detail["kudos_count"] == 2 and detail["comment_count"] == 2, "차단 전 카운트 2"
        ok("차단 전 3목록 B·F 노출·카운트 2")

        step("2. A가 B 차단 → 3목록에서 B 제외, F 유지")
        assert api(c, "POST", f"/users/{uids['b']}/block", tk["a"]).status_code == 204
        assert kudosers(c, run, tk["a"]) == {uids["f"]}, "kudos 명단 B 제외"
        assert run_commenters(c, run, tk["a"]) == {uids["f"]}, "run 댓글 B 제외"
        assert route_commenters(c, route, tk["a"]) == {uids["f"]}, "route 댓글 B 제외"
        ok("차단 후 3목록에서 B 제외·F 유지")

        step("3. count 정합 — 목록만 필터, 카운트는 전역 유지(2)")
        detail = api(c, "GET", f"/runs/{run}", tk["a"]).json()
        assert detail["kudos_count"] == 2, f"kudos_count 전역 유지 2(목록은 1), got {detail['kudos_count']}"
        assert detail["comment_count"] == 2, f"comment_count 전역 유지 2, got {detail['comment_count']}"
        ok("카운트 전역 유지(2) — 목록 필터와 의도적 불일치(뷰어별 카운트화 안 함)")

        step("4. 차단 해제 → B 재노출")
        assert api(c, "DELETE", f"/users/{uids['b']}/block", tk["a"]).status_code == 204
        assert kudosers(c, run, tk["a"]) == {uids["b"], uids["f"]}, "해제 후 kudos B 재노출"
        assert run_commenters(c, run, tk["a"]) == {uids["b"], uids["f"]}, "해제 후 run 댓글 B 재노출"
        assert route_commenters(c, route, tk["a"]) == {uids["b"], uids["f"]}, "해제 후 route 댓글 B 재노출"
        ok("차단 해제 후 3목록 B 재노출")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
