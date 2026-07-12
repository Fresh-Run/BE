"""
Integration test: 감사 3차 배치2 — M-4·M-7·M-5

M-4: 둘러보기 피드(GET /routes/public)가 차단·비공개 계정 owner 코스 제외
     (Decision B를 검색+둘러보기로 확장).
M-7: ProfileUpdate·RunUpdate에 extra=forbid — 오타/미지 키 422(silent swallow 봉쇄).
M-5: cover_url/icon_url은 크루 자체 crew-images 경로만 허용 — 외부/타크루 URL 422.

Run: python tests/test_audit3_batch2_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time, uuid
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


def make_route(c, owner_id, summary):
    r = c.post(f"{_SB}/rest/v1/routes", headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": owner_id, "summary": summary, "target_distance_km": 3.0,
                     "total_distance_km": 3.0, "estimated_duration_min": 20, "waypoints": [],
                     "polyline": [], "start_lat": 37.5, "start_lng": 127.0, "is_public": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()[0]["id"]


def summaries(feed):
    return {r["summary"] for r in feed}


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. A(뷰어)·B(차단 대상)·C(비공개 계정)")
        for k in ("a", "b", "c"):
            uids[k] = sb_user(c, f"a3b2-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"a3b2-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"A3B2{k}{TS}"}).status_code == 200
        sum_b, sum_c = f"A3B2코스B{TS}", f"A3B2코스C{TS}"
        make_route(c, uids["b"], sum_b)
        make_route(c, uids["c"], sum_c)
        ok("유저 3 + B·C 공개 코스")

        step("1. M-4 둘러보기 — 차단/비공개 전엔 B·C 코스 보임")
        feed = api(c, "GET", "/routes/public?limit=100", tk["a"]).json()
        assert sum_b in summaries(feed) and sum_c in summaries(feed), "차단·비공개 전 노출"
        ok("차단/비공개 전 B·C 코스 둘러보기 노출")

        step("2. M-4 — A가 B 차단 + C 계정 비공개 → 둘러보기 제외")
        assert api(c, "POST", f"/users/{uids['b']}/block", tk["a"]).status_code == 204
        assert api(c, "PATCH", "/me/profile", tk["c"], json={"visibility": "private"}).status_code == 200
        feed = api(c, "GET", "/routes/public?limit=100", tk["a"]).json()
        assert sum_b not in summaries(feed), "차단 상대 코스 둘러보기 제외"
        assert sum_c not in summaries(feed), "비공개 계정(비팔로워) 코스 둘러보기 제외"
        ok("차단 상대·비공개 계정 코스 둘러보기 제외 (검색과 동형)")

        step("3. M-7 ProfileUpdate extra=forbid — 오타 키 422")
        r = api(c, "PATCH", "/me/profile", tk["a"], json={"visibilty": "private"})  # 오타
        assert r.status_code == 422, f"오타 visibility 키 → 422 기대(구: 200 silent), got {r.status_code}"
        r = api(c, "PATCH", "/me/profile", tk["a"], json={"follow_aproval": True})  # 오타
        assert r.status_code == 422, f"오타 follow_approval 키 → 422, got {r.status_code}"
        assert api(c, "PATCH", "/me/profile", tk["a"], json={"visibility": "private"}).status_code == 200
        assert api(c, "PATCH", "/me/profile", tk["a"], json={"visibility": "public"}).status_code == 200
        ok("ProfileUpdate 오타 키 422 · 정상 키 200")

        step("4. M-7 RunUpdate extra=forbid — 오타 키 422")
        now = datetime.now(timezone.utc)
        run_id = c.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=representation"},
                        json={"user_id": uids["a"], "distance_km": 2.0, "duration_sec": 720,
                              "ran_at": now.isoformat(), "verification": "verified",
                              "visibility": "public"}).json()[0]["id"]
        r = api(c, "PATCH", f"/runs/{run_id}", tk["a"], json={"titel": "오타"})  # 오타
        assert r.status_code == 422, f"RunUpdate 오타 키 → 422 기대, got {r.status_code}"
        assert api(c, "PATCH", f"/runs/{run_id}", tk["a"], json={"title": "정상"}).status_code == 200
        ok("RunUpdate 오타 키 422 · 정상 키 200")

        step("5. M-5 cover_url — 자체 버킷 경로만 허용")
        crew = api(c, "POST", "/crews", tk["a"], json={"name": f"A3B2크루{TS}"}).json()["id"]
        pub = api(c, "POST", f"/crews/{crew}/cover/upload-url", tk["a"]).json()["public_url"]
        assert api(c, "PATCH", f"/crews/{crew}", tk["a"], json={"cover_url": pub}).status_code == 200
        assert api(c, "PATCH", f"/crews/{crew}", tk["a"], json={"cover_url": pub + "?v=123"}).status_code == 200
        r = api(c, "PATCH", f"/crews/{crew}", tk["a"], json={"cover_url": "https://evil.example/x.jpg"})
        assert r.status_code == 422, f"외부 URL → 422 기대, got {r.status_code}"
        other = f"https://x/storage/v1/object/public/crew-images/{uuid.uuid4()}/cover"
        r = api(c, "PATCH", f"/crews/{crew}", tk["a"], json={"icon_url": other})
        assert r.status_code == 422, f"타 크루 경로 → 422 기대, got {r.status_code}"
        db = c.get(f"{_SB}/rest/v1/crews", headers=_ADM, params={"id": f"eq.{crew}", "select": "cover_url"}).json()[0]
        assert db["cover_url"] and db["cover_url"].startswith(pub), f"거부돼도 정상값 유지, got {db}"
        api(c, "DELETE", f"/crews/{crew}", tk["a"])
        ok("cover/icon_url 자체 경로+캐시버스터 200 · 외부/타크루 422 · DB 미오염")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
