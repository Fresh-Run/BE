"""
Integration test: 피드 설정 강제 v1.5 (docs/PRIVATE_PROFILE_DESIGN.md §4)

allow_likes/allow_comments ON/OFF × 타인/본인 (run kudos·route like·run댓글·
route댓글) + auto_publish OFF에서 미지정 private·명시 존중 + 기존 기본값 무영향 +
가시성(404) 우선 순서.

Run: python tests/test_feed_settings_integration.py  (로컬 서버 필요)
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


def _track(dist, pace=360):
    step_m = 22.24; n = round(dist * 1000 / step_m) + 1; t0 = (TS - 7200) * 1000
    return [{"lat": 37.5445 + i * 0.0002, "lng": 127.0374, "t": t0 + i * round(step_m * pace),
             "acc": 5.0} for i in range(n)]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. O(콘텐츠 주인)·V(타인, O 팔로우) + O의 run·route")
        for k in ("o", "v"):
            uids[k] = sb_user(c, f"fs-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"fs-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"FS{k}{TS}"}).status_code == 200
        assert api(c, "POST", f"/users/{uids['o']}/follow", tk["v"]).status_code == 204
        now = datetime.now(timezone.utc)
        run = api(c, "POST", "/runs", tk["o"], json={
            "distance_km": 2.0, "duration_sec": 720, "visibility": "public",
            "gps_track": _track(2.0)}).json()["id"]
        route = c.post(f"{_SB}/rest/v1/routes", headers={**_ADM, "Prefer": "return=representation"},
                       json={"user_id": uids["o"], "summary": f"FS코스{TS}", "target_distance_km": 3.0,
                             "total_distance_km": 3.0, "estimated_duration_min": 20, "waypoints": [],
                             "polyline": [], "start_lat": 37.5, "start_lng": 127.0,
                             "is_public": True}).json()[0]["id"]
        ok("O run·route 생성 + V 팔로우")

        step("1. 기본값(허용) — V의 kudos·좋아요·댓글 전부 성공")
        assert api(c, "POST", f"/runs/{run}/kudos", tk["v"]).status_code == 204
        assert api(c, "POST", f"/routes/{route}/like", tk["v"]).status_code in (200, 204)
        assert api(c, "POST", f"/runs/{run}/comments", tk["v"], json={"content": "run댓글"}).status_code in (200, 201)
        assert api(c, "POST", f"/routes/{route}/comments", tk["v"], json={"content": "route댓글"}).status_code in (200, 201)
        ok("기본 allow_* True — 4종 전부 허용 (기존 동작 무영향)")

        step("2. allow_likes OFF — kudos·좋아요 403, 댓글은 여전히 허용")
        assert api(c, "PATCH", "/me/settings", tk["o"], json={"feed": {"allow_likes": False}}).status_code == 200
        api(c, "DELETE", f"/runs/{run}/kudos", tk["v"])  # 이전 kudos 취소해 재시도 가능
        r = api(c, "POST", f"/runs/{run}/kudos", tk["v"])
        assert r.status_code == 403 and r.json()["detail"]["error"] == "likes_disabled", r.text[:200]
        api(c, "DELETE", f"/routes/{route}/like", tk["v"])
        r = api(c, "POST", f"/routes/{route}/like", tk["v"])
        assert r.status_code == 403 and r.json()["detail"]["error"] == "likes_disabled"
        assert api(c, "POST", f"/runs/{run}/comments", tk["v"], json={"content": "여전히"}).status_code in (200, 201)
        ok("kudos·좋아요 403 likes_disabled · 댓글 무관 허용")

        step("3. allow_comments OFF — 댓글 403, 좋아요는 (재켜서) 허용")
        assert api(c, "PATCH", "/me/settings", tk["o"],
                   json={"feed": {"allow_likes": True, "allow_comments": False}}).status_code == 200
        r = api(c, "POST", f"/runs/{run}/comments", tk["v"], json={"content": "막힘"})
        assert r.status_code == 403 and r.json()["detail"]["error"] == "comments_disabled", r.text[:200]
        r = api(c, "POST", f"/routes/{route}/comments", tk["v"], json={"content": "막힘2"})
        assert r.status_code == 403 and r.json()["detail"]["error"] == "comments_disabled"
        api(c, "DELETE", f"/runs/{run}/kudos", tk["v"])
        assert api(c, "POST", f"/runs/{run}/kudos", tk["v"]).status_code == 204, "좋아요 재허용"
        ok("run·route 댓글 403 comments_disabled · 좋아요 재허용")

        step("4. 본인은 설정 무관 (자기 콘텐츠) — 댓글 OFF여도 본인 route 댓글 OK")
        # 본인 run kudos는 원래 400(self) — 설정과 무관하게 기존 계약
        assert api(c, "POST", f"/runs/{run}/kudos", tk["o"]).status_code == 400
        assert api(c, "POST", f"/routes/{route}/comments", tk["o"],
                   json={"content": "본인 댓글"}).status_code in (200, 201), "본인은 comments OFF 무관"
        ok("본인 route 댓글 통과 · self-kudos 400 유지")

        step("5. 가시성 우선 — 안 보이는 run은 설정 게이트 전에 404")
        priv = api(c, "POST", "/runs", tk["o"], json={
            "distance_km": 1.0, "duration_sec": 400, "visibility": "private"}).json()["id"]
        # V는 private run 못 봄 → likes_disabled(403)가 아니라 404 (은닉 우선)
        r = api(c, "POST", f"/runs/{priv}/kudos", tk["v"])
        assert r.status_code == 404, f"가시성 404 우선, got {r.status_code}"
        ok("비공개 run kudos 404 (설정 403보다 은닉 우선)")

        step("6. auto_publish OFF — 미지정 private·명시 존중")
        assert api(c, "PATCH", "/me/settings", tk["o"], json={"feed": {"auto_publish": False}}).status_code == 200
        r1 = api(c, "POST", "/runs", tk["o"], json={
            "distance_km": 1.5, "duration_sec": 600})  # visibility 미지정
        assert r1.json()["visibility"] == "private", f"미지정 → private: {r1.json()['visibility']}"
        r2 = api(c, "POST", "/runs", tk["o"], json={
            "distance_km": 1.5, "duration_sec": 600, "visibility": "public"})
        assert r2.json()["visibility"] == "public", "명시 public 존중"
        ok("auto_publish OFF: 미지정 private · 명시 public 존중")

        step("7. GET /me/settings — feed 3키 노출")
        s = api(c, "GET", "/me/settings", tk["o"]).json()
        assert s["feed"] == {"auto_publish": False, "allow_likes": True, "allow_comments": False}, s["feed"]
        # V(설정 안 건드림)는 전부 기본 True
        sv = api(c, "GET", "/me/settings", tk["v"]).json()
        assert sv["feed"] == {"auto_publish": True, "allow_likes": True, "allow_comments": True}
        ok("feed 설정 노출 · 미설정 유저 기본 True (breaking 0)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
