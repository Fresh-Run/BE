"""
Integration: 캐노니컬 코스 위 시작 (오너 확정 2026-07-27)

폴리라인 최근접 ≤30m면 우선진입점 경유 없이 제자리 시작(진입 leg 0, 루프 회전).
합격선: 배치4 플라자 t2.0 → ~2.0km(경유 2.6km 아님). 코스 밖은 현행(rank0) 유지.
실 canonical_courses(18코스) + 실 T-map(코스 밖 진입 leg만) 사용, DB 쓰기 없음.

Run: python tests/test_canonical_on_course.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import Coordinate  # noqa: E402
from app.services import canonical_service  # noqa: E402


def ok(m):
    print(f"  ✓ {m}")


async def main():
    print("[1. 배치4 플라자(코스 위) t2.0 — 제자리 1바퀴 ~2.0km]")
    r = await canonical_service.match_and_build(
        Coordinate(lat=37.544532, lng=126.66425), 2.0)
    assert r is not None, "플라자 매칭 실패"
    route, meta = r
    assert abs(route.total_distance_km - 1.96) <= 0.1, route.total_distance_km
    assert meta.get("on_course_start") is True and meta["access_rank"] is None, meta
    assert meta["laps"] == 1 and meta["access_dist_m"] <= 30, meta
    ok(f"{route.summary} {route.total_distance_km}km (경유 2.6km 아님) · "
       f"on_course_start=True · 진입 leg 0")

    print("\n[2. 코스 밖(연희동 오너 홈) t5.0 — 현행 rank0 경유 유지 회귀]")
    r2 = await canonical_service.match_and_build(
        Coordinate(lat=37.53814, lng=126.66067), 5.0)
    assert r2 is not None, "연희동 매칭 실패"
    route2, meta2 = r2
    assert meta2["access_rank"] == 0 and "on_course_start" not in meta2, meta2
    assert meta2["laps"] == 2 and 5.0 <= route2.total_distance_km <= 5.6, \
        (meta2, route2.total_distance_km)
    ok(f"{route2.summary} {route2.total_distance_km}km rank0 경유 — 현행 유지")

    print("\n[3. 청라 진입점 t4.5 — 회귀(거리 불변, 진입점=코스 위라 on_course 전환)]")
    r3 = await canonical_service.match_and_build(
        Coordinate(lat=37.528678, lng=126.635812), 4.5)
    assert r3 is not None, "청라 매칭 실패"
    route3, meta3 = r3
    assert meta3["course_name"] == "청라호수공원 순환", meta3
    assert abs(route3.total_distance_km - 4.5) <= 0.1, route3.total_distance_km
    ok(f"{route3.summary} {route3.total_distance_km}km "
       f"(on_course_start={meta3.get('on_course_start')}) — 거리 계약 불변")

    print("\n[4. 석촌 배수 매칭 t5.0 — 2바퀴 회귀]")
    from app.core.supabase_client import get_supabase_admin
    sk = get_supabase_admin().table("canonical_courses") \
        .select("access_points,distance_km").eq("name", "석촌호수 순환").single().execute().data
    ap0 = sk["access_points"][0]
    r4 = await canonical_service.match_and_build(
        Coordinate(lat=ap0[0], lng=ap0[1]), 5.0)
    assert r4 is not None, "석촌 매칭 실패"
    route4, meta4 = r4
    assert meta4["laps"] == 2, meta4
    exp = float(sk["distance_km"]) * 2
    assert abs(route4.total_distance_km - exp) <= 0.15, (route4.total_distance_km, exp)
    ok(f"{route4.summary} {route4.total_distance_km}km laps=2 — 배수 매칭 불변")


if __name__ == "__main__":
    asyncio.run(main())
    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
