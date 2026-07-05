"""
Integration test: 감사 배치 2 (M5 max_length, M6 limit/offset 클램프,
M9 int 상한, M7 /places 인증 필수 + 파라미터 클램프)
Run: python tests/test_audit_batch2_integration.py
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


def phase_pure():
    """M5+M9 결정론 — 전체 필드 경계값 루프."""
    from pydantic import ValidationError
    from app.models.schemas import (
        ProfileUpdate, RouteRequest, CrewCreate, CrewUpdate, ChallengeCreate,
    )

    step("1. M5 max_length + M9 int 상한 — 결정론 전수")
    START = {"start": {"lat": 37.5445, "lng": 127.0374}}
    reject = [
        ("ProfileUpdate.bio 501", ProfileUpdate, dict(nickname="ab", bio="x" * 501)),
        ("ProfileUpdate.avatar_url 501", ProfileUpdate, dict(nickname="ab", avatar_url="u" * 501)),
        ("RouteRequest.notes 501", RouteRequest, dict(**START, notes="n" * 501)),
        ("RouteRequest.pitstop 51", RouteRequest, dict(**START, pitstop_keyword="k" * 51)),
        ("CrewCreate.name 51", CrewCreate, dict(name="x" * 51)),
        ("CrewCreate.description 501", CrewCreate, dict(name="ok", description="d" * 501)),
        ("CrewCreate.area 51", CrewCreate, dict(name="ok", area="a" * 51)),
        ("CrewCreate.sport 31", CrewCreate, dict(name="ok", sport="s" * 31)),
        ("CrewCreate.active_days 8개", CrewCreate, dict(name="ok", active_days=["월"] * 8)),
        ("CrewCreate.active_days 항목 11자", CrewCreate, dict(name="ok", active_days=["x" * 11])),
        ("CrewCreate.color 21", CrewCreate, dict(name="ok", color="#" + "F" * 20)),
        ("CrewCreate.max_members 3e9 (int4 오버플로)", CrewCreate, dict(name="ok", max_members=3_000_000_000)),
        ("CrewCreate.radius_km 501", CrewCreate, dict(name="ok", radius_km=501)),
        ("CrewUpdate.name 51", CrewUpdate, dict(name="x" * 51)),
        ("CrewUpdate.max_members 3e9", CrewUpdate, dict(max_members=3_000_000_000)),
        ("ChallengeCreate.title 101", ChallengeCreate, dict(
            title="t" * 101, goal_km=10,
            starts_at="2026-07-07T00:00:00+09:00", ends_at="2026-07-13T00:00:00+09:00")),
    ]
    for label, cls, kw in reject:
        try:
            cls(**kw); fail(f"{label} → 422여야 함")
        except ValidationError:
            pass
    # 정상값 통과
    CrewCreate(name="한강크루", description="좋은 크루", area="성수", sport="러닝",
               active_days=["월", "수", "금"], max_members=50, radius_km=5, color="#FF8800")
    RouteRequest(**START, notes="한강 근처", pitstop_keyword="편의점")
    ProfileUpdate(nickname="러너", bio="안녕하세요")
    ok(f"거부 {len(reject)}종 전부 422 ✓ 정상값 통과 ✓")


def phase_api(c, tok):
    step("2. M6 limit/offset 클램프 — 음수·거대값이 502 아닌 200")
    endpoints = [
        ("/runs", {"limit": -1}), ("/runs", {"limit": 999999}),
        ("/notifications", {"limit": -5}), ("/notifications", {"limit": 10000}),
        ("/routes", {"limit": -1}),
        ("/routes/public", {"limit": -3, "sort": "newest"}),
        ("/routes/search", {"q": "한강", "limit": -1}),
        ("/routes/nearby", {"lat": 37.5445, "lng": 127.0374, "radius_km": -1, "limit": -1}),
        ("/routes/nearby", {"lat": 37.5445, "lng": 127.0374, "radius_km": 99999, "limit": 5}),
        ("/crews/search", {"q": "크루", "limit": -1}),
    ]
    for path, params in endpoints:
        r = api(c, "GET", path, tok, params=params)
        assert r.status_code == 200, f"{path} {params} → 200 기대(클램프), got {r.status_code} {r.text[:120]}"
    ok(f"{len(endpoints)}개 경로 음수·거대 limit/radius → 200 클램프 ✓ (502 방지)")

    step("3. M7 /places — 인증 필수 + 파라미터 클램프")
    # 무인증 → 401
    r = c.get(f"{BASE}/places", params={"keyword": "편의점", "lat": 37.5445, "lng": 127.0374})
    assert r.status_code == 401, f"무인증 → 401, got {r.status_code}"
    # 인증 + 정상 파라미터 → 200 (외부 API 결과)
    r = api(c, "GET", "/places", tok,
            params={"keyword": "편의점", "lat": 37.5445, "lng": 127.0374, "radius_m": 1000, "limit": 5})
    assert r.status_code == 200, f"인증 정상 → 200, got {r.status_code} {r.text[:150]}"
    # bbox 밖 / 범위 밖 파라미터 → 422
    for bad in ({"keyword": "x", "lat": 10.0, "lng": 127.0},          # lat bbox 밖
                {"keyword": "x", "lat": 37.5, "lng": 127.0, "radius_m": 999999},  # 반경 상한
                {"keyword": "", "lat": 37.5, "lng": 127.0}):           # 빈 keyword
        r = api(c, "GET", "/places", tok, params=bad)
        assert r.status_code == 422, f"/places {bad} → 422, got {r.status_code}"
    ok("무인증 401 ✓ 인증 정상 200 ✓ bbox·반경·빈keyword 422 ✓")


def run():
    ts = int(time.time())
    uids = []
    with httpx.Client(timeout=30) as c:
        try:
            phase_pure()
            step("공용: 유저")
            e = f"ab2-{ts}@t.l"
            uids.append(sb_user(c, e))
            tok = sb_login(c, e)
            assert api(c, "PATCH", "/me/profile", tok, json={"nickname": f"배치2-{ts%100000}"}).status_code == 200
            ok("유저 생성")
            phase_api(c, tok)
            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            sb_del_in(c, "profiles", "user_id", uids)
            for u in uids:
                c.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM)
            ok("profiles·auth 삭제")


if __name__ == "__main__":
    run()
