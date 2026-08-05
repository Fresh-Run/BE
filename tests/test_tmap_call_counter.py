"""
Unit: T-map 콜 카운터 + 예산 1단계(하드캡·leg 캐시·일일 소프트 임계) — 2026-08-05

외부 콜 0(가짜 클라이언트)·DB 무접촉. 섹션:
[C 카운터 — 캐시 OFF 조건] C-1 begin 전 None·무해 / C-2 순차 3 / C-3 gather 4
  유실 0 / C-4 실패도 +1 / C-5 begin 격리 / C-6 프로세스 합계
[K leg 캐시] K-1 미스→적중(HTTP 0·hit 관측) / K-2 라운딩 경계(5자리 ≈1.1m —
  0.000004° 동일 키·0.00002° 상이 키) / K-3 TTL 만료 재호출 / K-4 반환 리스트
  얕은 복사(호출측 변형 캐시 무오염) / K-5 적중은 예산·일일·프로세스 무소모
[B 하드캡] B-1 예산 도달 시 TmapBudgetExceeded·초과 시도는 카운트 미증가 /
  B-2 0=무제한(서빙 기본 — 서빙 무영향)
[D 일일 소프트] D-1 임계 도달 시 WARNING 1회(이후 100콜 전 재경고 없음·차단 없음)

Run: python tests/test_tmap_call_counter.py
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models.schemas import Coordinate  # noqa: E402
from app.services import map_service as ms  # noqa: E402

A = Coordinate(lat=37.5729, lng=126.9794)
B = Coordinate(lat=37.5745, lng=126.9770)
A2 = Coordinate(lat=37.6, lng=127.1)
B2 = Coordinate(lat=37.602, lng=127.102)

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


async def leg(c, o=A, d=B):
    return await ms._tmap_walk_leg(c, o, d)


async def scenario():
    print("[C 카운터 — 캐시 OFF]")
    settings.tmap_leg_cache_ttl_s = 0
    ms.clear_tmap_leg_cache()
    base = ms.tmap_process_total()

    assert ms.tmap_call_count() is None and ms.tmap_cache_hits() is None
    async with client() as c:
        await leg(c)
    assert ms.tmap_call_count() is None
    ok("C-1 begin 전 None·leg 호출 무해(no-op)")

    box = ms.begin_tmap_count()
    async with client() as c:
        for _ in range(3):
            await leg(c)
    assert ms.tmap_call_count() == 3 == box["n"]
    ok("C-2 순차 3 leg → 3 (캐시 OFF — 전부 실호출)")

    async with client() as c:
        await asyncio.gather(*[leg(c) for _ in range(4)])
    assert ms.tmap_call_count() == 7, ms.tmap_call_count()
    ok("C-3 gather 병렬 4 leg → +4 (자식 태스크 카운트 유실 0)")

    async with client(500) as c:
        try:
            await leg(c)
            raise AssertionError("500이 전파돼야 함")
        except httpx.HTTPStatusError:
            pass
    assert ms.tmap_call_count() == 8
    ok("C-4 실패 leg도 +1 (시도 기준 상한)")

    ms.begin_tmap_count()
    assert ms.tmap_call_count() == 0 and ms.tmap_cache_hits() == 0
    ok("C-5 새 begin → 0 (요청 간 격리)")

    assert ms.tmap_process_total() == base + 9
    ok("C-6 프로세스 합계 +9 (begin 전 1건 포함 — 캠페인 회계 무조건 집계)")

    print("[K leg 캐시]")
    settings.tmap_leg_cache_ttl_s = 600.0
    ms.clear_tmap_leg_cache()
    box = ms.begin_tmap_count()
    async with client() as c:
        r1 = await leg(c, A2, B2)          # 미스 → 실호출
        r2 = await leg(c, A2, B2)          # 적중 → HTTP 0
    assert box["n"] == 1 and box["hit"] == 1, box
    assert r1[0] == r2[0] and len(r1[2]) == len(r2[2])
    ok("K-1 미스 1콜 → 적중 0콜 · gen_meta 관측(hit=1)")

    async with client() as c:
        near = Coordinate(lat=A2.lat + 0.000004, lng=A2.lng)   # ≈0.4m — 동일 키
        await leg(c, near, B2)
        assert box["hit"] == 2 and box["n"] == 1, box
        far = Coordinate(lat=A2.lat + 0.00002, lng=A2.lng)     # ≈2.2m — 상이 키
        await leg(c, far, B2)
        assert box["hit"] == 2 and box["n"] == 2, box
    ok("K-2 라운딩 경계 — 0.000004° 적중·0.00002° 미스 (5자리 ≈1.1m 정밀도)")

    settings.tmap_leg_cache_ttl_s = 0.05
    ms.clear_tmap_leg_cache()
    async with client() as c:
        await leg(c, A2, B2)
        await asyncio.sleep(0.06)
        await leg(c, A2, B2)
    assert box["n"] == 4 and box["hit"] == 2, box
    ok("K-3 TTL 만료 → 재실호출")

    settings.tmap_leg_cache_ttl_s = 600.0
    ms.clear_tmap_leg_cache()
    async with client() as c:
        d1, s1, p1, rs1, cc1 = await leg(c, A2, B2)
        p1.append(Coordinate(lat=0, lng=0))         # 호출측 변형
        rs1.append(("x", "y", 1.0))
        d2, s2, p2, rs2, cc2 = await leg(c, A2, B2)  # 적중
    assert len(p2) == 2 and len(rs2) == 1, (len(p2), len(rs2))
    ok("K-4 반환 얕은 복사 — 호출측 변형이 캐시 원본 무오염")

    before = ms.tmap_process_total()
    daily_before = ms._daily_tmap["n"]
    async with client() as c:
        await leg(c, A2, B2)                        # 적중
    assert ms.tmap_process_total() == before and ms._daily_tmap["n"] == daily_before
    ok("K-5 적중은 프로세스 합계·일일 카운트 무소모(예산 미소모)")

    print("[B 하드캡]")
    settings.tmap_leg_cache_ttl_s = 0
    ms.clear_tmap_leg_cache()
    settings.tmap_budget_calls = ms.tmap_process_total() + 1
    n_before = ms.tmap_call_count()
    async with client() as c:
        await leg(c)                                 # 예산 마지막 1콜 — OK
        try:
            await leg(c)
            raise AssertionError("예산 소진 시 TmapBudgetExceeded여야")
        except ms.TmapBudgetExceeded:
            pass
    assert ms.tmap_process_total() == settings.tmap_budget_calls
    assert ms.tmap_call_count() == n_before + 1, "초과 시도는 카운트 미증가(HTTP 0)"
    ok("B-1 예산 도달 → TmapBudgetExceeded · 초과 시도 콜 0")

    settings.tmap_budget_calls = 0
    async with client() as c:
        await leg(c)
    ok("B-2 0=무제한(서빙 기본) — 정상 호출 재개")

    print("[D 일일 소프트 임계]")
    warnings: list[str] = []

    class Cap(logging.Handler):
        def emit(self, record):
            if record.levelno == logging.WARNING and "일일" in record.getMessage():
                warnings.append(record.getMessage())

    h = Cap()
    ms.logger.addHandler(h)
    try:
        settings.tmap_daily_warn_calls = ms._daily_tmap["n"] + 2
        async with client() as c:
            await leg(c)                 # 임계 미달 — 무경고
            assert warnings == []
            await leg(c)                 # 임계 도달 — WARNING 1회
            assert len(warnings) == 1, warnings
            await leg(c)                 # +1 (100콜 전) — 재경고 없음
            assert len(warnings) == 1
    finally:
        ms.logger.removeHandler(h)
    ok("D-1 임계 도달 WARNING 1회 · 100콜 전 재경고 없음 · 차단 없음")


def run_tests():
    orig = (settings.tmap_leg_cache_ttl_s, settings.tmap_budget_calls,
            settings.tmap_daily_warn_calls)
    try:
        ctx = contextvars.copy_context()
        ctx.run(lambda: asyncio.run(scenario()))
        assert ms.tmap_call_count() is None   # 바깥 컨텍스트 무오염
    finally:
        (settings.tmap_leg_cache_ttl_s, settings.tmap_budget_calls,
         settings.tmap_daily_warn_calls) = orig
        ms.clear_tmap_leg_cache()
    print("\n전부 통과 — 외부 콜 0·DB 무접촉·설정 원복·캐시 청소(부수효과 0)")


if __name__ == "__main__":
    run_tests()
