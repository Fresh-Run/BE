# TEMP — 에어코리아 진단 프로브 테스트 (2026-08-04). 제거 트리거: 미스터리 해소 시
# 프로브 엔드포인트·weather_service 블록·app/diag_airkorea_shell.py와 일괄 삭제.
"""
Integration: GET /admin/diag/airkorea-probe (TEMP 진단 — 관측 전용)

외부 콜 0(에어코리아 실호출 금지 — 전송 계층 전부 mock)·DB 무접촉·부수효과 0.
인증은 dependency_overrides(get_current_user)로 주입 — Supabase 무접촉.

A-1 미인증 → 401
A-2 비admin → 404 은닉(detail "Not Found")
A-3 ADMIN_USER_IDS 미설정(빈 set) → admin이어도 404 fail-safe
P-1 admin + 관측 성공 → 200 shape(필드 11종)·전송 정확히 1회(재시도 0)·
    요청 url/params 실기능 동일(측정소·ver·serviceKey 디코드형)
P-2 응답 전체에 키 원문 부재 + ****뒤4자 마스크 존재 (프라이버시 이중 검증)
P-3 전송 예외 → 200 {ok:false, error, detail(마스킹)} — 500 아님
P-4 키 미설정 → NotConfigured·전송 0회
M-1 _probe_mask — 원문·디코드형·URL인코드형 3형 전부 ****뒤4자
T-1 _probe_transport_observe 실코드 — FakeClient(send만 대체)로 URL 조립·
    마스킹·관측 필드 실검증 (extensions 부재 시 peer/tls None 방어 포함)
S-1 부수효과 없음 — _station_cache·_cache(응답 캐시) 전후 동일, DB 콜 0

Run: python tests/test_airkorea_probe_integration.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.auth import get_current_user  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models.schemas import CurrentUser  # noqa: E402
from app.services import weather_service as ws  # noqa: E402

PROBE_PATH = "/api/admin/diag/airkorea-probe"
ADMIN_UID = "00000000-0000-4000-8000-0000000000ad"
PLAIN_UID = "00000000-0000-4000-8000-0000000000bb"
# Encoding형(% 포함) 테스트 키 — 디코드형은 "test+key/ENC=abcd"
ENC_KEY = "test%2Bkey%2FENC%3Dabcd"
DEC_KEY = "test+key/ENC=abcd"

EXPECT_FIELDS = {"ok", "url", "status", "http_version", "headers", "body_head",
                 "peer", "local", "tls_version", "tls_cipher", "elapsed_ms"}


def ok(m):
    print(f"  ✓ {m}")


def as_user(uid):
    app.dependency_overrides[get_current_user] = (
        lambda: CurrentUser(user_id=uid, email="probe@test.local"))


def run_tests():
    orig = (settings.admin_user_ids, settings.airkorea_api_key,
            dict(app.dependency_overrides))
    client = TestClient(app)
    calls: list[dict] = []

    def observe_ok(url, params):
        calls.append({"url": url, "params": dict(params)})
        return {
            "url": ws._probe_mask(f"{url}?serviceKey={DEC_KEY}&returnType=json"),
            "status": 400, "http_version": "HTTP/1.1",
            "headers": {"server": "NIA-GW"},
            "body_head": ws._probe_mask(
                '{"errMsg":"SERVICE ERROR","returnReasonCode":"10"}'),
            "peer": ["211.0.0.1", 443], "local": ["172.16.0.2", 51234],
            "tls_version": "TLSv1.3", "tls_cipher": "TLS_AES_256_GCM_SHA384",
            "elapsed_ms": 123.4,
        }

    orig_observe = ws._probe_transport_observe
    try:
        settings.admin_user_ids = ADMIN_UID
        settings.airkorea_api_key = ENC_KEY
        ws._probe_transport_observe = observe_ok
        station_before = dict(ws._station_cache)
        wcache_before = dict(ws._cache)

        print("[A 게이트 — 404 은닉 표준]")
        app.dependency_overrides.pop(get_current_user, None)
        r = client.get(PROBE_PATH)
        assert r.status_code == 401, r.status_code
        ok("A-1 미인증 401")

        as_user(PLAIN_UID)
        r = client.get(PROBE_PATH)
        assert r.status_code == 404 and r.json()["detail"] == "Not Found", (
            r.status_code, r.text)
        assert calls == [], "비admin에서 전송이 발생하면 안 됨"
        ok("A-2 비admin 404 은닉 + 전송 0회")

        settings.admin_user_ids = ""
        as_user(ADMIN_UID)
        r = client.get(PROBE_PATH)
        assert r.status_code == 404, r.status_code
        settings.admin_user_ids = ADMIN_UID
        ok("A-3 ADMIN_USER_IDS 미설정 fail-safe 404")

        print("[P 프로브 동작 — 전송 mock, 실호출 0]")
        as_user(ADMIN_UID)
        r = client.get(PROBE_PATH)
        assert r.status_code == 200, (r.status_code, r.text)
        body = r.json()
        assert body["ok"] is True and set(body) == EXPECT_FIELDS, set(body)
        assert len(calls) == 1, f"원샷이어야 함(재시도 0) — {len(calls)}회"
        c = calls[0]
        assert c["url"].endswith(
            "/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty")
        assert c["params"]["stationName"] == ws._PROBE_STATION
        assert c["params"]["ver"] == "1.3" and c["params"]["dataTerm"] == "DAILY"
        assert c["params"]["serviceKey"] == DEC_KEY, "실기능 동일 — 디코드형 전달"
        ok("P-1 200 shape 11필드 · 전송 1회 · 실기능 동일 url/params")

        raw = r.text
        for leak in (ENC_KEY, DEC_KEY):
            assert leak not in raw, f"키 원문 누출: {leak[:8]}..."
        assert "****abcd" in raw, "마스크(****+뒤4자) 부재"
        ok("P-2 응답 전체 키 원문 부재 + ****abcd 마스크 존재")

        def observe_boom(url, params):
            calls.append({"url": url, "params": dict(params)})
            raise httpx.ConnectError(f"boom serviceKey={DEC_KEY}")

        ws._probe_transport_observe = observe_boom
        r = client.get(PROBE_PATH)
        assert r.status_code == 200, (r.status_code, r.text)
        body = r.json()
        assert body["ok"] is False and body["error"] == "ConnectError"
        assert DEC_KEY not in r.text and "****abcd" in body["detail"]
        assert len(calls) == 2, "예외에도 재시도 없음(원샷)"
        ok("P-3 전송 예외 → ok:false·error명·detail 마스킹·재시도 0")

        settings.airkorea_api_key = ""
        r = client.get(PROBE_PATH)
        assert r.status_code == 200 and r.json()["error"] == "NotConfigured"
        assert len(calls) == 2, "키 미설정 시 전송 0회"
        settings.airkorea_api_key = ENC_KEY
        ok("P-4 키 미설정 → NotConfigured·전송 0회")

        print("[M 마스킹 단독]")
        masked = ws._probe_mask(f"a={ENC_KEY} b={DEC_KEY} c=plain")
        assert ENC_KEY not in masked and DEC_KEY not in masked
        assert masked == "a=****abcd b=****abcd c=plain", masked
        assert ws._probe_mask("no-key-here") == "no-key-here"
        ok("M-1 3형(원문·디코드·재인코드) 전부 ****abcd, 무키 텍스트 무변형")

        print("[T 전송 관측 실코드 — send만 대체한 FakeClient]")

        class FakeClient:
            sent: list = []

            def __init__(self, timeout=None):
                assert timeout == ws._AIRKOREA_TIMEOUT, "전용 타임아웃 3s 동일 구성"
                self._real = httpx.Client(timeout=timeout)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                self._real.close()

            def build_request(self, method, url, params=None):
                return self._real.build_request(method, url, params=params)

            def send(self, req):
                FakeClient.sent.append(str(req.url))
                return httpx.Response(
                    400, headers={"Server": "NIA API GW"},
                    text=f'{{"errMsg":"x","key":"{DEC_KEY}"}}', request=req)

        class HttpxShim:
            Client = FakeClient

            def __getattr__(self, name):
                return getattr(httpx, name)

        orig_httpx = ws.httpx
        ws.httpx = HttpxShim()
        try:
            obs = orig_observe(
                f"{ws._AIRKOREA_BASE}/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty",
                {"stationName": ws._PROBE_STATION, "serviceKey": ws._airkorea_key()})
        finally:
            ws.httpx = orig_httpx
        assert len(FakeClient.sent) == 1
        flat = str(obs)
        assert ENC_KEY not in flat and DEC_KEY not in flat and "****abcd" in obs["url"]
        assert obs["status"] == 400 and obs["http_version"] == "HTTP/1.1"
        assert obs["headers"]["server"] == "NIA API GW"
        assert "errMsg" in obs["body_head"] and "****abcd" in obs["body_head"]
        assert obs["peer"] is None and obs["tls_version"] is None, (
            "extensions 부재 시 None 방어")
        assert isinstance(obs["elapsed_ms"], float)
        ok("T-1 실 URL 조립·본문/URL 마스킹·상태·헤더·extensions 부재 방어")

        print("[S 부수효과 없음]")
        assert ws._station_cache == station_before, "측정소 캐시 오염"
        assert ws._cache == wcache_before, "응답 캐시 오염"
        ok("S-1 측정소·응답 캐시 전후 동일 (DB 콜 0 — 전 구간 mock·무접촉)")

    finally:
        settings.admin_user_ids, settings.airkorea_api_key = orig[0], orig[1]
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig[2])
        ws._probe_transport_observe = orig_observe

    print("\n전부 통과 — 프로브 게이트·shape·마스킹·원샷·부수효과 없음 확인")


if __name__ == "__main__":
    run_tests()
