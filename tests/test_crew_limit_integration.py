"""
Integration test: 크루 생성 게이트 (무료 owner 1개 / 프리미엄 무제한)
BM 결정(2026-07-06): 기획 원안 '프리미엄 전용' → '무료 1개 맛보기'.
Run: python tests/test_crew_limit_integration.py
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
    emails = [f"cl-u{i}-{ts}@t.l" for i in range(1, 4)]  # u1 free, u2 위임 대상, u3 premium
    uids: list[str] = []
    crew_ids: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            step("1. 유저 3명 (u1/u2 free, u3 premium)")
            toks = []
            for i, e in enumerate(emails, start=1):
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
                assert api(c, "PATCH", "/me/profile", toks[-1],
                           json={"nickname": f"한도u{i}-{ts % 100000}"}).status_code == 200
            uid1, uid2, uid3 = uids
            tok1, tok2, tok3 = toks
            r = c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM,
                        params={"user_id": f"eq.{uid3}"}, json={"tier": "premium"})
            assert r.status_code in (200, 204)
            ok("생성 완료, u3만 premium")

            def make(tok, name):
                return api(c, "POST", "/crews", tok, json={"name": name})

            step("2. free: 1개 OK → 2개째 403 구조화")
            r = make(tok1, f"한도크루A-{ts}")
            assert r.status_code in (200, 201), r.text[:200]
            crew_a = r.json()["id"]
            crew_ids.append(crew_a)
            r = make(tok1, f"한도크루B-{ts}")
            assert r.status_code == 403, f"2개째는 403이어야 함, got {r.status_code}"
            d = r.json()["detail"]
            assert d["error"] == "premium_required" and d["feature"] == "crew_create"
            assert d["limit"] == 1 and "1개" in d["message"], d
            ok("1개 OK ✓ 2개째 403 (error/feature/limit=1/message) ✓")

            step("3. 크루 삭제 → 슬롯 반환 → 다시 생성 OK")
            assert api(c, "DELETE", f"/crews/{crew_a}", tok1).status_code in (200, 204)
            r = make(tok1, f"한도크루C-{ts}")
            assert r.status_code in (200, 201), f"삭제 후 재생성 OK여야 함: {r.text[:200]}"
            crew_c = r.json()["id"]
            crew_ids.append(crew_c)
            ok("삭제 후 재생성 200 ✓ (count 기반 슬롯)")

            step("4. 소유권 위임 → 슬롯 반환 → 다시 생성 OK")
            assert api(c, "POST", f"/crews/{crew_c}/join", tok2).status_code == 200
            r = api(c, "PATCH", f"/crews/{crew_c}/transfer", tok1,
                    json={"new_owner_id": uid2})
            assert r.status_code == 200, r.text[:200]
            r = make(tok1, f"한도크루D-{ts}")
            assert r.status_code in (200, 201), f"위임 후 재생성 OK여야 함: {r.text[:200]}"
            crew_ids.append(r.json()["id"])
            # 이제 u1 슬롯 다시 참 + u2도 1개 소유 → 둘 다 2개째는 403
            assert make(tok1, f"한도크루E-{ts}").status_code == 403
            assert make(tok2, f"한도크루F-{ts}").status_code == 403, \
                "위임받은 크루도 owner 카운트에 포함"
            ok("위임 후 재생성 200 ✓ 양쪽 모두 한도 재적용 ✓")

            step("5. premium: 2개 이상 생성 OK")
            for label in ("P1", "P2", "P3"):
                r = make(tok3, f"프리미엄크루{label}-{ts}")
                assert r.status_code in (200, 201), r.text[:200]
                crew_ids.append(r.json()["id"])
            ok("premium 3개 연속 생성 ✓ (무제한)")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            sb_del_in(c, "crews", "id", crew_ids)
            sb_del_in(c, "crews", "owner_id", uids)  # 위임된 크루 등 잔여
            sb_del_in(c, "notifications", "user_id", uids)
            sb_del_in(c, "notifications", "actor_id", uids)
            sb_del_in(c, "profiles", "user_id", uids)
            for uid in uids:
                sb_del_user(c, uid)
            ok("crews·notifications·profiles·auth users 삭제")


if __name__ == "__main__":
    run()
