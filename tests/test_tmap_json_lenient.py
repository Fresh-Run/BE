"""
Unit test: T-map 응답 제어문자 방어 (map_service loads_lenient, 2026-07-22 오진 정정)

E2E 성수 nopath의 실블로커는 Gemini가 아니라 **T-map GeoJSON 응답**의 도로/POI명에
섞인 미이스케이프 제어문자였다(route_service._snap → map_service resp.json()). 공용
loads_lenient로 4경로(kakao search/directions·naver·tmap) 방어. 여기선 실제 T-map
파서(_tmap_walk_leg)를 가짜 응답으로 구동해 검증.

Run: python tests/test_tmap_json_lenient.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.json_util import loads_lenient
from app.models.schemas import Coordinate
from app.services import map_service


def ok(m):  print(f"  ✓ {m}")
def fail(m): print(f"  ✗ {m}"); sys.exit(1)


class _Resp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status
    def raise_for_status(self):
        pass


class _Client:
    """_tmap_walk_leg가 쓰는 async post만 흉내 — 주입한 응답 text를 그대로 반환."""
    def __init__(self, text, status=200):
        self._text, self._status = text, status
    async def post(self, url, headers=None, json=None):
        return _Resp(self._text, self._status)


# 제어문자(\x01)가 properties 문자열에 섞인 T-map GeoJSON — 표준 json.loads는 깨진다
_GEOJSON_CTRL = (
    '{"features": ['
    '{"type":"Feature","geometry":{"type":"Point","coordinates":[127.0,37.5]},'
    '"properties":{"totalDistance":520,"totalTime":374,"name":"성수동 리버\x01사이드길"}},'
    '{"type":"Feature","geometry":{"type":"LineString",'
    '"coordinates":[[127.0,37.5],[127.001,37.501],[127.002,37.502]]},"properties":{}}'
    ']}'
)


def run_tests():
    print("[1. 표준 json.loads는 이 응답에 실패(전제 확인)]")
    try:
        json.loads(_GEOJSON_CTRL)
        fail("제어문자에 표준 파싱이 실패해야 전제 성립")
    except json.JSONDecodeError:
        pass
    ok("T-map 응답 제어문자 → 표준 json.loads 실패(재현)")

    print("\n[2. _tmap_walk_leg(공용 loads_lenient) → 파싱 성공·경로 반환]")
    o = Coordinate(lat=37.5, lng=127.0)
    d = Coordinate(lat=37.502, lng=127.002)
    dm, ds, path = asyncio.run(
        map_service._tmap_walk_leg(_Client(_GEOJSON_CTRL), o, d))
    assert dm == 520.0 and ds == 374.0, f"거리·시간 파싱, got {dm}, {ds}"
    assert len(path) == 3, f"LineString 3점, got {len(path)}"
    ok(f"제어문자 응답 스냅 성공: dist={dm}m · path={len(path)}점 (nopath 탈락 방지)")

    print("\n[3. 진짜 깨진 응답(문법) → 여전히 실패(기존 탈락 경로 유지)]")
    broken = '{"features": [ {"type":"Feature" '  # 미완결
    try:
        asyncio.run(map_service._tmap_walk_leg(_Client(broken), o, d))
        fail("문법 깨진 응답은 raise해야")
    except json.JSONDecodeError:
        pass
    ok("문법 오류 응답 → JSONDecodeError 전파(스냅 실패 = 기존 처리)")

    print("\n[4. 빈 경로 응답 → LegNotRoutable (기존 동작 회귀)]")
    empty = '{"features": [{"type":"Feature","geometry":{"type":"Point","coordinates":[127,37]},"properties":{"totalDistance":0}}]}'
    try:
        asyncio.run(map_service._tmap_walk_leg(_Client(empty), o, d))
        fail("빈 경로는 LegNotRoutable이어야")
    except map_service.LegNotRoutable:
        pass
    ok("거리 0·경로 없음 → LegNotRoutable(보행불가 폐기, 기존 동작)")

    print("\n[5. 429 응답 → TmapQuotaExceeded (기존 동작 회귀)]")
    try:
        asyncio.run(map_service._tmap_walk_leg(_Client("{}", status=429), o, d))
        fail("429는 TmapQuotaExceeded여야")
    except map_service.TmapQuotaExceeded:
        pass
    ok("429 → TmapQuotaExceeded(쿼터 소진 정직화 경로 유지)")

    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)


if __name__ == "__main__":
    run_tests()
