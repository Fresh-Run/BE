"""
Integration test: item2 — 크루 커버·아이콘 이미지 (db/2026-07-13_crew_images.sql 선행)

업로드 URL 발급(운영진만) + cover_url/icon_url 저장·서빙 + 명시 null 삭제 +
"" 422 + 비운영진 403 + 없는 크루 404 + admin 승격 후 업로드 + 크루 삭제 정리.

⚠️ crews.cover_url/icon_url 컬럼 + crew-images 버킷 선행 필요.
Run: python tests/test_crew_images_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys():
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):              anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}
TS = int(time.time())


def ok(m):        print(f"  ✓ {m}")
def step(t):      print(f"\n[{t}]")


def sb_user(c, email):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": "test1234", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]


def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


def db_crew(c, crew_id, cols="cover_url,icon_url"):
    return c.get(f"{_SB}/rest/v1/crews", headers=_ADM,
                 params={"id": f"eq.{crew_id}", "select": cols}).json()[0]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. 크루장 A + 멤버 B + 크루")
        for k in ("a", "b"):
            uids[k] = sb_user(c, f"cimg-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"cimg-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CIMG{k}{TS}"}).status_code == 200
        crew = api(c, "POST", "/crews", tk["a"], json={"name": f"CIMG크루{TS}"}).json()["id"]
        assert api(c, "POST", f"/crews/{crew}/join", tk["b"]).status_code == 200
        ok("크루 생성 + B 가입")

        step("1. 커버 업로드 URL — 운영진(owner) 200, 필드 확인")
        r = api(c, "POST", f"/crews/{crew}/cover/upload-url", tk["a"])
        assert r.status_code == 200, f"owner 200 기대, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body["upload_url"] and body["public_url"], f"URL 필드, got {body}"
        assert body["max_bytes"] == 5 * 1024 * 1024 and "image/jpeg" in body["allowed_types"]
        assert f"crew-images/{crew}/cover" in body["public_url"], f"고정 경로, got {body['public_url']}"
        cover_url = body["public_url"]
        ok("커버 업로드 URL 발급 + public_url 고정경로")

        step("2. 비운영진(member B) 403 / 없는 크루 404")
        assert api(c, "POST", f"/crews/{crew}/cover/upload-url", tk["b"]).status_code == 403
        import uuid
        assert api(c, "POST", f"/crews/{uuid.uuid4()}/cover/upload-url", tk["a"]).status_code == 404
        ok("member 403·없는 크루 404")

        step("3. cover_url/icon_url 저장(PATCH) + 서빙 + DB")
        icon_url = api(c, "POST", f"/crews/{crew}/icon/upload-url", tk["a"]).json()["public_url"]
        r = api(c, "PATCH", f"/crews/{crew}", tk["a"], json={"cover_url": cover_url, "icon_url": icon_url})
        assert r.status_code == 200, f"저장 200 기대, got {r.status_code}: {r.text[:200]}"
        assert r.json()["cover_url"] == cover_url and r.json()["icon_url"] == icon_url, "응답 서빙"
        db = db_crew(c, crew)
        assert db["cover_url"] == cover_url and db["icon_url"] == icon_url, f"DB 저장, got {db}"
        # 둘러보기 상세에도 노출
        got = api(c, "GET", f"/crews/{crew}", tk["b"]).json()
        assert got["cover_url"] == cover_url and got["icon_url"] == icon_url, "상세 헤더 additive 노출"
        ok("cover/icon 저장·응답·DB·상세 노출")

        step("4. 명시 null=삭제(DB null) / \"\"=422")
        r = api(c, "PATCH", f"/crews/{crew}", tk["a"], json={"cover_url": None})
        assert r.status_code == 200, r.text[:200]
        db = db_crew(c, crew)
        assert db["cover_url"] is None, f"cover 삭제 → null, got {db['cover_url']}"
        assert db["icon_url"] == icon_url, "icon은 유지(부분 갱신)"
        r = api(c, "PATCH", f"/crews/{crew}", tk["a"], json={"cover_url": ""})
        assert r.status_code == 422, f'"" → 422 기대, got {r.status_code}'
        ok("명시 null 삭제(icon 보존)·빈문자열 422")

        step("5. admin 승격 + edit_crew 부여 후 B도 업로드 가능 (v2: 이미지=edit_crew)")
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['b']}/role", tk["a"],
                   json={"role": "admin"}).status_code == 200
        # v2: 신규 admin은 edit_crew 기본 OFF → 이미지 403, 부여 후 200
        assert api(c, "POST", f"/crews/{crew}/cover/upload-url", tk["b"]).status_code == 403, "edit_crew 미보유 403"
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['b']}/permissions", tk["a"],
                   json={"edit_crew": True}).status_code == 200
        assert api(c, "POST", f"/crews/{crew}/cover/upload-url", tk["b"]).status_code == 200
        ok("admin 승격+edit_crew 부여 후 커버 업로드 200 (미보유 시 403)")

        step("6. 크루 삭제 — 정상 완료(이미지 정리 best-effort)")
        assert api(c, "DELETE", f"/crews/{crew}", tk["a"]).status_code == 204
        assert api(c, "GET", f"/crews/{crew}", tk["a"]).status_code == 404, "크루 삭제됨"
        ok("크루 삭제 + 이미지 정리(예외 없이 완료)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
