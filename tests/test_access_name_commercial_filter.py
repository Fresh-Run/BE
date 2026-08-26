"""
Integration: canonical _access_name 상업 landmark-borrow 배제 (P1 치킨마루, 2026-08-26)

진입점 실명이 이름 랜드마크 정규식에 맞아도 상업 카테고리(FD6·CE7 등)면 무효 —
"치킨마루 청라5단지호수공원점"(FD6, 상호에 '호수공원')이 채택되던 라이브 버그 교정.
실 랜드마크(공공)는 통과, 상업 차용은 배제, 없으면 중립(None).

Run: python tests/test_access_name_commercial_filter.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import Coordinate, Place  # noqa: E402
from app.services import canonical_service, map_service  # noqa: E402

_n = 0
C = Coordinate(lat=37.524412, lng=126.626413)   # 솔빛 블록 순환 진입점(실측)


def ok(m):
    global _n
    _n += 1
    print(f"  ✓ {m}")


def _place(name, cat, lat=37.524412, lng=126.626413):
    return Place(name=name, coordinate=Coordinate(lat=lat, lng=lng),
                 category=None, category_code=cat, address=None)


async def _with_search(results, coord=C):
    orig = map_service.search_places

    async def _mock(*a, **k):
        return results
    map_service.search_places = _mock
    try:
        return await canonical_service._access_name(coord)
    finally:
        map_service.search_places = orig


async def main():
    print("[합성 — 상업 배제 / 실랜드마크 통과]")
    # 상업 차용(FD6)이 최근접이어도 배제 → 다음 실 랜드마크(공원) 채택
    r = await _with_search([_place("치킨마루 청라5단지호수공원점", "FD6"),
                            _place("청라5단지호수공원", None)])
    assert r == "청라5단지호수공원", r
    ok(f"상업(FD6) 최근접 배제 → 실 랜드마크 '{r}' 채택")

    # 상업만 있으면 → 중립(None)
    r = await _with_search([_place("치킨마루 청라5단지호수공원점", "FD6"),
                            _place("스타벅스 호수공원점", "CE7")])
    assert r is None, r
    ok("상업(FD6·CE7)만 → None(중립 진입점) — 차용 채택 0")

    # 실 랜드마크(카테고리 None/공공)는 통과
    r = await _with_search([_place("청라호수공원", None)])
    assert r == "청라호수공원", r
    ok("실 랜드마크(공공, 카테고리 None) 통과")

    # 이름에 랜드마크 토큰 없으면(상호만) → None(정규식 미스)
    r = await _with_search([_place("GS25 청라점", "CS2")])
    assert r is None, r
    ok("랜드마크 토큰 없는 상호 → None(정규식+카테고리 이중 배제)")

    # 90m 밖 랜드마크 → 배제
    r = await _with_search([_place("먼공원", None, lat=37.5300, lng=126.6300)])
    assert r is None, r
    ok("90m 밖 랜드마크 → 배제(근접 가드 유지)")

    print("\n[청라 재현 — 솔빛 블록 진입점 실 Kakao (치킨마루 부재)]")
    live = await canonical_service._access_name(C)
    assert live is None or "치킨마루" not in live, f"치킨마루 잔존: {live!r}"
    ok(f"실 진입점 → {live!r} (치킨마루 배제 확인)")


if __name__ == "__main__":
    asyncio.run(main())
    print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_n} assert)\n" + "=" * 50)
