"""
Integration: 반복 생성 dedup — 소유 코스 회피 (2026-07-27 오너 승인 설계)

시나리오 6종: ①첫 서빙 무영향 ②2회차 캐노니컬 회피 ③삭제 후 재서빙
④앵커 지문 회피(+구행 waypoints 소급) ⑤바닥 규칙(캐노니컬 last-resort·앵커 split)
⑥one-way 무영향. 임시 유저 생성→종료 시 행·유저 전량 삭제, DB 부수효과 assert.

Run: python tests/test_route_dedup_integration.py
비용: 실 생성 ~3회(Gemini 풀 롤 — §E 승인 범위), 캐노니컬 서빙은 Gemini 0콜.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.models.schemas import Coordinate, KoreaCoordinate, RouteRequest  # noqa: E402
from app.services import openai_service, route_service  # noqa: E402
from app.services.route_service import (  # noqa: E402
    RouteGenerationFailed, _anchor_sig, _anchor_sig_from_row, _split_in_band_dedup,
)

CHEONGRA = KoreaCoordinate(lat=37.528678, lng=126.635812)   # 청라 우선진입점(캐노니컬)
GAROSU = KoreaCoordinate(lat=37.52326, lng=127.02255)        # 가로수길(앵커권 실측)
TS = int(time.time())
EMAIL = f"dedup-{TS}@test.com"

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_created_user_id: str | None = None


def ok(m):
    print(f"  ✓ {m}")


def _admin_headers():
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or settings.supabase_service_role_key
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def make_user() -> str:
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_admin_headers(),
                   json={"email": EMAIL, "password": "test1234", "email_confirm": True},
                   timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def user_rows(uid: str) -> list[dict]:
    sb = get_supabase_admin()
    return (sb.table("routes").select("id,summary,waypoints,gen_meta")
            .eq("user_id", uid).order("created_at").execute().data or [])


def wipe_rows(uid: str):
    sb = get_supabase_admin()
    ids = [r["id"] for r in user_rows(uid)]
    if ids:
        sb.table("routes").delete().in_("id", ids).execute()


async def main():
    global _created_user_id
    uid = make_user()
    _created_user_id = uid
    sb = get_supabase_admin()

    print("[1. 첫 서빙 무영향 회귀 — 청라 캐노니컬]")
    req = RouteRequest(start=CHEONGRA, target_distance_km=4.5)
    r1 = await route_service.create_running_route(req, user_id=uid)
    rows = user_rows(uid)
    assert len(rows) == 1, f"routes 1행 기대, {len(rows)}"
    gm1 = rows[0]["gen_meta"]
    assert gm1["engine"] == "canonical", gm1["engine"]
    assert gm1.get("course_id"), "course_id 기록 필수"
    assert "dedup_skipped_canonical" not in gm1 and "dedup_exhausted" not in gm1, \
        "첫 서빙에 dedup 키 없어야"
    ok(f"canonical 서빙({r1.summary}) · course_id 기록 · dedup 키 부재")

    print("\n[2. 2회차 캐노니컬 회피 — 같은 유저 재요청]")
    r2 = await route_service.create_running_route(req, user_id=uid)
    rows = user_rows(uid)
    assert len(rows) == 2, f"routes 2행 기대, {len(rows)}"
    gm2 = rows[1]["gen_meta"]
    if gm2["engine"] == "canonical":
        # 생성층까지 실패한 경우만 허용되는 경로 — 바닥 규칙으로 재서빙
        assert gm2.get("dedup_exhausted") is True, "canonical 재서빙은 exhausted 플래그 필수"
        ok(f"생성 실패 → 바닥 규칙 재서빙(dedup_exhausted, {r2.summary})")
    else:
        assert gm2.get("dedup_skipped_canonical", 0) >= 1, gm2
        assert r2.summary != r1.summary, "같은 캐노니컬 실명 카드가 재서빙되면 안 됨"
        ok(f"engine={gm2['engine']} 로 회피(dedup_skipped_canonical="
           f"{gm2['dedup_skipped_canonical']})")

    print("\n[3. 삭제 후 재서빙 — 삭제 = 재서빙 허용(오너 확정)]")
    wipe_rows(uid)
    assert user_rows(uid) == [], "삭제 후 0행"
    r3 = await route_service.create_running_route(req, user_id=uid)
    gm3 = user_rows(uid)[0]["gen_meta"]
    assert gm3["engine"] == "canonical" and not gm3.get("dedup_exhausted"), gm3
    ok(f"삭제 후 canonical 정상 복귀({r3.summary})")

    print("\n[4. 앵커 지문 회피 — 가로수길, anchor_pool_n=2]")
    wipe_rows(uid)
    _orig_n = settings.anchor_pool_n
    settings.anchor_pool_n = 2
    try:
        req_a = RouteRequest(start=GAROSU, target_distance_km=5.0)
        ra1 = await route_service.create_running_route(req_a, user_id=uid)
        row_a1 = user_rows(uid)[0]
        gma1 = row_a1["gen_meta"]
        sig1 = gma1.get("anchor_sig")
        if gma1["engine"] == "anchor":
            assert sig1, "anchor 채택 시 anchor_sig 기록 필수"
            assert _anchor_sig_from_row(row_a1["waypoints"]) == sig1, \
                "저장 waypoints 즉석 계산 지문이 기록 지문과 일치해야(구행 소급 커버)"
            ok(f"1회차 anchor 채택 sig={sig1} · waypoints 소급 계산 일치")

            # 구행 호환: anchor_sig 키를 제거해도 waypoints 계산 경로로 회피돼야
            gm_stripped = {k: v for k, v in gma1.items() if k != "anchor_sig"}
            sb.table("routes").update({"gen_meta": gm_stripped}).eq("id", row_a1["id"]).execute()

            ra2 = await route_service.create_running_route(req_a, user_id=uid)
            gma2 = user_rows(uid)[1]["gen_meta"]
            # 핵심 불변식: 같은 앵커 조합 재서빙 금지
            assert not (gma2["engine"] == "anchor"
                        and gma2.get("anchor_sig") == sig1
                        and not gma2.get("dedup_exhausted")), \
                f"소유 앵커 지문 재서빙: {gma2}"
            ok(f"2회차 engine={gma2['engine']} sig={gma2.get('anchor_sig')} "
               f"skipped={gma2.get('dedup_skipped_anchor', 0)} "
               f"exhausted={gma2.get('dedup_exhausted', False)} — 불변식 통과")
        else:
            # 앵커 미채택 라운드(스냅 변동) — 지문 자체가 없으니 회피 대상 아님. 관측만.
            ok(f"1회차 engine={gma1['engine']}(앵커 미채택 라운드) — 지문 경로는 "
               f"시나리오 5(b) 단위로 커버")
    finally:
        settings.anchor_pool_n = _orig_n

    print("\n[5. 바닥 규칙]")
    # (a) 캐노니컬 last-resort: 청라 소유 상태에서 생성 전 롤 강제 실패 → 재서빙
    wipe_rows(uid)
    await route_service.create_running_route(req, user_id=uid)  # 청라 소유 확보(canonical)
    _orig_gen = openai_service.generate_route

    async def _boom(*a, **k):
        raise RuntimeError("forced-fail(test)")

    openai_service.generate_route = _boom
    try:
        r5 = await route_service.create_running_route(req, user_id=uid)
    finally:
        openai_service.generate_route = _orig_gen
    rows5 = user_rows(uid)
    gm5 = rows5[-1]["gen_meta"]
    assert gm5["engine"] == "canonical" and gm5.get("dedup_exhausted") is True, gm5
    ok(f"생성 전패 → 502 대신 소유 캐노니컬 재서빙({r5.summary}, dedup_exhausted)")

    # (b) 앵커 split 단위 — fresh 유지 / 전부 소유 시 exhausted
    from app.models.schemas import RouteResponse, Waypoint

    def _mk(coords):
        wps = [Waypoint(name="x", coordinate=Coordinate(lat=la, lng=lo), is_pitstop=False)
               for la, lo in coords]
        return RouteResponse(summary="x", total_distance_km=5.0, waypoints=wps)

    a1 = _mk([(37.50, 127.00), (37.51, 127.01), (37.52, 127.00), (37.50, 127.00)])
    a2 = _mk([(37.50, 127.00), (37.53, 127.03), (37.54, 127.02), (37.50, 127.00)])
    v1 = _mk([(37.50, 127.00), (37.55, 127.05), (37.50, 127.00)])
    eng = {id(a1): "anchor", id(a2): "anchor", id(v1): "v87"}
    owned = {_anchor_sig(a1)}
    band = [(5.0, a1), (5.1, a2), (5.2, v1)]
    sel, skipped, exhausted = _split_in_band_dedup(band, owned, eng)
    assert skipped == 1 and not exhausted and a1 not in [r for _, r in sel], (skipped, exhausted)
    sel2, skipped2, exhausted2 = _split_in_band_dedup([(5.0, a1)], owned, eng)
    assert exhausted2 is True and skipped2 == 0 and sel2 == [(5.0, a1)], (skipped2, exhausted2)
    sel3, sk3, ex3 = _split_in_band_dedup(band, set(), eng)
    assert sel3 == band and sk3 == 0 and ex3 is False
    ok("split 단위: 소유 앵커 제외·전부 소유 시 exhausted·빈 지문 무영향")

    print("\n[6. one-way 무영향 — 지문 조회 자체 스킵]")
    called = {"fetch": False}
    _orig_fetch = route_service._fetch_owned_fingerprints

    async def _spy(u):
        called["fetch"] = True
        return await _orig_fetch(u)

    route_service._fetch_owned_fingerprints = _spy
    openai_service.generate_route = _boom  # 생성 도달 전후 비용 0(전 롤 즉시 실패)
    try:
        req_ow = RouteRequest(start=GAROSU, target_distance_km=5.0,
                              end=KoreaCoordinate(lat=37.5250, lng=127.0250))
        try:
            await route_service.create_running_route(req_ow, user_id=uid)
            raise AssertionError("one-way 강제 실패 경로가 502를 내야")
        except RouteGenerationFailed:
            pass
    finally:
        route_service._fetch_owned_fingerprints = _orig_fetch
        openai_service.generate_route = _orig_gen
    assert called["fetch"] is False, "one-way에서 지문 조회가 호출되면 안 됨"
    ok("one-way 요청은 지문 조회 0 (현행 동일 경로)")


def cleanup():
    if not _created_user_id:
        return
    sb = get_supabase_admin()
    wipe_rows(_created_user_id)
    # 테스트가 만든 gen_failures(강제 실패 6번 케이스) 정리 — 시작 좌표 격자로 특정
    fails = (sb.table("gen_failures").select("id,meta,created_at")
             .gte("created_at", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(TS - 60)))
             .execute().data or [])
    test_grids = {(37.53, 126.64), (37.52, 127.02), (37.53, 127.02)}  # 청라·가로수길
    kill = [f["id"] for f in fails
            if ((f.get("meta") or {}).get("grid_lat"),
                (f.get("meta") or {}).get("grid_lng")) in test_grids]
    if kill:
        sb.table("gen_failures").delete().in_("id", kill).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_created_user_id}",
                 headers=_admin_headers(), timeout=30)
    left = (sb.table("routes").select("id", count="exact")
            .eq("user_id", _created_user_id).execute().count)
    assert left == 0, f"정리 후 잔여 {left}행"
    print(f"\n[cleanup] routes 0행 · gen_failures {len(kill)}건 · 임시 유저 삭제 완료")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
