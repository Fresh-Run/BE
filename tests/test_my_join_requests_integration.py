"""
Integration test: GET /me/join-requests (내 가입 신청 전체 목록 — 모든 크루)
Run: python tests/test_my_join_requests_integration.py
"""
from __future__ import annotations

import os
import sys
import time

import httpx

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
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


def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


def run():
    ts = int(time.time())
    pw = "TestPass123!"
    emails = [f"mj-u{i}-{ts}@t.l" for i in range(1, 4)]  # u1 크루장, u2 신청자, u3 무신청
    uids: list[str] = []
    toks: list[str] = []
    crew_ids: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            step("1. 유저 3명 + 승인제 크루 3개 (A/B/C)")
            for i, e in enumerate(emails, start=1):
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
                assert api(c, "PATCH", "/me/profile", toks[-1],
                           json={"nickname": f"목록u{i}-{ts % 100000}"}).status_code == 200
            tok1, tok2, tok3 = toks
            names = {}
            for label in ("A", "B", "C"):
                r = api(c, "POST", "/crews", tok1,
                        json={"name": f"목록크루{label}-{ts % 100000}",
                              "join_policy": "approval"})
                assert r.status_code in (200, 201), r.text[:200]
                crew_ids.append(r.json()["id"])
                names[r.json()["id"]] = r.json()["name"]
            CA, CB, CC = crew_ids
            ok("크루 3개 생성")

            step("2. 빈 목록 (신청 전)")
            r = api(c, "GET", "/me/join-requests", tok2)
            assert r.status_code == 200 and r.json() == [], r.text[:200]
            ok("[] ✓")

            step("3. u2가 A→B→C 순 신청, B 거절·C 승인 → 전체 목록 상태별 포함")
            req_ids = {}
            for cid in (CA, CB, CC):
                r = api(c, "POST", f"/crews/{cid}/join", tok2)
                assert r.status_code == 202, r.text[:200]
                req_ids[cid] = r.json()["id"]
                time.sleep(1.1)  # created_at 초 단위 순서 보장
            assert api(c, "POST", f"/crews/{CB}/join-requests/{req_ids[CB]}/reject",
                       tok1).status_code == 204
            assert api(c, "POST", f"/crews/{CC}/join-requests/{req_ids[CC]}/approve",
                       tok1).status_code == 204

            r = api(c, "GET", "/me/join-requests", tok2)
            assert r.status_code == 200, r.text[:200]
            items = r.json()
            assert len(items) == 3, items
            # 최신순: C(승인) → B(거절) → A(대기)
            assert [i["crew_id"] for i in items] == [CC, CB, CA], "최신순이어야 함"
            by_crew = {i["crew_id"]: i for i in items}
            assert by_crew[CA]["status"] == "pending" and by_crew[CA]["decided_at"] is None
            assert by_crew[CB]["status"] == "rejected" and by_crew[CB]["decided_at"]
            assert by_crew[CC]["status"] == "approved" and by_crew[CC]["decided_at"]
            for i in items:
                assert i["crew_name"] == names[i["crew_id"]], "크루 이름 배치"
                assert i["created_at"]
            ok("3건 최신순 ✓ pending/rejected/approved 전부 포함 ✓ crew_name·decided_at ✓")

            step("4. 페이지네이션 (limit/offset)")
            r = api(c, "GET", "/me/join-requests", tok2, params={"limit": 2})
            assert [i["crew_id"] for i in r.json()] == [CC, CB]
            r = api(c, "GET", "/me/join-requests", tok2, params={"limit": 2, "offset": 2})
            assert [i["crew_id"] for i in r.json()] == [CA]
            r = api(c, "GET", "/me/join-requests", tok2, params={"limit": 2, "offset": 4})
            assert r.json() == []
            ok("limit=2 → [C,B] ✓ offset=2 → [A] ✓ 범위 밖 → [] ✓")

            step("5. 타 유저 격리 + 기존 크루별 단건 조회 회귀")
            r = api(c, "GET", "/me/join-requests", tok3)
            assert r.json() == [], "u3은 신청이 없어야 함"
            r = api(c, "GET", f"/crews/{CA}/join-requests/me", tok2)
            assert r.status_code == 200 and r.json()["status"] == "pending", \
                "기존 크루별 단건 조회는 그대로 동작해야 함"
            ok("유저 격리 ✓ GET /crews/{id}/join-requests/me 하위 호환 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)

        finally:
            step("Cleanup")
            sb_del_in(c, "crews", "id", crew_ids)  # members/join_requests CASCADE
            sb_del_in(c, "notifications", "user_id", uids)
            sb_del_in(c, "notifications", "actor_id", uids)
            sb_del_in(c, "profiles", "user_id", uids)
            for uid in uids:
                sb_del_user(c, uid)
            ok("crews(CASCADE)·notifications·profiles·auth users 삭제")


if __name__ == "__main__":
    run()
