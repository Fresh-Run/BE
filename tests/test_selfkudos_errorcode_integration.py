"""
Integration: ①자기 kudos 허용(2026-07-30 오너 정책) + ②error_code 계약(중앙 핸들러)

in-process ASGI(httpx.ASGITransport) + 실 DB. 임시 유저 2명 생성→종료 시 전량 삭제.

Run: python tests/test_selfkudos_errorcode_integration.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.main import app, _resolve_error_code  # noqa: E402

TS = int(time.time())
_SB = settings.supabase_url
_created: list[str] = []


def ok(m):
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def make_user(tag):
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"sk-{tag}-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _created.append(r.json()["id"])
    return r.json()["id"]


def token(tag):
    r = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                   headers={"apikey": settings.supabase_key, "Content-Type": "application/json"},
                   json={"email": f"sk-{tag}-{TS}@test.com", "password": "test1234"}, timeout=30)
    return r.json()["access_token"]


async def main():
    sb = get_supabase_admin()
    A, B = make_user("a"), make_user("b")
    tokA, tokB = token("a"), token("b")
    run_id = sb.table("runs").insert({
        "user_id": A, "ran_at": "2026-07-30T00:00:00+00:00", "distance_km": 5.0,
        "duration_sec": 1800, "avg_pace_sec_per_km": 360, "visibility": "public",
        "title": "셀프쿠도스", "start_lat": 37.55, "start_lng": 127.0,
    }).execute().data[0]["id"]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        print("[1. 본인 kudos — 2xx·멱등·카운트·알림 0]")
        HA = {"Authorization": f"Bearer {tokA}"}
        r1 = await c.post(f"/api/runs/{run_id}/kudos", headers=HA)
        r2 = await c.post(f"/api/runs/{run_id}/kudos", headers=HA)   # 멱등
        assert r1.status_code == 204 and r2.status_code == 204, (r1.status_code, r2.status_code)
        cnt = len(sb.table("run_kudos").select("user_id").eq("run_id", run_id).execute().data)
        assert cnt == 1, cnt
        notifs = sb.table("notifications").select("id").eq("user_id", A).execute().data
        assert len(notifs) == 0, "자기 kudos는 알림 0이어야(self-skip)"
        ok("본인 204·재호출 204(행 1)·본인 알림 0")

        print("\n[2. 타인 kudos 알림 회귀]")
        r3 = await c.post(f"/api/runs/{run_id}/kudos", headers={"Authorization": f"Bearer {tokB}"})
        assert r3.status_code == 204
        await asyncio.sleep(1.0)   # 알림 best-effort 백그라운드
        notifs = sb.table("notifications").select("actor_id,type").eq("user_id", A).execute().data
        assert any(n["type"] == "run_kudoed" and n["actor_id"] == B for n in notifs), notifs
        ok("타인 kudos → run_kudoed 알림 1 정상")

        print("\n[3. error_code — 큐레이션 문자열(detail 바이트 불변)]")
        r4 = await c.get(f"/api/crews/{uuid.uuid4()}", headers=HA)
        body = r4.json()
        assert r4.status_code == 404 and body["detail"] == "Crew not found", body
        assert body["error_code"] == "crew_not_found", body
        ok(f'404 {{"detail": "Crew not found", "error_code": "crew_not_found"}} — detail 원문 유지')

        print("\n[4. 구조화 dict 승격 — loop_target_too_short(쿼터·Gemini 0)]")
        r5 = await c.post("/api/routes/generate", headers=HA,
                          json={"start": {"lat": 37.55, "lng": 127.0}, "target_distance_km": 1.0})
        b5 = r5.json()
        assert r5.status_code == 422 and b5["detail"]["error"] == "loop_target_too_short", b5
        assert b5["error_code"] == "loop_target_too_short"
        ok("dict detail 원형 유지 + error 키 승격")

        print("\n[5. validation·제네릭 폴백]")
        r6 = await c.post("/api/routes/generate", headers=HA, json={"target_distance_km": 5})
        assert r6.status_code == 422 and r6.json()["error_code"] == "validation_error", r6.json()
        r7 = await c.get("/api/me/profile")   # 무토큰 → 401 "Not authenticated"
        b7 = r7.json()
        assert r7.status_code in (401, 403) and b7.get("error_code") in ("unauthorized", "forbidden"), b7
        ok(f"validation_error · 무토큰 {r7.status_code}→{b7.get('error_code')}")

    print("\n[6. 기존 구조화 코드 21종 스팟 — resolver 단위]")
    for code in ("quota_exceeded", "route_generation_failed", "route_generation_unavailable",
                 "one_way_end_too_far", "premium_required", "crew_owner", "demo_account",
                 "likes_disabled", "rsvp_closed", "weather_not_configured"):
        assert _resolve_error_code(400, {"error": code, "message": "x"}) == code
    assert _resolve_error_code(502, "boom") == "server_error"
    assert _resolve_error_code(404, "미등재 문자열") == "not_found"
    ok("dict 승격 10스팟 · 5xx server_error · 미등재→status 제네릭")


def cleanup():
    sb = get_supabase_admin()
    for uid in _created:
        for t, col in (("run_kudos", "user_id"), ("notifications", "user_id"),
                       ("runs", "user_id"), ("profiles", "user_id")):
            sb.table(t).delete().eq(col, uid).execute()
        httpx.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_adm(), timeout=30)
    print(f"\n[cleanup] 임시 유저 {len(_created)}명·run·kudos·알림 삭제")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
