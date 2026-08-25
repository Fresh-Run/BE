"""
Regression: 비uuid path param 전수 404 은닉 — 공용 라우터 가드(§C '비uuid 22P02' 근절)

전례: 비uuid path param({crew_id}="my"·route DELETE 등)이 PostgREST uuid 필터에서
22P02 → 일반 예외 → 502 노출. route delete(2026-08-04)·crews(2026-08-08) 개별
교정에 이어, `validate_uuid_path_params` 라우터 dependency로 전 uuid param(`id`/
`*_id`) 일괄 근절. 검증: 비uuid → 404(502 아님)·DB 무접촉·유효 uuid 통과·고정 경로 불변.

Run: python tests/test_uuid_path_guard.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.auth import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.models.schemas import CurrentUser  # noqa: E402
from app.services import (  # noqa: E402
    crew_service, follow_service, notification_service, route_service, run_service,
)

VALID = "00000000-0000-4000-8000-000000000001"

# 카테고리별 대표 at-risk 엔드포인트(agent 분류 47건 커버 — param 종류 전수):
# route_id·run_id·crew_id·user_id·requester_id·report_id·notification_id·comment_id(중첩)·
# target_id(중첩)·announcement_id(중첩)·message_id(중첩).
NONUUID_PROBES = [
    ("get", "/api/routes/not-a-uuid"),
    ("patch", "/api/routes/xx"),
    ("post", "/api/routes/xx/copy"),
    ("post", "/api/routes/xx/like"),
    ("get", "/api/routes/xx/comments"),
    ("delete", f"/api/routes/{VALID}/comments/cc"),   # 중첩 2번째(comment_id) 비uuid
    ("delete", "/api/routes/rr/comments/cc"),          # 중첩 1번째(route_id) 비uuid
    ("get", "/api/runs/my"),
    ("delete", "/api/runs/xx"),
    ("post", "/api/runs/xx/kudos"),
    ("get", "/api/runs/xx/track"),
    ("delete", f"/api/runs/{VALID}/comments/cc"),      # 중첩 comment_id
    ("get", "/api/crews/abc/ranking"),
    ("get", "/api/crews/abc/members"),
    ("post", "/api/crews/abc/join"),
    ("post", "/api/crews/abc/invitations"),
    ("patch", f"/api/crews/{VALID}/members/tt/role"),  # 중첩 target_id 비uuid
    ("delete", f"/api/crews/{VALID}/members/tt"),      # 중첩 target_id 비uuid
    ("get", "/api/users/notauser/profile"),
    ("post", "/api/users/notauser/follow"),
    ("delete", "/api/me/followers/notauser"),
    ("patch", "/api/me/follow-requests/notauser"),
    ("patch", "/api/notifications/xx/read"),
    ("delete", "/api/notifications/xx"),
    ("delete", f"/api/crews/{VALID}/chat/messages/mm"),  # 중첩 message_id
]


def run_tests():
    orig_over = dict(app.dependency_overrides)
    calls = []
    services = [route_service, run_service, crew_service, follow_service, notification_service]
    origs = {s: s.get_supabase_admin for s in services}

    def make_counter(orig):
        def counting():
            calls.append(1)
            return orig()
        return counting

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="00000000-0000-4000-8000-00000000dead", email="x@t.l")
    for s in services:
        s.get_supabase_admin = make_counter(origs[s])
    try:
        c = TestClient(app, raise_server_exceptions=False)

        # 1) 비uuid 전수 → 404 은닉(502 아님) · DB 무접촉
        for m, u in NONUUID_PROBES:
            r = getattr(c, m)(u)
            assert r.status_code == 404, (m, u, r.status_code, r.text[:80])
            assert r.json().get("error_code") == "not_found", (u, r.text[:80])
        assert calls == [], f"비uuid는 DB 조회 전 차단돼야 함(쿼리 0) — {len(calls)}회 유출"
        print(f"  ✓ 비uuid {len(NONUUID_PROBES)}엔드포인트(param 전종) 404 은닉 · DB 무접촉 (502 근절)")

        # 2) 유효 uuid는 가드 통과 → 핸들러 경로(DB 접촉) → 무존재 404 (계약 불변)
        calls.clear()
        r = c.get(f"/api/routes/{VALID}")
        assert r.status_code == 404, (r.status_code, r.text[:80])
        assert len(calls) >= 1, "유효 uuid는 가드 통과해 핸들러가 DB 조회해야(가드 오차단 아님)"
        print(f"  ✓ 유효 uuid 무존재 404 · DB 조회 {len(calls)}회(가드 통과·계약 불변)")

        # 3) 고정 경로는 param 없어 가드 무동작(경로 순서 계약 불변)
        r = c.get("/api/routes/public")
        assert r.status_code == 200, (r.status_code, r.text[:80])
        r = c.get("/api/crews/mine")
        assert r.status_code == 200, (r.status_code, r.text[:80])
        print("  ✓ /routes/public·/crews/mine 200(고정 경로 가드 무영향)")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig_over)
        for s in services:
            s.get_supabase_admin = origs[s]
    print("\n전부 통과 — 비uuid 22P02→502 전수 근절, 부수효과 0")


if __name__ == "__main__":
    run_tests()
