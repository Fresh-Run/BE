"""
Integration: UV 야간 0 처리 (AIR_QUALITY_SOURCE_DESIGN §3 ⓐ, 오너 승인 2026-07-31)

1. 야간 → value 0·"낮음" (일몰 직후 경계 포함)
2. 주간 → 현행(daily max) 유지 (일몰 직전 경계 포함)
3. 캐시 누출 차단 — 낮에 적재된 캐시가 일몰 뒤 히트돼도 0 (응답 시점 판정)
   + 공유 캐시 원본 무수정(deep copy — 07/05 오염 전례 축)
4. sun 결손 폴백 — 적재 시점 is_day 사용
5. uv 자체 결손 → 무변화(None 유지)

Run: python tests/test_uv_night_integration.py  (외부 콜 0 — 전부 mock, DB 무접촉)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings  # noqa: E402
from app.services import weather_service as ws  # noqa: E402


def ok(m):
    print(f"  ✓ {m}")


def _mock_fetchers(icon="01d", uv=9.3, sr=None, ss=None):
    now = time.time()
    sr = now - 6 * 3600 if sr is None else sr
    ss = now + 6 * 3600 if ss is None else ss

    async def fc(client, lat, lng, key):
        return {"name": "테스트", "dt": int(now),
                "main": {"temp": 20.0, "feels_like": 20.0, "humidity": 50},
                "weather": [{"id": 800, "description": "맑음", "icon": icon}],
                "wind": {"speed": 1.0},
                "sys": {"sunrise": int(sr), "sunset": int(ss)}}

    async def fa(client, lat, lng, key):
        return {"pm2_5": 10.0, "pm10": 20.0}

    async def fu(client, lat, lng, key):
        return uv

    return fc, fa, fu


def run_tests():
    orig = (ws._fetch_current, ws._fetch_air, ws._fetch_uv,
            settings.openweather_api_key)
    settings.openweather_api_key = settings.openweather_api_key or "test-dummy"
    try:
        now = time.time()

        print("[1. 야간 — 일몰 직후(60초 전 일몰) → 0·낮음]")
        ws._cache.clear()
        ws._fetch_current, ws._fetch_air, ws._fetch_uv = _mock_fetchers(
            icon="01n", uv=9.3, sr=now - 12 * 3600, ss=now - 60)
        r = asyncio.run(ws.get_weather(37.57, 126.98))
        assert r.uv is not None and r.uv.value == 0.0 and r.uv.grade == "낮음", r.uv
        ok(f"일몰 60초 뒤 → uv 0.0 '{r.uv.grade}' (daily max 9.3 미노출)")

        print("\n[2. 주간 — 일몰 직전(60초 후 일몰) → 현행 유지]")
        ws._cache.clear()
        ws._fetch_current, ws._fetch_air, ws._fetch_uv = _mock_fetchers(
            icon="01d", uv=9.3, sr=now - 6 * 3600, ss=now + 60)
        r = asyncio.run(ws.get_weather(37.57, 126.98))
        assert r.uv.value == 9.3 and r.uv.grade == "매우높음", r.uv
        ok("일몰 60초 전 → uv 9.3 '매우높음' 그대로(주간 daily max 현행)")

        print("\n[3. 캐시 누출 차단 — 낮 적재 → 일몰 통과 → 히트에도 0]")
        ws._cache.clear()
        ws._fetch_current, ws._fetch_air, ws._fetch_uv = _mock_fetchers(
            icon="01d", uv=9.3, sr=now - 6 * 3600, ss=now + 2)  # 2초 뒤 일몰
        r1 = asyncio.run(ws.get_weather(37.57, 126.98))
        assert r1.uv.value == 9.3, "적재 시점(낮)엔 실값"

        async def boom(*a, **k):
            raise AssertionError("캐시 히트여야 — 재페치 금지")
        ws._fetch_current = ws._fetch_air = ws._fetch_uv = boom
        time.sleep(3)  # 일몰 통과
        r2 = asyncio.run(ws.get_weather(37.57, 126.98))
        assert r2.uv.value == 0.0 and r2.uv.grade == "낮음", r2.uv
        cached = ws._cache[ws._cache_key(37.57, 126.98)][1]
        assert cached.uv.value == 9.3, "공유 캐시 원본은 무수정(deep copy)"
        ok("낮 적재 캐시가 일몰 뒤 히트 → 응답 0 · 캐시 원본 9.3 보존(오염 0)")

        print("\n[4. sun 결손 — 적재 시점 is_day 폴백]")
        ws._cache.clear()
        fc, fa, fu = _mock_fetchers(icon="01n", uv=9.3)

        async def fc_nosun(client, lat, lng, key):
            d = await fc(client, lat, lng, key)
            d["sys"] = {}
            return d
        ws._fetch_current, ws._fetch_air, ws._fetch_uv = fc_nosun, fa, fu
        r = asyncio.run(ws.get_weather(37.57, 126.98))
        assert r.uv.value == 0.0, "icon 'n'(야간) 폴백 → 0"
        ok("sun 결손 + 야간 icon → is_day 폴백으로 0")

        print("\n[5. uv 결손 — None 유지(무변화)]")
        ws._cache.clear()
        fc, fa, _ = _mock_fetchers(icon="01n")

        async def fu_none(client, lat, lng, key):
            return None
        ws._fetch_current, ws._fetch_air, ws._fetch_uv = fc, fa, fu_none
        r = asyncio.run(ws.get_weather(37.57, 126.98))
        assert r.uv is None
        ok("uv None → 그대로 None(타일 숨김 현행)")
    finally:
        (ws._fetch_current, ws._fetch_air, ws._fetch_uv,
         settings.openweather_api_key) = orig
        ws._cache.clear()
        print("\n[cleanup] mock 원복·캐시 클리어 — DB 무접촉·잔여 0")


if __name__ == "__main__":
    run_tests()
    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
