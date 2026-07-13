"""
Integration test: 비공개 프로필 v1 (docs/PRIVATE_PROFILE_DESIGN.md)

profile visibility × run visibility 3×3 조합 매트릭스(비팔로워 뷰어) +
팔로워는 프로필 게이트 통과 + 크루원도 비팔로워면 locked(결정 A′)·run은 ⓑ 탭스루 + 잠금 응답(locked) +
공개 프로필 탭 빈 목록 + 검색 제외(결정 B) + 본인 무영향.

Run: python tests/test_private_profile_integration.py  (로컬 서버 필요)
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
    step_m = 22.24
    n = round(dist * 1000 / step_m) + 1
    t0 = (TS - 7200) * 1000
    return [{"lat": 37.5445 + i * 0.0002, "lng": 127.0374, "t": t0 + i * round(step_m * pace),
             "acc": 5.0} for i in range(n)]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. O(대상)·V(비팔로워)·F(팔로워)·M(크루원) + O의 run 3종")
        for k in ("o", "v", "f", "m"):
            uids[k] = sb_user(c, f"pp-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"pp-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"PP{k}{TS}"}).status_code == 200
        assert api(c, "POST", f"/users/{uids['o']}/follow", tk["f"]).status_code == 204  # F→O 팔로우
        crew = api(c, "POST", "/crews", tk["o"], json={"name": f"PP크루{TS}"}).json()["id"]
        assert api(c, "POST", f"/crews/{crew}/join", tk["m"]).status_code == 200  # M 크루원
        now = datetime.now(timezone.utc)
        runs = {}
        for i, vis in enumerate(("public", "followers", "private")):
            d = api(c, "POST", "/runs", tk["o"], json={
                "distance_km": 2.0, "duration_sec": 720, "visibility": vis,
                "gps_track": _track(2.0)}).json()
            runs[vis] = d["id"]
        ok("유저 4명 + F팔로우·M크루 + run public/followers/private")

        step("1. 프로필 public일 때 3×3 (현행 동작 — 비팔로워 V)")
        # public 계정: run public만 보임(비팔로워)
        assert api(c, "GET", f"/runs/{runs['public']}", tk["v"]).status_code == 200
        assert api(c, "GET", f"/runs/{runs['followers']}", tk["v"]).status_code == 404
        assert api(c, "GET", f"/runs/{runs['private']}", tk["v"]).status_code == 404
        prof = api(c, "GET", f"/users/{uids['o']}/profile", tk["v"]).json()
        assert prof["locked"] is False and prof["public_run_count"] >= 1
        ok("public 계정: run public 200·나머지 404·프로필 unlocked (현행 보존)")

        step("2. 프로필 private로 전환 → 비팔로워 V는 전면 잠금")
        assert api(c, "PATCH", "/me/profile", tk["o"],
                   json={"nickname": f"PPo{TS}", "visibility": "private"}).status_code == 200
        # 3×3의 비공개 계정 행: run 무관하게 전부 404
        for vis in ("public", "followers", "private"):
            r = api(c, "GET", f"/runs/{runs[vis]}", tk["v"])
            assert r.status_code == 404, f"private 계정 run {vis}: 404 기대, got {r.status_code}"
        # 프로필 잠금 응답 — 카운트는 진실값(2026-07-13 계약: 0은 프라이버시가
        # 아니라 오보), bio·콘텐츠·명단은 잠금.
        p = api(c, "GET", f"/users/{uids['o']}/profile", tk["v"]).json()
        assert p["locked"] is True and p["visibility"] == "private"
        assert p["bio"] is None, "잠금: bio는 여전히 null"
        assert p["follower_count"] == 1, f"잠금이어도 팔로워 수 진실값(F→O 1), got {p['follower_count']}"
        assert p["following_count"] == 0, f"팔로잉 수 진실값(O는 팔로잉 0), got {p['following_count']}"
        assert p["public_run_count"] == 1, f"공개 러닝 수 진실값(public 1), got {p['public_run_count']}"
        assert p["nickname"] and "user_id" in p, "닉네임은 잠금 화면에 노출"
        # 콘텐츠·명단은 잠금: 러닝 탭 빈 목록 + 팔로워/팔로잉 명단 빈 목록(비대칭 요점)
        assert api(c, "GET", f"/users/{uids['o']}/runs", tk["v"]).json() == []
        assert api(c, "GET", f"/users/{uids['o']}/followers", tk["v"]).json() == [], "잠금: 팔로워 명단 차단"
        assert api(c, "GET", f"/users/{uids['o']}/following", tk["v"]).json() == [], "잠금: 팔로잉 명단 차단"
        # 언락(팔로워 F)은 명단 접근 가능 — 무영향 확인
        assert len(api(c, "GET", f"/users/{uids['o']}/followers", tk["f"]).json()) >= 1, "팔로워는 명단 열람"
        ok("비공개 계정: 카운트 진실값·bio null·러닝/팔로워/팔로잉 명단 잠금·팔로워는 명단 열람")

        step("3. 팔로워 F는 프로필 게이트 통과 (run 축만 적용)")
        assert api(c, "GET", f"/runs/{runs['public']}", tk["f"]).status_code == 200
        assert api(c, "GET", f"/runs/{runs['followers']}", tk["f"]).status_code == 200  # 팔로워
        assert api(c, "GET", f"/runs/{runs['private']}", tk["f"]).status_code == 404   # 본인만
        pf = api(c, "GET", f"/users/{uids['o']}/profile", tk["f"]).json()
        assert pf["locked"] is False and pf["public_run_count"] >= 1
        assert len(api(c, "GET", f"/users/{uids['o']}/runs", tk["f"]).json()) >= 2  # public+followers
        ok("팔로워: 프로필 통과·public/followers run 200·private 404")

        step("4. 크루원 M — 결정 A′: 프로필은 잠기되(비팔로워) run은 크루 탭스루(ⓑ)")
        assert api(c, "GET", f"/runs/{runs['public']}", tk["m"]).status_code == 200
        assert api(c, "GET", f"/runs/{runs['followers']}", tk["m"]).status_code == 200  # ⓑ: 크루 노출 run 탭스루
        assert api(c, "GET", f"/runs/{runs['private']}", tk["m"]).status_code == 404, "private run은 ⓑ 제외"
        pm = api(c, "GET", f"/users/{uids['o']}/profile", tk["m"]).json()
        assert pm["locked"] is True, "A′: 비팔로워 크루원은 프로필 locked (크루 예외는 크루 서피스로 한정)"
        ok("A′: 크루원 비팔로워 프로필 locked·히스토리 잠김 / 크루 문맥 run은 ⓑ로 200(private 404)")

        step("5. 검색 — 비공개 계정 코스 제외 (결정 B)")
        summ = f"PP검색코스{TS}"
        c.post(f"{_SB}/rest/v1/routes", headers=_ADM, json={
            "user_id": uids["o"], "summary": summ, "target_distance_km": 3.0,
            "total_distance_km": 3.0, "estimated_duration_min": 20, "waypoints": [],
            "polyline": [], "start_lat": 37.5, "start_lng": 127.0, "is_public": True})
        v_res = api(c, "GET", f"/routes/search?q=PP검색코스{TS}", tk["v"]).json()
        assert not any(r["summary"] == summ for r in v_res), "비공개 계정 코스는 V 검색에서 제외"
        f_res = api(c, "GET", f"/routes/search?q=PP검색코스{TS}", tk["f"]).json()
        assert any(r["summary"] == summ for r in f_res), "팔로워는 검색됨"
        ok("V 검색 제외·F 검색 노출 ✓")

        step("6. 본인·public 복귀 무영향")
        # O 본인은 자기 것 전부
        assert api(c, "GET", f"/runs/{runs['private']}", tk["o"]).status_code == 200
        assert api(c, "GET", "/me/profile", tk["o"]).json()["visibility"] == "private"
        # public 복귀 → V 다시 public run 200
        assert api(c, "PATCH", "/me/profile", tk["o"],
                   json={"nickname": f"PPo{TS}", "visibility": "public"}).status_code == 200
        assert api(c, "GET", f"/runs/{runs['public']}", tk["v"]).status_code == 200
        ok("본인 전체 접근·GET /me visibility·public 복귀 후 200")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        if "o" in uids:
            api(c, "DELETE", f"/crews/{crew}", tk["o"])
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
