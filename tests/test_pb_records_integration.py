"""
Integration test: 개인 최고 기록 (PB)
1) 결정론 순수 함수 — _compute_records 4종·자격조건·pace 파생·5K 환산·동률
2) 통합 (본 서버 8000) — POST /runs new_records 경신 감지 + GET /me/stats records
Run: python tests/test_pb_records_integration.py
"""
from __future__ import annotations

import os
import sys
import time

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
    anon = svc = ""
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                svc = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(m):
    print(f"  ✓ {m}")


def fail(m, d=""):
    print(f"  ✗ {m}" + (f": {d}" if d else ""))
    sys.exit(1)


def step(t):
    print(f"\n[{t}]")


def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201):
        fail("create user", r.text[:200])
    return r.json()["id"]


def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200:
        fail("login", r.text[:200])
    return r.json()["access_token"]


def sb_del_user(c, uid):
    c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)


def sb_del_in(c, table, col, vals):
    if not vals:
        return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})


# ═══ Phase 1: 결정론 순수 함수 ════════════════════════════════════════════════

def phase1():
    from app.models.schemas import RunRequest
    from app.services import run_service as rs

    def row(i, ran_at, d, dur, pace=None):
        return {"id": f"r{i}", "ran_at": ran_at, "distance_km": d,
                "duration_sec": dur, "avg_pace_sec_per_km": pace}

    step("1-1. 4종 정상 계산 + 빈 rows")
    b = rs._compute_records([])
    assert (b.best_pace, b.best_5k, b.longest_distance, b.longest_duration) == (None,) * 4
    rows = [
        row(1, "2026-06-01T09:00:00+00:00", 6.0, 2160, 360),  # 6km 36' pace 360
        row(2, "2026-06-02T09:00:00+00:00", 2.0, 600, 300),   # 2km 10' pace 300
        row(3, "2026-06-03T09:00:00+00:00", 3.0, 1080, 360),  # 3km 18'
    ]
    b = rs._compute_records(rows)
    assert b.best_pace.value == 300 and b.best_pace.run_id == "r2"
    assert b.best_5k.value == 1800 and b.best_5k.run_id == "r1"  # 2160*5/6
    assert b.longest_distance.value == 6.0 and b.longest_distance.run_id == "r1"
    assert b.longest_duration.value == 2160 and b.longest_duration.run_id == "r1"
    assert b.best_pace.ran_at == "2026-06-02T09:00:00+00:00" and b.best_pace.distance_km == 2.0
    ok("4종 값·run_id·ran_at ✓ 빈 rows → 전부 null ✓")

    step("1-2. 최소 거리 조건 (0.5km 초고속 → best_pace 제외)")
    b = rs._compute_records(rows + [row(4, "2026-06-04T09:00:00+00:00", 0.5, 90, 180)])
    assert b.best_pace.value == 300, "0.5km run이 best_pace를 차지하면 안 됨"
    assert b.best_pace.run_id == "r2"
    ok("1km 미만 run은 best_pace 자격 없음 ✓ (다른 PB에는 영향 없음)")

    step("1-3. pace 파생 (avg_pace null → duration/distance)")
    b = rs._compute_records([row(5, "2026-06-05T09:00:00+00:00", 2.0, 580, None)])
    assert b.best_pace.value == 290, b.best_pace  # round(580/2)
    ok("파생 pace 290 ✓")

    step("1-4. 5K 환산 (4.9km 제외, 7km는 환산)")
    b = rs._compute_records([
        row(6, "2026-06-06T09:00:00+00:00", 4.9, 1400, None),   # 자격 미달
        row(7, "2026-06-07T09:00:00+00:00", 7.0, 2240, None),   # 환산 1600
    ])
    assert b.best_5k.value == 1600 and b.best_5k.run_id == "r7", b.best_5k
    ok("4.9km 제외 ✓ 7km → round(2240·5/7)=1600 ✓")

    step("1-5. 동률 → 먼저 달성한 run 유지")
    b = rs._compute_records([
        row(9, "2026-06-09T09:00:00+00:00", 3.0, 900, 300),   # 나중 (입력 순서는 앞)
        row(8, "2026-06-08T09:00:00+00:00", 2.0, 600, 300),   # 먼저
    ])
    assert b.best_pace.run_id == "r8", "같은 페이스면 먼저 달성한 run이 유지돼야 함"
    b2 = rs._compute_records([
        row(10, "2026-06-10T09:00:00+00:00", 5.0, 1500, None),
        row(11, "2026-06-11T09:00:00+00:00", 5.0, 1500, None),  # 모든 값 동률
    ])
    assert all(e.run_id == "r10" for e in
               (b2.best_pace, b2.best_5k, b2.longest_distance, b2.longest_duration))
    ok("pace 동률 ✓ 전 종목 동률 ✓ (strict 비교)")

    step("1-6. _detect_new_records 스냅샷 규칙")
    assert rs._detect_new_records([], RunRequest(distance_km=5, duration_sec=1500)) == []
    # 종전 기록이 있는 종류만 경신 대상 (4km run들만 있으면 best_5k는 첫 자격이라 미포함)
    prev = [row(12, "2026-06-12T09:00:00+00:00", 4.0, 1300, None)]
    nr = rs._detect_new_records(prev, RunRequest(distance_km=6.0, duration_sec=1800))
    types = {n.type for n in nr}
    assert "best_5k" not in types, "종전 5K 기록이 없으면 경신이 아님"
    assert {"best_pace", "longest_distance", "longest_duration"} <= types
    pace_rec = next(n for n in nr if n.type == "best_pace")
    assert (pace_rec.previous, pace_rec.current) == (325.0, 300.0)
    assert pace_rec.improvement_pct == 7.7  # (325-300)/325
    ok("첫 run [] ✓ 종류별 첫 자격 미포함 ✓ improvement_pct 7.7 ✓")


