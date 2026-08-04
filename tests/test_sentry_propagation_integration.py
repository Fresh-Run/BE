"""
Integration: Sentry 추적 헤더 전파 차단 + _mask_key 3형 백포트 (2026-08-04)

배경: 에어코리아 게이트웨이가 sentry-trace/baggage 실린 요청을 400 reason 10으로
반려(프로브 3면 비교 실측). 수리 = trace_propagation_targets=[](전면 미전파 —
traces_sample_rate=0이라 전파 실익 0). 이 파일은 영구 회귀(프로브 TEMP와 별개).

외부 콜 0(Sentry DSN은 더미·httpx는 MockTransport) · DB 무접촉 · 부수효과 0.

S-1 init_sentry 실구성 — trace_propagation_targets=[] 적용·활성 True
S-2 에러 캡처 불변 — capture_exception이 transport까지 도달(envelope 1건)
S-3 [민감도 양성 대조] 기본 targets(전체 매치)+전파 문맥이면 실제로 주입됨
    — 이 테스트 장치가 주입을 잡아낼 수 있음을 먼저 증명
S-4 [수리 검증] 동일 조건에서 targets=[]면 외부 URL(에어코리아 포함) 미주입
    — should_propagate_trace False + 실발신 헤더에 sentry 2종 부재
M-1 _mask_key 3형 — 원문·디코드형·URL재인코드형 전부 <key>, 빈 키 무변형

Run: python tests/test_sentry_propagation_integration.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging  # noqa: E402

import httpx  # noqa: E402
import sentry_sdk  # noqa: E402

# 더미 DSN(localhost:9)으로의 배달 실패 재시도 경고 — 기대된 소음이라 침묵.
logging.getLogger("urllib3").setLevel(logging.ERROR)
from sentry_sdk.tracing_utils import should_propagate_trace  # noqa: E402

from app import main as app_main  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services import weather_service as ws  # noqa: E402

# 더미 DSN — 실계정 아님(전부 0), localhost로 향해 어떤 외부 전송도 불가.
DUMMY_DSN = "http://00000000000000000000000000000000@localhost:9/1"
AK_URL = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/x"
FAKE_INCOMING = {"sentry-trace": "11112222333344445555666677778888-1234567812345678-1"}

ENC_KEY = "test%2Bkey%2FENC%3Dabcd"
DEC_KEY = "test+key/ENC=abcd"


def ok(m):
    print(f"  ✓ {m}")


def send_and_capture_headers() -> dict:
    """센트리가 패치한 실 httpx.Client.send 경유로 1회 발신, 실발신 헤더 반환.
    와이어는 MockTransport — 외부 콜 0."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({k: v for k, v in request.headers.items()})
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        c.send(c.build_request("GET", AK_URL))
    return seen


def run_tests():
    orig_dsn = settings.sentry_dsn
    orig_ak = settings.airkorea_api_key
    try:
        print("[S 센트리 전파 차단]")
        settings.sentry_dsn = DUMMY_DSN
        assert app_main.init_sentry() is True
        client = sentry_sdk.get_client()
        assert client.is_active()
        assert client.options["trace_propagation_targets"] == [], (
            client.options["trace_propagation_targets"])
        ok("S-1 init_sentry 활성 + trace_propagation_targets=[] 실적용")

        envelopes = []
        client.transport.capture_envelope = envelopes.append
        event_id = sentry_sdk.capture_exception(RuntimeError("전파 차단 회귀 프로브"))
        assert event_id is not None and len(envelopes) == 1, (
            event_id, len(envelopes))
        ok("S-2 에러 캡처 불변 — capture_exception → envelope 도달 1건")

        # 양성 대조: 기본 targets(전체 매치)로 재-init — 주입이 실제로 일어남을
        # 증명해 테스트 민감도 확보(§4-9 무교란 증명 동형). 대조용 최소 구성.
        # 서빙 동형 문맥 = 수신 요청 **트랜잭션**(FastAPI 통합이 요청마다 시작).
        # 트랜잭션 없는 단독 스팬은 주입 0(2026-08-04 로컬 실측) — 필수 조건.
        sentry_sdk.init(dsn=DUMMY_DSN, traces_sample_rate=0)
        ctl = sentry_sdk.get_client()
        assert should_propagate_trace(ctl, AK_URL) is True
        tx = sentry_sdk.continue_trace(FAKE_INCOMING, op="http.server", name="req")
        with sentry_sdk.start_transaction(tx):
            seen = send_and_capture_headers()
        assert "sentry-trace" in seen and "baggage" in seen, (
            "양성 대조 실패 — 장치가 주입을 못 잡으면 S-4가 무의미")
        assert seen["sentry-trace"].startswith("11112222333344445555666677778888-")
        ok("S-3 양성 대조 — 기본 targets+수신 트랜잭션 문맥이면 2종 실주입")

        # 수리 검증: 실구성(init_sentry)으로 재-init — 동일 문맥에서 미주입.
        assert app_main.init_sentry() is True
        fixed = sentry_sdk.get_client()
        assert should_propagate_trace(fixed, AK_URL) is False
        assert should_propagate_trace(fixed, "https://api.openweathermap.org/x") is False
        tx = sentry_sdk.continue_trace(FAKE_INCOMING, op="http.server", name="req")
        with sentry_sdk.start_transaction(tx):
            seen = send_and_capture_headers()
        assert "sentry-trace" not in seen and "baggage" not in seen, seen
        ok("S-4 수리 검증 — 동일 트랜잭션 문맥에서도 외부 발신 sentry 2종 부재")

        print("[M _mask_key 3형 백포트]")
        settings.airkorea_api_key = ENC_KEY
        masked = ws._mask_key(f"a={ENC_KEY} b={DEC_KEY} c=plain")
        assert masked == "a=<key> b=<key> c=plain", masked
        assert ws._mask_key("no-key") == "no-key"
        settings.airkorea_api_key = ""
        assert ws._mask_key(f"still {DEC_KEY}") == f"still {DEC_KEY}", "빈 키 가드"
        ok("M-1 원문·디코드형·재인코드형 전부 <key> · 빈 키 무변형")

    finally:
        settings.sentry_dsn = orig_dsn
        settings.airkorea_api_key = orig_ak
        # 남은 세션에 더미 클라이언트가 살지 않게 비활성으로 원복.
        sentry_sdk.get_global_scope().set_client(None)

    print("\n전부 통과 — 전파 차단 실증(양성 대조 포함)·캡처 불변·마스킹 3형")


if __name__ == "__main__":
    run_tests()
