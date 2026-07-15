"""
Integration test: followers_run_count 프로필 표시 계약 (2026-07-15)

목표: 비팔로워가 프로필 볼 때 "followers 공개 run이 N개 존재·팔로우하면 보인다"
성립. A′ "숫자는 사실값, 리스트는 잠금" — 카운트만 노출, 목록·트랙 미노출.

매트릭스:
 1. public 계정 O(public 2·followers 3 run) 프로필을 비팔로워 S가 조회:
    public_run_count=2 · followers_run_count=3 (존재 노출) · locked=false
 2. 목록 잠금: GET /users/O/runs (S 비팔로워) → public 2건만, followers run 부재
    (트랙·제목·날짜 등 followers run 내용 응답 전체에 부재 — 이중검증)
 3. 팔로워 F가 조회: followers run이 목록에 노출(카운트는 동일)
 4. 잠금 계정 P(private) 프로필을 비팔로워 조회: locked=true ·
    followers_run_count=0(잠금) · public_run_count는 진실값
 5. 회귀: 기존 public_run_count·locked·차단 404 불변

Run: python tests/test_followers_run_count_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
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


def ok(m):         print(f"  ✓ {m}")
def fail(m, d=""):  print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):       print(f"\n[{t}]")


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


SECRET_TITLE = f"팔로워전용제목{TS}"


def save_run(c, tok, vis, title=None):
    r = api(c, "POST", "/runs", tok, json={
        "distance_km": 3.0, "duration_sec": 900, "visibility": vis,
        **({"title": title} if title else {})})
    assert r.status_code in (200, 201), r.text[:150]
    return r.json()["id"]


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    try:
        step("0. O(public)·S(비팔로워)·F(팔로워)·P(private) 준비")
        for k in ("o", "s", "f", "p"):
            uids[k] = sb_user(c, f"frc-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"frc-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"FRC{k}{TS}"}).status_code == 200
        # O: public 2 + followers 3 (followers run에 비밀 제목 — 목록 누출 이중검증용)
        for _ in range(2): save_run(c, tk["o"], "public")
        for _ in range(3): save_run(c, tk["o"], "followers", title=SECRET_TITLE)
        # P: private 계정, public 1 + followers 1
        assert api(c, "PATCH", "/me/profile", tk["p"], json={"visibility": "private"}).status_code == 200
        save_run(c, tk["p"], "public"); save_run(c, tk["p"], "followers")
        # F가 O 팔로우
        assert api(c, "POST", f"/users/{uids['o']}/follow", tk["f"]).status_code == 204
        ok("O(public: pub2·fol3) · P(private: pub1·fol1) · F→O 팔로우")

        step("1. 비팔로워 S가 O 프로필 → 카운트로 존재 노출")
        p = api(c, "GET", f"/users/{uids['o']}/profile", tk["s"]).json()
        assert p["locked"] is False, "public 계정은 잠금 아님"
        assert p["public_run_count"] == 2, f"public 2, got {p['public_run_count']}"
        assert p["followers_run_count"] == 3, f"followers 3(존재 노출), got {p['followers_run_count']}"
        assert p["is_following"] is False
        ok("비팔로워: public_run_count=2 · followers_run_count=3 · locked=false")

        step("2. 목록 잠금 — S에게 followers run 미노출 (프라이버시 이중검증)")
        r = api(c, "GET", f"/users/{uids['o']}/runs", tk["s"])
        d, raw = r.json(), r.text
        assert len(d) == 2, f"비팔로워 목록 public 2건만, got {len(d)}"
        assert all(x["run_id"] for x in d), "public run만"
        assert SECRET_TITLE not in raw, "followers run 제목이 응답 전체에 부재(내용 잠금)"
        ok(f"목록 public 2건만 · followers run 내용('{SECRET_TITLE[:10]}…') 무노출")

        step("3. 팔로워 F가 O 프로필·목록 → followers run 노출")
        pf = api(c, "GET", f"/users/{uids['o']}/profile", tk["f"]).json()
        assert pf["public_run_count"] == 2 and pf["followers_run_count"] == 3, "카운트 동일(사실값)"
        rf = api(c, "GET", f"/users/{uids['o']}/runs", tk["f"]).json()
        assert len(rf) == 5, f"팔로워는 public+followers 5건, got {len(rf)}"
        ok("팔로워: 카운트 동일 · 목록 5건(followers 노출)")

        step("4. 잠금 계정 P → followers_run_count=0(잠금), public은 진실값")
        pp = api(c, "GET", f"/users/{uids['p']}/profile", tk["s"]).json()
        assert pp["locked"] is True, "비공개 계정 비팔로워 → 잠금"
        assert pp["public_run_count"] == 1, f"잠금이어도 public 진실값 1, got {pp['public_run_count']}"
        assert pp["followers_run_count"] == 0, f"잠금 계정 followers_run_count=0, got {pp['followers_run_count']}"
        ok("잠금 계정: locked=true · public_run_count=1(진실값) · followers_run_count=0")

        step("5. 회귀 — 차단 404 · 본인 조회")
        assert api(c, "POST", f"/users/{uids['s']}/block", tk["o"]).status_code == 204
        assert api(c, "GET", f"/users/{uids['o']}/profile", tk["s"]).status_code == 404, "차단 404"
        api(c, "DELETE", f"/users/{uids['s']}/block", tk["o"])
        ok("차단 관계 404 은닉 (기존 게이트 불변)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (runs·follows·blocks cascade)")


if __name__ == "__main__":
    run_tests()
