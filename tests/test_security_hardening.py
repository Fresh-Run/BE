"""
Integration: 출시 전 보안 미비 처리 (2026-08-26)

#18 /docs 프로덕션 차단 · #18 보안 헤더(HSTS·nosniff·frame) · #11 per-IP rate limit.
하위호환(헤더 additive·정상 요청 무영향). DB 무접촉(라우팅·미들웨어만).

Run: python tests/test_security_hardening.py
"""
from __future__ import annotations

import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_mod  # noqa: E402
from app.core.config import settings  # noqa: E402

_n = 0


def ok(m):
    global _n
    _n += 1
    print(f"  ✓ {m}")


def run_tests():
    c = TestClient(main_mod.app, raise_server_exceptions=False)

    print("[#18 보안 헤더 — 전 응답]")
    for path in ("/health", "/.well-known/apple-app-site-association"):
        r = c.get(path)
        assert r.headers.get("strict-transport-security", "").startswith("max-age="), path
        assert r.headers.get("x-content-type-options") == "nosniff", path
        assert r.headers.get("x-frame-options") == "DENY", path
    ok("HSTS·X-Content-Type-Options:nosniff·X-Frame-Options:DENY (health·AASA)")

    # AASA 하위호환: 헤더 추가돼도 Content-Type·본문 불변
    a = c.get("/.well-known/apple-app-site-association")
    assert a.status_code == 200 and a.headers["content-type"] == "application/json"
    assert "applinks" in a.json()
    ok("AASA 무영향 — application/json·본문 불변(헤더만 additive)")

    print("\n[#18 /docs 환경별]")
    assert c.get("/docs").status_code == 200 and c.get("/openapi.json").status_code == 200
    ok(f"dev(environment={settings.environment}) /docs·/openapi.json 200(유지)")

    print("\n[#11 per-IP rate limit]")
    orig = settings.rate_limit_per_min
    try:
        settings.rate_limit_per_min = 5
        main_mod._rl_buckets.clear()
        codes = [c.get("/api/crews/mine", headers={"fly-client-ip": "1.2.3.4"}).status_code
                 for _ in range(8)]
        assert 429 in codes and codes[:5].count(429) == 0, codes  # 처음 5 통과, 이후 429
        r429 = c.get("/api/crews/mine", headers={"fly-client-ip": "1.2.3.4"})
        assert r429.status_code == 429 and r429.json()["error_code"] == "rate_limited"
        assert r429.headers.get("retry-after") == "60"
        # 보안 헤더는 429에도(security 미들웨어가 바깥)
        assert r429.headers.get("x-frame-options") == "DENY"
        ok(f"한도5 초과→429·error_code=rate_limited·Retry-After·헤더 유지 (codes={codes})")

        # 다른 IP는 독립(오탐 없음)
        main_mod._rl_buckets.clear()
        settings.rate_limit_per_min = 3
        ip_a = [c.get("/api/crews/mine", headers={"fly-client-ip": "10.0.0.1"}).status_code for _ in range(4)]
        ip_b = c.get("/api/crews/mine", headers={"fly-client-ip": "10.0.0.2"}).status_code
        assert 429 in ip_a and ip_b != 429, (ip_a, ip_b)
        ok("IP별 독립 카운트(A 초과 429·B 무영향) — 프록시 IP 오탐 없음")

        # health·AASA는 exempt(무제한)
        main_mod._rl_buckets.clear()
        settings.rate_limit_per_min = 2
        hc = [c.get("/health", headers={"fly-client-ip": "9.9.9.9"}).status_code for _ in range(5)]
        assert all(x == 200 for x in hc), hc
        ok("/health exempt(한도2, 5회 전부 200) — Fly 헬스체크 무영향")
    finally:
        settings.rate_limit_per_min = orig
        main_mod._rl_buckets.clear()

    print("\n[하위호환 — 정상 요청 무영향]")
    # 한도 넉넉(기본)에서 정상 요청은 429 없음(200/401 등 종전 계약)
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    ok("정상 요청 종전 계약 유지(rate limit 무발동·헤더만 additive)")

    print("\n[#18 /docs 프로덕션 차단 — env reload]")
    orig_env = settings.environment
    try:
        settings.environment = "production"
        importlib.reload(main_mod)
        pc = TestClient(main_mod.app, raise_server_exceptions=False)
        assert pc.get("/docs").status_code == 404, pc.get("/docs").status_code
        assert pc.get("/redoc").status_code == 404
        assert pc.get("/openapi.json").status_code == 404
        # 헬스는 여전히 200(앱 정상)
        assert pc.get("/health").status_code == 200
        ok("production /docs·/redoc·/openapi.json 404(은닉) · /health 200(정상)")
    finally:
        settings.environment = orig_env
        importlib.reload(main_mod)   # dev 복원


if __name__ == "__main__":
    run_tests()
    print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_n} assert)\n" + "=" * 50)
