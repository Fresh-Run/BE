"""
Integration: 관측 확장 — cand_quality.crossing_count + gen_meta.prefs (2026-07-31)

1. _count_crossings 결정적 검증 — 실프로브 shape 픽스처(Point turnType 211 ×3 +
   LineString facilityType '15' ×3), 라인 폴백, 0건, 쓰레기 입력 → None(무해화)
2. 파이프라인 — cand_quality 전 후보에 crossing_count 병기 + gen_meta.prefs
   (요청 raw·미전송 null 명시·effective·avoid_tags)
3. 실패 주입 — crossing_count None이어도 서빙 200(생성 실패 전이 0)

Run: python tests/test_crossing_prefs_obs_integration.py
외부 콜 0(전부 mock). 임시 유저·routes 종료 시 전삭·잔여 0.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.models.schemas import (  # noqa: E402
    Coordinate, KoreaCoordinate, PedestrianRoute, RouteRequest,
)
from app.services import map_service, openai_service, route_service  # noqa: E402
from app.services.map_service import _count_crossings  # noqa: E402
from tests.test_spur_rescue_integration import (  # noqa: E402 — 하네스 재사용
    START, _mk_candidate, clean_path,
)

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
TS = int(time.time())
_uid: str | None = None


def ok(m):
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _pt(turn):
    return {"geometry": {"type": "Point"}, "properties": {"turnType": turn,
                                                          "facilityType": "11"}}


def _ln(facility):
    return {"geometry": {"type": "LineString"},
            "properties": {"facilityType": facility, "roadType": 21}}


# 실프로브(2026-07-31 강남) shape 재현: 횡단 3개 = Point 211 ×3 + 라인 '15' ×3
PROBE_SHAPE = ([_pt(200), _pt(12), _pt(211), _pt(211), _pt(211), _pt(17)]
               + [_ln("11")] * 10 + [_ln("15")] * 3 + [_ln("14")] * 2)


def unit_tests():
    print("[1. _count_crossings 결정적 검증]")
    assert _count_crossings(PROBE_SHAPE) == 3, _count_crossings(PROBE_SHAPE)
    ok("프로브 shape → 3 (Point turnType 211 기준)")
    only_lines = [_ln("11")] * 4 + [_ln("15")] * 2
    assert _count_crossings(only_lines) == 2
    ok("Point 없음 → facilityType '15' 라인 폴백 2")
    assert _count_crossings([_pt(12), _ln("11")]) == 0
    ok("횡단 없음 → 명시적 0 (None 아님)")
    assert _count_crossings(None) is None
    assert _count_crossings([None, {"geometry": "x"}, 42]) is None
    ok("쓰레기 입력(None·비dict 원소) → None — 예외 전파 0(무해화)")


async def pipeline_tests():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"obs-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    sb = get_supabase_admin()

    orig = (openai_service.generate_route, map_service.get_pedestrian_route,
            map_service.search_places, map_service.count_apartment_signal,
            settings.anchor_pool_n)

    async def gen_mock(**kw):
        return _mk_candidate(kw["start"])

    async def parks(*a, **k):
        return []

    async def apt(*a, **k):
        return (0, 0)

    def snap_with(crossings):
        async def snap(origin, destination, waypoints=None):
            return PedestrianRoute(distance_m=5000, duration_s=4000,
                                   path=clean_path(), provider="tmap",
                                   road_segments=[(21, "mock로", 5000)],
                                   crossing_count=crossings)
        return snap

    def last_gm():
        rows = sb.table("routes").select("gen_meta,created_at").eq("user_id", _uid) \
            .order("created_at", desc=True).limit(1).execute().data
        return rows[0]["gen_meta"]

    openai_service.generate_route = gen_mock
    map_service.search_places = parks
    map_service.count_apartment_signal = apt
    settings.anchor_pool_n = 0
    try:
        print("\n[2. 파이프라인 — crossing_count 병기 + prefs 기록(명시 요청)]")
        req = RouteRequest(start=KoreaCoordinate(lat=START.lat, lng=START.lng),
                           target_distance_km=5.0, terrain="flat", avoid_hills=True)
        map_service.get_pedestrian_route = snap_with(7)
        await route_service.create_running_route(req, user_id=_uid)
        gm = last_gm()
        cq = gm["cand_quality"]
        assert cq and all(c.get("crossing_count") == 7 for c in cq), cq
        p = gm["prefs"]
        assert p["terrain"] == "flat" and p["avoid_hills"] is True, p
        assert p["effective_terrain"] == "flat" and p["effective_avoid_hills"] is True, p
        assert isinstance(p["avoid_tags"], list), p
        ok(f"후보 {len(cq)}개 전원 crossing_count=7 · prefs raw+effective+avoid_tags 기록")

        print("\n[3. prefs 미전송 — null 명시(부재 표기)]")
        req0 = RouteRequest(start=KoreaCoordinate(lat=START.lat, lng=START.lng),
                            target_distance_km=5.0)
        await route_service.create_running_route(req0, user_id=_uid)
        p = last_gm()["prefs"]
        assert p["terrain"] is None and p["avoid_hills"] is None, p
        assert p["effective_terrain"] is not None, "병합 기본값은 실려야"
        ok(f"raw null 명시 · effective 기본값({p['effective_terrain']}/"
           f"{p['effective_avoid_hills']}) 기록")

        print("\n[4. 실패 주입 — crossing None이어도 서빙 200·null 기록]")
        map_service.get_pedestrian_route = snap_with(None)
        route = await route_service.create_running_route(req0, user_id=_uid)
        assert route.total_distance_km == 5.0, "관측 실패가 생성 실패로 전이되면 안 됨"
        cq = last_gm()["cand_quality"]
        assert all(c.get("crossing_count") is None for c in cq), cq
        ok("서빙 정상 + crossing_count null 기록(전이 0)")
    finally:
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.count_apartment_signal,
         settings.anchor_pool_n) = orig


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    rows = sb.table("routes").select("id").eq("user_id", _uid).execute().data
    if rows:
        sb.table("routes").delete().in_("id", [x["id"] for x in rows]).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    left = len(sb.table("routes").select("id").eq("user_id", _uid).execute().data)
    assert left == 0
    print(f"\n[cleanup] routes {len(rows)}건·임시 유저 삭제·잔여 0")


if __name__ == "__main__":
    import asyncio
    try:
        unit_tests()
        asyncio.run(pipeline_tests())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
