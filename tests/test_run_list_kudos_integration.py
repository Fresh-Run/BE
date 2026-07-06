"""
Integration test: GET /runs·/runs/{id} 응답에 kudos_count (기록 탭 ♥)
- kudos 받은 run·안 받은 run 섞어 목록/단건 카운트 정확 검증
- my_kudos·comment_count 없음(본인 목록) 확인
Run: python tests/test_run_list_kudos_integration.py
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


def _keys():
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


def ok(m): print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")


def mkuser(c, e):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": e, "password": "TestPass123!", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    uid = r.json()["id"]
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": e, "password": "TestPass123!"})
    return uid, r.json()["access_token"]


def api(c, m, p, tok, **k):
    return c.request(m, f"{BASE}{p}", headers={"Authorization": f"Bearer {tok}"}, **k)


def del_in(c, table, col, vals):
    if vals:
        c.delete(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "return=minimal"},
                 params={col: f"in.({','.join(vals)})"})


def run():
    ts = int(time.time())
    uids, crew_ids = [], []
    with httpx.Client(timeout=40) as c:
        try:
            step("공용: A(주인) + B·C(크루원, kudos 제공)")
            A_id, A = mkuser(c, f"lk-a-{ts}@t.l"); uids.append(A_id)
            B_id, B = mkuser(c, f"lk-b-{ts}@t.l"); uids.append(B_id)
            C_id, C = mkuser(c, f"lk-c-{ts}@t.l"); uids.append(C_id)
            for uid, tok, nn in [(A_id, A, "목록A"), (B_id, B, "목록B"), (C_id, C, "목록C")]:
                api(c, "PATCH", "/me/profile", tok, json={"nickname": f"{nn}-{ts%100000}"})
            # A가 크루 만들고 B·C를 넣음 → followers run도 크루원이 kudos 가능
            r = api(c, "POST", "/crews", A, json={"name": f"목록크루-{ts%100000}", "max_members": 10})
            crew_id = r.json()["id"]; crew_ids.append(crew_id)
            for uid in (B_id, C_id):
                c.post(f"{_SB}/rest/v1/crew_members", headers={**_ADM, "Prefer": "return=minimal"},
                       json={"crew_id": crew_id, "user_id": uid, "role": "member"})
            ok("A + 크루(B·C 멤버)")

            step("A의 run 3개: run2=kudos2, run1=kudos1, run0=kudos0")
            rid = []
            for i in range(3):
                r = api(c, "POST", "/runs", A, json={
                    "distance_km": 5.0 + i, "duration_sec": 1800 + i,
                    "visibility": "followers", "title": f"기록{i}"})
                assert r.status_code in (200, 201), r.text[:200]
                # 갓 만든 run 단건 응답도 kudos_count 필드 존재(0)
                assert r.json()["kudos_count"] == 0
                rid.append(r.json()["id"])
            # run[2]에 B·C 둘, run[1]에 B 하나, run[0]엔 없음
            assert api(c, "POST", f"/runs/{rid[2]}/kudos", B).status_code == 204
            assert api(c, "POST", f"/runs/{rid[2]}/kudos", C).status_code == 204
            assert api(c, "POST", f"/runs/{rid[1]}/kudos", B).status_code == 204
            ok("kudos 부여: run2←2명, run1←1명, run0←0")

            step("1. GET /runs (목록) — kudos_count 정확 + N+1 없이 한 번에")
            rows = api(c, "GET", "/runs", A, params={"limit": 50}).json()
            by = {r["id"]: r for r in rows}
            assert by[rid[2]]["kudos_count"] == 2, by[rid[2]]["kudos_count"]
            assert by[rid[1]]["kudos_count"] == 1
            assert by[rid[0]]["kudos_count"] == 0
            # my_kudos·comment_count 없음 (본인 목록)
            assert "my_kudos" not in by[rid[2]] and "comment_count" not in by[rid[2]]
            ok("run2=2 ✓ run1=1 ✓ run0=0 ✓ my_kudos·comment_count 미포함 ✓")

            step("2. GET /runs/{id} 단건 — 동일 카운트")
            one = api(c, "GET", f"/runs/{rid[2]}", A).json()
            assert one["kudos_count"] == 2, one["kudos_count"]
            zero = api(c, "GET", f"/runs/{rid[0]}", A).json()
            assert zero["kudos_count"] == 0
            ok("단건 run2=2 ✓ run0=0 ✓ (목록과 일관)")

            step("3. 회귀 — 기존 필드 유지")
            r2 = by[rid[2]]
            assert r2["distance_km"] == 7.0 and r2["title"] == "기록2"
            assert r2["visibility"] == "followers" and "splits" in r2 and "has_track" in r2
            ok("distance/title/visibility/splits/has_track 유지 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            del_in(c, "crews", "id", crew_ids)
            del_in(c, "runs", "user_id", uids)
            del_in(c, "profiles", "user_id", uids)
            for u in uids:
                c.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM)
            ok("crews·runs·profiles·auth 삭제")


if __name__ == "__main__":
    run()
