"""
Unit: T-map 실 HTTP 콜 카운터 (관측 additive, 2026-08-05 청구 회계)

외부 콜 0(MockTransport)·DB 무접촉. 검증 축:
C-1 begin 전 — tmap_call_count() None(비생성 문맥 no-op)·leg 호출 무해
C-2 begin 후 순차 3 leg → 3 (시도 기준)
C-3 asyncio.gather 병렬 4 leg → 4 — ContextVar 가변 박스가 자식 태스크
    컨텍스트 복사에도 공유됨(카운트 유실 없음 — 이 설계의 존재 이유)
C-4 실패 leg(500)도 +1 — 청구는 실패 응답도 셀 수 있어 시도 기준 상한
C-5 새 begin으로 요청 간 격리(리셋)

Run: python tests/test_tmap_call_counter.py
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.models.schemas import Coordinate  # noqa: E402
from app.services import map_service as ms  # noqa: E402

A = Coordinate(lat=37.5729, lng=126.9794)
B = Coordinate(lat=37.5745, lng=126.9770)

GEOJSON = {
    "features": [
        {"geometry": {"type": "Point", "coordinates": [126.9794, 37.5729]},
         "properties": {"totalDistance": 500, "totalTime": 360}},
        {"geometry": {"type": "LineString",
                      "coordinates": [[126.9794, 37.5729], [126.977, 37.5745]]},
         "properties": {"distance": 500}},
    ]
}


def client(status=200):
    def handler(request):
        return httpx.Response(status, text=json.dumps(GEOJSON))
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def ok(m):
    print(f"  ✓ {m}")


async def scenario():
    # C-1: begin 전 — 비생성 문맥 no-op
    assert ms.tmap_call_count() is None
    async with client() as c:
        await ms._tmap_walk_leg(c, A, B)
    assert ms.tmap_call_count() is None
    ok("C-1 begin 전 None·leg 호출 무해(no-op)")

    box = ms.begin_tmap_count()
    async with client() as c:
        for _ in range(3):
            await ms._tmap_walk_leg(c, A, B)
    assert ms.tmap_call_count() == 3 == box["n"]
    ok("C-2 순차 3 leg → 3")

    async with client() as c:
        await asyncio.gather(*[ms._tmap_walk_leg(c, A, B) for _ in range(4)])
    assert ms.tmap_call_count() == 7, ms.tmap_call_count()
    ok("C-3 gather 병렬 4 leg → +4 (자식 태스크 카운트 유실 0)")

    async with client(500) as c:
        try:
            await ms._tmap_walk_leg(c, A, B)
            raise AssertionError("500이 전파돼야 함")
        except httpx.HTTPStatusError:
            pass
    assert ms.tmap_call_count() == 8
    ok("C-4 실패 leg도 +1 (시도 기준 상한)")

    ms.begin_tmap_count()
    assert ms.tmap_call_count() == 0
    ok("C-5 새 begin → 0 (요청 간 격리)")


def run_tests():
    # 요청 격리 재현 — 요청마다 독립 컨텍스트에서 시나리오 실행
    ctx = contextvars.copy_context()
    ctx.run(lambda: asyncio.run(scenario()))
    # 부수효과 없음: 바깥 컨텍스트는 여전히 비생성 문맥
    assert ms.tmap_call_count() is None
    print("\n전부 통과 — 외부 콜 0·DB 무접촉·바깥 컨텍스트 무오염")


if __name__ == "__main__":
    run_tests()
