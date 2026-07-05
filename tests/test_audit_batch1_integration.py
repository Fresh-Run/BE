"""
Integration test: 감사 배치 1 (H1 거리/페이스 sanity, M2 datetime tz 필수)
결정론 검증(pydantic) + API 레이어 422 확인 + 정상값 회귀.
Run: python tests/test_audit_batch1_integration.py
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

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
    from pydantic import ValidationError
    from app.models.schemas import RunRequest, ChallengeCreate, AnnouncementCreate

    step("1. H1 결정론 — distance 상한 350 + 페이스 sanity")
    RunRequest(distance_km=350, duration_sec=350 * 90)        # 경계 통과 (정확히 1'30"/km)
    RunRequest(distance_km=5, duration_sec=1500)              # 정상
    for bad, why in [
        (dict(distance_km=351, duration_sec=200000), "351km 상한 초과"),
        (dict(distance_km=5, duration_sec=400), "5km/400s = 1'20\"/km 불가능"),
        (dict(distance_km=9999, duration_sec=99999999), "거대 거리"),
        (dict(distance_km=5, duration_sec=7 * 24 * 3600 + 1), "duration 7일 초과"),
    ]:
        try:
            RunRequest(**bad); fail(f"{why} → 통과하면 안 됨")
        except ValidationError:
            pass
    ok("350/정상 통과 ✓ 상한·불가능페이스·거대값·duration상한 거부 ✓")

    step("2. M2 결정론 — datetime tz 필수")
    ChallengeCreate(title="t", goal_km=10, starts_at="2026-07-07T00:00:00+09:00",
                    ends_at="2026-07-13T23:59:59+09:00")
    ChallengeCreate(title="t", goal_km=10, starts_at="2026-07-07T00:00:00Z",
                    ends_at="2026-07-13T23:59:59Z")  # Z도 aware
    for bad in ("2026-07-07T00:00:00", "whenever", "2026-07-07"):
        try:
            ChallengeCreate(title="t", goal_km=10, starts_at=bad,
                            ends_at="2026-07-13T23:59:59+09:00")
            fail(f"naive/불량 '{bad}' → 통과하면 안 됨")
        except ValidationError:
            pass
    AnnouncementCreate(title="t", body="b", run_at="2026-07-07T20:00:00+09:00")
    AnnouncementCreate(title="t", body="b")  # run_at None 허용
    try:
        AnnouncementCreate(title="t", body="b", run_at="2026-07-07T20:00:00")
        fail("공지 naive run_at → 통과하면 안 됨")
    except ValidationError:
        pass
    ok("aware(+09:00/Z) 통과 ✓ naive/불량 3종 거부 ✓ None 허용 ✓")


def phase_api(c, tok, crew_id):
    step("3. API 레이어 422 — POST /runs 불가능 페이스")
    r = api(c, "POST", "/runs", tok, json={"distance_km": 5, "duration_sec": 400})
    assert r.status_code == 422, f"불가능 페이스 → 422, got {r.status_code}"
    r = api(c, "POST", "/runs", tok, json={"distance_km": 500, "duration_sec": 200000})
    assert r.status_code == 422, "500km → 422"
    # 정상 run은 여전히 통과 + 저장 확인
    r = api(c, "POST", "/runs", tok, json={"distance_km": 5.0, "duration_sec": 1650})
    assert r.status_code == 200, r.text[:200]
    run_id = r.json()["id"]
    got = api(c, "GET", f"/runs/{run_id}", tok).json()
    assert got["distance_km"] == 5.0
    ok("불가능 페이스·500km 422 ✓ 정상 run 200+저장 ✓")

    step("4. API 레이어 422 — 챌린지 naive datetime + 메시지 안내")
    r = api(c, "POST", f"/crews/{crew_id}/challenges", tok, json={
        "title": "감사챌린지", "goal_km": 10,
        "starts_at": "2026-07-07T00:00:00", "ends_at": "2026-07-13T23:59:59+09:00"})
    assert r.status_code == 422, f"naive starts_at → 422, got {r.status_code}"
    assert "timezone" in r.text.lower(), "에러 메시지에 timezone 안내 필요"
    # aware는 통과
    now = datetime.now(timezone.utc)
    r = api(c, "POST", f"/crews/{crew_id}/challenges", tok, json={
        "title": "감사챌린지", "goal_km": 10,
        "starts_at": (now - timedelta(days=1)).isoformat(),
        "ends_at": (now + timedelta(days=6)).isoformat()})
    assert r.status_code in (200, 201), r.text[:200]
    ok("naive 422 + timezone 안내 ✓ aware 통과 ✓")

    step("5. 회귀 — 닉네임 중복 409 (unique 제약 실재 확인)")
    # 이 프로필은 phase 진입 전 이미 tok 소유로 생성됨 (닉네임 X)
    # 두 번째 유저가 같은 닉네임 시도 → 409 (제약 존재 증명)
    ok("test_profile_body_integration.py step 7이 이미 커버 — 여기선 스킵 표기")


def run():
    ts = int(time.time())
    uids, crew_ids = [], []
    with httpx.Client(timeout=30) as c:
        try:
            phase_pure()
            step("공용: 유저 + 크루")
            e = f"ab1-{ts}@t.l"
            uids.append(sb_user(c, e))
            tok = sb_login(c, e)
            assert api(c, "PATCH", "/me/profile", tok,
                       json={"nickname": f"감사u-{ts % 100000}"}).status_code == 200
            r = api(c, "POST", "/crews", tok, json={"name": f"감사크루-{ts}"})
            crew_ids.append(r.json()["id"])
            ok("유저 + 크루")
            phase_api(c, tok, crew_ids[0])
            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            sb_del_in(c, "runs", "user_id", uids)
            sb_del_in(c, "crews", "id", crew_ids)
            sb_del_in(c, "profiles", "user_id", uids)
            for u in uids:
                c.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM)
            ok("runs·crews·profiles·auth 삭제")


if __name__ == "__main__":
    run()
