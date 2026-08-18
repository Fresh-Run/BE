"""
Unit: UV One Call 4.0 current 파싱 (2026-08-18 전환 — /data/4.0/onecall/current)

외부 콜 0(가짜 클라이언트)·DB 무접촉.
V-1 정상 shape {"data":[{"uvi":8.6}]} → 8.6 (3.0의 current.uvi 아님 — 실검증 경로)
V-2 방어 — data 빈 배열 / uvi 부재 / data 키 자체 부재 / 비200 → 전부 None
V-3 요청 경로가 /data/4.0/onecall/current (구 /2.5/uvi 아님)
V-4 OW 콜 카운터 — 4.0 전환에도 콜당 +1 배선 유지
V-5 appid — 요청 params로만 전달(URL 문자열 조립 없음 — 로그 노출면 없음)

Run: python tests/test_uv_v4_parsing.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.services import weather_service as ws  # noqa: E402


def ok(m):
    print(f"  ✓ {m}")


def client(payload, status=200, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, text=json.dumps(payload))
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def fetch(payload, status=200, seen=None):
    async def run():
        async with client(payload, status, seen) as c:
            return await ws._fetch_uv(c, 37.57, 126.98, "test-key")
    return asyncio.run(run())


def run_tests():
    seen = []
    v = fetch({"data": [{"uvi": 8.6, "dt": 1}], "lat": 37.57}, seen=seen)
    assert v == 8.6, v
    ok("V-1 data[0].uvi → 8.6")

    assert fetch({"data": []}) is None
    assert fetch({"data": [{"dt": 1}]}) is None
    assert fetch({"lat": 37.57}) is None
    assert fetch({"current": {"uvi": 9.0}}) is None, "3.0 shape는 미지원 — None 방어"
    assert fetch({}, status=401) is None
    ok("V-2 빈 data·uvi 부재·data 부재·3.0 shape·비200 → 전부 None(타일 숨김)")

    req = seen[0]
    assert req.url.path == "/data/4.0/onecall/current", req.url.path
    ok("V-3 요청 경로 /data/4.0/onecall/current (구 /2.5/uvi 아님)")

    before = ws.ow_process_total()
    fetch({"data": [{"uvi": 1.0}]})
    assert ws.ow_process_total() == before + 1
    ok("V-4 OW 콜 카운터 +1 (4.0 전환에도 배선 유지)")

    assert req.url.params.get("appid") == "test-key"
    ok("V-5 appid는 params 전달 — 코드에 URL 문자열 조립·로그 없음")

    print("\n전부 통과 — 외부 콜 0·DB 무접촉")


if __name__ == "__main__":
    run_tests()
