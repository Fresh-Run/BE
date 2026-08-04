"""
Regression: DELETE /routes/{비uuid} → 404 은닉 (2026-08-04 실서버 관측 교정)

전례: 비uuid path param이 PostgREST uuid 필터에서 22P02 APIError → 일반 예외
경로로 502 server_error 노출(스테이징 실관측). 계약(API_GUIDE §5)은 존재할 수
없는 id도 404 은닉. DB 무접촉(uuid 검증이 쿼리 전에 차단 — 전송 0 assert),
인증은 dependency_overrides.

Run: python tests/test_route_delete_nonuuid.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.auth import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.models.schemas import CurrentUser  # noqa: E402
from app.services import route_service  # noqa: E402


def run_tests():
    orig = dict(app.dependency_overrides)
    calls = []
    orig_admin = route_service.get_supabase_admin

    def counting_admin():
        calls.append(1)
        return orig_admin()

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="00000000-0000-4000-8000-00000000dead", email="x@t.l")
    route_service.get_supabase_admin = counting_admin
    try:
        c = TestClient(app, raise_server_exceptions=False)
        for bad in ("not-a-uuid", "123", "00000000-0000-4000-8000"):
            r = c.delete(f"/api/routes/{bad}")
            assert r.status_code == 404, (bad, r.status_code, r.text)
            assert r.json()["error_code"] in ("route_not_found", "not_found"), r.text
        assert calls == [], "비uuid는 DB 조회 전에 차단돼야 함(쿼리 0)"
        print("  ✓ 비uuid 3형 전부 404 은닉 · DB 쿼리 0 (22P02 502 재발 방지)")
        # 유효 uuid(무소유)는 기존 경로 그대로 404 — 계약 불변 확인(DB 1조회)
        r = c.delete("/api/routes/00000000-0000-4000-8000-000000000001")
        assert r.status_code == 404, (r.status_code, r.text)
        assert len(calls) == 1
        print("  ✓ 유효 uuid 무소유 404(기존 경로 불변·DB 조회 1)")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig)
        route_service.get_supabase_admin = orig_admin
    print("\n전부 통과 — 부수효과 0(삭제 대상 자체가 없음·select 1회뿐)")


if __name__ == "__main__":
    run_tests()
