"""
Integration test: crew update (PATCH /crews/{id}) + kick (DELETE /crews/{id}/members/{uid})
Run: python tests/test_crew_manage_integration.py
"""
from __future__ import annotations

import os
import sys
import time

import httpx

BASE = "http://localhost:8000/api"
_SUPABASE_URL = "https://jlmmqnpddkokyintlawd.supabase.co"


def _load_keys() -> tuple[str, str]:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = service = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                service = line.split("=", 1)[1]
    return anon, service


_ANON, _SVC = _load_keys()
_ADMIN = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")

def fail(msg: str, detail: str = "") -> None:
    print(f"  ✗ {msg}" + (f": {detail}" if detail else ""))
    sys.exit(1)

def step(title: str) -> None:
    print(f"\n[{title}]")

def sb_create(c: httpx.Client, email: str, pw: str) -> str:
    r = c.post(f"{_SUPABASE_URL}/auth/v1/admin/users", headers=_ADMIN,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201):
        fail("create user", r.text[:200])
    return r.json()["id"]

def sb_login(c: httpx.Client, email: str, pw: str) -> str:
    r = c.post(f"{_SUPABASE_URL}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200:
        fail("login", r.text[:200])
    return r.json()["access_token"]

def sb_del_user(c: httpx.Client, uid: str) -> None:
    c.delete(f"{_SUPABASE_URL}/auth/v1/admin/users/{uid}", headers=_ADMIN)

def sb_del_where(c: httpx.Client, table: str, col: str, val: str) -> None:
    c.delete(f"{_SUPABASE_URL}/rest/v1/{table}",
             headers={**_ADMIN, "Prefer": "return=minimal"},
             params={col: f"eq.{val}"})

def sb_del_in(c: httpx.Client, table: str, col: str, vals: list[str]) -> None:
    if not vals:
        return
    c.delete(f"{_SUPABASE_URL}/rest/v1/{table}",
             headers={**_ADMIN, "Prefer": "return=minimal"},
             params={col: f"in.({',' .join(vals)})"})

def api(c: httpx.Client, method: str, path: str, tok: str, **kw) -> httpx.Response:
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


def run() -> None:
    ts = int(time.time())
    pw = "TestPass123!"
    emails = [f"mgmt-owner-{ts}@t.l", f"mgmt-member-{ts}@t.l", f"mgmt-out-{ts}@t.l"]
    uids: list[str] = []
    toks: list[str] = []
    crew_id: str | None = None

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 3명 생성 ──────────────────────────────────────────
            step("1. 유저 3명 생성 (owner / member / outsider)")
            for email in emails:
                uids.append(sb_create(c, email, pw))
                toks.append(sb_login(c, email, pw))
            tok1, tok2, tok3 = toks
            uid1, uid2, uid3 = uids
            ok(f"owner={uid1[:8]}… member={uid2[:8]}… outsider={uid3[:8]}…")

            # ── 2. 크루 생성, member 가입 ─────────────────────────────────
            step("2. 크루 생성 + member 가입")
            r = api(c, "POST", "/crews", tok1, json={
                "name": "원래이름", "description": "원래소개",
                "is_public": True, "level": "무관", "active_days": ["월", "수"],
            })
            if r.status_code != 200:
                fail("create crew", r.text[:200])
            crew_id = r.json()["id"]
            r = api(c, "POST", f"/crews/{crew_id}/join", tok2)
            if r.status_code != 200:
                fail("join", r.text[:200])
            ok(f"크루 id={crew_id[:8]}… member 가입 완료")

            # ── 3. owner가 이름·소개 수정 ─────────────────────────────────
            step("3. owner → 이름·소개 수정")
            r = api(c, "PATCH", f"/crews/{crew_id}", tok1,
                    json={"name": "바뀐이름", "description": "바뀐소개"})
            if r.status_code != 200:
                fail("update crew", r.text[:200])
            updated = r.json()
            assert updated["name"] == "바뀐이름", f"name mismatch: {updated['name']}"
            assert updated["description"] == "바뀐소개", f"desc mismatch: {updated['description']}"
            ok("name='바뀐이름' description='바뀐소개' ✓")

            # ── 4. 부분 수정 — level만 바꾸고 나머지 유지 ────────────────
            step("4. 부분 수정 (level만) → name은 그대로")
            r = api(c, "PATCH", f"/crews/{crew_id}", tok1, json={"level": "중급"})
            if r.status_code != 200:
                fail("partial update", r.text[:200])
            p = r.json()
            assert p["level"] == "중급",     f"level mismatch: {p['level']}"
            assert p["name"] == "바뀐이름", f"name should be unchanged: {p['name']}"
            assert p["active_days"] == ["월", "수"], f"active_days changed: {p['active_days']}"
            ok("level='중급' ✓  name·active_days 유지 ✓")

            # ── 5. 비-owner(outsider)가 수정 시도 → 403 ──────────────────
            step("5. 비-owner 수정 시도 → 403")
            r = api(c, "PATCH", f"/crews/{crew_id}", tok3, json={"name": "해킹"})
            assert r.status_code == 403, f"expected 403 got {r.status_code}"
            ok("403 ✓")

            # ── 6. owner가 member 강퇴 ────────────────────────────────────
            step("6. owner → member(uid2) 강퇴")
            r = api(c, "DELETE", f"/crews/{crew_id}/members/{uid2}", tok1)
            assert r.status_code == 204, f"expected 204 got {r.status_code}: {r.text}"
            ok("204 ✓")

            # 강퇴 후 멤버 목록에 uid2 없는지 확인
            r = api(c, "GET", f"/crews/{crew_id}/members", tok1)
            if r.status_code != 200:
                fail("GET members", r.text[:200])
            member_ids = [m["user_id"] for m in r.json()]
            assert uid2 not in member_ids, f"uid2 should be gone, got {member_ids}"
            assert uid1 in member_ids, "owner(uid1) should still be there"
            ok(f"uid2 제거 확인 ✓  남은 멤버: {[m[:8]+'…' for m in member_ids]}")

            # ── 7. owner가 자기 강퇴 시도 → 400 ─────────────────────────
            step("7. owner 자기 강퇴 시도 → 400")
            r = api(c, "DELETE", f"/crews/{crew_id}/members/{uid1}", tok1)
            assert r.status_code == 400, f"expected 400 got {r.status_code}"
            ok("400 ✓")

            # ── 8. 없는 멤버(이미 강퇴된 uid2) 강퇴 → 404 ───────────────
            step("8. 없는 멤버 강퇴 → 404")
            r = api(c, "DELETE", f"/crews/{crew_id}/members/{uid2}", tok1)
            assert r.status_code == 404, f"expected 404 got {r.status_code}"
            ok("404 ✓")

            # ── 9. 비-owner(outsider)가 강퇴 시도 → 403 ─────────────────
            step("9. 비-owner 강퇴 시도 → 403")
            r = api(c, "DELETE", f"/crews/{crew_id}/members/{uid1}", tok3)
            assert r.status_code == 403, f"expected 403 got {r.status_code}"
            ok("403 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)

        finally:
            step("Cleanup")
            if crew_id:
                sb_del_where(c, "crews", "id", crew_id)
            ok("crews 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid:
                    sb_del_user(c, uid)
            ok("auth users 삭제")


if __name__ == "__main__":
    run()
