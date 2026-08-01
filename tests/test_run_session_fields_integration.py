"""
Integration: 개인 런 페이로드 크루 세션 필드 (2026-08-01, 프라이버시 판정 A)

매트릭스(시청자 × 크루 공개):
1. 소유자 본인 리스트 — 비공개 크루 세션 노출(3필드) + 비세션 null 대칭 + 키 세트 +3
2. 소유자 본인 단건 — 4필드 + count = 크루 피드 계산과 동일값
3. 크루원 시청자 단건(비공개 크루) — 노출
4. 비크루원 × 비공개 — 4필드 전부 null(200은 유지)
5. 비크루원 × 공개 크루 — 노출
6. 단건 키 세트 = 리스트 +1 정확
7. 쿼리 수 고정 — 헬퍼 crews 1 + (타인 소유분 있을 때만) crew_members 1

Run: python tests/test_run_session_fields_integration.py
임시 유저·크루·run 종료 시 전삭·잔여 0.
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
from app.services import crew_service, run_service  # noqa: E402

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_ADM = {"apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json"}
TS = int(time.time())
uids: list[str] = []
run_ids: list[str] = []
crew_ids: list[str] = []


def ok(m):
    print(f"  ✓ {m}")


def sb_user(tag):
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                   json={"email": f"rsf-{tag}-{TS}@t.l", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    uid = r.json()["id"]
    uids.append(uid)
    httpx.post(f"{_SB}/rest/v1/profiles",
               headers={**_ADM, "Prefer": "resolution=merge-duplicates"},
               params={"on_conflict": "user_id"},
               json={"user_id": uid, "nickname": f"rf{tag[:2]}{TS}"},  # ≤20자 + unique(owner/outside 첫자 충돌 회피)
               timeout=30).raise_for_status()
    return uid


def sb_login(tag):
    r = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                   headers={"apikey": settings.supabase_key,
                            "Content-Type": "application/json"},
                   json={"email": f"rsf-{tag}-{TS}@t.l", "password": "test1234"},
                   timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def sb_crew(owner, name, is_public):
    r = httpx.post(f"{_SB}/rest/v1/crews", headers={**_ADM, "Prefer": "return=representation"},
                   json={"owner_id": owner, "name": name, "is_public": is_public},
                   timeout=30)
    r.raise_for_status()
    cid = r.json()[0]["id"]
    crew_ids.append(cid)
    httpx.post(f"{_SB}/rest/v1/crew_members", headers=_ADM,
               json={"crew_id": cid, "user_id": owner, "role": "owner"},
               timeout=30).raise_for_status()
    return cid


def sb_run(uid, title, crew=None, skey=None):
    body = {"user_id": uid, "distance_km": 3.0, "duration_sec": 1200,
            "visibility": "public", "title": title}
    if crew:
        body["crew_id"] = crew
        body["session_key"] = skey
    r = httpx.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=representation"},
                   json=body, timeout=30)
    r.raise_for_status()
    run_ids.append(r.json()[0]["id"])
    return r.json()[0]["id"]


def run_tests():
    o = sb_user("owner")     # 런 소유자·양 크루 멤버
    m = sb_user("member")    # 비공개 크루 멤버(시청자)
    x = sb_user("outside")   # 비크루원 시청자
    tok_o, tok_m, tok_x = sb_login("owner"), sb_login("member"), sb_login("outside")
    cpriv = sb_crew(o, f"rsf-priv-{TS}", False)
    cpub = sb_crew(o, f"rsf-pub-{TS}", True)
    httpx.post(f"{_SB}/rest/v1/crew_members", headers=_ADM,
               json={"crew_id": cpriv, "user_id": m, "role": "member"},
               timeout=30).raise_for_status()
    k_priv = f"c:{cpriv}:2026-08-01"
    k_pub = f"c:{cpub}:2026-08-01"
    r_priv = sb_run(o, f"rsf-{TS}-priv", crew=cpriv, skey=k_priv)
    r_pub = sb_run(o, f"rsf-{TS}-pub", crew=cpub, skey=k_pub)
    r_plain = sb_run(o, f"rsf-{TS}-plain")

    cl = TestClient(app)

    def api(method, path, tok, **kw):
        return cl.request(method, f"/api{path}",
                          headers={"Authorization": f"Bearer {tok}"}, **kw)

    print("[1. 소유자 리스트 — 비공개 크루 노출·비세션 null·키 +3]")
    items = {x_["id"]: x_ for x_ in api("GET", "/runs", tok_o).json()}
    it = items[r_priv]
    assert it["crew_id"] == cpriv and it["crew_name"] == f"rsf-priv-{TS}" \
        and it["session_key"] == k_priv, it
    pl = items[r_plain]
    assert pl["crew_id"] is None and pl["crew_name"] is None and pl["session_key"] is None
    assert {"crew_id", "crew_name", "session_key"} <= set(it.keys())
    assert "session_participant_count" not in it, "count는 단건 전용(리스트 +3 정확)"
    ok("본인에겐 비공개 크루도 노출 ✓ 비세션 null 대칭 ✓ 리스트 +3 정확 ✓")

    print("\n[2. 소유자 단건 — 4필드 + count=피드 계산 동일]")
    d = api("GET", f"/runs/{r_priv}", tok_o).json()
    assert d["crew_name"] == f"rsf-priv-{TS}" and d["session_key"] == k_priv
    feed_count = asyncio.run(
        crew_service._session_participant_counts([k_priv])).get(k_priv)
    assert d["session_participant_count"] == feed_count == 1, \
        (d["session_participant_count"], feed_count)
    ok(f"단건 4필드 ✓ count {d['session_participant_count']} = 피드 헬퍼 값(단일 소스) ✓")

    print("\n[3. 크루원 시청자 — 비공개 크루 노출]")
    d = api("GET", f"/runs/{r_priv}", tok_m).json()
    assert d["crew_id"] == cpriv and d["session_key"] == k_priv \
        and d["session_participant_count"] == 1, d
    ok("멤버 시청자에겐 비공개 크루 세션 노출")

    print("\n[4. 비크루원 × 비공개 — 4필드 전부 null(200 유지)]")
    r = api("GET", f"/runs/{r_priv}", tok_x)
    assert r.status_code == 200
    d = r.json()
    assert (d["crew_id"] is None and d["crew_name"] is None
            and d["session_key"] is None and d["session_participant_count"] is None), d
    ok("run은 보이되 크루 문맥 4필드 완전 은닉")

    print("\n[5. 비크루원 × 공개 크루 — 노출]")
    d = api("GET", f"/runs/{r_pub}", tok_x).json()
    assert d["crew_id"] == cpub and d["crew_name"] == f"rsf-pub-{TS}" \
        and d["session_key"] == k_pub and d["session_participant_count"] == 1, d
    ok("공개 크루는 비크루원에게도 노출")

    print("\n[6. 단건 키 세트 = 리스트 +1 정확]")
    list_keys = set(items[r_priv].keys())
    detail_keys = set(api("GET", f"/runs/{r_priv}", tok_o).json().keys())
    extra = detail_keys - list_keys
    assert "session_participant_count" in extra, extra
    ok(f"단건 전용 추가 필드: {sorted(extra)} (session_participant_count 포함)")

    print("\n[7. 쿼리 수 고정 — crews 1 + 조건부 crew_members 1]")
    calls = {"crews": 0, "crew_members": 0}
    real = run_service.get_supabase_admin()

    class Proxy:
        def table(self, name):
            if name in calls:
                calls[name] += 1
            return real.table(name)

    orig = run_service.get_supabase_admin
    run_service.get_supabase_admin = lambda: Proxy()
    try:
        rows = [{"id": r_priv, "user_id": o, "crew_id": cpriv, "session_key": k_priv},
                {"id": r_pub, "user_id": o, "crew_id": cpub, "session_key": k_pub},
                {"id": r_plain, "user_id": o, "crew_id": None, "session_key": None}]
        asyncio.run(run_service._crew_session_fields(rows, o))       # 본인 — 멤버십 불요
        assert calls == {"crews": 1, "crew_members": 0}, calls
        asyncio.run(run_service._crew_session_fields(rows, x))       # 타인 — +1
        assert calls == {"crews": 2, "crew_members": 1}, calls
    finally:
        run_service.get_supabase_admin = orig
    ok("본인 1쿼리 · 타인 2쿼리 — 행 수 무관 고정(N+1 없음)")


def cleanup():
    sb = get_supabase_admin()
    if run_ids:
        sb.table("runs").delete().in_("id", run_ids).execute()
    for cid in crew_ids:
        httpx.delete(f"{_SB}/rest/v1/crews", headers=_ADM,
                     params={"id": f"eq.{cid}"}, timeout=30)
    for u in uids:
        httpx.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM, timeout=30)
    left = sb.table("runs").select("id").in_("id", run_ids).execute().data if run_ids else []
    assert left == []
    print(f"\n[cleanup] runs {len(run_ids)}·크루 {len(crew_ids)}·유저 {len(uids)} 삭제·잔여 0")


if __name__ == "__main__":
    try:
        run_tests()
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
