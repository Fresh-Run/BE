"""
Integration: 크루 필드 통일 게이트 (2026-08-03 오너 판정 — 전 표면 3-tier)

규칙: 본인=전 필드+show_crew 실값 / 크루원=크루 필드 표시(플래그 null) /
타인=공개 AND show_crew=true일 때만(플래그 null — 추론 누출 차단).

표면×뷰어 매트릭스:
1. LIST 본인 — show_crew 실값(T/F/기본 F) + 비공개 크루도 표시, 계약 +1
2. DETAIL 크루원 — 비공개 표시·OFF여도 표시(크루원 tier)·플래그 null
3. DETAIL 타인 — 공개×옵트인 표시 / 공개×OFF null(② 대비 조임) / 비공개 전부 null
4. PROFILE(/users/{id}/runs) — 공백 수리 실증: 타인에게 옵트인 실명 실림
5. K1 — 타인 옵트인만 / 크루원은 OFF여도 실명(통일)

Run: python tests/test_crew_unified_gate_integration.py
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
crew_ids: list[str] = []


def ok(m):
    print(f"  ✓ {m}")


def sb_user(tag):
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                   json={"email": f"ug-{tag}-{TS}@t.l", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    uid = r.json()["id"]
    uids.append(uid)
    httpx.post(f"{_SB}/rest/v1/profiles",
               headers={**_ADM, "Prefer": "resolution=merge-duplicates"},
               params={"on_conflict": "user_id"},
               json={"user_id": uid, "nickname": f"ug{tag[:2]}{TS}"},
               timeout=30).raise_for_status()
    return uid


def sb_login(tag):
    r = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                   headers={"apikey": settings.supabase_key,
                            "Content-Type": "application/json"},
                   json={"email": f"ug-{tag}-{TS}@t.l", "password": "test1234"},
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


def sb_member(crew, uid):
    httpx.post(f"{_SB}/rest/v1/crew_members", headers=_ADM,
               json={"crew_id": crew, "user_id": uid, "role": "member"},
               timeout=30).raise_for_status()


def sb_run(uid, title, crew=None, show=None):
    body = {"user_id": uid, "distance_km": 3.0, "duration_sec": 1200,
            "visibility": "public", "title": title}
    if crew:
        body["crew_id"] = crew
        body["session_key"] = f"c:{crew}:2026-08-03"
    if show is not None:
        body["show_crew"] = show
    r = httpx.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=representation"},
                   json=body, timeout=30)
    r.raise_for_status()
    run_ids.append(r.json()[0]["id"])
    return r.json()[0]["id"]


def run_tests():
    o, m, x = sb_user("owner"), sb_user("member"), sb_user("out")
    tok_o, tok_m, tok_x = sb_login("owner"), sb_login("member"), sb_login("out")
    cpub = sb_crew(o, f"ug-pub-{TS}", True)
    cpriv = sb_crew(o, f"ug-priv-{TS}", False)
    sb_member(cpub, m)
    sb_member(cpriv, m)
    r_pub_on = sb_run(o, f"ug-{TS}-pubon", crew=cpub, show=True)
    r_pub_off = sb_run(o, f"ug-{TS}-puboff", crew=cpub, show=False)
    r_priv_on = sb_run(o, f"ug-{TS}-privon", crew=cpriv, show=True)
    r_plain = sb_run(o, f"ug-{TS}-plain")

    cl = TestClient(app)

    def api(method, path, tok, **kw):
        return cl.request(method, f"/api{path}",
                          headers={"Authorization": f"Bearer {tok}"}, **kw)

    print("[1. LIST 본인 — show_crew 실값·비공개 표시·계약 +1]")
    items = {i["id"]: i for i in api("GET", "/runs", tok_o).json()}
    assert items[r_pub_on]["show_crew"] is True
    assert items[r_pub_off]["show_crew"] is False
    assert items[r_plain]["show_crew"] is False, "미지정=디폴트 OFF 실값"
    assert items[r_priv_on]["crew_name"] == f"ug-priv-{TS}", "본인에겐 비공개도 표시"
    assert "show_crew" in items[r_plain], "계약 +1"
    ok("본인 플래그 실값(T/F/기본F) ✓ 비공개 크루 표시 ✓")

    print("\n[2. DETAIL 크루원 — 비공개·OFF 모두 표시, 플래그 null]")
    d = api("GET", f"/runs/{r_priv_on}", tok_m).json()
    assert d["crew_name"] == f"ug-priv-{TS}" and d["show_crew"] is None, d
    d = api("GET", f"/runs/{r_pub_off}", tok_m).json()
    assert d["crew_name"] == f"ug-pub-{TS}", "크루원은 OFF여도 표시(통일 tier)"
    assert d["show_crew"] is None
    ok("크루원: 비공개 표시 ✓ OFF도 표시 ✓ 플래그 null ✓")

    print("\n[3. DETAIL 타인 — 옵트인만·플래그 항상 null]")
    d = api("GET", f"/runs/{r_pub_on}", tok_x).json()
    assert d["crew_name"] == f"ug-pub-{TS}" and d["show_crew"] is None, d
    d = api("GET", f"/runs/{r_pub_off}", tok_x).json()
    assert d["crew_name"] is None and d["session_key"] is None, "공개×OFF 조임(② 대비)"
    d = api("GET", f"/runs/{r_priv_on}", tok_x).json()
    assert (d["crew_id"] is None and d["crew_name"] is None
            and d["session_key"] is None and d["show_crew"] is None), d
    ok("공개×옵트인 표시 ✓ 공개×OFF null ✓ 비공개 전부 null(추론 차단) ✓")

    print("\n[4. PROFILE 표면 — 공백 수리 실증]")
    prof = {i["run_id"]: i for i in api("GET", f"/users/{o}/runs", tok_x).json()}
    assert prof[r_pub_on]["crew_name"] == f"ug-pub-{TS}", "제3 빌더 공백 수리"
    assert prof[r_pub_off]["crew_name"] is None
    assert prof[r_priv_on]["crew_name"] is None
    ok("타인 프로필: 옵트인 실명 실림(수리) ✓ OFF·비공개 null ✓")

    print("\n[5. K1 — 타인 옵트인만 / 크루원은 OFF도 실명(통일)]")
    for tok in (tok_x, tok_m):
        assert api("POST", f"/users/{o}/follow", tok).status_code in (202, 204)
    fx = {i["run_id"]: i for i in api("GET", "/feed/activities", tok_x).json()
          if str(i.get("title", "")).startswith(f"ug-{TS}")}
    assert fx[r_pub_on]["crew_name"] == f"ug-pub-{TS}"
    assert fx[r_pub_off]["crew_name"] is None and fx[r_priv_on]["crew_name"] is None
    fm = {i["run_id"]: i for i in api("GET", "/feed/activities", tok_m).json()
          if str(i.get("title", "")).startswith(f"ug-{TS}")}
    assert fm[r_pub_off]["crew_name"] == f"ug-pub-{TS}", "크루원 tier — OFF여도 표시"
    assert fm[r_priv_on]["crew_name"] == f"ug-priv-{TS}", "크루원 tier — 비공개도 표시"
    ok("타인 옵트인만 ✓ 크루원은 OFF·비공개도 실명(전 표면 통일) ✓")


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
