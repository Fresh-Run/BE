"""
Integration: 에러 계약 보강 (2026-07-31 — 에러 감사 반영 소품 배치)

1. 미처리 예외 → 500 JSON {detail 고정 문자열, error_code:"server_error"}
   (기존 Starlette 기본 text/plain 공백 메움) + 내부 상세 비노출
2. [필수] Sentry 캡처 생존 — 고의 예외 라우트(임시, 테스트 프로세스 내 생성·제거)
   에서 capture 이벤트 ≥1 assert (before_send 수집·드롭 — 실전송 0)
3. 422 detail[].input 제거 — type·loc·msg 유지, 전송 원문(민감값) 에코백 0 실증
4. 임시 라우트 잔여 0 assert. DB 무접촉(부수효과 0).

Run: python tests/test_error_contract_integration.py
"""
from __future__ import annotations

import os
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402


def ok(m):
    print(f"  ✓ {m}")


class _Probe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., max_length=3)
    secret_note: Optional[str] = None


async def _boom():
    raise RuntimeError("sentry-capture-test")


async def _echo(m: _Probe):
    return {"ok": True}


def run_tests():
    n_routes_before = len(app.router.routes)
    app.add_api_route("/test-boom", _boom, methods=["GET"])
    app.add_api_route("/test-422", _echo, methods=["POST"])

    events = []
    import sentry_sdk

    def _before_send(event, hint):
        events.append(event)
        return None  # 드롭 — 실전송 0

    orig_dsn = settings.sentry_dsn
    try:
        # 더미 DSN으로 클라이언트 활성(전송은 before_send가 전량 드롭)
        sentry_sdk.init(dsn="https://pub@o0.ingest.sentry.io/1",
                        traces_sample_rate=0, before_send=_before_send)
        settings.sentry_dsn = "test-dummy"  # 핸들러의 명시 캡처 분기 활성
        c = TestClient(app, raise_server_exceptions=False)

        print("[1. 미처리 예외 → 500 JSON + error_code]")
        r = c.get("/test-boom")
        assert r.status_code == 500, r.status_code
        assert r.headers["content-type"].startswith("application/json"), r.headers
        body = r.json()
        assert body == {"detail": "일시적인 서버 오류입니다. 잠시 후 다시 시도해 주세요.",
                        "error_code": "server_error"}, body
        assert "sentry-capture-test" not in r.text, "내부 예외 메시지 노출 금지"
        assert "RuntimeError" not in r.text
        ok("500 JSON shape 고정·server_error·내부 상세 비노출")

        print("\n[2. Sentry 캡처 생존 실검증]")
        assert len(events) >= 1, "핸들러 경유 후 Sentry 이벤트 0 — 캡처 끊김"
        vals = [v.get("value", "") for e in events
                for v in (e.get("exception", {}).get("values") or [])]
        assert any("sentry-capture-test" in v for v in vals), vals
        ok(f"이벤트 {len(events)}건 캡처(예외 원문 포함) — before_send 드롭이라 실전송 0")

        print("\n[3. 422 — input 에코백 제거·type/loc/msg 유지]")
        r = c.post("/test-422", json={"name": "toolong",
                                      "secret_note": "MY-PRIVATE-GPS-37.5,127.0",
                                      "typo_field": 1})
        assert r.status_code == 422
        body = r.json()
        assert body["error_code"] == "validation_error", body
        assert isinstance(body["detail"], list) and len(body["detail"]) >= 2
        for e in body["detail"]:
            assert {"type", "loc", "msg"} <= set(e.keys()), e
            assert "input" not in e, f"input 에코백 잔존: {e}"
        assert "MY-PRIVATE-GPS" not in r.text, "민감값이 응답에 반사되면 안 됨"
        assert "toolong" not in r.text
        ok("전 원소 input 부재·type/loc/msg 유지·민감값 반사 0")

        print("\n[4. 401(중앙 핸들러) 회귀 — error_code 동봉 유지]")
        r = c.get("/api/me/settings")  # 토큰 없음
        assert r.status_code == 401 and r.json().get("error_code") == "unauthorized", r.text
        ok("401 error_code=unauthorized 유지")
    finally:
        settings.sentry_dsn = orig_dsn
        sentry_sdk.init(dsn=None)   # 더미 클라이언트 해제
        app.router.routes = [rt for rt in app.router.routes
                             if getattr(rt, "path", None) not in ("/test-boom", "/test-422")]
        assert len(app.router.routes) == n_routes_before, "임시 라우트 잔여"
        print("\n[cleanup] 임시 라우트 제거·라우트 수 원복·DB 무접촉")


if __name__ == "__main__":
    run_tests()
    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
