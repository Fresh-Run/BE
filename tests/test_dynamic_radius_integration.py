"""
Integration test: 동적 탐색 반경 (배치 풀 반경 분배)
1) 순수 함수 — _radius_schedule(목표 비례 스케줄)·_pool_radii(풀 순환 분배)·
   프롬프트 반경 주입 (Gemini/T-map 호출 없음)
2) 실호출 1회 (본 서버 8000) — 정상 생성 + search_radius_km/quota 확인
⚠️ pool 플로우(밴드 hit/missed/502·leg 상한·pool_size 만큼 Gemini 호출)는
   test_route_distance_guarantee_integration.py가 mock_route_app로 커버 — 여기선
   반경 분배 로직만(v2.7 순차-재시도→배치 풀 리팩터로 구 재시도 mock은 폐기).
Run: python tests/test_dynamic_radius_integration.py
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


# ═══ Phase 1: 순수 함수 (반경 스케줄·풀 분배·프롬프트) ═══════════════════════════

def phase1():
    """반경 스케줄링 순수 함수 + 프롬프트 반경 주입.

    ⚠️ 재작성(2026-07-22): 구 phase1(1-3~1-9)은 **순차 재시도 루프**(attempt마다
    반경 확장, call_count 1/2/4)를 검증했으나 v2.7 배치 풀 리팩터로 그 아키텍처가
    제거됨 — 지금은 9개 병렬 풀(`_pool_radii`가 스케줄을 순환 분산)이 1패스로 선택.
    pool 플로우(밴드 hit/missed/502·leg 상한·gen_meta·pool_size 만큼 Gemini 호출)는
    `test_route_distance_guarantee_integration.py`가 mock_route_app 시나리오로 커버.
    여기서는 그 파일과 겹치지 않는 **반경 분배 로직 + 프롬프트 배선**만 검증한다."""
    from app.models.schemas import Coordinate
    from app.services import route_service as rs
    from app.services.openai_service import _build_prompt

    START = Coordinate(lat=37.5445, lng=127.0374)

    step("1-1. _radius_schedule 순수 함수 — 목표 비례 r0·점증·cap 8·dedupe")
    assert rs._radius_schedule(3) == [1.0, 2.0, 3.5, 8.0]
    assert rs._radius_schedule(5) == [1.2, 2.2, 3.7, 8.0]
    assert rs._radius_schedule(10) == [2.5, 3.5, 5.0, 8.0]
    assert rs._radius_schedule(20) == [5.0, 6.0, 7.5, 8.0]
    assert rs._radius_schedule(32) == [8.0], "r0가 상한이면 1개로 dedup"
    # end-aware(v2.3): |start−end|/2+1.0이 r0 하한을 밀어올림
    assert rs._radius_schedule(5, start_end_km=6.0) == [4.0, 5.0, 6.5, 8.0], \
        "corridor 반경 max(r0, 6/2+1=4.0) 시작"
    ok("목표 비례 스케줄 + end-aware corridor 반경 ✓")

    step("1-2. _pool_radii 순수 함수 — 스케줄을 N개로 순환 분배(배치 풀 다양성)")
    # n=_POOL_SIZE(9): [1.2,2.2,3.7,8.0]을 순환 → 9개
    assert rs._pool_radii(5, None, 9) == [1.2, 2.2, 3.7, 8.0, 1.2, 2.2, 3.7, 8.0, 1.2]
    assert rs._pool_radii(5, None, 4) == [1.2, 2.2, 3.7, 8.0], "정확히 한 바퀴"
    assert rs._pool_radii(5, None, 2) == [1.2, 2.2], "일부만"
    # 스케줄이 1개(32km)면 전부 8.0 — dedup된 스케줄을 순환해도 단일값
    assert rs._pool_radii(32, None, 9) == [8.0] * 9, "단일 스케줄 → 전 풀 동일 반경"
    # end-aware 스케줄도 순환
    assert rs._pool_radii(5, 6.0, 5) == [4.0, 5.0, 6.5, 8.0, 4.0]
    # _POOL_SIZE와 정합: 실제 풀 크기로 호출해도 길이 일치
    assert len(rs._pool_radii(5, None, rs._POOL_SIZE)) == rs._POOL_SIZE
    ok("스케줄 순환 분배 ✓ 단일 스케줄 fanout ✓ _POOL_SIZE 정합 ✓")

    step("1-3. 프롬프트에 반경 수치 주입(HARD 제약) — 있으면 명시 반경, 없으면 근처")
    p = _build_prompt(5, START, None, None, None, radius_km=2.2)
    assert "within 2.2 km (straight-line)" in p and "near the start" not in p
    p = _build_prompt(5, START, None, None, None)  # radius 없으면 기존 문구
    assert "near the start" in p
    ok("radius 문구 교체 ✓ 레거시 문구 보존 ✓")


# ═══ Phase 2: 실호출 1회 (본 서버 8000) ══════════════════════════════════════════

def phase2(c, tok):
    def api(method, path, **kw):
        return c.request(method, f"{BASE}{path}",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=120, **kw)

    step("2-1. 실호출: 정상 생성 → 새 필드 + 기존 필드 회귀")
    r = api("POST", "/routes/generate",
            json={"start": {"lat": 37.5445, "lng": 127.0374}, "target_distance_km": 5})
    assert r.status_code == 200, r.text[:400]
    d = r.json()
    assert d["summary"] and len(d["waypoints"]) >= 2 and d["total_distance_km"] > 0
    assert d["search_radius_km"] in (1.2, 2.2, 3.7, 8.0), d["search_radius_km"]
    assert isinstance(d["radius_expanded"], bool)
    ok(f"200 ✓ {d['total_distance_km']}km, radius {d['search_radius_km']}km "
       f"(expanded={d['radius_expanded']})")

    step("2-2. 쿼터: 재시도와 무관하게 요청당 1 차감")
    r = api("GET", "/me/quota")
    assert r.status_code == 200
    q = r.json()["ai_generation"]
    assert q["used"] == 1, f"요청 1번 = 차감 1이어야 함, got {q['used']}"
    ok("used=1 ✓")


def run():
    ts = int(time.time())
    pw = "TestPass123!"
    email = f"dr-u1-{ts}@t.l"
    uid = None
    with httpx.Client(timeout=30) as c:
        try:
            phase1()

            step("공용: 테스트 유저 생성")
            uid = sb_user(c, email, pw)
            tok = sb_login(c, email, pw)
            r = c.patch(f"{BASE}/me/profile",
                        headers={"Authorization": f"Bearer {tok}"},
                        json={"nickname": f"반경u1-{ts % 100000}"})
            assert r.status_code == 200, r.text[:200]
            ok(f"u1={uid[:8]}…")

            phase2(c, tok)

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            if uid:
                sb_del_in(c, "route_generations", "user_id", [uid])
                sb_del_in(c, "routes", "user_id", [uid])
                sb_del_in(c, "profiles", "user_id", [uid])
                sb_del_user(c, uid)
            ok("routes·quota·profiles·auth user 삭제")


if __name__ == "__main__":
    run()
