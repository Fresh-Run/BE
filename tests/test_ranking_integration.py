"""
Integration test: GET /api/crews/{id}/ranking (weekly distance ranking)

Spins up two temporary Supabase users, exercises the ranking endpoint through
the live FastAPI server at http://localhost:8000, then deletes all created data.
Run with:  python tests/test_ranking_integration.py
"""

from __future__ import annotations

import sys
import time
import httpx

BASE = "http://localhost:8000/api"
SUPABASE_URL = "https://jlmmqnpddkokyintlawd.supabase.co"
ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpsbW1xbnBkZGtva3lpbnRsYXdkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE3NTkxMTgsImV4cCI6MjA5NzMzNTExOH0"
    ".l2yL07n7V84FyGvS9SZiO7La6x7aAcIV2D02R3pONSo"
)
SERVICE_KEY = "sb_secret_och_B_efnohN80MjSTFong_OtyRUZCH"

ADMIN_HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}

# ── helpers ──────────────────────────────────────────────────────────────────

def ok(label: str) -> None:
    print(f"  ✓ {label}")

def fail(label: str, detail: str) -> None:
    print(f"  ✗ {label}: {detail}")
    sys.exit(1)

def step(title: str) -> None:
    print(f"\n[{title}]")


def sb_create_user(client: httpx.Client, email: str, password: str) -> str:
    r = client.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers=ADMIN_HEADERS,
        json={"email": email, "password": password, "email_confirm": True},
    )
    if r.status_code not in (200, 201):
        fail("create user", f"{r.status_code} {r.text}")
    return r.json()["id"]


def sb_sign_in(client: httpx.Client, email: str, password: str) -> str:
    r = client.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    if r.status_code != 200:
        fail("sign in", f"{r.status_code} {r.text}")
    return r.json()["access_token"]


def sb_delete_user(client: httpx.Client, user_id: str) -> None:
    client.delete(
        f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
        headers=ADMIN_HEADERS,
    )


def sb_delete_crew(client: httpx.Client, crew_id: str) -> None:
    """Delete crew directly via Supabase REST (bypasses ownership check for cleanup)."""
    client.delete(
        f"{SUPABASE_URL}/rest/v1/crews",
        headers={**ADMIN_HEADERS, "Prefer": "return=minimal"},
        params={"id": f"eq.{crew_id}"},
    )


def sb_delete_runs_by_users(client: httpx.Client, user_ids: list[str]) -> None:
    """Delete all runs belonging to the test users."""
    uid_filter = "(" + ",".join(user_ids) + ")"
    client.delete(
        f"{SUPABASE_URL}/rest/v1/runs",
        headers={**ADMIN_HEADERS, "Prefer": "return=minimal"},
        params={"user_id": f"in.{uid_filter}"},
    )


def api(
    client: httpx.Client,
    method: str,
    path: str,
    token: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
) -> httpx.Response:
    return client.request(
        method,
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=json,
        params=params,
    )


# ── test body ─────────────────────────────────────────────────────────────────

