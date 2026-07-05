"""
Integration test: AI 오디오 코치 (POST /routes/{id}/coach-script, 프리미엄)
1) 결정론 — 후처리 순수 함수, settings.audio_coach 왕복/422, 캐시 mock(in-process),
   free 403 구조화, 404 2종 (Gemini 호출 0)
2) 실호출 1회 — premium 유저 + fixture route → 구조·한국어·정렬 → 재호출 캐시
Run: python tests/test_coach_script_integration.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, patch

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
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


def ok(m):
    print(f"  ✓ {m}")


def fail(m, d=""):
    print(f"  ✗ {m}" + (f": {d}" if d else ""))
    sys.exit(1)


def step(t):
    print(f"\n[{t}]")


def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201):
        fail("create user", r.text[:200])
    return r.json()["id"]


def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200:
        fail("login", r.text[:200])
    return r.json()["access_token"]


def sb_del_user(c, uid):
    c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)


def sb_del_in(c, table, col, vals):
    if not vals:
        return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})


def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


FIXTURE_WPS = [
    {"name": "서울숲 정문", "coordinate": {"lat": 37.5445, "lng": 127.0374},
     "is_pitstop": False, "description": "서울숲 공원의 주 출입구"},
    {"name": "은행나무길", "coordinate": {"lat": 37.5460, "lng": 127.0400},
     "is_pitstop": False, "description": "가을이면 노란 단풍 터널이 되는 길"},
    {"name": "한강 전망 데크", "coordinate": {"lat": 37.5430, "lng": 127.0420},
     "is_pitstop": False, "description": "한강이 내려다보이는 전망 지점"},
]


def mk_fixture_route(c, user_id, summary="서울숲 한 바퀴 5km 코스"):
    """Gemini 없이 routes 행을 직접 삽입 (코스 생성 비용 절약)."""
    r = c.post(f"{_SB}/rest/v1/routes", headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": user_id, "summary": summary,
                     "target_distance_km": 5.0, "total_distance_km": 5.0,
                     "waypoints": FIXTURE_WPS,
                     "start_lat": 37.5445, "start_lng": 127.0374})
    if r.status_code not in (200, 201):
        fail("fixture route insert", r.text[:200])
    return r.json()[0]["id"]


# ═══ Phase 1: 결정론 ═════════════════════════════════════════════════════════

def phase1_pure():
    from app.models.schemas import CoachCue
    from app.services import coach_service as cs

    step("1-1. 후처리(_sanitize_cues): 범위 검증·정렬·절삭")
    cues = [
        CoachCue(trigger="finish", text="완주"),
        CoachCue(trigger="distance_km", at=9.0, text="범위 밖 (거리 초과)"),
        CoachCue(trigger="distance_km", at=0.0, text="범위 밖 (0)"),
        CoachCue(trigger="waypoint", at=5, text="범위 밖 인덱스"),
        CoachCue(trigger="waypoint", at=1.4, text="은행나무길"),
        CoachCue(trigger="distance_km", at=1.0, text="1킬로미터"),
        CoachCue(trigger="distance_km", at=4.0, text="4킬로미터"),
        CoachCue(trigger="start", text="출발"),
    ]
    out = cs._sanitize_cues(cues, distance_km=5.0, waypoint_count=3)
    assert [c.trigger for c in out] == \
        ["start", "distance_km", "waypoint", "distance_km", "finish"], \
        [(c.trigger, c.at) for c in out]
    # waypoint idx 1 → 진행 위치 근사 (1/2)*5 = 2.5 → 1km와 4km 사이
    assert out[2].at == 1.0 and out[2].text == "은행나무길", "인덱스 정수화"
    ok("범위 밖 3개 제거 ✓ start→진행순→finish 정렬 ✓ 인덱스 보정 ✓")

    # 절삭: start/finish 보존 + 중간 10개 유지 (총 12)
    many = ([CoachCue(trigger="start", text="s")]
            + [CoachCue(trigger="distance_km", at=0.1 * i, text=f"m{i}") for i in range(1, 40)]
            + [CoachCue(trigger="finish", text="f")])
    out = cs._sanitize_cues(many, distance_km=5.0, waypoint_count=0)
    assert len(out) == cs.MAX_CUES == 12
    assert out[0].trigger == "start" and out[-1].trigger == "finish"
    ok("12개 절삭 (start/finish 보존) ✓")

    # trigger enum은 pydantic이 강제
    try:
        CoachCue(trigger="halfway", text="x")
        fail("허용 외 trigger는 검증 실패해야 함")
    except Exception:
        ok("trigger enum 검증 ✓")


def phase1_settings(c, tok):
    step("1-2. settings.audio_coach 기본값/PATCH 왕복/422")
    r = api(c, "GET", "/me/settings", tok)
    ac = r.json()["audio_coach"]
    assert ac == {"enabled": True, "voice": "joy", "rate": 1.0, "cue_interval_km": 1.0,
                  "announce_distance": True, "announce_pace": True,
                  "announce_calories": False}, ac
    r = api(c, "PATCH", "/me/settings", tok,
            json={"audio_coach": {"voice": "david", "rate": 1.3, "cue_interval_km": 2.0}})
    assert r.status_code == 200
    ac = r.json()["audio_coach"]
    assert (ac["voice"], ac["rate"], ac["cue_interval_km"]) == ("david", 1.3, 2.0)
    assert ac["enabled"] is True, "안 보낸 키는 유지"
    for bad in ({"audio_coach": {"rate": 2.0}},
                {"audio_coach": {"voice": "alex"}},
                {"audio_coach": {"volume": 1}}):
        assert api(c, "PATCH", "/me/settings", tok, json=bad).status_code == 422, bad
    ok("기본값 ✓ 부분 PATCH ✓ 범위·화이트리스트 422 ✓")


def phase1_cache_mock(c, uid_prem):
    step("1-3. 캐시 (in-process mock): 2회째는 Gemini 미호출 + from_cache")
    from app.models.schemas import CoachCue
    from app.services import coach_service as cs

    route_b = mk_fixture_route(c, uid_prem, summary="캐시 테스트 코스")
    fake = [CoachCue(trigger="start", text="출발해요"),
            CoachCue(trigger="distance_km", at=2.5, text="절반이에요"),
            CoachCue(trigger="finish", text="완주예요")]
    gen = AsyncMock(return_value=fake)
    with patch.object(cs.openai_service, "generate_coach_script", gen):
        r1 = asyncio.run(cs.get_or_create_script(route_b, uid_prem))
        r2 = asyncio.run(cs.get_or_create_script(route_b, uid_prem))
    assert gen.call_count == 1, f"2회째는 캐시여야 함, called {gen.call_count}"
    assert r1.from_cache is False and r2.from_cache is True
    assert [c_.text for c_ in r2.cues] == [c_.text for c_ in r1.cues]
    # 남의 route → RouteNotFound (in-process)
    try:
        asyncio.run(cs.get_or_create_script(route_b, "00000000-0000-0000-0000-000000000000"))
        fail("남의 route는 RouteNotFound여야 함")
    except cs.RouteNotFound:
        pass
    ok("생성 1회 + 캐시 재반환 ✓ from_cache 플래그 ✓ 소유권 격리 ✓")


def phase1_gates(c, tok_free, tok_prem, route_free):
    step("1-4. free 403 구조화 + 404 2종")
    r = api(c, "POST", f"/routes/{route_free}/coach-script", tok_free)
    assert r.status_code == 403, r.text[:200]
    d = r.json()["detail"]
    assert d["error"] == "premium_required" and d["feature"] == "audio_coach" and d["message"]
    # 404: 존재하지 않는 route / 남의(free 유저의) route
    r = api(c, "POST", "/routes/00000000-0000-0000-0000-000000000000/coach-script", tok_prem)
    assert r.status_code == 404, r.text[:200]
    r = api(c, "POST", f"/routes/{route_free}/coach-script", tok_prem)
    assert r.status_code == 404, "남의 route는 404 (존재 숨김)"
    ok("403 premium_required 구조화 ✓ 미존재 404 ✓ 남의 route 404 ✓")


# ═══ Phase 2: 실호출 1회 ═════════════════════════════════════════════════════

def phase2(c, tok_prem, route_a):
    import re

    step("2-1. Gemini 실호출: 스크립트 생성 → 구조·한국어·정렬")
    r = api(c, "POST", f"/routes/{route_a}/coach-script", tok_prem, timeout=90)
    assert r.status_code == 200, r.text[:400]
    d = r.json()
    assert d["route_id"] == route_a and d["from_cache"] is False
    cues = d["cues"]
    triggers = [q["trigger"] for q in cues]
    assert 3 <= len(cues) <= 12, f"cue 개수 {len(cues)}"
    assert triggers[0] == "start" and triggers[-1] == "finish"
    assert all(t in ("start", "distance_km", "waypoint", "finish") for t in triggers)
    dist_ats = [q["at"] for q in cues if q["trigger"] == "distance_km"]
    assert all(0 < a < 5.0 for a in dist_ats), dist_ats
    assert dist_ats == sorted(dist_ats), "distance_km 멘트는 진행 순서"
    for q in cues:
        assert re.search(r"[가-힣]", q["text"]), f"한국어 멘트여야 함: {q['text'][:40]}"
    sample = " / ".join(q["text"] for q in cues[:3])
    ok(f"{len(cues)}개 cue ✓ start~finish ✓ 정렬·범위 ✓ — {sample[:80]}…")

    step("2-2. 재호출 → 캐시 (from_cache=true, 비용 0)")
    r = api(c, "POST", f"/routes/{route_a}/coach-script", tok_prem)
    assert r.status_code == 200 and r.json()["from_cache"] is True
    assert len(r.json()["cues"]) == len(cues)
    ok("캐시 재반환 ✓")

    step("2-3. AI 생성 쿼터 미차감")
    r = api(c, "GET", "/me/quota", tok_prem)
    assert r.json()["ai_generation"]["used"] == 0, r.json()
    ok("used=0 ✓ (코치 스크립트는 쿼터 별개)")


def run():
    ts = int(time.time())
    pw = "TestPass123!"
    uids: list[str] = []
    route_ids: list[str] = []
    with httpx.Client(timeout=30) as c:
        try:
            phase1_pure()

            step("공용: premium/free 유저 + fixture route 2개")
            toks = []
            for i, label in ((1, "prem"), (2, "free")):
                e = f"ac-u{i}-{ts}@t.l"
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
                r = api(c, "PATCH", "/me/profile", toks[-1],
                        json={"nickname": f"코치u{i}-{ts % 100000}"})
                assert r.status_code == 200, r.text[:200]
            uid_prem, uid_free = uids
            tok_prem, tok_free = toks
            r = c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM,
                        params={"user_id": f"eq.{uid_prem}"}, json={"tier": "premium"})
            assert r.status_code in (200, 204), r.text[:200]
            route_a = mk_fixture_route(c, uid_prem)
            route_free = mk_fixture_route(c, uid_free, summary="free 유저 코스")
            route_ids += [route_a, route_free]
            ok("premium 승격 + fixture route 삽입 (Gemini 비용 0)")

            phase1_settings(c, tok_prem)
            phase1_cache_mock(c, uid_prem)  # route_b 생성 — cleanup은 user_id 기준
            phase1_gates(c, tok_free, tok_prem, route_free)
            phase2(c, tok_prem, route_a)

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            sb_del_in(c, "routes", "user_id", uids)  # coach_scripts CASCADE
            sb_del_in(c, "profiles", "user_id", uids)
            for uid in uids:
                sb_del_user(c, uid)
            ok("routes(coach_scripts CASCADE)·profiles·auth users 삭제")


if __name__ == "__main__":
    run()
