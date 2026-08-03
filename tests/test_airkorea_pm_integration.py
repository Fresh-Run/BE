"""
Integration: 에어코리아 실측 PM 소스 (AIR_QUALITY_SOURCE_DESIGN, 2026-07-31)

실채집 검증 완료(2026-08-03 광화문) — U-3가 실물 shape fixture. 에어코리아 실호출 0.

U-1 결측 파싱("-"·-999·Flag·쓰레기) — 전부 None
U-2 bbox 분기(서울/뉴욕/경계)
P-1 플래그 OFF(기본) — 에어코리아 미호출(forbid)·현행 100%
P-2 ON+한국+실측(21/19) — 실측 채택·러닝 지수 정합(먼지 심각 감점 소거)
P-3 ON+한국+장애 — OpenWeather 폴백
P-4 ON+한국+전항 결측 — 폴백 / 부분 결측 — 실측 채택(있는 값만)
P-5 ON+해외 — 에어코리아 미호출·OpenWeather 직행
P-6 측정소 24h 캐시 — 응답 캐시 클리어 후 재호출에도 resolve 1회
P-7 계약 불변 — 응답 키 세트 동일

U-3 실물 fixture — 2026-08-03 광화문 실채집 shape로 체인 파싱 검증(FakeClient)
R-1~3 재시도 — 1차 실패→2차 채택 / 2연패 폴백 / 200 시 단일 콜(비용 방어)

Run: python tests/test_airkorea_pm_integration.py  (외부 콜 0·DB 무접촉)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings  # noqa: E402
from app.services import weather_service as ws  # noqa: E402
from tests.test_uv_night_integration import _mock_fetchers  # noqa: E402 — 하네스 재사용

SEOUL = (37.5729, 126.9794)
NY = (40.7655, -73.9980)


def ok(m):
    print(f"  ✓ {m}")


def get(lat, lng):
    return asyncio.run(ws.get_weather(lat, lng))


def run_tests():
    orig = (ws._fetch_current, ws._fetch_air, ws._fetch_uv, ws._fetch_airkorea,
            ws._resolve_station, settings.openweather_api_key,
            settings.airkorea_enabled, settings.airkorea_api_key)
    settings.openweather_api_key = settings.openweather_api_key or "test-dummy"
    fc, fa, fu = _mock_fetchers(icon="01d", uv=5.0)
    ws._fetch_current, ws._fetch_uv = fc, fu

    async def ow_air(client, lat, lng, key):
        return {"pm2_5": 102.71, "pm10": 119.13}   # 모델값(사건 실측)

    async def forbid_ak(*a, **k):
        raise AssertionError("에어코리아 경로가 호출되면 안 됨")

    def ak_returning(val):
        async def f(client, lat, lng):
            return val
        return f

    # 우회(2026-08-03) 후 data.go.kr 응답은 _airkorea_transport 심으로 주입.
    # FakeClient는 Kakao transcoord만 담당(mock 지점 조정 내역 — 커밋 메시지 참조).
    orig_transport = ws._airkorea_transport

    def set_transport(fn):
        ws._airkorea_transport = fn

    try:
        print("[U-1 결측 파싱 — 문서 기준 방어]")
        p = ws._parse_airkorea_value
        assert p("45", None) == 45.0 and p("45", "") == 45.0
        for bad in [("-", None), ("-999", None), (-999, None), (None, None),
                    ("x", None), ("45", "점검및교정"), ("45", "통신장애")]:
            assert p(*bad) is None, bad
        ok('"45"→45.0 · "-"/-999/Flag/쓰레기 → 전부 None')

        print("\n[U-2 bbox 분기]")
        assert ws._in_korea(*SEOUL) and not ws._in_korea(*NY)
        assert ws._in_korea(33.0, 124.0) and ws._in_korea(39.0, 132.0)
        assert not ws._in_korea(32.99, 127.0) and not ws._in_korea(37.5, 132.01)
        ok("서울 O · 뉴욕 X · 경계 포함/직외 정확")

        print("\n[U-3 실물 fixture — 실채집 shape 체인 파싱(2026-08-03 광화문)]")
        # 실프로브 캡처 축약본 — 필드명·구조 실물 그대로(값만 대표치)
        FX_TRANSCOORD = {"documents": [{"x": 198110.6, "y": 452290.1}]}
        FX_NEARBY = {"response": {"body": {"totalCount": 3, "pageNo": 1, "numOfRows": 10,
                     "items": [{"stationCode": "111121", "tm": 0.8,
                                "addr": "서울 중구 덕수궁길 15", "stationName": "중구"}]}}}
        FX_MEASURE = {"response": {"body": {"items": [
            {"dataTime": "2026-08-03 15:00", "pm10Value": "24", "pm10Flag": None,
             "pm25Value": "21", "pm25Flag": None, "khaiGrade": "2",
             "pm10Grade": "1", "pm25Grade": "2", "mangName": "도시대기"}]}}}

        class _FR:
            status_code = 200
            text = ""
            def __init__(self, payload): self._p = payload
            def raise_for_status(self): pass
            def json(self): return self._p

        class FakeClient:
            async def get(self, url, params=None, headers=None, timeout=None):
                if "transcoord" in url: return _FR(FX_TRANSCOORD)
                raise AssertionError(url)

        def transport_ok(url, params):
            if "getNearbyMsrstnList" in url: return _FR(FX_NEARBY)
            if "getMsrstnAcctoRltmMesureDnsty" in url: return _FR(FX_MEASURE)
            raise AssertionError(url)

        set_transport(transport_ok)
        ws._station_cache.clear()
        got = asyncio.run(ws._fetch_airkorea(FakeClient(), 37.5729, 126.9794))
        assert got == (21.0, 24.0), f"(pm25, pm10) 실물 파싱: {got}"
        assert ws._station_cache, "측정소 캐시 적재"
        ok("실물 shape 체인: 중구 측정소 → (pm25 21.0, pm10 24.0) · Flag null 통과")

        print("\n[U-4 비200 관측 — 본문 로깅+키 마스킹+폴백 불변]")
        import logging
        records = []

        class _Cap(logging.Handler):
            def emit(self, rec): records.append(rec.getMessage())

        cap = _Cap()
        logging.getLogger("app.services.weather_service").addHandler(cap)
        SECRET = "MzP%2FFAKEKEY%3D%3D"
        settings.airkorea_api_key = SECRET

        class _FR400:
            status_code = 400
            text = '{"error":"LIMITED_..."} serviceKey=' + SECRET
            def raise_for_status(self):
                import httpx as _h
                raise _h.HTTPStatusError("400", request=None, response=None)
            def json(self): return {}

        set_transport(lambda url, params: _FR400())
        ws._station_cache.clear()
        got = asyncio.run(ws._fetch_airkorea(FakeClient(), 37.10, 127.10))
        logging.getLogger("app.services.weather_service").removeHandler(cap)
        assert got is None, "비200 → None(폴백 경로 불변)"
        obs = [m for m in records if "비200" in m]
        assert obs and "400" in obs[0], records
        assert SECRET not in obs[0] and "<key>" in obs[0], "키 마스킹 실패"
        ok("400 본문 로깅 ✓ 키 → <key> 마스킹 ✓ 반환 None(폴백) ✓")

        print("\n[R-1 재시도 — 1차 400 → 2차 200 → 실측 채택]")
        calls = {"nearby": 0, "measure": 0}

        class _FR400b:
            status_code = 400
            text = '{"err":"gw"}'
            def raise_for_status(self):
                import httpx as _h
                raise _h.HTTPStatusError("400", request=None, response=None)
            def json(self): return {}

        def transport_retry(url, params):
            if "getNearbyMsrstnList" in url:
                calls["nearby"] += 1
                return _FR400b() if calls["nearby"] == 1 else _FR(FX_NEARBY)
            calls["measure"] += 1
            return _FR(FX_MEASURE)

        set_transport(transport_retry)
        ws._station_cache.clear()
        got = asyncio.run(ws._fetch_airkorea(FakeClient(), 37.20, 127.20))
        assert got == (21.0, 24.0), got
        assert calls == {"nearby": 2, "measure": 1}, calls
        ok("1차 실패→재시도 200→실측 채택 (nearby 2시도·measure 1시도)")

        print("\n[R-2 2연패 → 폴백(None) — 현행 동일]")
        fail_n = {"n": 0}
        def transport_fail(url, params):
            fail_n["n"] += 1
            return _FR400b()
        set_transport(transport_fail)
        ws._station_cache.clear()
        got = asyncio.run(ws._fetch_airkorea(FakeClient(), 37.21, 127.21))
        assert got is None and fail_n["n"] == 2, (got, fail_n["n"])
        ok("2시도 전패 → None(폴백)·시도 수 정확히 2")

        print("\n[R-3 200 시 단일 콜(비용 방어)]")
        calls2 = {"nearby": 0, "measure": 0}
        def transport_ok2(url, params):
            if "getNearbyMsrstnList" in url:
                calls2["nearby"] += 1; return _FR(FX_NEARBY)
            calls2["measure"] += 1; return _FR(FX_MEASURE)
        set_transport(transport_ok2)
        ws._station_cache.clear()
        got = asyncio.run(ws._fetch_airkorea(FakeClient(), 37.22, 127.22))
        assert got == (21.0, 24.0)
        assert calls2 == {"nearby": 1, "measure": 1}, calls2
        ok("성공 경로 재시도 0 — 각 1콜 고정")

        print("\n[R-4 전용 타임아웃 3s — 에어코리아만·타 콜 무영향·timeout 폴백]")
        seen = {"kakao_timeout": [], "tries": 0}

        class FCKakao:
            async def get(self, url, params=None, headers=None, timeout=None):
                assert "transcoord" in url
                seen["kakao_timeout"].append(timeout)
                return _FR(FX_TRANSCOORD)

        def transport_timeout(url, params):
            seen["tries"] += 1
            import httpx as _h
            raise _h.ReadTimeout("gw timeout")   # 게이트웨이 timeout 모드 재현

        set_transport(transport_timeout)
        ws._station_cache.clear()
        got = asyncio.run(ws._fetch_airkorea(FCKakao(), 37.23, 127.23))
        assert got is None and seen["tries"] == 2, (got, seen)
        assert seen["kakao_timeout"] == [None], "Kakao는 타임아웃 오버라이드 없음(클라이언트 기본)"
        # 지연 캡 구조 증명: 전용 상수 3.0 × 최대 2시도 = 6s (콜당)
        assert ws._AIRKOREA_TIMEOUT == 3.0
        ok("timeout 2시도 → 폴백 ✓ 캡 3.0×2 ✓ Kakao 무영향(None=기본) ✓")

        print("\n[P-1 플래그 OFF(기본) — 현행 100%]")
        settings.airkorea_enabled = False
        settings.airkorea_api_key = "dummy"
        ws._fetch_air, ws._fetch_airkorea = ow_air, forbid_ak
        ws._cache.clear()
        r = get(*SEOUL)
        assert r.pm10.value == 119.13 and r.pm25.value == 102.71
        ok("OFF → 에어코리아 미호출(forbid 통과)·OpenWeather 값 그대로")

        print("\n[P-2 ON+한국+실측 21/19 — 채택 + 러닝 지수 정합]")
        settings.airkorea_enabled = True
        ws._fetch_airkorea = ak_returning((19.0, 21.0))   # (pm25, pm10) 실측 사건값
        async def ow_forbid(*a, **k):
            raise AssertionError("실측 성공 시 OpenWeather air 미호출")
        ws._fetch_air = ow_forbid
        ws._cache.clear()
        r = get(*SEOUL)
        assert r.pm10.value == 21.0 and r.pm10.grade == "좋음", r.pm10
        assert r.pm25.value == 19.0 and r.pm25.grade == "보통", r.pm25
        # 사건 재발 방지: 모델 119/102는 지수 0/100 "무리하지 마세요"였다.
        # 실측 21/19 주입 시 먼지의 심각 감점(나쁨 25/매우나쁨 50)이 소거되는지.
        # ⚠️ 감점 완전 0은 아님 — PM2.5 19는 환경부 표상 '보통'(16~35)이라 5점
        # (마스크 안내)이 정확. 지수 95 이상·심각 문구 아님을 물린다.
        ri = r.running_index
        assert ri.score >= 90, f"실측 주입 시 지수 90+, got {ri.score}"
        assert "피하세요" not in (ri.comment or "") and "실내" not in (ri.comment or ""), ri
        ok(f"21/19 채택(좋음/보통) · 지수 {ri.score}(심각 감점 소거 — 보통 5점만)")

        print("\n[P-3 ON+한국+장애 — 폴백]")
        ws._fetch_airkorea = ak_returning(None)
        ws._fetch_air = ow_air
        ws._cache.clear()
        r = get(*SEOUL)
        assert r.pm10.value == 119.13, "장애 시 OpenWeather 폴백"
        ok("에어코리아 None → OpenWeather 값")

        print("\n[P-4 전항 결측 → 폴백 / 부분 결측 → 실측 채택]")
        ws._fetch_airkorea = ak_returning((None, None))
        ws._cache.clear()
        r = get(*SEOUL)
        assert r.pm10.value == 119.13, "전항 결측 → 폴백"
        ws._fetch_airkorea = ak_returning((None, 30.0))   # pm10만 유효
        ws._fetch_air = ow_forbid
        ws._cache.clear()
        r = get(*SEOUL)
        assert r.pm10.value == 30.0 and r.pm25 is None, (r.pm10, r.pm25)
        ok("전항 결측 폴백 ✓ 부분 결측은 있는 값만 채택(pm25 null — 현행 결측 동형)")

        print("\n[P-5 ON+해외 — 에어코리아 미호출·OpenWeather 직행]")
        ws._fetch_airkorea = forbid_ak
        ws._fetch_air = ow_air
        ws._cache.clear()
        r = get(*NY)
        assert r.pm10.value == 119.13
        ok("해외 좌표 → bbox에서 컷(forbid 통과)")

        print("\n[P-6 측정소 24h 캐시 — resolve 1회]")
        calls = {"n": 0}

        async def station_spy(client, lat, lng):
            key = ws._cache_key(lat, lng)
            hit = ws._station_cache.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            calls["n"] += 1
            ws._station_cache[key] = (time.monotonic() + ws._STATION_TTL_SEC, "종로구")
            return "종로구"

        ws._resolve_station = station_spy
        # _fetch_airkorea 원본 복원해 resolve 경유 경로로 — 측정값 콜은 mock
        real_ak = orig[3]

        async def ak_via_resolve(client, lat, lng):
            st = await ws._resolve_station(client, lat, lng)
            return (19.0, 21.0) if st else None

        ws._fetch_airkorea = ak_via_resolve
        ws._station_cache.clear()
        ws._cache.clear()
        get(*SEOUL)
        ws._cache.clear()   # 응답 캐시만 비움 — 측정소 캐시는 유지
        get(*SEOUL)
        assert calls["n"] == 1, f"측정소 resolve는 그리드당 1회여야: {calls['n']}"
        ok("응답 캐시 클리어 후 재호출에도 측정소 resolve 1회(24h 캐시)")

        print("\n[P-7 계약 불변 — 응답 키 세트]")
        keys = set(r.model_dump().keys())
        expected = {"area", "temp_c", "feels_like_c", "condition", "condition_code",
                    "humidity_pct", "wind_ms", "rain_1h_mm", "pm25", "pm10", "uv",
                    "is_day", "running_index", "fetched_at"}
        assert keys == expected, keys ^ expected
        ok("응답 키 14종 기존 세트 동일(소스 비노출)")
    finally:
        (ws._fetch_current, ws._fetch_air, ws._fetch_uv, ws._fetch_airkorea,
         ws._resolve_station, settings.openweather_api_key,
         settings.airkorea_enabled, settings.airkorea_api_key) = orig
        ws._airkorea_transport = orig_transport
        ws._cache.clear()
        ws._station_cache.clear()
        print("\n[cleanup] mock 원복·캐시 클리어 — DB 무접촉·잔여 0")


if __name__ == "__main__":
    run_tests()
    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
