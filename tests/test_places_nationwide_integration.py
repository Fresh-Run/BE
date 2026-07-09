"""
Integration test: GET /places 좌표 Optional (전국 검색 — 출발지 검색용)

매트릭스: 좌표 both(현행 거리순, 무변경) / 없음(전국 정확도순) / 한쪽만 422 /
좌표 없이 radius_m 422. 카카오 실호출은 200 케이스 2회(무료 쿼터 내).

Run: python tests/test_places_nationwide_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):              anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(m):        print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):      print(f"\n[{t}]")


def run_tests():
    ts = int(time.time())
    c = httpx.Client(timeout=30)
    email = f"places-nw-{ts}@test.com"
    uid = None
    try:
        r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                   json={"email": email, "password": "test1234", "email_confirm": True})
        assert r.status_code in (200, 201), r.text[:200]
        uid = r.json()["id"]
        tok = c.post(f"{_SB}/auth/v1/token?grant_type=password",
                     headers={"apikey": _ANON, "Content-Type": "application/json"},
                     json={"email": email, "password": "test1234"}).json()["access_token"]
        H = {"Authorization": f"Bearer {tok}"}

        def places(**params):
            return c.get(f"{BASE}/places", headers=H, params=params)

        step("1. 좌표 both — 현행 거리순 (하위 호환, 실호출)")
        r = places(keyword="편의점", lat=37.5445, lng=127.0374, radius_m=2000, limit=3)
        assert r.status_code == 200, r.text[:200]
        near = r.json()
        assert near and all("coordinate" in p and p["name"] for p in near), near[:1]
        ok(f"경유지 검색 200 · {len(near)}건 (기존 계약 무변경)")

        step("2. 좌표 없음 — 전국 정확도순 (실호출)")
        r = places(keyword="해운대해수욕장", limit=3)
        assert r.status_code == 200, r.text[:200]
        nw = r.json()
        assert nw, "전국 검색 결과 없음"
        assert any("부산" in (p.get("address") or "") for p in nw), \
            f"성수 밖(부산) 결과가 나와야 전국 증명: {[(p['name'], p.get('address')) for p in nw]}"
        ok(f"전국 검색 200 · 부산 결과 확인 — {nw[0]['name']} ({nw[0].get('address')})")

        step("3. 422 매트릭스 (실호출 없이 검증 계층에서 거부)")
        for bad, why in [
            ({"keyword": "편의점", "lat": 37.5}, "lat만"),
            ({"keyword": "편의점", "lng": 127.0}, "lng만"),
            ({"keyword": "편의점", "radius_m": 2000}, "좌표 없이 radius_m"),
            ({"keyword": "편의점", "lat": 37.5, "lng": 127.0, "radius_m": 25000}, "radius 캡 초과(기존 회귀)"),
            ({"keyword": "편의점", "lat": 50.0, "lng": 127.0}, "bbox 밖(기존 회귀)"),
        ]:
            r = places(**bad)
            assert r.status_code == 422, f"{why} → 422 기대, got {r.status_code}"
        ok("한쪽 좌표 422 ✓ 좌표 없는 radius 422 ✓ 기존 클램프 회귀 ✓")

        step("4. 무인증 401 (기존 회귀)")
        r = c.get(f"{BASE}/places", params={"keyword": "편의점"})
        assert r.status_code == 401, f"401 기대, got {r.status_code}"
        ok("무인증 401 ✓")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        if uid:
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  임시 유저 삭제 (데이터 생성 없음)")


if __name__ == "__main__":
    run_tests()