def run_tests() -> None:
    ts = int(time.time())
    email1 = f"ranking-test1-{ts}@test.local"
    email2 = f"ranking-test2-{ts}@test.local"
    password = "TestPass123!"

    uid1 = uid2 = None
    crew_id = priv_crew_id = empty_crew_id = None
    run_ids: list[str] = []

    with httpx.Client(timeout=20) as client:
        try:
            # ── 1. Create temporary users ─────────────────────────────────
            step("1. Create test users")
            uid1 = sb_create_user(client, email1, password)
            uid2 = sb_create_user(client, email2, password)
            ok(f"test1 uid={uid1[:8]}…  test2 uid={uid2[:8]}…")

            # ── 2. Sign in ────────────────────────────────────────────────
            step("2. Sign in → get tokens")
            tok1 = sb_sign_in(client, email1, password)
            tok2 = sb_sign_in(client, email2, password)
            ok("both tokens obtained")

            # ── 3. Set nicknames ──────────────────────────────────────────
            step("3. Set nicknames")
            r = api(client, "PATCH", "/me/profile", tok1, json={"nickname": "테스트러너1"})
            if r.status_code != 200:
                fail("set nickname test1", f"{r.status_code} {r.text}")
            r = api(client, "PATCH", "/me/profile", tok2, json={"nickname": "테스트러너2"})
            if r.status_code != 200:
                fail("set nickname test2", f"{r.status_code} {r.text}")
            # u1이 크루 2개 생성 — 무료 1개 한도 게이트를 넘기 위해 premium 승격
            client.patch(f"{SUPABASE_URL}/rest/v1/profiles", headers=ADMIN_HEADERS,
                         params={"user_id": f"eq.{uid1}"}, json={"tier": "premium"})
            ok("테스트러너1 / 테스트러너2")

            # ── 4. Create all crews up front ──────────────────────────────
            step("4. 크루 3개 생성 (메인 / 비공개 / 빈 크루)")
            r = api(client, "POST", "/crews", tok1, json={
                "name": f"랭킹테스트크루-{ts}",
                "is_public": True,
                "level": "무관",
                "active_days": [],
            })
            if r.status_code != 200:
                fail("create main crew", f"{r.status_code} {r.text}")
            crew_id = r.json()["id"]
            ok(f"메인 크루 id={crew_id[:8]}…")

            r = api(client, "POST", "/crews", tok1, json={
                "name": f"비공개크루-{ts}",
                "is_public": False,
                "level": "무관",
                "active_days": [],
            })
            if r.status_code != 200:
                fail("create private crew", f"{r.status_code} {r.text}")
            priv_crew_id = r.json()["id"]
            ok(f"비공개 크루 id={priv_crew_id[:8]}…")

            r = api(client, "POST", "/crews", tok2, json={
                "name": f"빈크루-{ts}",
                "is_public": True,
                "level": "무관",
                "active_days": [],
            })
            if r.status_code != 200:
                fail("create empty crew", f"{r.status_code} {r.text}")
            empty_crew_id = r.json()["id"]
            ok(f"빈 크루 id={empty_crew_id[:8]}… (test2 solo, 아직 기록 없음)")

            r = api(client, "POST", f"/crews/{crew_id}/join", tok2)
            if r.status_code != 200:
                fail("test2 join main crew", f"{r.status_code} {r.text}")
            ok("test2 → 메인 크루 가입")

            # ── 5. Empty crew ranking check (BEFORE any runs) ────────────
            step("5. 이번 주 기록 없는 크루 → 빈 배열 확인 (runs 로깅 전)")
            r = api(client, "GET", f"/crews/{empty_crew_id}/ranking", tok2)
            if r.status_code != 200:
                fail("GET ranking empty crew", f"{r.status_code} {r.text}")
            assert r.json() == [], \
                f"기록 없는 크루 ranking은 [] 이어야 함, got {r.json()}"
            ok("기록 없는 크루 → [] ✓")

            # ── 6. Log runs: test1=5km, test2=3km ────────────────────────
            step("6. Log runs: test1=5km, test2=3km")
            r = api(client, "POST", "/runs", tok1, json={"distance_km": 5.0, "duration_sec": 1800})
            if r.status_code != 200:
                fail("log run test1 5km", f"{r.status_code} {r.text}")
            run_ids.append(r.json()["id"])
            ok("test1: 5 km logged")

            r = api(client, "POST", "/runs", tok2, json={"distance_km": 3.0, "duration_sec": 1200})
            if r.status_code != 200:
                fail("log run test2 3km", f"{r.status_code} {r.text}")
            run_ids.append(r.json()["id"])
            ok("test2: 3 km logged")

            # ── 7. Ranking: test1 #1 (5km), test2 #2 (3km) ───────────────
            step("7. GET ranking → test1 1등 5km, test2 2등 3km")
            r = api(client, "GET", f"/crews/{crew_id}/ranking", tok1)
            if r.status_code != 200:
                fail("GET ranking", f"{r.status_code} {r.text}")
            ranking = r.json()
            print(f"  ranking: {[(e['rank'], e['nickname'], e['distance_km']) for e in ranking]}")

            assert len(ranking) == 2, f"expected 2 entries, got {len(ranking)}"
            first, second = ranking[0], ranking[1]

            assert first["user_id"] == uid1,       f"1등 user_id mismatch: {first['user_id']}"
            assert first["rank"] == 1,              f"1등 rank should be 1, got {first['rank']}"
            assert first["distance_km"] == 5.0,    f"1등 distance should be 5.0, got {first['distance_km']}"
            assert first["nickname"] == "테스트러너1", f"1등 nickname mismatch: {first['nickname']}"

            assert second["user_id"] == uid2,       f"2등 user_id mismatch: {second['user_id']}"
            assert second["rank"] == 2,             f"2등 rank should be 2, got {second['rank']}"
            assert second["distance_km"] == 3.0,   f"2등 distance should be 3.0, got {second['distance_km']}"
            assert second["nickname"] == "테스트러너2", f"2등 nickname mismatch: {second['nickname']}"
            ok("test1 1등 5km ✓  test2 2등 3km ✓  닉네임 ✓")

            # ── 8. test2 logs 4km more → total 7km → should overtake ─────
            step("8. test2 추가 4km → 합산 7km → 역전 1등 확인")
            r = api(client, "POST", "/runs", tok2, json={"distance_km": 4.0, "duration_sec": 1500})
            if r.status_code != 200:
                fail("log run test2 4km", f"{r.status_code} {r.text}")
            run_ids.append(r.json()["id"])
            ok("test2: 4 km logged (총 7 km)")

            r = api(client, "GET", f"/crews/{crew_id}/ranking", tok1)
            if r.status_code != 200:
                fail("GET ranking after overtake", f"{r.status_code} {r.text}")
            ranking2 = r.json()
            print(f"  ranking: {[(e['rank'], e['nickname'], e['distance_km']) for e in ranking2]}")

            first2, second2 = ranking2[0], ranking2[1]
            assert first2["user_id"] == uid2,      f"역전 후 1등은 test2여야 함: {first2['user_id']}"
            assert first2["rank"] == 1,             f"역전 후 1등 rank=1 이어야 함"
            assert first2["distance_km"] == 7.0,   f"test2 합산 7.0km 이어야 함, got {first2['distance_km']}"
            assert second2["user_id"] == uid1,      f"역전 후 2등은 test1이어야 함"
            assert second2["rank"] == 2,            f"역전 후 2등 rank=2 이어야 함"
            assert second2["distance_km"] == 5.0,  f"test1 5.0km 그대로여야 함"
            ok("test2 역전 1등 7km ✓  test1 2등 5km ✓  합산 정확 ✓")

            # ── 9. Private crew: non-member gets 404 ─────────────────────
            step("9. 비공개 크루 → 비멤버 조회 404 확인")
            r = api(client, "GET", f"/crews/{priv_crew_id}/ranking", tok2)
            assert r.status_code == 404, \
                f"비멤버가 비공개 크루 ranking 조회 → 404 이어야 함, got {r.status_code}"
            ok("비공개 크루 비멤버 조회 → 404 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            # ── Cleanup ───────────────────────────────────────────────────
            step("Cleanup: 테스트 데이터 삭제")

            # Runs (no DELETE endpoint → use Supabase REST directly)
            if uid1 or uid2:
                sb_delete_runs_by_users(client, [u for u in [uid1, uid2] if u])
                ok("runs 삭제")

            # Crews (DELETE /api/crews/{id} via API — cascades crew_members)
            for cid in [crew_id, priv_crew_id, empty_crew_id]:
                if cid:
                    sb_delete_crew(client, cid)
            ok("crews + crew_members 삭제")

            # Profiles (delete via Supabase REST)
            if uid1 or uid2:
                uid_filter = "(" + ",".join(u for u in [uid1, uid2] if u) + ")"
                client.delete(
                    f"{SUPABASE_URL}/rest/v1/profiles",
                    headers={**ADMIN_HEADERS, "Prefer": "return=minimal"},
                    params={"user_id": f"in.{uid_filter}"},
                )
                ok("profiles 삭제")

            # Auth users
            for uid in [uid1, uid2]:
                if uid:
                    sb_delete_user(client, uid)
            ok("auth users 삭제")


if __name__ == "__main__":
    run_tests()
