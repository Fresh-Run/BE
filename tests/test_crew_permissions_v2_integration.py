"""
Integration test: 크루 세부 권한 v2 (docs/CREW_PERMISSIONS_V2_DESIGN.md)

권한 5키 × owner/admin(보유·미보유)/member 매트릭스 + 승격 기본값 + 위임 사슬
§3 제한 + admin_count + permissions 응답 노출 + 하위호환(role 유지).

Run: python tests/test_crew_permissions_v2_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timezone, timedelta
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
DEFAULT = {"announcements": True, "challenges": True, "edit_crew": False,
           "kick_members": False, "manage_admins": False}


def ok(m):        print(f"  ✓ {m}")
def step(t):      print(f"\n[{t}]")


def sb_user(c, email):
    return c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                  json={"email": email, "password": "test1234", "email_confirm": True}).json()["id"]


def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. ow(owner)·a1·a2(admin)·m(member)·kt(kick 대상)")
        for k in ("ow", "a1", "a2", "m", "kt"):
            uids[k] = sb_user(c, f"cpv2-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"cpv2-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CPV2{k}{TS}"}).status_code == 200
        crew = api(c, "POST", "/crews", tk["ow"], json={"name": f"CPV2크루{TS}"}).json()["id"]
        for k in ("a1", "a2", "m", "kt"):
            assert api(c, "POST", f"/crews/{crew}/join", tk[k]).status_code == 200
        ann_body = {"title": f"공지{TS}", "body": "x"}
        now = datetime.now(timezone.utc)
        ch_body = {"title": f"챌{TS}", "goal_km": 50, "starts_at": (now - timedelta(hours=1)).isoformat(),
                   "ends_at": (now + timedelta(days=3)).isoformat()}

        def perms_of(uid):
            mem = api(c, "GET", f"/crews/{crew}/members", tk["ow"]).json()
            return next((x["permissions"] for x in mem if x["user_id"] == uid), "MISSING")

        step("1. 승격 기본값 — ow가 a1·a2 admin 승격 → 시안 기본 permissions")
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a1']}/role", tk["ow"], json={"role": "admin"}).status_code == 200
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a2']}/role", tk["ow"], json={"role": "admin"}).status_code == 200
        assert perms_of(uids["a1"]) == DEFAULT, f"승격 기본값, got {perms_of(uids['a1'])}"
        ok("admin 승격 시 시안 기본(announcements·challenges ON, 나머지 OFF)")

        step("2. permissions 응답 노출 — owner 전권 합성·admin obj·member null")
        mem = {x["user_id"]: x for x in api(c, "GET", f"/crews/{crew}/members", tk["ow"]).json()}
        assert mem[uids["ow"]]["permissions"] == {k: True for k in DEFAULT}, "owner 전권 합성"
        assert mem[uids["a1"]]["permissions"] == DEFAULT, "admin 부여값"
        assert mem[uids["m"]]["permissions"] is None, "member null"
        # 대상이 admin 아님(member m) → permissions 설정 422
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['m']}/permissions", tk["ow"], json={"announcements": True}).status_code == 422, "member 대상 permissions 422"
        ok("owner all-true·admin obj·member null·member 대상 422")

        step("3. 게이트 매트릭스 — 보유 통과 / 미보유 403 / member 403")
        # announcements: a1 기본 ON → 201, 회수 후 403
        assert api(c, "POST", f"/crews/{crew}/announcements", tk["a1"], json=ann_body).status_code == 201
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a1']}/permissions", tk["ow"], json={"announcements": False}).status_code == 200
        assert api(c, "POST", f"/crews/{crew}/announcements", tk["a1"], json=ann_body).status_code == 403, "회수 후 공지 403"
        # member는 항상 403
        assert api(c, "POST", f"/crews/{crew}/announcements", tk["m"], json=ann_body).status_code == 403, "member 공지 403"
        # challenges: a1 기본 ON → 201
        assert api(c, "POST", f"/crews/{crew}/challenges", tk["a1"], json=ch_body).status_code in (200, 201)
        # edit_crew: a1 기본 OFF → update_crew·이미지 403 → 부여 후 200
        assert api(c, "PATCH", f"/crews/{crew}", tk["a1"], json={"description": "z"}).status_code == 403, "edit_crew 미보유 403"
        assert api(c, "POST", f"/crews/{crew}/cover/upload-url", tk["a1"]).status_code == 403, "이미지도 edit_crew 403"
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a1']}/permissions", tk["ow"], json={"edit_crew": True}).status_code == 200
        assert api(c, "PATCH", f"/crews/{crew}", tk["a1"], json={"description": "z"}).status_code == 200, "부여 후 update 200"
        assert api(c, "POST", f"/crews/{crew}/cover/upload-url", tk["a1"]).status_code == 200
        # kick_members: a1 기본 OFF → kt kick 403 → 부여 후 200
        assert api(c, "DELETE", f"/crews/{crew}/members/{uids['kt']}", tk["a1"]).status_code == 403, "kick 미보유 403"
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a1']}/permissions", tk["ow"], json={"kick_members": True}).status_code == 200
        assert api(c, "DELETE", f"/crews/{crew}/members/{uids['kt']}", tk["a1"]).status_code == 204, "부여 후 kick 204"
        ok("announcements·challenges·edit_crew·kick 게이트 보유/미보유/member 정확")

        step("4. manage_admins 게이트 — a2(미보유) role 변경 403")
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['m']}/role", tk["a2"], json={"role": "admin"}).status_code == 403, "manage_admins 미보유 role변경 403"
        ok("manage_admins 미보유 admin은 role 변경 403")

        step("5. 위임 사슬 §3 — a2에 manage_admins 부여 후 제한 검증")
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a2']}/permissions", tk["ow"], json={"manage_admins": True}).status_code == 200
        # a2는 announcements 보유(기본) → a1에 부여 가능
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a1']}/permissions", tk["a2"], json={"announcements": True}).status_code == 200, "자기 보유 키 grant 200"
        # a2는 edit_crew 미보유 → a1에 edit_crew 부여 불가 403
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a1']}/permissions", tk["a2"], json={"edit_crew": True}).status_code == 403, "미보유 키 grant 403"
        # a2는 주의 2키(kick_members) 부여 불가(owner만) 403
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a1']}/permissions", tk["a2"], json={"kick_members": True}).status_code == 403, "주의 키 grant 403"
        # a2 자기 manage_admins 회수 불가(owner만) 403
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a2']}/permissions", tk["a2"], json={"manage_admins": False}).status_code == 403, "셀프 manage_admins 회수 403"
        # a2는 role 변경 가능(manage_admins 보유) — m 승격
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['m']}/role", tk["a2"], json={"role": "admin"}).status_code == 200, "manage_admins admin의 승격 200"
        # owner 대상은 불변 422
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['ow']}/permissions", tk["a2"], json={"announcements": False}).status_code == 422, "owner permissions 불변 422"
        ok("§3: 자기보유만·주의키 owner만·셀프회수 불가·승격 가능·owner 불변")

        step("6. 대상이 admin 아님 → 422 / admin_count")
        # kt는 kick됨 → 남은 member 없음. m은 방금 admin됨. 새 member로 검증은 생략,
        # 대신 owner를 permissions 대상으로(422는 위에서 RoleTargetIsOwner). member 대상은
        # 새 유저 필요 → 여기선 admin_count만.
        detail = api(c, "GET", f"/crews/{crew}", tk["ow"]).json()
        # admin: a1, a2, m (승격됨) = 3
        assert detail["admin_count"] == 3, f"admin_count=3 기대(a1·a2·m), got {detail['admin_count']}"
        # 하위호환: role 필드 유지
        assert all("role" in x for x in api(c, "GET", f"/crews/{crew}/members", tk["ow"]).json()), "role 필드 유지"
        ok("admin_count=3·role 필드 유지(하위호환)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
