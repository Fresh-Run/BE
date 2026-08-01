"""
Integration: 크루 피드 session_key 노출 (CREW_SESSION_COLLAPSE ⓐ, 2026-08-01 승인)

1. 세션 런 — 실키(c: 접두) + 같은 세션 2유저 키 동일(클라 접기 성립)
2. 비세션 런 — null
3. K1 활동 피드 — 항상 null(상속 함정 처리)
4. 계약 — 크루 피드 키 세트 기존+1 정확(session_key만 추가)

Run: python tests/test_crew_session_key_integration.py  (TestClient 인프로세스)
임시 유저·크루·run 종료 시 전삭·잔여 0.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.main import app  # noqa: E402

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_ADM = {"apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json"}
TS = int(time.time())
uids: list[str] = []
run_ids: list[str] = []
crew_id: str | None = None


def ok(m):
    print(f"  ✓ {m}")


def sb_user(tag):
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                   json={"email": f"csk-{tag}-{TS}@t.l", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    uids.append(r.json()["id"])
    return r.json()["id"]


def sb_login(tag):
    r = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                   headers={"apikey": settings.supabase_key,
                            "Content-Type": "application/json"},
                   json={"email": f"csk-{tag}-{TS}@t.l", "password": "test1234"},
                   timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def sb_run(uid, title, session_key=None, crew=None):
    body = {"user_id": uid, "distance_km": 3.0, "duration_sec": 1200,
            "visibility": "public", "title": title}
    if session_key:
        body["session_key"] = session_key
        body["crew_id"] = crew
    r = httpx.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=representation"},
                   json=body, timeout=30)
    r.raise_for_status()
    run_ids.append(r.json()[0]["id"])
    return r.json()[0]["id"]


def run_tests():
    global crew_id
    a, b = sb_user("a"), sb_user("b")
    tok_a = sb_login("a")
    cl = TestClient(app)

    def api(method, path, tok, **kw):
        return cl.request(method, f"/api{path}",
                          headers={"Authorization": f"Bearer {tok}"}, **kw)

    r = api("POST", "/crews", tok_a, json={"name": f"csk-{TS}"})
    assert r.status_code in (200, 201), r.text
    crew_id = r.json()["id"]
    httpx.post(f"{_SB}/rest/v1/crew_members", headers=_ADM,
               json={"crew_id": crew_id, "user_id": b, "role": "member"},
               timeout=30).raise_for_status()
    skey = f"c:{crew_id}:2026-08-01"
    r_a = sb_run(a, f"csk-{TS}-sess-a", session_key=skey, crew=crew_id)
    r_b = sb_run(b, f"csk-{TS}-sess-b", session_key=skey, crew=crew_id)
    r_plain = sb_run(a, f"csk-{TS}-plain")

    print("[1·2. 크루 피드 — 세션 실키·동일 키·비세션 null]")
    items = [x for x in api("GET", f"/crews/{crew_id}/runs", tok_a).json()
             if str(x.get("title", "")).startswith(f"csk-{TS}")]
    by_id = {x["run_id"]: x for x in items}
    assert by_id[r_a]["session_key"] == skey and by_id[r_b]["session_key"] == skey
    assert by_id[r_a]["session_key"].startswith("c:")
    assert by_id[r_plain]["session_key"] is None
    assert by_id[r_a]["is_crew_session"] is True and by_id[r_plain]["is_crew_session"] is False
    ok(f"세션 2유저 키 동일({skey[:20]}…) ✓ c: 접두 ✓ 비세션 null ✓")

    print("\n[4. 계약 — 키 세트 기존+1 정확]")
    EXPECTED = {"run_id", "user_id", "nickname", "avatar_url", "ran_at", "title",
                "distance_km", "duration_sec", "avg_pace_sec_per_km", "route_id",
                "area", "photo_thumb", "polyline_thumb", "route_summary",
                "comment_count", "kudos_count", "my_kudos", "allow_likes",
                "allow_comments", "is_crew_session", "session_participant_count",
                "session_key"}
    got = set(by_id[r_a].keys())
    assert got == EXPECTED, got ^ EXPECTED
    ok("크루 피드 키 22종 = 기존 21 + session_key 정확히 1 추가")

    print("\n[3. K1 활동 피드 — 항상 null]")
    # a가 b를 팔로우 → b의 세션 런이 a의 활동 피드에 노출.
    # 신규 auth 유저는 profiles 행이 없어 follow가 404 — upsert 선행(scope 테스트 전례)
    for uid, tag in ((a, "a"), (b, "b")):
        httpx.post(f"{_SB}/rest/v1/profiles",
                   headers={**_ADM, "Prefer": "resolution=merge-duplicates"},
                   params={"on_conflict": "user_id"},
                   json={"user_id": uid, "nickname": f"csk-{tag}-{TS}"},
                   timeout=30).raise_for_status()
    r = api("POST", f"/users/{b}/follow", tok_a)
    assert r.status_code in (202, 204), r.text
    feed = api("GET", "/feed/activities", tok_a).json() if True else []
    mine = [x for x in feed if str(x.get("title", "")).startswith(f"csk-{TS}")]
    assert mine, "팔로우 후 b 런이 활동 피드에 있어야"
    assert all(x.get("session_key") is None for x in mine), mine
    ok(f"K1 피드 {len(mine)}건 전부 session_key null(상속 필드 미채움)")


def cleanup():
    sb = get_supabase_admin()
    if run_ids:
        sb.table("runs").delete().in_("id", run_ids).execute()
    if crew_id:
        httpx.delete(f"{_SB}/rest/v1/crews", headers=_ADM,
                     params={"id": f"eq.{crew_id}"}, timeout=30)
    for u in uids:
        httpx.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM, timeout=30)
    left = sb.table("runs").select("id").in_("id", run_ids).execute().data if run_ids else []
    assert left == []
    print(f"\n[cleanup] runs {len(run_ids)}·크루·유저 {len(uids)} 삭제·잔여 0")


if __name__ == "__main__":
    try:
        run_tests()
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
