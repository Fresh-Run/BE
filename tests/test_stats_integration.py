"""
Integration test: GET /api/me/stats (personal running statistics)
Run: python tests/test_stats_integration.py
"""
from __future__ import annotations

import os, sys, time
import httpx
from datetime import datetime, timedelta, timezone

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"
_KST = timezone(timedelta(hours=9))


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

def sb_insert_run(c, uid, distance_km, duration_sec, ran_at_iso):
    """Insert a run row directly with explicit ran_at (bypassing the API)."""
    r = c.post(f"{_SB}/rest/v1/runs",
               headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": uid, "distance_km": distance_km,
                     "duration_sec": duration_sec, "ran_at": ran_at_iso})
    if r.status_code not in (200, 201): fail("insert run", r.text[:200])
    return r.json()[0]["id"]

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def get_stats(c, tok):
    r = api(c, "GET", "/me/stats", tok)
    assert r.status_code == 200, f"GET /me/stats → 200 이어야 함, got {r.status_code}: {r.text[:200]}"
    return r.json()


def this_week_ts() -> str:
    """ISO timestamp for Tuesday noon KST of this week (safely within this week)."""
    now_kst = datetime.now(_KST)
    monday = (now_kst - timedelta(days=now_kst.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (monday + timedelta(days=1, hours=12)).isoformat()  # Tuesday noon KST


def last_week_ts() -> str:
    """ISO timestamp for Wednesday noon KST of last week."""
    now_kst = datetime.now(_KST)
    monday = (now_kst - timedelta(days=now_kst.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    last_monday = monday - timedelta(weeks=1)
    return (last_monday + timedelta(days=2, hours=12)).isoformat()  # Wednesday noon KST


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"st-u{i}-{ts}@t.s" for i in range(1, 3)]
    uids: list[str] = []; toks: list[str] = []
    run_ids: list[str] = []

    this_week = this_week_ts()
    last_week = last_week_ts()

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 2명 ───────────────────────────────────────────────
            step("1. 유저 2명 생성 + 로그인")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2 = uids; tok1, tok2 = toks
            ok(f"u1={uid1[:8]}(기록 있는 유저)  u2={uid2[:8]}(기록 없는 유저)")

            # ── 2. 이번 주 러닝 3개 삽입 ─────────────────────────────────
            # Run A: 5km, 1500sec → pace = 300 sec/km
            # Run B: 3km, 1200sec → pace = 400 sec/km
            # Run C: 7km, 2450sec → pace = 350 sec/km
            # 단순평균 pace = 350, 거리가중 pace = 5150/15 = 343
            step("2. 이번 주 러닝 3개 삽입 (5km+3km+7km = 15km)")
            run_ids.append(sb_insert_run(c, uid1, 5.0, 1500, this_week))
            run_ids.append(sb_insert_run(c, uid1, 3.0, 1200, this_week))
            run_ids.append(sb_insert_run(c, uid1, 7.0, 2450, this_week))
            ok(f"this_week 러닝 3개 삽입 (ran_at≈{this_week[:16]})")

            # ── 3. 지난 주 러닝 1개 삽입 ─────────────────────────────────
            step("3. 지난 주 러닝 1개 삽입 (6km)")
            run_ids.append(sb_insert_run(c, uid1, 6.0, 2400, last_week))
            ok(f"last_week 러닝 1개 삽입 (ran_at≈{last_week[:16]})")

            # ── 4. /me/stats 조회 후 week 검증 ───────────────────────────
            step("4. GET /me/stats → week 통계 검증")
            stats = get_stats(c, tok1)
            w = stats["week"]

            assert w["total_distance_km"] == 15.0, \
                f"week total_distance_km 15.0 이어야 함, got {w['total_distance_km']}"
            assert w["run_count"] == 3, \
                f"week run_count 3 이어야 함, got {w['run_count']}"
            assert w["longest_run_km"] == 7.0, \
                f"week longest_run_km 7.0 이어야 함, got {w['longest_run_km']}"
            ok(f"total_distance_km=15 ✓  run_count=3 ✓  longest=7 ✓")

            # ── 5. 거리 가중 페이스 확인 (단순평균 350 ≠ 가중 343) ────────
            step("5. avg_pace_sec_per_km 거리 가중 확인")
            pace = w["avg_pace_sec_per_km"]
            expected_weighted = round(5150 / 15)  # = 343
            expected_simple   = 350               # (300+400+350)/3
            assert pace == expected_weighted, \
                f"거리 가중 페이스 {expected_weighted} 이어야 함, got {pace}"
            assert pace != expected_simple, \
                f"단순평균({expected_simple})과 달라야 함, got {pace}"
            ok(f"avg_pace={pace} sec/km ✓  (거리 가중={expected_weighted}, 단순평균={expected_simple})")

            # ── 6. delta_distance_km (이번 주 - 지난 주) ─────────────────
            step("6. delta_distance_km = 15 - 6 = 9.0")
            delta = w["delta_distance_km"]
            assert delta == 9.0, \
                f"delta_distance_km 9.0 이어야 함, got {delta}"
            ok(f"delta_distance_km={delta} ✓")

            # ── 7. all_time 통계 + delta=null ─────────────────────────────
            step("7. all_time: 총 4회, 21km, delta=null")
            at = stats["all_time"]
            assert at["total_distance_km"] == 21.0, \
                f"all_time total_distance_km 21.0 이어야 함, got {at['total_distance_km']}"
            assert at["run_count"] == 4, \
                f"all_time run_count 4 이어야 함, got {at['run_count']}"
            assert at["delta_distance_km"] is None, \
                f"all_time delta는 null이어야 함, got {at['delta_distance_km']}"
            ok(f"all_time: total=21 ✓  run_count=4 ✓  delta=null ✓")

            # ── 8. 기록 없는 유저(u2) → 0/null ──────────────────────────
            step("8. 기록 없는 유저(u2) → 전 기간 0/null")
            stats2 = get_stats(c, tok2)
            for period in ("week", "month", "all_time"):
                p = stats2[period]
                assert p["total_distance_km"] == 0.0, \
                    f"u2 {period} total_distance_km 0 이어야 함, got {p['total_distance_km']}"
                assert p["run_count"] == 0, \
                    f"u2 {period} run_count 0 이어야 함, got {p['run_count']}"
                assert p["avg_pace_sec_per_km"] is None, \
                    f"u2 {period} avg_pace None 이어야 함, got {p['avg_pace_sec_per_km']}"
                assert p["longest_run_km"] is None, \
                    f"u2 {period} longest None 이어야 함, got {p['longest_run_km']}"
            ok("u2 전 기간 0/null ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)

        finally:
            step("Cleanup")
            sb_del_in(c, "runs", "id", run_ids)
            ok("runs 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")


if __name__ == "__main__":
    run()
