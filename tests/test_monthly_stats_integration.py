"""
Integration test: monthly stats (GET /me/stats/monthly?year&month)
KST 월 경계·일별 그룹핑·전월 대비 delta 검증.
Run: python tests/test_monthly_stats_integration.py
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
            if   line.startswith("SUPABASE_KEY="):             anon = line.split("=",1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=",1)[1]
    return anon, svc

_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}

def ok(m):   print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")

def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200,201): fail("create user", r.text[:200])
    return r.json()["id"]

def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type":"application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]

def sb_del_user(c, uid): c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)

def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer":"return=minimal"},
             params={col: f"in.({',' .join(vals)})"})

def sb_insert_run(c, uid, ran_at_utc, km, sec):
    r = c.post(f"{_SB}/rest/v1/runs",
               headers={**_ADM, "Prefer":"return=minimal"},
               json={"user_id": uid, "ran_at": ran_at_utc,
                     "distance_km": km, "duration_sec": sec})
    if r.status_code not in (200,201): fail("insert run", r.text[:200])

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"ms-u{i}-{ts}@t.l" for i in range(1,3)]
    uids: list[str] = []
    toks: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            step("1. 유저 2명 생성")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2 = uids; tok1, tok2 = toks
            ok(f"u1={uid1[:8]}… u2={uid2[:8]}…")

            step("2. 2026년 6월 기준 러닝 시딩 (KST 경계 포함)")
            # KST 시각 → UTC로 변환해 저장
            sb_insert_run(c, uid1, "2026-05-31T15:30:00+00:00", 2.0, 700)   # 6/1 00:30 KST (경계)
            sb_insert_run(c, uid1, "2026-06-04T23:00:00+00:00", 5.0, 1500)  # 6/5 08:00 KST
            sb_insert_run(c, uid1, "2026-06-05T11:00:00+00:00", 3.0, 1080)  # 6/5 20:00 KST (같은 날 2회)
            sb_insert_run(c, uid1, "2026-06-19T22:00:00+00:00", 10.0, 3600) # 6/20 07:00 KST
            sb_insert_run(c, uid1, "2026-07-01T22:00:00+00:00", 4.0, 1400)  # 7월 (제외 대상)
            sb_insert_run(c, uid1, "2026-05-10T00:00:00+00:00", 5.0, 1800)  # 5월 (delta용)
            sb_insert_run(c, uid2, "2026-06-10T00:00:00+00:00", 7.0, 2400)  # 남의 기록 (격리)
            ok("u1 6회 + u2 1회 시딩")

            step("3. 6월 조회: 합계·일별·delta")
            r = api(c, "GET", "/me/stats/monthly", tok1,
                    params={"year": 2026, "month": 6})
            assert r.status_code == 200, r.text[:200]
            d = r.json()
            assert d["year"] == 2026 and d["month"] == 6
            s = d["stats"]
            assert s["run_count"] == 4, f"6월 4회여야 함 (KST 경계 포함), got {s['run_count']}"
            assert s["total_distance_km"] == 20.0, f"합계 20.0, got {s['total_distance_km']}"
            assert s["total_duration_sec"] == 6880
            assert s["avg_pace_sec_per_km"] == 344   # 6880/20
            assert s["longest_run_km"] == 10.0
            assert s["delta_distance_km"] == 15.0, f"5월(5.0) 대비 +15.0, got {s['delta_distance_km']}"
            ok("run_count=4 ✓ 20.0km ✓ pace 344 ✓ delta +15.0 ✓ (u2 기록 미포함)")

            step("4. 일별 내역 (캘린더 점): 날짜·합산·정렬")
            days = d["days"]
            assert [x["date"] for x in days] == ["2026-06-01", "2026-06-05", "2026-06-20"], \
                f"일별 날짜 불일치: {[x['date'] for x in days]}"
            by = {x["date"]: x for x in days}
            assert by["2026-06-01"]["distance_km"] == 2.0 and by["2026-06-01"]["run_count"] == 1
            assert by["2026-06-05"]["distance_km"] == 8.0 and by["2026-06-05"]["run_count"] == 2
            assert by["2026-06-20"]["distance_km"] == 10.0 and by["2026-06-20"]["run_count"] == 1
            ok("UTC 5/31 저장분이 KST 6/1로 잡힘 ✓ 같은 날 2회 합산 ✓ 오름차순 ✓")

            step("5. 7월 조회 + 빈 달 + 검증 오류")
            d = api(c, "GET", "/me/stats/monthly", tok1,
                    params={"year": 2026, "month": 7}).json()
            assert d["stats"]["total_distance_km"] == 4.0 and d["stats"]["run_count"] == 1
            assert d["stats"]["delta_distance_km"] == -16.0, "6월 20 대비 -16.0"
            d = api(c, "GET", "/me/stats/monthly", tok1,
                    params={"year": 2025, "month": 1}).json()
            assert d["stats"]["run_count"] == 0 and d["days"] == []
            r = api(c, "GET", "/me/stats/monthly", tok1,
                    params={"year": 2026, "month": 13})
            assert r.status_code == 422, f"month=13 → 422, got {r.status_code}"
            ok("7월 4.0km·delta -16.0 ✓ 빈 달 0 ✓ month=13 422 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "runs", "user_id", [u for u in uids if u])
            ok("runs 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
