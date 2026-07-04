"""
Integration test: crew challenge (POST /challenges, GET /challenges/current)
Creates temporary users, runs all assertions, deletes test data.
Run: python tests/test_challenge_integration.py
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

BASE = "http://localhost:8000/api"
_SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://jlmmqnpddkokyintlawd.supabase.co")

def _load_keys() -> tuple[str, str]:
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = service = ""
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                service = line.split("=", 1)[1]
    return anon, service

_ANON_KEY, _SERVICE_KEY = _load_keys()
_ADMIN_H = {
    "apikey": _SERVICE_KEY,
    "Authorization": f"Bearer {_SERVICE_KEY}",
    "Content-Type": "application/json",
}


# ── helpers ──────────────────────────────────────────────────────────────────

def ok(msg: str) -> None:
    print(f"  ✓ {msg}")

def fail(msg: str, detail: str = "") -> None:
    print(f"  ✗ {msg}" + (f": {detail}" if detail else ""))
    sys.exit(1)

def step(title: str) -> None:
    print(f"\n[{title}]")

def sb_create_user(c: httpx.Client, email: str, pw: str) -> str:
    r = c.post(f"{_SUPABASE_URL}/auth/v1/admin/users",
               headers=_ADMIN_H,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201):
        fail("create user", r.text[:200])
    return r.json()["id"]

def sb_sign_in(c: httpx.Client, email: str, pw: str) -> str:
    r = c.post(f"{_SUPABASE_URL}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON_KEY, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200:
        fail("sign in", r.text[:200])
    return r.json()["access_token"]

def sb_delete_user(c: httpx.Client, uid: str) -> None:
    c.delete(f"{_SUPABASE_URL}/auth/v1/admin/users/{uid}", headers=_ADMIN_H)

def sb_delete_where(c: httpx.Client, table: str, col: str, val: str) -> None:
    c.delete(f"{_SUPABASE_URL}/rest/v1/{table}",
             headers={**_ADMIN_H, "Prefer": "return=minimal"},
             params={col: f"eq.{val}"})

def sb_delete_in(c: httpx.Client, table: str, col: str, vals: list[str]) -> None:
    if not vals:
        return
    c.delete(f"{_SUPABASE_URL}/rest/v1/{table}",
             headers={**_ADMIN_H, "Prefer": "return=minimal"},
             params={col: f"in.({',' .join(vals)})"})

def api(c: httpx.Client, method: str, path: str, tok: str, **kw) -> httpx.Response:
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


# ── test ─────────────────────────────────────────────────────────────────────

def run() -> None:
    ts = int(time.time())
    pw = "TestPass123!"
    email1 = f"chal-owner-{ts}@test.local"
    email2 = f"chal-member-{ts}@test.local"

    uid1 = uid2 = crew_id = priv_crew_id = None
    run_ids: list[str] = []

    # challenge period: started 3 days ago, ends 4 days from now (runs logged
    # "now" by the DB will fall inside this window)
    now = datetime.now(timezone.utc)
    starts_at = (now - timedelta(days=3)).isoformat()
    ends_at   = (now + timedelta(days=4)).isoformat()

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. Users ──────────────────────────────────────────────────
            step("1. 유저 생성 + 로그인 + 닉네임")
            uid1 = sb_create_user(c, email1, pw)
            uid2 = sb_create_user(c, email2, pw)
            tok1 = sb_sign_in(c, email1, pw)
            tok2 = sb_sign_in(c, email2, pw)
            for tok, nick in [(tok1, "챌린지오너"), (tok2, "챌린지멤버")]:
                r = api(c, "PATCH", "/me/profile", tok, json={"nickname": nick})
                if r.status_code != 200:
                    fail("set nickname", r.text[:200])
            ok(f"uid1={uid1[:8]}… uid2={uid2[:8]}… 닉네임 설정 완료")

            # ── 2. 크루 생성 + test2 가입 ─────────────────────────────────
            step("2. 공개 크루 생성 + test2 가입")
            r = api(c, "POST", "/crews", tok1, json={
                "name": f"챌린지크루-{ts}", "is_public": True,
                "level": "무관", "active_days": [],
            })
            if r.status_code != 200:
                fail("create crew", r.text[:200])
            crew_id = r.json()["id"]
            r = api(c, "POST", f"/crews/{crew_id}/join", tok2)
            if r.status_code != 200:
                fail("join crew", r.text[:200])
            ok(f"크루 id={crew_id[:8]}… test2 가입")

            # ── 3. 챌린지 없을 때 current → null ─────────────────────────
            step("3. 챌린지 없는 상태 → null 반환")
            r = api(c, "GET", f"/crews/{crew_id}/challenges/current", tok1)
            if r.status_code != 200:
                fail("GET current (no challenge)", r.text[:200])
            assert r.json() is None, f"챌린지 없으면 null이어야 함, got {r.json()}"
            ok("null 반환 ✓")

            # ── 4. 비-owner(test2)가 챌린지 생성 시도 → 403 ──────────────
            step("4. 비-owner 챌린지 생성 → 403")
            r = api(c, "POST", f"/crews/{crew_id}/challenges", tok2, json={
                "title": "불법챌린지", "goal_km": 50.0,
                "starts_at": starts_at, "ends_at": ends_at,
            })
            assert r.status_code == 403, f"비-owner → 403 이어야 함, got {r.status_code}"
            ok("403 ✓")

            # ── 5. owner가 챌린지 생성 ────────────────────────────────────
            step("5. owner 챌린지 생성 (목표 20km)")
            r = api(c, "POST", f"/crews/{crew_id}/challenges", tok1, json={
                "title": "이번 주 20km 달성!", "goal_km": 20.0,
                "starts_at": starts_at, "ends_at": ends_at,
            })
            if r.status_code != 200:
                fail("create challenge", r.text[:200])
            ch = r.json()
            assert ch["goal_km"] == 20.0
            assert ch["achieved_km"] == 0.0
            assert ch["progress_pct"] == 0.0
            assert ch["is_completed"] is False
            assert ch["is_active"] is True
            ok(f"챌린지 생성 id={ch['id'][:8]}… goal=20km is_active=True ✓")

            # ── 6. 활성 챌린지 있는데 또 생성 → 409 ─────────────────────
            step("6. 중복 챌린지 생성 → 409")
            r = api(c, "POST", f"/crews/{crew_id}/challenges", tok1, json={
                "title": "또 만들기", "goal_km": 30.0,
                "starts_at": starts_at, "ends_at": ends_at,
            })
            assert r.status_code == 409, f"중복 챌린지 → 409 이어야 함, got {r.status_code}"
            ok("409 ✓")

            # ── 7. 멤버들 기록 남기기 ─────────────────────────────────────
            step("7. test1=8km, test2=5km 기록")
            for tok, km in [(tok1, 8.0), (tok2, 5.0)]:
                r = api(c, "POST", "/runs", tok,
                        json={"distance_km": km, "duration_sec": int(km * 360)})
                if r.status_code != 200:
                    fail(f"log {km}km", r.text[:200])
                run_ids.append(r.json()["id"])
            ok("test1 8km, test2 5km 기록 완료")

            # ── 8. 진행도 확인: 13km / 20km = 65% ────────────────────────
            step("8. GET current → 13km, 65%, 미완료")
            r = api(c, "GET", f"/crews/{crew_id}/challenges/current", tok1)
            if r.status_code != 200:
                fail("GET current", r.text[:200])
            prog = r.json()
            print(f"  achieved={prog['achieved_km']} progress={prog['progress_pct']}% "
                  f"completed={prog['is_completed']}")
            assert prog["achieved_km"] == 13.0,   f"expected 13.0 got {prog['achieved_km']}"
            assert prog["progress_pct"] == 65.0,  f"expected 65.0 got {prog['progress_pct']}"
            assert prog["is_completed"] is False,  "아직 미완료여야 함"
            ok("13km / 65% / 미완료 ✓")

            # ── 9. test2 추가 10km → 합산 23km → 목표 초과 완료 ─────────
            step("9. test2 추가 10km → 합산 23km → 완료 확인")
            r = api(c, "POST", "/runs", tok2,
                    json={"distance_km": 10.0, "duration_sec": 3600})
            if r.status_code != 200:
                fail("log 10km", r.text[:200])
            run_ids.append(r.json()["id"])

            r = api(c, "GET", f"/crews/{crew_id}/challenges/current", tok1)
            if r.status_code != 200:
                fail("GET current after completion", r.text[:200])
            prog2 = r.json()
            print(f"  achieved={prog2['achieved_km']} progress={prog2['progress_pct']}% "
                  f"completed={prog2['is_completed']}")
            assert prog2["achieved_km"] == 23.0,  f"expected 23.0 got {prog2['achieved_km']}"
            assert prog2["progress_pct"] == 100.0, f"100% capped got {prog2['progress_pct']}"
            assert prog2["is_completed"] is True,  "23km >= 20km → 완료여야 함"
            ok("23km / 100% (capped) / 완료 ✓")

            # ── 10. 비공개 크루 비멤버 → 404 ─────────────────────────────
            step("10. 비공개 크루 비멤버가 current 조회 → 404")
            r = api(c, "POST", "/crews", tok1, json={
                "name": f"비공개챌린지크루-{ts}", "is_public": False,
                "level": "무관", "active_days": [],
            })
            if r.status_code != 200:
                fail("create private crew", r.text[:200])
            priv_crew_id = r.json()["id"]
            r = api(c, "GET", f"/crews/{priv_crew_id}/challenges/current", tok2)
            assert r.status_code == 404, f"비멤버 비공개 크루 → 404 이어야 함, got {r.status_code}"
            ok("404 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)

        finally:
            step("Cleanup")
            sb_delete_in(c, "runs", "user_id",
                         [u for u in [uid1, uid2] if u])
            ok("runs 삭제")
            for cid in [crew_id, priv_crew_id]:
                if cid:
                    sb_delete_where(c, "crew_challenges", "crew_id", cid)
                    sb_delete_where(c, "crews", "id", cid)
            ok("crews + crew_challenges 삭제")
            sb_delete_in(c, "profiles", "user_id",
                         [u for u in [uid1, uid2] if u])
            ok("profiles 삭제")
            for uid in [uid1, uid2]:
                if uid:
                    sb_delete_user(c, uid)
            ok("auth users 삭제")


if __name__ == "__main__":
    run()