# ═══ Phase 2: 통합 (본 서버 8000) ════════════════════════════════════════════

def phase2(c, tok, uid):
    def api(method, path, **kw):
        return c.request(method, f"{BASE}{path}",
                         headers={"Authorization": f"Bearer {tok}"}, **kw)

    def save_run(d, dur, pace=None):
        body = {"distance_km": d, "duration_sec": dur}
        if pace is not None:
            body["avg_pace_sec_per_km"] = pace
        r = api("POST", "/runs", json=body)
        assert r.status_code == 200, r.text[:300]
        return r.json()

    step("2-1. 첫 run → new_records == []")
    d = save_run(6.0, 2160, 360)
    assert d["new_records"] == [], d["new_records"]
    ok("첫 run은 경신 아님 ✓")

    step("2-2. run 3개 후 GET /me/stats records 4종")
    save_run(2.0, 600, 300)     # best_pace 후보
    d3 = save_run(0.5, 90)      # 초고속이지만 자격 미달
    assert d3["new_records"] == [], "0.5km run이 best_pace 경신으로 잡히면 안 됨"
    r = api("GET", "/me/stats")
    assert r.status_code == 200, r.text[:300]
    s = r.json()
    rec = s["records"]
    assert rec["best_pace"]["value"] == 300 and rec["best_pace"]["distance_km"] == 2.0
    assert rec["best_5k"]["value"] == 1800    # 6km run 환산 2160*5/6
    assert rec["best_5k"]["distance_km"] == 6.0
    assert rec["longest_distance"]["value"] == 6.0
    assert rec["longest_duration"]["value"] == 2160
    for k in ("best_pace", "best_5k", "longest_distance", "longest_duration"):
        assert rec[k]["run_id"] and rec[k]["ran_at"], f"{k}에 run_id/ran_at 필요"
    ok("records 4종 값 ✓ (0.5km 무시, 5K는 6km 환산) run_id·ran_at ✓")

    step("2-3. 경신 run (5km 1450s) → best_pace + best_5k만")
    d4 = save_run(5.0, 1450)    # pace 290 < 300, 5K 1450 < 1800
    got = {n["type"]: n for n in d4["new_records"]}
    assert set(got) == {"best_pace", "best_5k"}, d4["new_records"]
    assert (got["best_pace"]["previous"], got["best_pace"]["current"]) == (300, 290)
    assert got["best_pace"]["improvement_pct"] == 3.3
    assert (got["best_5k"]["previous"], got["best_5k"]["current"]) == (1800, 1450)
    assert got["best_5k"]["improvement_pct"] == 19.4
    ok("best_pace 300→290 (3.3%) ✓ best_5k 1800→1450 (19.4%) ✓ 최장기록 미포함 ✓")

    step("2-4. 경신 아닌 run → []")
    d5 = save_run(1.0, 400, 400)
    assert d5["new_records"] == [], d5["new_records"]
    ok("느린 run은 [] ✓")

    step("2-5. 기존 stats 필드 회귀 (week/all_time 불변 확인)")
    s = api("GET", "/me/stats").json()
    assert s["all_time"]["run_count"] == 5
    assert s["all_time"]["total_distance_km"] == 14.5   # 6+2+0.5+5+1
    assert s["all_time"]["longest_run_km"] == 6.0
    assert s["week"]["run_count"] == 5                   # 방금 만든 run은 전부 이번 주
    assert s["records"]["best_pace"]["value"] == 290     # 경신 반영
    ok("기존 필드 유지 ✓ records 최신값 반영 ✓")


def run():
    ts = int(time.time())
    pw = "TestPass123!"
    email = f"pb-u1-{ts}@t.l"
    uid = None
    with httpx.Client(timeout=30) as c:
        try:
            phase1()

            step("공용: 테스트 유저 생성")
            uid = sb_user(c, email, pw)
            tok = sb_login(c, email, pw)
            r = c.patch(f"{BASE}/me/profile",
                        headers={"Authorization": f"Bearer {tok}"},
                        json={"nickname": f"PBu1-{ts % 100000}"})
            assert r.status_code == 200, r.text[:200]
            ok(f"u1={uid[:8]}…")

            phase2(c, tok, uid)

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            if uid:
                sb_del_in(c, "runs", "user_id", [uid])
                sb_del_in(c, "profiles", "user_id", [uid])
                sb_del_user(c, uid)
            ok("runs·profiles·auth user 삭제")


if __name__ == "__main__":
    run()
