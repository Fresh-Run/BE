"""S2 효과 측정 — 한남동·성북동 5km를 N회 생성해 밴드 안 서빙 성공 횟수·추가 호출·지연 실측.

변경 전 코드(부모 커밋 워크트리)와 변경 후(main)에서 각각 실행해 비교한다. create_running_route를
직접 호출(쿼터 핸들러 우회) · 생성 route 전삭. Gemini·T-map 실호출(소량, N회로 상한).

실행: python scripts/measure_s2_effect.py [N]   (기본 N=5)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import KoreaCoordinate, RouteRequest  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.services import route_service, map_service, openai_service  # noqa: E402

TARGET = 5.0
STARTS = {"한남동": (37.54, 127.00), "성북동": (37.59, 126.99)}

_gem = {"n": 0}
_orig_gen = openai_service.generate_route


async def _counting_gen(**kw):
    _gem["n"] += 1
    return await _orig_gen(**kw)


async def run(n):
    openai_service.generate_route = _counting_gen
    sb = get_supabase_admin()
    created: list[str] = []
    for name, (la, ln) in STARTS.items():
        inband = missed = failed = 0
        redraws = 0
        for i in range(n):
            _gem["n"] = 0
            t0 = map_service.tmap_call_count() or 0
            st = time.perf_counter()
            req = RouteRequest(start=KoreaCoordinate(lat=la, lng=ln), target_distance_km=TARGET)
            tot = None
            try:
                route = await route_service.create_running_route(req, user_id=None)
                if route.route_id:
                    created.append(route.route_id)
                    gm = sb.table("routes").select("gen_meta").eq("id", route.route_id).execute().data
                    verdict = (gm[0]["gen_meta"] or {}).get("verdict") if gm else None
                else:
                    verdict = None
                tot = route.total_distance_km
                if 4.7 <= tot <= 5.5:
                    inband += 1
                else:
                    missed += 1
                if verdict and "redraw" in str(verdict):
                    redraws += 1
            except route_service.RouteGenerationFailed:
                failed += 1
            dt = time.perf_counter() - st
            tmap = (map_service.tmap_call_count() or 0) - t0
            print(f"  {name} run{i+1}: gemini={_gem['n']} tmap={tmap} {dt:.1f}s "
                  f"-> {'FAIL(502)' if tot is None else f'{tot}km' + (' [band]' if 4.7<=tot<=5.5 else ' [out]')}")
        print(f"  >>> {name}: 밴드 안 {inband}/{n} · 밴드 밖 서빙 {missed} · 실패(502) {failed} · redraw검출 {redraws}\n")
    if created:
        sb.table("routes").delete().in_("id", created).execute()
        print(f"[cleanup] 생성 route {len(created)}건 삭제")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5
    print(f"=== S2 효과 측정 (N={n}/지점, anchor_pool_n={route_service.settings.anchor_pool_n}) ===")
    asyncio.run(run(n))
