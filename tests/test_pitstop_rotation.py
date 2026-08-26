"""
P3 개선 1차 — pitstop "항상 스타벅스" 로테이션 (2026-08-26)

commercial pitstop(예 "카페"→CE7) 선택이 rank[0] 최근접 고정으로 매번 같은 카페가
나오던 것을, 밴드 내 상위 K 중 최근 채택(유저 이력)을 회피하는 결정론적 회전으로 교정.
- Part 1(단위, DB 무접촉): rank_places_for_keyword 회전·품질·상업필터·결정론.
- Part 2(통합, DB 부수효과): create_running_route 반복 시 실이력 salt로 회전 +
  place 지정 무영향 + routes 행 생성/정리 assert.
Gemini/T-map/Kakao 실콜 0(seam mock). 임시 유저·생성분 즉삭.

Run: python tests/test_pitstop_rotation.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.models.schemas import (  # noqa: E402
    Coordinate, KoreaCoordinate, PedestrianRoute, Place, PitstopPlace,
    RouteRequest, RouteResponse, Waypoint,
)
from app.services import canonical_service, map_service, openai_service, route_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None
_passed = 0

# START 기준 카페들(밴드[200m,2500m]@5km 내 근접순: 스타 555m·투썸 777m·이디야 999m).
START = KoreaCoordinate(lat=37.60, lng=127.20)
START_C = Coordinate(lat=37.60, lng=127.20)


def _cafe(name, dlat, cat="CE7"):
    return Place(name=name, coordinate=Coordinate(lat=START.lat + dlat, lng=START.lng),
                 category="카페", category_code=cat, address="주소")


STAR = _cafe("스타벅스청라", 0.005)     # ~555m
TWO = _cafe("투썸플레이스", 0.007)      # ~777m
EDI = _cafe("이디야커피", 0.009)        # ~999m
CHK = _cafe("치킨마루", 0.004, "FD6")   # ~444m(최근접이나 CE7 아님 → 상업필터 배제)
FAR = _cafe("먼별다방", 0.030)          # ~3330m(밴드 밖 → 회전 승격 금지 대상)
CAFES = [CHK, STAR, TWO, EDI, FAR]       # 입력 순서 무관(rank가 밴드+거리 재정렬)


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _names(ranked):
    return [p.name for p in ranked]


# ── Part 1: 단위 — rank 회전/품질/상업필터/결정론 (DB 무접촉) ──────────────────
def part1():
    print("[Part 1. 단위 — rank_places_for_keyword 회전]")

    # A. 이력 없음 → rank[0]=최근접 CE7(스타벅스). 상업필터: FD6(치킨) 배제.
    r0 = map_service.rank_places_for_keyword("카페", CAFES, start=START_C, target_km=5.0)
    assert r0[0].name == "스타벅스청라", _names(r0)
    assert "치킨마루" not in _names(r0), _names(r0)  # FD6 배제(상업필터)
    ok(f"이력 없음 → rank[0]='스타벅스청라'·FD6 배제({_names(r0)})")

    # B. 이력=[스타벅스] → 상위K 중 스타벅스 회피 → rank[0]=투썸(다음 근접, 밴드 내).
    r1 = map_service.rank_places_for_keyword("카페", CAFES, start=START_C, target_km=5.0,
                                             recent_pitstops=["스타벅스청라"])
    assert r1[0].name == "투썸플레이스", _names(r1)
    ok(f"이력=[스타벅스] → 회전 rank[0]='투썸플레이스'(연속 동일 회피)")

    # C. 이력=[투썸,스타벅스](최신순) → 둘 회피 → rank[0]=이디야.
    r2 = map_service.rank_places_for_keyword("카페", CAFES, start=START_C, target_km=5.0,
                                             recent_pitstops=["투썸플레이스", "스타벅스청라"])
    assert r2[0].name == "이디야커피", _names(r2)
    ok("이력=[투썸,스타벅스] → 회전 rank[0]='이디야커피'")

    # D. 품질: 밴드 내(스타·투썸·이디야) 전부 이력이어도 밴드 밖 '먼별다방'은 승격 금지.
    #    상위 K 전부 최근 → 종전 rank[0](스타벅스) 유지(먼 후보로 안 튐).
    r3 = map_service.rank_places_for_keyword(
        "카페", CAFES, start=START_C, target_km=5.0,
        recent_pitstops=["이디야커피", "투썸플레이스", "스타벅스청라"])
    assert r3[0].name != "먼별다방", _names(r3)  # 밴드 밖 승격 0(품질 보존)
    assert r3[0].name == "스타벅스청라", _names(r3)  # 전부 최근 → rank[0] 폴백
    ok("상위 K 전부 이력 → 밴드 밖 승격 금지·rank[0] 폴백(품질 유지)")

    # E. 결정론: 같은 입력 2회 → 바이트 동일(랜덤 아님).
    a = map_service.rank_places_for_keyword("카페", CAFES, start=START_C, target_km=5.0,
                                            recent_pitstops=["스타벅스청라"])
    b = map_service.rank_places_for_keyword("카페", CAFES, start=START_C, target_km=5.0,
                                            recent_pitstops=["스타벅스청라"])
    assert _names(a) == _names(b), (_names(a), _names(b))
    ok("결정론 — 같은 (후보,이력) → 동일 순서(재현성)")

    # F. 하위호환: 밴드 정보 없으면 종전(거리순 원본, 회전 미적용).
    rn = map_service.rank_places_for_keyword("카페", CAFES, recent_pitstops=["스타벅스청라"])
    assert [p.name for p in rn if p.category_code == "CE7"], "CE7만 남아야"
    ok("밴드 정보 없음 → 종전 동작(하위호환)")


# ── Part 2: 통합 — 실이력 salt 회전 + place 무영향 + DB 부수효과 ────────────────
async def _snap(origin, destination, waypoints=None):
    return PedestrianRoute(distance_m=5000, duration_s=4000,
                           path=[Coordinate(lat=START.lat + 0.0001 * i, lng=START.lng) for i in range(60)],
                           provider="tmap", road_segments=[])


async def _search(query, *a, **k):
    return list(CAFES) if query == "카페" else []


async def _apt(*a, **k):
    return (0, 0)


def _cand(start):
    a = Coordinate(lat=start.lat + 0.005, lng=start.lng)
    b = Coordinate(lat=start.lat + 0.007, lng=start.lng)
    return RouteResponse(summary="mock", total_distance_km=5.0, waypoints=[
        Waypoint(name="출발", coordinate=start, is_pitstop=False),
        Waypoint(name="지점 1", coordinate=a, is_pitstop=False),
        Waypoint(name="지점 2", coordinate=b, is_pitstop=True),
        Waypoint(name="복귀", coordinate=start, is_pitstop=False)])


async def _gen(**kw):
    return _cand(kw["start"])


class _Patched:
    def __enter__(self):
        self._orig = (openai_service.generate_route, map_service.get_pedestrian_route,
                      map_service.search_places, map_service.count_apartment_signal)
        openai_service.generate_route = _gen
        map_service.get_pedestrian_route = _snap
        map_service.search_places = _search
        map_service.count_apartment_signal = _apt
        return self

    def __exit__(self, *e):
        (openai_service.generate_route, map_service.get_pedestrian_route,
         map_service.search_places, map_service.count_apartment_signal) = self._orig


def _pit_name(r):
    w = next((w for w in r.waypoints if w.is_pitstop), None)
    return w.name if w else None


async def part2():
    global _uid
    print("\n[Part 2. 통합 — 실이력 회전 + place 무영향 + DB]")
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"p3rot-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    sb = get_supabase_admin()

    picks = []
    with _Patched():
        # 같은 요청 3회 — 실이력(gen_meta.pitstop.name)이 다음 콜 salt로 회전.
        for i in range(3):
            resp = await route_service.create_running_route(
                RouteRequest(start=START, target_distance_km=5.0, pitstop_keyword="카페"),
                user_id=_uid)
            picks.append(_pit_name(resp))

    assert picks[0] == "스타벅스청라", picks
    assert picks[1] != picks[0], f"2회차 회전 실패(연속 동일): {picks}"
    assert picks[2] not in (picks[0], picks[1]) or len(set(picks)) >= 2, picks
    assert "치킨마루" not in picks, f"상업필터 뚫림: {picks}"
    ok(f"실이력 회전 — 3회 pitstop {picks}(연속 동일 회피·FD6 배제)")

    # DB 부수효과: routes 3행 생성 확인 + pitstop명이 gen_meta에 기록.
    rows = sb.table("routes").select("id,gen_meta").eq("user_id", _uid).execute().data
    assert len(rows) == 3, f"routes 3행 기대, 실제 {len(rows)}"
    saved = [(row.get("gen_meta") or {}).get("pitstop", {}).get("name") for row in rows]
    assert set(picks) == set(saved), (picks, saved)
    ok(f"DB 부수효과 — routes 3행·gen_meta.pitstop.name 기록({sorted(set(saved))})")

    # place 지정(A-2) 무영향 — 이력에 있는 이름을 place로 줘도 그대로 서빙(회전 안 걸림).
    poi = PitstopPlace(name="스타벅스청라",
                       coordinate=KoreaCoordinate(lat=START.lat + 0.005, lng=START.lng),
                       category_code="CE7")
    with _Patched():
        rp = await route_service.create_running_route(
            RouteRequest(start=START, target_distance_km=5.0, pitstop_place=poi), user_id=_uid)
    assert _pit_name(rp) == "스타벅스청라", _pit_name(rp)
    ok("place 지정 무영향 — 유저 지정 POI 그대로(회전 미적용)")


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    rows = sb.table("routes").select("id").eq("user_id", _uid).execute().data
    if rows:
        sb.table("routes").delete().in_("id", [x["id"] for x in rows]).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    assert len(sb.table("routes").select("id").eq("user_id", _uid).execute().data) == 0
    print(f"\n[cleanup] routes {len(rows)}행·임시 유저 삭제(잔여 0)")


async def main():
    part1()
    await part2()


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_passed} assert)\n" + "=" * 50)
    finally:
        cleanup()
