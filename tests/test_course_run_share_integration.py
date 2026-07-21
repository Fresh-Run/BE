"""
Integration test: 코스-런 비율 소셜프루프 GET /stats/course-run-share (Ivan 퍼널 v1)

케이스:
 1. me scope 정확성 — window 내 route 8 + plain 12 = 20 → total 20·course 8·share 0.4
 2. route_id 카운트 정확 (course = route_id not null 수)
 3. window 경계 — 35일 전 run은 미집계(ran_at gte cutoff)
 4. 임계 미만 null — 19 run(<20) 유저 → share null (total/course는 실수)
 5. window_days 파라미터 — 90 상한 clamp, 기본 30
 6. scope 분리 + global 데모 제외 — global total > me(임시유저), 데모 course 미포함

Run: python tests/test_course_run_share_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timedelta, timezone
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
_ADMR = {**_ADM, "Prefer": "return=representation"}
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


def iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def insert_runs(c, uid, route_id, n, days_ago, with_route):
    """admin REST로 run 직접 insert (ran_at·route_id 지정 — POST /runs는 now() 강제)."""
    rows = [{"user_id": uid, "distance_km": 5.0, "duration_sec": 1800,
             "ran_at": iso(days_ago), "route_id": route_id if with_route else None}
            for _ in range(n)]
    r = c.post(f"{_SB}/rest/v1/runs", headers=_ADM, json=rows)
    assert r.status_code in (200, 201), r.text[:200]


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    route_id = None
    try:
        step("0. 임시 유저 U(20 run)·V(19 run) + 임시 route")
        for k in ("u", "v"):
            uids[k] = sb_user(c, f"crs-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"crs-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CRS{k}{TS}"}).status_code == 200
        route_id = c.post(f"{_SB}/rest/v1/routes", headers=_ADMR,
                          json={"user_id": uids["u"], "summary": "임시", "total_distance_km": 5.0,
                                "waypoints": [], "is_public": True}).json()[0]["id"]
        # U: window 내(5일 전) route 8 + plain 12 = 20
        insert_runs(c, uids["u"], route_id, 8, days_ago=5, with_route=True)
        insert_runs(c, uids["u"], route_id, 12, days_ago=5, with_route=False)
        # U: window 밖(35일 전) route 3 (미집계 대상)
        insert_runs(c, uids["u"], route_id, 3, days_ago=35, with_route=True)
        # V: window 내 route 5 + plain 14 = 19 (<20 임계)
        insert_runs(c, uids["v"], route_id, 5, days_ago=5, with_route=True)
        insert_runs(c, uids["v"], route_id, 14, days_ago=5, with_route=False)
        ok("U 20 run(route 8) + window밖 3 · V 19 run(route 5)")

        step("1·2·3. me scope — total 20·course 8·share 0.4 (window 밖 3 미집계, route_id 카운트)")
        d = api(c, "GET", "/stats/course-run-share", tk["u"], params={"scope": "me"}).json()
        assert d["scope"] == "me" and d["window_days"] == 30, d
        assert d["total_runs"] == 20, f"window 내 20(35일 전 3 제외), got {d['total_runs']}"
        assert d["course_runs"] == 8, f"route_id not null 8, got {d['course_runs']}"
        assert d["share"] == 0.4, f"8/20=0.4, got {d['share']}"
        ok(f"me: total=20 course=8 share=0.4 · window 밖 3 미집계 · route_id 카운트 정확")

        step("4. 임계 미만 null — V 19 run(<20) → share null, total/course는 실수")
        d = api(c, "GET", "/stats/course-run-share", tk["v"], params={"scope": "me"}).json()
        assert d["total_runs"] == 19 and d["course_runs"] == 5, d
        assert d["share"] is None, f"total<20 → share null, got {d['share']}"
        ok(f"V: total=19 course=5 share=null (임계 20 미만 방어)")

        step("5. window_days — 90 상한 clamp / 기본 30")
        d90 = api(c, "GET", "/stats/course-run-share", tk["u"], params={"scope": "me", "window_days": 90}).json()
        assert d90["window_days"] == 90 and d90["total_runs"] == 23, \
            f"90일이면 35일 전 3도 포함 → 23, got {d90['total_runs']}"
        d_clamp = api(c, "GET", "/stats/course-run-share", tk["u"], params={"scope": "me", "window_days": 500})
        assert d_clamp.status_code == 422, "상한 90 초과는 422(Query le=90)"
        ok("window_days=90 → 35일 전 포함(23) · 500 → 422 clamp")

        step("6. scope 분리 + global 데모 제외")
        g = api(c, "GET", "/stats/course-run-share", tk["u"], params={"scope": "global"}).json()
        assert g["scope"] == "global", g
        # global은 U(20)+다른 실/임시 포함이나 데모 제외 → U의 course 8은 반영
        assert g["course_runs"] >= 8, f"global course에 U의 8 포함, got {g['course_runs']}"
        # 데모 제외 검증: 데모 소유 window내 course run 수를 직접 세어, global course에
        # 그게 안 더해졌는지 확인
        demo_emails = {"test1@freshrun.com", "test2@freshrun.com"} | {f"demo{i}@freshrun.com" for i in range(1, 6)}
        users = {u["email"]: u["id"] for u in c.get(f"{_SB}/auth/v1/admin/users?page=1&per_page=200", headers=_ADM).json()["users"] if u.get("email")}
        demo_uids = [users[e] for e in demo_emails if e in users]
        cutoff = iso(30)
        dq = c.get(f"{_SB}/rest/v1/runs?ran_at=gte.{cutoff}&route_id=not.is.null&user_id=in.({','.join(demo_uids)})&select=id",
                   headers={**_ADM, "Prefer": "count=exact", "Range": "0-0"})
        demo_course = int(dq.headers["content-range"].split("/")[1])
        # 전체(데모 포함) course run
        aq = c.get(f"{_SB}/rest/v1/runs?ran_at=gte.{cutoff}&route_id=not.is.null&select=id",
                   headers={**_ADM, "Prefer": "count=exact", "Range": "0-0"})
        all_course = int(aq.headers["content-range"].split("/")[1])
        assert g["course_runs"] == all_course - demo_course, \
            f"global course({g['course_runs']}) = 전체({all_course}) − 데모({demo_course})"
        ok(f"global course={g['course_runs']} = 전체 {all_course} − 데모 {demo_course}(제외 확인) · scope 분리")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/rest/v1/runs?user_id=eq.{uid}", headers=_ADM)
            c.delete(f"{_SB}/rest/v1/routes?user_id=eq.{uid}", headers=_ADM)
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (임시 유저·run·route)")


if __name__ == "__main__":
    run_tests()
