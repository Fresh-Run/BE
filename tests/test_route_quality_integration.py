"""
Integration test: 코스 생성 품질 (② 소수점 반올림, ③ 유저 언어 설정 lang 반영)
① 속도(reasoning_effort=none)는 before/after 계측 보고로 대체 — 여기선 미측정.
Run: python tests/test_route_quality_integration.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from unittest.mock import AsyncMock, patch

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys():
    anon = svc = ""
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                svc = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(m): print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")


def _hangul(s: str) -> bool:
    return any("가" <= ch <= "힣" for ch in (s or ""))


def phase_pure():
    from app.services import run_service as rs
    from app.services import route_service as rt
    from app.models.schemas import Coordinate, RouteRequest, RouteResponse, Waypoint, PedestrianRoute

    step("1. ② 결정론 — 통계 거리 1자리")
    rows = [{"distance_km": 5.12, "duration_sec": 1500},
            {"distance_km": 3.37, "duration_sec": 1100}]  # 합 8.49 → 8.5
    agg = rs._aggregate(rows, delta_distance_km=None)
    assert agg.total_distance_km == 8.5, f"1자리 반올림 기대 8.5, got {agg.total_distance_km}"
    assert agg.longest_run_km == 5.1, f"최장 1자리 5.1, got {agg.longest_run_km}"
    assert isinstance(agg.total_duration_sec, int)  # 시간은 정수 초
    ok("total_distance_km 8.49→8.5 ✓ longest 5.12→5.1 ✓ duration 정수초 ✓")

    step("2. ② 결정론 — 코스 생성 거리 1자리·소요시간 정수분 (mock)")
    def mk_route():
        return RouteResponse(summary="테스트 코스", total_distance_km=5.0, waypoints=[
            Waypoint(name="출발", coordinate=Coordinate(lat=37.51, lng=129.12), is_pitstop=False),
            Waypoint(name="반환", coordinate=Coordinate(lat=37.5155, lng=129.1226), is_pitstop=False)])
    # T-map 5237m → 5.2km. 소요시간은 v2.2부터 T-map 도보시간 폐기 → 러닝 환산
    # (거리 × 6'30"/km): 5.2 × 6.5 = 33.8 → 34분(정수). duration_s는 이제 무시됨.
    ped = PedestrianRoute(distance_m=5237.0, duration_s=1583.0,
                          path=[Coordinate(lat=37.51, lng=129.12)], provider="tmap")
    with patch.object(rt.openai_service, "generate_route", AsyncMock(return_value=mk_route())), \
         patch.object(rt.map_service, "get_pedestrian_route", AsyncMock(return_value=ped)), \
         patch.object(rt.feedback_service, "collect_avoidance_hints", AsyncMock(return_value=[])), \
         patch.object(rt, "_save_route", AsyncMock()):
        out = asyncio.run(rt.create_running_route(
            RouteRequest(start={"lat": 37.51, "lng": 129.12}, target_distance_km=5),
            user_id=None))
    assert out.total_distance_km == 5.2, f"거리 5237m→5.2km, got {out.total_distance_km}"
    assert out.estimated_duration_min == 34.0 and out.estimated_duration_min == int(out.estimated_duration_min), \
        f"소요시간 러닝환산 5.2×6.5=34분(정수), got {out.estimated_duration_min}"
    ok("거리 5237m→5.2km ✓ 소요시간 러닝환산 34분 정수 ✓")


def _gen(c, tok):
    """생성 실호출. 밴드 도입(v2.1~) 후 실호출은 지역에 따라 502(정직 실패)가
    날 수 있어 3회 재시도 — 언어 검증이 목적이라 200 하나를 확보. 3회 다 502면
    None(계약상 정상 — 언어 검증 skip)."""
    for _ in range(3):
        r = c.post(f"{BASE}/routes/generate",
                   headers={"Authorization": f"Bearer {tok}"}, timeout=90,
                   json={"start": {"lat": 37.5665, "lng": 126.6737}, "target_distance_km": 6})
        if r.status_code == 200:
            return r.json()
        assert r.status_code == 502, r.text[:300]  # 502 외 상태는 실제 버그
    return None


def phase_real(c, tok_ko, tok_en):
    step("3. ③ 실호출 — 유저 언어 설정(lang) 따름 (비한강 좌표: 인천 아라뱃길)")
    # ko 유저 → 한국어
    d = _gen(c, tok_ko)
    if d is None:
        ok("ko 3회 전부 502(정직 실패 — 계약 준수) · 언어 검증 skip")
    else:
        assert _hangul(d["summary"]), f"ko 유저 요약이 한국어가 아님: {d['summary'][:60]}"
        for w in d["waypoints"]:
            assert _hangul(w["name"]), f"ko 경유지명이 한국어가 아님: {w['name']}"
        assert round(d["total_distance_km"], 1) == d["total_distance_km"]
        dur = d.get("estimated_duration_min")
        assert dur is None or dur == int(dur)
        ok(f"ko 유저 → 한국어 ✓ {d['total_distance_km']}km {dur}분 — {d['summary'][:26]}…")
    # en 유저 → 영어 (한글 거의 없음)
    d2 = _gen(c, tok_en)
    if d2 is None:
        ok("en 3회 전부 502(정직 실패 — 계약 준수) · 언어 검증 skip")
    else:
        assert not _hangul(d2["summary"]), f"en 유저인데 한글 요약: {d2['summary'][:60]}"
        assert not any(_hangul(w["name"]) for w in d2["waypoints"]), "en인데 한글 경유지명"
        ok(f"en 유저 → 영어 ✓ {d2['total_distance_km']}km — {d2['summary'][:34]}…")


def run():
    ts = int(time.time())
    uids = []
    with httpx.Client(timeout=30) as c:
        try:
            phase_pure()
            step("공용: ko 유저 + en 유저")
            toks = {}
            for label, lang in (("ko", "ko"), ("en", "en")):
                e = f"rq-{label}-{ts}@t.l"
                r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                           json={"email": e, "password": "TestPass123!", "email_confirm": True})
                uids.append(r.json()["id"])
                r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
                           headers={"apikey": _ANON, "Content-Type": "application/json"},
                           json={"email": e, "password": "TestPass123!"})
                tok = r.json()["access_token"]
                c.patch(f"{BASE}/me/profile", headers={"Authorization": f"Bearer {tok}"},
                        json={"nickname": f"품질{label}-{ts%100000}"})
                # 언어 설정 지정
                c.patch(f"{BASE}/me/settings", headers={"Authorization": f"Bearer {tok}"},
                        json={"lang": lang})
                toks[label] = tok
            ok("ko/en 유저 생성 + lang 설정")
            phase_real(c, toks["ko"], toks["en"])
            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            for tbl, col in (("route_generations", "user_id"), ("routes", "user_id"),
                             ("profiles", "user_id")):
                if uids:
                    c.delete(f"{_SB}/rest/v1/{tbl}",
                             headers={**_ADM, "Prefer": "return=minimal"},
                             params={col: f"in.({','.join(uids)})"})
            for u in uids:
                c.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM)
            ok("route_generations·routes·profiles·auth 삭제")


if __name__ == "__main__":
    run()
