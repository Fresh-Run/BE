"""
Integration test: 감사 H2 회귀 — 챌린지 생성자 계정 삭제 (위임 후)
H2 이전엔 crew_challenges.created_by FK에 ON DELETE 절이 없어, 챌린지를 만든
뒤 크루 소유권을 위임하면 생성자 계정 삭제가 FK 위반으로 영구 차단됐다.
이제 ON DELETE SET NULL이라 삭제가 성공하고 챌린지는 created_by=null로 보존.

시나리오: A가 크루+챌린지 생성 → B에게 위임 → A 계정 삭제 성공 →
챌린지 행 잔존 + created_by null + 크루는 B 소유로 정상.
Run: python tests/test_challenge_creator_delete_integration.py
"""
from __future__ import annotations

import os
import sys
import time
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


def sb_user(c, e):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": e, "password": "TestPass123!", "email_confirm": True})
    if r.status_code not in (200, 201): fail("create user", r.text[:200])
    return r.json()["id"]


def sb_login(c, e):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": e, "password": "TestPass123!"})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]


def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})


def api(c, m, p, tok, **k):
    return c.request(m, f"{BASE}{p}", headers={"Authorization": f"Bearer {tok}"}, **k)


def run():
    ts = int(time.time())
    ea, eb = f"h2a-{ts}@t.l", f"h2b-{ts}@t.l"
    uid_a = uid_b = None
    crew_id = ch_id = None
    a_deleted = False

    with httpx.Client(timeout=30) as c:
        try:
            step("1. 유저 A(생성자)·B(위임 대상)")
            uid_a = sb_user(c, ea); uid_b = sb_user(c, eb)
            tok_a = sb_login(c, ea); tok_b = sb_login(c, eb)
            assert api(c, "PATCH", "/me/profile", tok_a, json={"nickname": f"H2a-{ts%100000}"}).status_code == 200
            assert api(c, "PATCH", "/me/profile", tok_b, json={"nickname": f"H2b-{ts%100000}"}).status_code == 200
            ok(f"A={uid_a[:8]}… B={uid_b[:8]}…")

            step("2. A가 크루 생성 + B 가입 + A가 챌린지 생성")
            r = api(c, "POST", "/crews", tok_a, json={"name": f"H2크루-{ts}"})
            assert r.status_code in (200, 201), r.text[:200]
            crew_id = r.json()["id"]
            assert api(c, "POST", f"/crews/{crew_id}/join", tok_b).status_code == 200
            now = datetime.now(timezone.utc)
            r = api(c, "POST", f"/crews/{crew_id}/challenges", tok_a, json={
                "title": "H2 챌린지", "goal_km": 50,
                "starts_at": (now - timedelta(days=1)).isoformat(),
                "ends_at": (now + timedelta(days=6)).isoformat()})
            assert r.status_code in (200, 201), r.text[:300]
            ch_id = r.json()["id"]
            assert r.json()["created_by"] == uid_a, "생성자가 A여야 함"
            ok(f"크루+챌린지 생성 (created_by=A) ch={ch_id[:8]}…")

            step("3. A → B 소유권 위임")
            r = api(c, "PATCH", f"/crews/{crew_id}/transfer", tok_a, json={"new_owner_id": uid_b})
            assert r.status_code == 200, r.text[:300]
            ok("위임 완료 (A는 이제 일반 멤버)")

            step("4. A 계정 삭제 — H2 이전엔 FK 위반으로 차단됐던 지점")
            # A는 이제 크루 owner가 아니므로 crews CASCADE가 챌린지를 지우지 않는다 →
            # created_by FK의 ON DELETE 절만이 삭제 성공을 좌우.
            r = c.delete(f"{_SB}/auth/v1/admin/users/{uid_a}", headers=_ADM)
            assert r.status_code in (200, 204), \
                f"계정 삭제가 성공해야 함(H2 SET NULL), got {r.status_code} {r.text[:200]}"
            a_deleted = True
            # auth 유저가 실제로 사라졌는지 확인
            chk = c.get(f"{_SB}/auth/v1/admin/users/{uid_a}", headers=_ADM)
            assert chk.status_code == 404, f"A 계정이 남아있음: {chk.status_code}"
            ok("A 계정 삭제 성공 ✓ (FK 위반 없음)")

            step("5. 챌린지 보존 + created_by null + 크루는 B 소유")
            rows = c.get(f"{_SB}/rest/v1/crew_challenges", headers=_ADM,
                         params={"id": f"eq.{ch_id}", "select": "id,created_by,goal_km"}).json()
            assert len(rows) == 1, f"챌린지가 사라짐(잘못된 CASCADE?): {rows}"
            assert rows[0]["created_by"] is None, f"created_by가 null이어야 함: {rows[0]}"
            assert rows[0]["goal_km"] == 50, "챌린지 내용 보존"
            # 크루는 B 소유로 살아있음 + B가 조회 가능
            r = api(c, "GET", f"/crews/{crew_id}", tok_b)
            assert r.status_code == 200 and r.json()["owner_id"] == uid_b
            # 진행 중 챌린지 조회도 정상 (created_by null 직렬화 OK)
            r = api(c, "GET", f"/crews/{crew_id}/challenges/current", tok_b)
            assert r.status_code == 200 and r.json()["created_by"] is None
            ok("챌린지 보존+created_by null ✓ 크루 B 소유 ✓ current 조회 null 직렬화 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            sb_del_in(c, "crews", "id", [crew_id] if crew_id else [])  # challenges/members CASCADE
            sb_del_in(c, "profiles", "user_id", [u for u in (uid_a, uid_b) if u])
            if uid_b:
                c.delete(f"{_SB}/auth/v1/admin/users/{uid_b}", headers=_ADM)
            if uid_a and not a_deleted:
                c.delete(f"{_SB}/auth/v1/admin/users/{uid_a}", headers=_ADM)
            ok("crews(CASCADE)·profiles·auth 삭제")


if __name__ == "__main__":
    run()
