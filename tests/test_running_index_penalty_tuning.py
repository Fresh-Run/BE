"""
Unit: 러닝지수 페널티 완화 튜닝 (Ivan 2026-08-25) — 조정 전/후 값 고정(재변경 감지)

배경: 더위·PM 페널티가 과했음(Ivan 조정). 임계 숫자·등급 기준·라벨·타축(체감온도
band 경계·바람·습도·condition)은 불변, **페널티 값만** 완화. 유저 더위기준 설정
기능 없음 확인(오너) → "설정하신 더위 기준" 오보를 "권장 기준"으로 정정.

이 테스트는 새 값을 명시적으로 박제해 향후 무단 재변경을 감지한다(§C).
외부 콜 0 — 순수 함수. Run: python tests/test_running_index_penalty_tuning.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import WeatherResponse, RunningIndex, WeatherSettings, PmReading  # noqa: E402
from app.services import weather_service as ws  # noqa: E402

_n = 0


def ok(m):
    global _n
    _n += 1
    print(f"  ✓ {m}")


def main():
    print("[1. 더위 페널티 완화 — 임계 숫자 유지, 값만 (deduction은 양수 반환)]")
    # (feels_like, OLD→NEW deduction). 임계 32/28/24/22 불변.
    HEAT = [(33.0, 60, 35), (29.0, 40, 20), (25.0, 25, 10), (22.5, 10, 5)]
    for f, old, new in HEAT:
        d, msg = ws._temp_deduction(f)
        assert d == new, f"{f}°C: deduction {d} != {new} (was {old})"
        assert msg, "완화해도 문구는 유지"
    ok(f"더위 4단: >32=-35 >28=-20 >24=-10 >22=-5 (was -60/-40/-25/-10)")

    print("\n[2. PM 페널티 완화 — 환경부 등급 기준 유지, 값만]")
    # 보통 -5→0 / 나쁨 -25→-15 / 매우나쁨 -50→-35 (PM2.5 기준 대표 관측치)
    assert ws._dust_deduction(20.0, None)[0] == 0, "보통 -5→0"    # 15<20<35 보통
    assert ws._dust_deduction(50.0, None)[0] == 15, "나쁨 -25→-15"  # 35<50<75 나쁨
    assert ws._dust_deduction(100.0, None)[0] == 35, "매우나쁨 -50→-35"  # >75 매우나쁨
    assert ws._dust_deduction(10.0, None)[0] == 0, "좋음 0 불변"      # <15 좋음
    ok("PM 3단: 보통=0 나쁨=-15 매우나쁨=-35 (was -5/-25/-50), 좋음=0 불변")

    print("\n[3. 타축 무변경 — 바람·습도·condition deduction 불변]")
    assert ws._wind_deduction(12.0)[0] == 30 and ws._wind_deduction(8.0)[0] == 15
    assert ws._wind_deduction(5.0)[0] == 0
    assert ws._humidity_deduction(85)[0] == 10 and ws._humidity_deduction(84)[0] == 0
    assert ws._condition_deduction(211)[0] == 60   # 뇌우
    assert ws._condition_deduction(501)[0] == 35    # 비
    assert ws._condition_deduction(300)[0] == 20    # 이슬비
    assert ws._condition_deduction(800)[0] == 0     # 맑음
    ok("바람 30/15/0 · 습도 10/0 · condition 60/35/20/0 전부 불변")

    print("\n[4. 라벨 임계·PM 등급 경계 무변경]")
    assert (ws._label(90), ws._label(70), ws._label(50), ws._label(30), ws._label(29)) \
        == ("최고", "좋음", "보통", "주의", "비추천")
    assert ws._pm_grade(15.0, ws._PM25_BOUNDS) == "좋음"
    assert ws._pm_grade(16.0, ws._PM25_BOUNDS) == "보통"
    assert ws._pm_grade(36.0, ws._PM25_BOUNDS) == "나쁨"
    assert ws._pm_grade(76.0, ws._PM25_BOUNDS) == "매우나쁨"
    ok("라벨 임계 90/70/50/30 · PM 경계 15/35/75 불변")

    print("\n[5. 체감온도 band 경계·이상구간 무변경 (값만 바뀜, 경계는 그대로)]")
    assert ws._temp_deduction(32.0)[0] == 20   # 경계: >32 아님 → >28 band
    assert ws._temp_deduction(22.0)[0] == 0     # 이상구간 상한(>22 아님)
    assert ws._temp_deduction(5.0)[0] == 0      # 이상구간 하한
    assert ws._temp_deduction(4.9)[0] == 5      # 쌀쌀(무변경 축)
    assert ws._temp_deduction(-5.0)[0] == 20 and ws._temp_deduction(-6.0)[0] == 35
    ok("band 경계 32/28/24/22/5/0/-5 불변, 추위축(5/20/35) 무변경")

    print("\n[6. 더위 문구 오보 정정 — '설정하신 더위 기준'→'권장 기준', 숫자 유지]")
    resp = WeatherResponse(
        area="성수동", temp_c=30.0, feels_like_c=30.0, condition="맑음",
        condition_code=800, humidity_pct=50, wind_ms=2.0, rain_1h_mm=None,
        pm25=None, pm10=None,
        running_index=RunningIndex(score=80, label="좋음", comment="기본"),
        fetched_at="2026-08-25T00:00:00Z")
    out = ws.personalize_index(resp, WeatherSettings(avoid_heat=True, heat_temp_c=28))
    assert out.running_index.personalized
    assert "권장 기준" in out.running_index.comment, out.running_index.comment
    assert "설정하신 더위" not in out.running_index.comment, "오보 문구 잔존"
    assert "28°C" in out.running_index.comment, "임계 숫자 유지"
    ok(f'"{out.running_index.comment}"')

    print("\n[7. 문구 일관성 — en 더위·미세먼지 ko/en '설정/your'→'권장/recommended']")
    # en 더위: "your heat threshold" → "recommended threshold"
    out_en = ws.personalize_index(
        resp, WeatherSettings(avoid_heat=True, heat_temp_c=28), lang="en")
    assert "recommended threshold" in out_en.running_index.comment, out_en.running_index.comment
    assert "your" not in out_en.running_index.comment, "설정 함의('your') 잔존"
    assert "28°C" in out_en.running_index.comment
    ok(f'en 더위: "{out_en.running_index.comment}"')

    # 미세먼지 ko/en: "설정하신 미세먼지 기준"/"your dust threshold" → "권장 기준"/"recommended"
    dust_resp = WeatherResponse(
        area="성수동", temp_c=20.0, feels_like_c=20.0, condition="맑음",
        condition_code=800, humidity_pct=50, wind_ms=2.0, rain_1h_mm=None,
        pm25=None, pm10=PmReading(value=70.0, grade="나쁨"),
        running_index=RunningIndex(score=80, label="좋음", comment="기본"),
        fetched_at="2026-08-25T00:00:00Z")
    dset = WeatherSettings(avoid_dust=True, dust_level_pm10=50)
    dko = ws.personalize_index(dust_resp, dset, lang="ko")
    assert "권장 기준" in dko.running_index.comment
    assert "설정하신 미세먼지" not in dko.running_index.comment, "오보 문구 잔존(ko)"
    assert "PM10 50" in dko.running_index.comment  # 임계 숫자 유지
    den = ws.personalize_index(dust_resp, dset, lang="en")
    assert "recommended threshold" in den.running_index.comment
    assert "your" not in den.running_index.comment, "설정 함의('your') 잔존(en)"
    assert "PM10 50" in den.running_index.comment
    ok(f'미세먼지 ko:"{dko.running_index.comment}" / en:"{den.running_index.comment}"')


if __name__ == "__main__":
    main()
    print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_n} assert)\n" + "=" * 50)
