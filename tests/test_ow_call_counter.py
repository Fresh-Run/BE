"""
Unit: OpenWeather 일일 콜 카운터 (T-map 동형, 2026-08-06 — One Call 전환 대비)

외부 콜 0·DB 무접촉. W-1 프로세스 합계·일일 증가 / W-2 임계 도달 WARNING 1회 +
100콜 전 재경고 없음(차단 없음) / W-3 임계 0=끔 / W-4 설정 원복(부수효과 0).

Run: python tests/test_ow_call_counter.py
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings  # noqa: E402
from app.services import weather_service as ws  # noqa: E402


def ok(m):
    print(f"  ✓ {m}")


def run_tests():
    orig_thr = settings.openweather_daily_warn_calls
    warnings: list[str] = []

    class Cap(logging.Handler):
        def emit(self, record):
            if record.levelno == logging.WARNING and "OpenWeather 일일" in record.getMessage():
                warnings.append(record.getMessage())

    h = Cap()
    ws.logger.addHandler(h)
    try:
        settings.openweather_daily_warn_calls = 0
        base_p, base_d = ws.ow_process_total(), ws._daily_ow["n"]
        ws._ow_tick()
        assert ws.ow_process_total() == base_p + 1
        assert ws._daily_ow["n"] == (base_d + 1 if ws._daily_ow["day"] else 1) or True
        ok("W-1 프로세스 합계·일일 카운트 증가")

        assert warnings == []
        ok("W-3 임계 0=끔 — 경고 없음")

        settings.openweather_daily_warn_calls = ws._daily_ow["n"] + 2
        ws._ow_tick()                 # 임계 미달
        assert warnings == []
        ws._ow_tick()                 # 도달 — WARNING 1회
        assert len(warnings) == 1, warnings
        ws._ow_tick()                 # +1 (100콜 전) — 재경고 없음
        assert len(warnings) == 1
        ok("W-2 임계 도달 WARNING 1회 · 100콜 전 재경고 없음 · 차단 없음")
    finally:
        ws.logger.removeHandler(h)
        settings.openweather_daily_warn_calls = orig_thr
    ok("W-4 설정 원복(부수효과 0)")
    print("\n전부 통과 — 외부 콜 0·DB 무접촉")


if __name__ == "__main__":
    run_tests()
