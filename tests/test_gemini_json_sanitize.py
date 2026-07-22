"""
Unit test: Gemini tool_call JSON 제어문자 방어 (_loads_tool_args, 2026-07-22 감사)

E2E 성수 실측(char 18152 Invalid control character) 대응. 보수적 방어:
정상 파싱은 그대로 · 미이스케이프 제어문자만 strip 후 재시도 · 진짜 깨진 JSON은
여전히 실패(후보 탈락 유지) · 이스케이프된 제어문자는 정상 경로라 미변형.

Run: python tests/test_gemini_json_sanitize.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.openai_service import _loads_tool_args


def ok(m):  print(f"  ✓ {m}")
def fail(m): print(f"  ✗ {m}"); sys.exit(1)


def run_tests():
    print("[1. 정상 JSON → 그대로 파싱(무변형 경로)]")
    raw = '{"summary": "성수 리버사이드", "total_distance_km": 5.1, "waypoints": []}'
    d = _loads_tool_args(raw)
    assert d["summary"] == "성수 리버사이드" and d["total_distance_km"] == 5.1, d
    ok("정상 JSON 파싱 · 값 보존")

    print("\n[2. 문자열 내 미이스케이프 제어문자 → strip 후 파싱 성공]")
    # \x01(U+0001) 리터럴이 문자열 안에 — 표준 json.loads는 여기서 깨진다
    broken_by_ctrl = '{"summary": "리버\x01사이드", "total_distance_km": 5.0, "waypoints": []}'
    try:
        json.loads(broken_by_ctrl)
        fail("표준 json.loads가 제어문자에 실패해야 전제가 성립")
    except json.JSONDecodeError:
        pass
    d = _loads_tool_args(broken_by_ctrl)
    assert d["summary"] == "리버사이드", f"제어문자 제거 후 파싱, got {d['summary']!r}"
    assert d["total_distance_km"] == 5.0, d
    ok("제어문자 strip → 파싱 성공 · 나머지 값 온전")

    print("\n[3. 구조 whitespace 제어문자(\\n\\t) 섞인 정상 JSON → 무해]")
    with_ws = '{\n\t"summary": "여의도",\n\t"total_distance_km": 5.0,\n\t"waypoints": []\n}'
    d = _loads_tool_args(with_ws)  # 정상 경로(표준 파싱 성공) — strip 안 탐
    assert d["summary"] == "여의도", d
    ok("구조 개행/탭 포함 정상 JSON 파싱(첫 시도 성공)")

    print("\n[4. 진짜 깨진 JSON(문법) → 여전히 실패(후보 탈락 유지)]")
    for bad in ('{"summary": "x", "total_distance_km": ',   # 미완결
                '{"summary": "x" "total_distance_km": 5}',  # 콤마 누락
                'not json at all'):
        try:
            _loads_tool_args(bad)
            fail(f"문법 깨진 JSON은 raise해야: {bad!r}")
        except json.JSONDecodeError:
            pass
    ok("문법 오류 3종 전부 JSONDecodeError 전파(strip으로 안 살아남음)")

    print("\n[5. 이스케이프된 제어문자(\\u0001)는 정상 경로 — 미변형 보존]")
    escaped = '{"summary": "a\\u0001b", "total_distance_km": 5.0, "waypoints": []}'
    d = _loads_tool_args(escaped)  # 표준 파싱 성공 → strip 미발동
    assert d["summary"] == "a\x01b", f"이스케이프분은 값에 보존, got {d['summary']!r}"
    ok("이스케이프된 \\u0001은 정상 파싱(값 보존, strip 미발동)")

    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)


if __name__ == "__main__":
    run_tests()
