"""
Regression: GET /crews/{비uuid} → 404 은닉 (2026-08-08 실관측 — /crews/my 502)

전례: FE가 /crews/my 오호출 → 고정 경로 /crews/mine이 아닌 패턴 경로
{crew_id}="my" 매칭 → PostgREST uuid 필터 22P02 → 일반 예외 → 502 노출.
route delete 교정(2026-08-04)과 동형 — 비uuid 재발 2호. 계약: 존재 불가 id도
404 은닉. DB 무접촉(uuid 검증이 쿼리 전 차단), 인증은 dependency_overrides.

Run: python tests/test_crew_nonuuid_404.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.auth import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.models.schemas import CurrentUser  # noqa: E402
from app.services import crew_service  # noqa: E402


def run_tests():
    orig = dict(app.dependency_overrides)
    calls = []
    orig_admin = crew_service.get_supabase_admin

    def counting_admin():
        calls.append(1)
        return orig_admin()

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="00000000-0000-4000-8000-00000000dead", email="x@t.l")
    crew_service.get_supabase_admin = counting_admin
    try:
        c = TestClient(app, raise_server_exceptions=False)
        for bad in ("my", "not-a-uuid", "123"):
            r = c.get(f"/api/crews/{bad}")
            assert r.status_code == 404, (bad, r.status_code, r.text)
            assert r.json()["error_code"] in ("crew_not_found", "not_found"), r.text
        assert calls == [], "비uuid는 DB 조회 전 차단(쿼리 0)"
        print("  ✓ /crews/my·비uuid 2형 전부 404 은닉 · DB 쿼리 0 (502 재발 방지)")
        # 고정 경로 /crews/mine은 패턴에 안 잡히고 정상(경로 순서 계약 불변)
        r = c.get("/api/crews/mine")
        assert r.status_code == 200, (r.status_code, r.text)
        print("  ✓ /crews/mine 200 (고정 경로 선순위 불변)")
        # 유효 uuid 무존재는 기존 경로 404(DB 1조회)
        r = c.get("/api/crews/00000000-0000-4000-8000-000000000001")
        assert r.status_code == 404 and len(calls) >= 1
        print("  ✓ 유효 uuid 무존재 404(기존 경로 불변)")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig)
        crew_service.get_supabase_admin = orig_admin
    print("\n전부 통과 — 부수효과 0(읽기 1회뿐)")


if __name__ == "__main__":
    run_tests()
