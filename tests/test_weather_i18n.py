"""
Unit: 날씨 응답 i18n (2026-07-29 Ivan) — comment·condition lang 조립 + 캐시 무오염.

외부 콜 0 — WeatherResponse 픽스처로 localize/personalize/deduction 전수 검증.

Run: python tests/test_weather_i18n.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import WeatherResponse, RunningIndex, WeatherSettings, PmReading  # noqa: E402
from app.services import weather_service as ws  # noqa: E402


def ok(m):
    print(f"  ✓ {m}")


def mk(comment="뛰기 딱 좋은 날씨예요!", code=800, personalized=False):
    return WeatherResponse(
        temp_c=20.0, feels_like_c=20.0, humidity_pct=50, wind_ms=2.0,
        condition="맑음", condition_code=code, uv_index=3.0,
        rain_1h_mm=None, pm25=None, pm10=None, fetched_at="2026-07-29T12:00:00Z",
        running_index=RunningIndex(score=95, label="최고", comment=comment,
                                   personalized=personalized))


def run():
    print("[1. en 유저 — comment·condition 영문 조립]")
    r = mk()
    out = ws.localize_weather(r, "en")
    assert out.running_index.comment == "Perfect running weather!" and out.condition == "Clear", \
        (out.running_index.comment, out.condition)
    r2 = mk(comment="비가 와요 — 실내 러닝을 추천해요", code=502)
    out2 = ws.localize_weather(r2, "en")
    assert out2.running_index.comment == "Rainy — indoor running recommended"
    assert out2.condition == "Rain"
    ok(f'"{out.running_index.comment}"·"{out.condition}" / "{out2.running_index.comment}"·"{out2.condition}"')

    print("\n[2. ko·미설정 — 원본 그대로(복사조차 없음)]")
    r3 = mk()
    assert ws.localize_weather(r3, "ko") is r3
    assert ws.localize_weather(r3, "") is r3
    ok("ko/미설정은 동일 객체 반환 — 현행 무변")

    print("\n[3. 캐시 교차 오염 0 — en 조회 후 ko 원본 불변]")
    shared = mk()   # 공유 캐시 원본 시뮬레이션
    _ = ws.localize_weather(shared, "en")
    assert shared.condition == "맑음" and shared.running_index.comment == "뛰기 딱 좋은 날씨예요!"
    ok("en deep copy 조립 후 공유 원본 ko 유지(07/05 전례 축)")

    print("\n[4. deduction 고정 문구 전수 — en 사전 커버리지]")
    produced = set()
    for f in (-10, -3, 2, 10, 23, 26, 30, 35):
        produced.add(ws._temp_deduction(f)[1])
    for c in (210, 310, 500, 502, 601, 741, 800):
        produced.add(ws._condition_deduction(c)[1])
    for w in (2, 9, 13):
        produced.add(ws._wind_deduction(w)[1])
    for p25, p10 in ((90, None), (50, None), (20, None), (5, 5)):
        produced.add(ws._dust_deduction(p25, p10)[1])
    for h in (50, 90):
        produced.add(ws._humidity_deduction(h)[1])
    produced.add("뛰기 딱 좋은 날씨예요!")
    produced.discard("")
    missing = [p for p in produced if p not in ws._COMMENT_EN]
    assert not missing, f"en 페어 누락: {missing}"
    ok(f"실생성 문구 {len(produced)}종 전부 en 페어 보유(누락 0)")

    print("\n[5. personalize lang 분기 + localize 이중조립 방지]")
    wset = WeatherSettings(avoid_rain=True)
    rainy = mk(code=502)
    pen = ws.personalize_index(rainy, wset, "en")
    assert pen.running_index.comment == "Matches your rain-avoidance setting — indoor running recommended"
    assert pen.running_index.personalized
    after = ws.localize_weather(pen, "en")
    assert after.running_index.comment == pen.running_index.comment  # personalized 스킵
    assert after.condition == "Rain"
    pko = ws.personalize_index(rainy, wset)   # lang 기본 ko — 기존 호출 호환
    assert pko.running_index.comment == "설정하신 비 회피 조건에 해당해요 — 실내 러닝을 추천해요"
    ok("personalize en/ko 분기·localize는 personalized comment 스킵·condition만 교체")


if __name__ == "__main__":
    run()
    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
