"""
Integration test: Gemini 버스트 완화 (롤 스태거 + SDK 단일 재시도, 2026-07-22)

E2E 성수 502(9-병렬이 Gemini relay 429 스로틀 유발) 대응:
 1. 롤 스태거 — 9콜을 _POOL_STAGGER_S 간격으로 발사(순간 RPM 평탄화). mock으로
    콜 진입 시각을 재 스태거 실측.
 2. 재시도 단일화 — SDK 층(_client.max_retries=2)만, 앱 미추가(이중 방지) config 확인.
 3. 전 생성 실패 → 기존 502(스태거가 실패를 삼키지 않음) 회귀.

Run: python tests/test_gemini_burst_mitigation_integration.py   (mock 8001 자동 기동)
"""
from __future__ import annotations

import os, subprocess, sys, time
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
B8001 = "http://localhost:8001"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys():
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


def ok(m):  print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")


def sb_user(c, e):
    return c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                  json={"email": e, "password": "test1234", "email_confirm": True}).json()["id"]


def login(c, e):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": e, "password": "test1234"}).json()["access_token"]


def gen(c, tok):
    return c.post(f"{B8001}/api/routes/generate", headers={"Authorization": f"Bearer {tok}"},
                  json={"start": {"lat": 37.5445, "lng": 127.0374}, "target_distance_km": 5.0})


def scenario(c, seq, **extra):
    assert c.post(f"{B8001}/__mock/scenario", json={"seq": seq, **extra}).status_code == 200


def stats(c):
    return c.get(f"{B8001}/__mock/stats").json()


def run_tests():
    c = httpx.Client(timeout=60)
    uid = None
    proc = None
    try:
        step("0. config — 스태거 상수 + SDK 단일 재시도")
        from app.services import route_service, openai_service
        assert route_service._POOL_STAGGER_S == 0.25, route_service._POOL_STAGGER_S
        assert openai_service._client.max_retries == 2, \
            f"재시도는 SDK 층 단일(2), got {openai_service._client.max_retries}"
        ok("_POOL_STAGGER_S=0.25 · SDK max_retries=2(앱 미추가 — 이중 재시도 없음)")

        uid = sb_user(c, f"burst-{TS}@test.com")
        tok = login(c, f"burst-{TS}@test.com")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.mock_route_app:app", "--port", "8001", "--log-level", "warning"],
            cwd=os.path.join(os.path.dirname(__file__), ".."))
        for _ in range(40):
            try:
                if c.get(f"{B8001}/health").status_code == 200: break
            except Exception: pass
            time.sleep(0.5)
        else:
            fail("mock 기동 실패")
        c.request("PATCH", f"{B8001}/api/me/profile", headers={"Authorization": f"Bearer {tok}"},
                  json={"nickname": f"BST{TS}"})
        c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{uid}", headers=_ADM, json={"tier": "premium"})
        ok("premium 유저 + mock 8001 up")

        step("1. 롤 스태거 실측 — pool 5, 인접 콜 간격 ≈ 0.25s")
        scenario(c, [{"snap_km": 5.0}], pool_size=5)
        r = gen(c, tok)
        assert r.status_code == 200, r.text[:200]
        st = stats(c)
        span, gaps = st["call_span"], st["call_gaps"]
        # 5롤 × 0.25 스태거 → span ≈ 1.0s. 스케줄 지터 감안 하한 0.7·상한 2.0.
        assert 0.7 <= span <= 2.0, f"콜 span {span}s (스태거 미적용이면 ~0s), gaps={gaps}"
        # 대부분 간격이 양수(순차 발사) — 동시 발사면 gaps≈0
        assert sum(1 for g in gaps if g >= 0.15) >= 3, f"인접 간격 대부분 ≈0.25 기대, got {gaps}"
        ok(f"콜 span={span}s · gaps={gaps} — 스태거 실측(9RPS 버스트 평탄화)")

        step("2. 전 생성 실패 → 기존 502 (스태거가 실패를 삼키지 않음)")
        scenario(c, [{"snap_km": 5.0}], gemini_seq=[-1, -1, -1], pool_size=3)
        r = gen(c, tok)
        assert r.status_code == 502, f"전 생성 실패 → 502, got {r.status_code}"
        ok("전 롤 실패 시 여전히 502 (완화가 실패 은닉 안 함)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        if proc: proc.terminate()
        if uid:
            c.delete(f"{_SB}/rest/v1/routes?user_id=eq.{uid}", headers=_ADM)
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
