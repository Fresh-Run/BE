"""
Unit test: 아파트 관통 관측 (백로그 #6 옵션 2, 2026-07-23)

선택 route의 waypoint 역지오코딩 → 아파트 building_name 신호 카운트(관측 전용).
regex 분류 + count_apartment_signal 집계(HTTP mock). 실 Kakao 호출 0.

Run: python tests/test_apt_signal.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import Coordinate
from app.services import map_service as ms


def ok(m): print(f"  ✓ {m}")


class _FakeResp:
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass


class _FakeClient:
    """x(lng)==127.0이면 아파트 building_name, 아니면 도로(빈 building_name)."""
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, headers=None, params=None):
        if params["x"] == 127.0:
            return _FakeResp(json.dumps({"documents": [
                {"road_address": {"building_name": "청라푸르지오라피아노 2단지"}}]}))
        return _FakeResp(json.dumps({"documents": [
            {"road_address": {"building_name": ""}, "address": {"address_name": "청라동 105-1"}}]}))


def run_tests():
    print("[1. _is_apartment_name regex: 아파트 신호 vs 도로/공원]")
    for name in ("청라푸르지오라피아노 2단지", "래미안", "e편한세상", "힐스테이트", "OO아파트", "주공3단지"):
        assert ms._is_apartment_name(name), name
    for name in ("", None, "청라호수공원", "GS25 청라핑크점", "스타벅스"):
        assert not ms._is_apartment_name(name), name
    ok("아파트/단지/브랜드 hit · 빈값·None·공원·상호 미hit")

    print("\n[2. count_apartment_signal: 아파트 1 + 도로 1 → (1, 2)]")
    with patch.object(ms.settings, "kakao_rest_api_key", "test-key"), \
            patch.object(ms.httpx, "AsyncClient", _FakeClient):
        coords = [Coordinate(lat=37.53, lng=127.0),   # 아파트
                  Coordinate(lat=37.53, lng=128.0)]   # 도로
        hits, checked = asyncio.run(ms.count_apartment_signal(coords))
    assert (hits, checked) == (1, 2), f"(1,2) 기대, got {(hits, checked)}"
    ok("아파트 1/도로 1 → hits=1 checked=2")

    print("\n[3. 엣지: 빈 좌표·키 없음 → (0,0), 생성 무영향(관측 실패 안전)]")
    assert asyncio.run(ms.count_apartment_signal([])) == (0, 0)
    with patch.object(ms.settings, "kakao_rest_api_key", ""):
        assert asyncio.run(ms.count_apartment_signal([Coordinate(lat=37.5, lng=127.0)])) == (0, 0)
    ok("빈 좌표·키 없음 → (0,0) — best-effort 안전")

    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)


if __name__ == "__main__":
    run_tests()
