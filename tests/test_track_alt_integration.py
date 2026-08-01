"""
Integration: GPS 트랙 alt 보존 (2026-08-01, Ivan 계약 — 고도 차트+avoid_hills 실효 측정)

1. process_track — alt 포인트는 저장 폴리라인에 alt 병기(반올림 1), 미전송은 키 생략
2. 수평 불변 — 동일 좌표 alt 유/무 → server_distance·kept 동일(필터·거리 무유입)
3. E2E — alt 트랙 저장 → GET /runs/{id}/track 응답 polyline[].alt 실림
4. 구트랙(alt 없음) — 응답 alt null(기존 키·값 무영향, additive 1키)

Run: python tests/test_track_alt_integration.py
임시 유저·run 종료 시 전삭·잔여 0.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.main import app  # noqa: E402
from app.models.schemas import GpsPoint, RunRequest  # noqa: E402
from app.services import run_service, track_service  # noqa: E402

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_ADM = {"apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json"}
TS = int(time.time())
_uid: str | None = None
run_ids: list[str] = []


def ok(m):
    print(f"  ✓ {m}")


def _pts(n=80, with_alt=True):
    """~10m 간격 북진, 6분/km대 — 필터 통과형 합성 트랙."""
    out = []
    for i in range(n):
        alt = 20.0 + (i % 10) * 0.77 if with_alt and i % 3 != 2 else None  # 일부 결측
        out.append(track_service.TrackPoint(
            lat=37.51 + i * 0.00009, lng=129.115, t_ms=i * 3600, acc=4.0, alt=alt))
    return out


def _gps(n=80, with_alt=True):
    return [GpsPoint(lat=p.lat, lng=p.lng, t=p.t_ms, acc=p.acc,
                     **({"alt": p.alt} if p.alt is not None else {}))
            for p in _pts(n, with_alt)]


def run_tests():
    global _uid
    print("[1. process_track — alt 병기·미전송 키 생략]")
    proc = track_service.process_track(_pts(with_alt=True))
    with_alt = [p for p in proc.polyline if "alt" in p]
    assert with_alt, "alt 포인트가 폴리라인에 보존돼야"
    assert all(isinstance(p["alt"], float) for p in with_alt)
    # 혼합 트랙 불변식: 폴리라인 점은 "float alt 보유" 또는 "키 자체 없음" —
    # null alt는 절대 없다(간축이 결측점을 남길지는 선택 편향이라 비강제).
    assert all(("alt" not in p) or isinstance(p["alt"], float) for p in proc.polyline)
    none_proc = track_service.process_track(_pts(with_alt=False))
    assert all("alt" not in p for p in none_proc.polyline), "전량 결측 → 키 0"
    ok(f"보존 {len(with_alt)}pt · null 없음 불변식 ✓ · 전량 결측 시 키 0 ✓")

    print("\n[2. 수평 불변 — alt 유/무 거리·kept 동일]")
    pa = track_service.process_track(_pts(with_alt=True))
    pb = track_service.process_track(_pts(with_alt=False))
    assert pa.server_distance_km == pb.server_distance_km, \
        (pa.server_distance_km, pb.server_distance_km)
    assert pa.point_count_kept == pb.point_count_kept
    assert pb.polyline and all("alt" not in p for p in pb.polyline)
    ok(f"거리 {pa.server_distance_km}km·kept {pa.point_count_kept} 동일 — 고도 무유입")

    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                   json={"email": f"alt-{TS}@t.l", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    tok = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                     headers={"apikey": settings.supabase_key,
                              "Content-Type": "application/json"},
                     json={"email": f"alt-{TS}@t.l", "password": "test1234"},
                     timeout=30).json()["access_token"]
    cl = TestClient(app)

    print("\n[3. E2E — alt 트랙 저장 → track 응답 alt 실림]")
    res = asyncio.run(run_service.create_run(
        RunRequest(distance_km=0.8, duration_sec=300, gps_track=_gps(with_alt=True)),
        user_id=_uid))
    run_ids.append(res.id)
    tr = cl.get(f"/api/runs/{res.id}/track",
                headers={"Authorization": f"Bearer {tok}"}).json()
    alts = [p.get("alt") for p in tr["polyline"]]
    assert any(a is not None for a in alts), "응답에 alt 실려야"
    assert set(tr["polyline"][0].keys()) == {"lat", "lng", "alt"}
    ok(f"polyline {len(alts)}pt 중 alt 비null {sum(a is not None for a in alts)}pt")

    print("\n[4. 구트랙(alt 없음) — 응답 alt null·기존 키 무영향]")
    res2 = asyncio.run(run_service.create_run(
        RunRequest(distance_km=0.8, duration_sec=300, gps_track=_gps(with_alt=False)),
        user_id=_uid))
    run_ids.append(res2.id)
    tr2 = cl.get(f"/api/runs/{res2.id}/track",
                 headers={"Authorization": f"Bearer {tok}"}).json()
    assert all(p.get("alt") is None for p in tr2["polyline"])
    assert set(tr2.keys()) == {"polyline", "server_distance_km", "elev_gain_m",
                               "moving_sec", "point_count_raw", "point_count_kept"}
    ok("alt 전부 null(additive 1키) · 응답 top-level 키 기존 6종 불변")


def cleanup():
    sb = get_supabase_admin()
    if run_ids:
        sb.table("runs").delete().in_("id", run_ids).execute()  # run_tracks CASCADE
    if _uid:
        httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_ADM, timeout=30)
    left = sb.table("runs").select("id").in_("id", run_ids).execute().data if run_ids else []
    assert left == []
    print(f"\n[cleanup] runs {len(run_ids)}(트랙 cascade)·임시 유저 삭제·잔여 0")


if __name__ == "__main__":
    try:
        run_tests()
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
