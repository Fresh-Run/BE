"""
Integration: K1 크루 배너 유저 초이스 show_crew (2026-08-01, 오너 결정 ①ON ②비공개 하드)

0. [게이트 무관] K1 계약 — crew_name 키 존재(+1), 컬럼 미적용이면 방어 폴백 전부 null
   [게이트] runs.show_crew 미적용이면 명시 대기 exit 1
1. ON×공개 → 실명 / 2. ON×비공개 → null(하드 게이트) / 3. OFF×공개 → null
4. 비크루런 → null / 5. PATCH 토글 왕복 / 6. 쿼리 고정(runs 1 + crews ≤1)

Run: python tests/test_show_crew_integration.py
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
from app.models.schemas import ActivityFeedItem  # noqa: E402
from app.services import run_service  # noqa: E402

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
                   json={"email": f"shc-{tag}-{TS}@t.l", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    uid = r.json()["id"]
    uids.append(uid)
    httpx.post(f"{_SB}/rest/v1/profiles",
               headers={**_ADM, "Prefer": "resolution=merge-duplicates"},
               params={"on_conflict": "user_id"},
               json={"user_id": uid, "nickname": f"sc{tag[:2]}{TS}"},
               timeout=30).raise_for_status()
    return uid


def sb_login(tag):
    r = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                   headers={"apikey": settings.supabase_key,
                            "Content-Type": "application/json"},
                   json={"email": f"shc-{tag}-{TS}@t.l", "password": "test1234"},
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
               json={"crew_id": cid, "user_id": owner, "role": "owner"}, timeout=30)
    return cid


def sb_run(uid, title, crew=None, show=None):
    body = {"user_id": uid, "distance_km": 3.0, "duration_sec": 1200,
            "visibility": "public", "title": title}
    if crew:
        body["crew_id"] = crew
        body["session_key"] = f"c:{crew}:2026-08-01"
    if show is not None:
        body["show_crew"] = show
    r = httpx.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=representation"},
                   json=body, timeout=30)
    r.raise_for_status()
    run_ids.append(r.json()[0]["id"])
    return r.json()[0]["id"]


def _column_exists():
    k = settings.supabase_service_role_key
    spec = httpx.get(f"{_SB}/rest/v1/", headers={"apikey": k, "Authorization": f"Bearer {k}"},
                     timeout=30).json()
    return "show_crew" in spec["definitions"]["runs"]["properties"]


def run_tests():
    o, v = sb_user("owner"), sb_user("viewer")
    tok_o, tok_v = sb_login("owner"), sb_login("viewer")
    cl = TestClient(app)

    def api(method, path, tok, **kw):
        return cl.request(method, f"/api{path}",
                          headers={"Authorization": f"Bearer {tok}"}, **kw)

    assert api("POST", f"/users/{o}/follow", tok_v).status_code in (202, 204)
    plain = sb_run(o, f"shc-{TS}-plain")

    print("[0. K1 계약 — crew_name 키(+1)·게이트 무관]")
    feed = api("GET", "/feed/activities", tok_v).json()
    mine = [x for x in feed if str(x.get("title", "")).startswith(f"shc-{TS}")]
    assert mine and "crew_name" in mine[0], mine
    assert set(mine[0].keys()) == set(ActivityFeedItem.model_fields.keys())
    assert mine[0]["crew_name"] is None, "비크루런 null"
    ok("K1 키 = 모델 필드 세트(crew_name 포함) ✓ 비크루런 null ✓")

    if not _column_exists():
        print("\n[검증 불가] runs.show_crew 미적용 — 오너가 "
              "db/2026-08-01_runs_show_crew.sql 실행 후 재실행 필요:\n"
              "  python tests/test_show_crew_integration.py")
        sys.exit(1)

    # 디폴트 게이트(동작 기반): 미지정 insert의 실값이 false여야(2026-08-02 OFF 재판정)
    _probe = sb_run(o, f"shc-{TS}-probe")
    pv = httpx.get(f"{_SB}/rest/v1/runs", headers=_ADM,
                   params={"select": "show_crew", "id": f"eq.{_probe}"},
                   timeout=30).json()[0]["show_crew"]
    if pv is not False:
        print("\n[검증 불가] show_crew 디폴트가 아직 ON — 오너가 "
              "db/2026-08-02_show_crew_default_off.sql 실행 후 재실행 필요")
        sys.exit(1)

    cpub = sb_crew(o, f"shc-pub-{TS}", True)
    cpriv = sb_crew(o, f"shc-priv-{TS}", False)
    r_on_pub = sb_run(o, f"shc-{TS}-onpub", crew=cpub, show=True)   # 명시 옵트인
    r_on_priv = sb_run(o, f"shc-{TS}-onpriv", crew=cpriv, show=True)  # 옵트인+비공개
    r_def_pub = sb_run(o, f"shc-{TS}-defpub", crew=cpub)            # 미지정=OFF(디폴트)

    print("\n[1~4. 매트릭스 — 디폴트 OFF(2026-08-02 재판정)]")
    feed = {x["run_id"]: x for x in api("GET", "/feed/activities", tok_v).json()
            if str(x.get("title", "")).startswith(f"shc-{TS}")}
    assert feed[r_on_pub]["crew_name"] == f"shc-pub-{TS}", feed[r_on_pub]["crew_name"]
    assert feed[r_on_priv]["crew_name"] is None, "비공개 하드 게이트(옵트인이어도)"
    assert feed[r_def_pub]["crew_name"] is None, "미지정=디폴트 OFF → null"
    assert feed[plain]["crew_name"] is None
    ok("옵트인×공개 실명 ✓ 옵트인×비공개 null(하드) ✓ 디폴트(미지정) null ✓ 비크루 null ✓")

    print("\n[5. PATCH 토글 왕복]")
    r = api("PATCH", f"/runs/{r_on_pub}", tok_o, json={"show_crew": False})
    assert r.status_code == 200, r.text
    feed = {x["run_id"]: x for x in api("GET", "/feed/activities", tok_v).json()}
    assert feed[r_on_pub]["crew_name"] is None, "토글 OFF 즉시 반영"
    r = api("PATCH", f"/runs/{r_on_pub}", tok_o, json={"show_crew": True})
    assert r.status_code == 200
    feed = {x["run_id"]: x for x in api("GET", "/feed/activities", tok_v).json()}
    assert feed[r_on_pub]["crew_name"] == f"shc-pub-{TS}", "토글 ON 복원"
    ok("PATCH false→null, true→실명 왕복")

    print("\n[6. 쿼리 고정 — runs 1 + crews 1 + members ≤1 (통일 게이트 2026-08-03)]")
    calls = {"runs": 0, "crews": 0, "crew_members": 0}
    real = run_service.get_supabase_admin()

    class Proxy:
        def table(self, name):
            if name in calls:
                calls[name] += 1
            return real.table(name)

    orig = run_service.get_supabase_admin
    run_service.get_supabase_admin = lambda: Proxy()
    try:
        asyncio.run(run_service._k1_crew_names(
            [r_on_pub, r_on_priv, r_def_pub, plain], o))   # 본인 뷰어 — 멤버십 스킵
        assert calls == {"runs": 1, "crews": 1, "crew_members": 0}, calls
        asyncio.run(run_service._k1_crew_names(
            [r_on_pub, r_on_priv, r_def_pub, plain], v))   # 타인 뷰어 — +1
        assert calls == {"runs": 2, "crews": 2, "crew_members": 1}, calls
        asyncio.run(run_service._k1_crew_names([plain], v))  # 태그 0 → 게이트 조기 종료
        assert calls == {"runs": 3, "crews": 2, "crew_members": 1}, calls
    finally:
        run_service.get_supabase_admin = orig
    ok("본인 2쿼리 · 타인 3쿼리 · 비크루만 1쿼리 — 행 수 무관 고정")


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
