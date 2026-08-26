"""
Unit: Apple Universal Links AASA 정적 서빙 (2026-08-26)

/.well-known/apple-app-site-association 가 Apple 요구대로 200·application/json
(정확·charset 없음)·리다이렉트 없이·인증 불요로 서빙되는지. /api 라우터 밖이라
uuid path guard·auth dependency 우회.

Run: python tests/test_aasa_route.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

_n = 0


def ok(m):
    global _n
    _n += 1
    print(f"  ✓ {m}")


def run_tests():
    # 인증 오버라이드 없이(공개 경로) — 토큰 없이 200이어야
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/.well-known/apple-app-site-association")

    assert r.status_code == 200, r.status_code
    ok("200 (인증 불요·공개)")

    # Apple 엄격: 정확히 application/json (charset 파라미터 없이)
    assert r.headers["content-type"] == "application/json", r.headers.get("content-type")
    ok(f"Content-Type '{r.headers['content-type']}' (charset 없음)")

    # 리다이렉트 없이 직접 200
    assert r.history == [], r.history
    ok("리다이렉트 0 (직접 200)")

    # 본문 JSON 유효 + Apple 형식(applinks.details[].appID·paths)
    body = r.json()
    det = body["applinks"]["details"][0]
    assert "appID" in det and "paths" in det, det
    ok(f"JSON 유효 · applinks.details appID={det['appID']} paths={det['paths']}")

    # HEAD도 200(curl -I 검증 대응) — content-type 동일
    rh = c.head("/.well-known/apple-app-site-association")
    assert rh.status_code == 200 and rh.headers["content-type"] == "application/json", \
        (rh.status_code, rh.headers.get("content-type"))
    ok("HEAD 200 · application/json (curl -I 대응)")


if __name__ == "__main__":
    run_tests()
    print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_n} assert)\n" + "=" * 50)
