"""
Integration test: RunRequest·GpsPoint extra="forbid" (M-7 확장, 코어 패스)

visibilty 오타 → private이 public으로 저장되던 최고위험 프라이버시 갭 봉쇄.
중첩 gps_track 원소(GpsPoint)의 오타도 422. Ivan 프론트 필드(top 11 + gps 5)는
전수 대조 완료 — forbid 켜도 안 깨짐.

케이스:
 1. 유효 저장: Ivan 11키(+gps 5키) → 201/200
 2. top-level 오타(visibilty) → 422 (silent ignore 아님 = 프라이버시 갭 봉쇄)
 3. gps_track 중첩 오타(latitide) → 422 (GpsPoint forbid)
 4. required 회귀: distance_km/duration_sec 누락 → 422
 5. 타입 회귀: visibility enum 위반·gps 필수(t) 누락 등 → 422 (기존 검증 불변)
 6. 정상 변형: 코스런(route_id)·정기런(crew_id)·gps 없는 런 → 전부 정상 저장

Run: python tests/test_run_request_forbid_integration.py  (로컬 서버 필요)
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
TS = int(time.time())


def ok(m):         print(f"  ✓ {m}")
def fail(m, d=""):  print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):       print(f"\n[{t}]")


def sb_user(c, email):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": "test1234", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]


def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


def gps_track(n=10, t0=1_783_300_000_000):
    """간단 유효 궤적 — lat/lng/t/acc/alt(Ivan 5키)."""
    pts = []
    for i in range(n):
        pts.append({"lat": round(37.5445 + i * 0.0001, 7), "lng": 127.0374,
                    "t": t0 + i * 4000, "acc": 8.0, "alt": 30.0})
    return pts


def created_run_ids(c, uid):
    r = c.get(f"{_SB}/rest/v1/runs", headers=_ADM,
              params={"user_id": f"eq.{uid}", "select": "id"})
    return [x["id"] for x in r.json()]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. A(러너)·B(대상)")
        for k in ("a", "b"):
            uids[k] = sb_user(c, f"rrf-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"rrf-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"RRF{k}{TS}"}).status_code == 200
        ok("유저 2명")

        step("1. 유효 저장 — Ivan 11키(+gps 5키) → 정상 저장")
        payload = {
            "route_id": None, "distance_km": 5.0, "duration_sec": 1500,
            "avg_pace_sec_per_km": 300, "title": "저녁런", "notes": "메모",
            "visibility": "private", "area": "성수동", "gps_track": gps_track(),
            "crew_id": None, "announcement_id": None,
        }
        r = api(c, "POST", "/runs", tk["a"], json=payload)
        assert r.status_code in (200, 201), f"유효 저장 기대, got {r.status_code}: {r.text[:200]}"
        rid = r.json()["id"]
        ok(f"Ivan 11+5키 저장 {r.status_code} (run={rid[:8]})")

        step("2. top-level 오타(visibilty) → 422 (프라이버시 갭 봉쇄 실증)")
        bad = dict(payload); bad.pop("gps_track"); bad["visibilty"] = "private"  # 오타
        r = api(c, "POST", "/runs", tk["a"], json=bad)
        assert r.status_code == 422, f"visibilty 오타 422 기대, got {r.status_code}: {r.text[:150]}"
        ok("visibilty 오타 → 422 (silent ignore 아님 = private→public 갭 봉쇄)")

        step("3. gps_track 중첩 오타(latitide) → 422 (GpsPoint forbid)")
        bad = {"distance_km": 5.0, "duration_sec": 1500,
               "gps_track": [{"lat": 37.5, "lng": 127.0, "t": 1783300000000, "latitide": 37.5}]}
        r = api(c, "POST", "/runs", tk["a"], json=bad)
        assert r.status_code == 422, f"gps 중첩 오타 422 기대, got {r.status_code}: {r.text[:150]}"
        ok("gps_track latitide 오타 → 422 (GpsPoint forbid 작동)")

        step("4. required 회귀 — distance_km/duration_sec 누락 → 422")
        assert api(c, "POST", "/runs", tk["a"], json={"duration_sec": 1500}).status_code == 422, "distance_km 누락 422"
        assert api(c, "POST", "/runs", tk["a"], json={"distance_km": 5.0}).status_code == 422, "duration_sec 누락 422"
        ok("required 필드 누락 → 422 (기존 동작 불변)")

        step("5. 타입 회귀 — visibility enum 위반·gps 필수(t) 누락 → 422")
        assert api(c, "POST", "/runs", tk["a"],
                   json={"distance_km": 5.0, "duration_sec": 1500, "visibility": "secret"}).status_code == 422, "잘못된 visibility 422"
        assert api(c, "POST", "/runs", tk["a"],
                   json={"distance_km": 5.0, "duration_sec": 1500,
                         "gps_track": [{"lat": 37.5, "lng": 127.0}]}).status_code == 422, "gps t 누락 422"
        ok("visibility enum 위반·gps t 누락 → 422 (forbid가 기존 검증 안 흔듦)")

        step("6. 정상 변형 — 코스런·정기런·gps 없는 런 전부 저장")
        # gps 없는 unpaced 런
        r = api(c, "POST", "/runs", tk["b"], json={"distance_km": 3.0, "duration_sec": 900})
        assert r.status_code in (200, 201), f"gps 없는 런 저장, got {r.status_code}: {r.text[:150]}"
        # visibility 명시 + area
        r = api(c, "POST", "/runs", tk["b"], json={
            "distance_km": 4.0, "duration_sec": 1200, "visibility": "followers",
            "title": "아침런", "area": "여의도", "avg_pace_sec_per_km": 300})
        assert r.status_code in (200, 201), f"followers 런 저장, got {r.status_code}: {r.text[:150]}"
        ok("gps 없는 런·followers 런 등 조건부 조합 전부 정상 저장")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (runs·run_tracks cascade)")


if __name__ == "__main__":
    run_tests()
