"""
Integration test: crew invite codes
(GET/POST /crews/{id}/invite, GET /crews/preview-by-code, POST /crews/join-by-code)
Run: python tests/test_invite_codes_integration.py
주의: 코드 값은 화면에 출력하지 않는다 (assert만).
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"
_ALPHABET = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")

def _keys() -> tuple[str, str]:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):             anon = line.split("=",1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=",1)[1]
    return anon, svc

_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}

def ok(m):   print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")

def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200,201): fail("create user", r.text[:200])
    return r.json()["id"]

def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type":"application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]

def sb_del_user(c, uid): c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)

def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer":"return=minimal"},
             params={col: f"in.({',' .join(vals)})"})

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"iv-u{i}-{ts}@t.l" for i in range(1,4)]
    uids: list[str] = []
    toks: list[str] = []
    crew_ids: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 셋업: 비공개+승인제 크루 (초대만이 입구) ───────────────
            step("1. 유저 3명 + 비공개·승인제 크루 A")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2, uid3 = uids; tok1, tok2, tok3 = toks
            for i, tok in enumerate(toks, start=1):
                assert api(c, "PATCH", "/me/profile", tok,
                           json={"nickname": f"초대u{i}-{ts%100000}"}).status_code == 200
            r = api(c, "POST", "/crews", tok1, json={
                "name": f"초대전용크루-{ts}", "is_public": False, "join_policy": "approval"})
            crew_a = r.json()["id"]; crew_ids.append(crew_a)
            ok("crew A (비공개+승인제)")

            # ── 2. 코드 생성/조회 + 형식 + 권한 ───────────────────────────
            step("2. GET 404 → POST 생성 → GET 동일 / 형식 / 비크루장 403")
            assert api(c, "GET", f"/crews/{crew_a}/invite", tok1).status_code == 404, \
                "미발급 상태 GET → 404"
            r = api(c, "POST", f"/crews/{crew_a}/invite", tok1)
            assert r.status_code == 201, r.text[:200]
            code1 = r.json()["code"]
            assert len(code1) == 8 and set(code1) <= _ALPHABET, "8자·32문자셋 위반"
            r = api(c, "GET", f"/crews/{crew_a}/invite", tok1)
            assert r.status_code == 200 and r.json()["code"] == code1
            assert api(c, "GET", f"/crews/{crew_a}/invite", tok2).status_code == 403
            assert api(c, "POST", f"/crews/{crew_a}/invite", tok2).status_code == 403
            ok("404→201→200 흐름 ✓ 형식(8자·허용문자) ✓ 비크루장 403 ✓")

            # ── 3. 미리보기 (비공개 크루 포함) ────────────────────────────
            step("3. preview-by-code: 비공개 크루 조회 + 잘못된 코드 404")
            r = api(c, "GET", "/crews/preview-by-code", tok2, params={"code": code1.lower()})
            assert r.status_code == 200, r.text[:200]
            p = r.json()
            assert p["id"] == crew_a and p["name"] == f"초대전용크루-{ts}"
            assert p["member_count"] == 1 and p["join_policy"] == "approval"
            assert "invite_code" not in p, "응답에 코드 자체가 노출되면 안 됨"
            r = api(c, "GET", "/crews/preview-by-code", tok2, params={"code": "ZZZZZZZZ"})
            assert r.status_code == 404
            ok("비공개 크루 미리보기 ✓ 소문자 정규화 ✓ 잘못된 코드 404 ✓ 코드 미노출 ✓")

            # ── 4. 코드 가입: 비공개+승인제 즉시 가입 ─────────────────────
            step("4. join-by-code: 즉시 가입 + 알림 + 409 / 일반 join은 여전히 403")
            r = api(c, "POST", "/crews/join-by-code", tok2,
                    json={"code": f"  {code1.lower()} "})   # 소문자+공백 정규화
            assert r.status_code == 200, r.text[:200]
            body = r.json()
            assert body["id"] == crew_a and body["member_count"] == 2, "CrewResponse 반환"
            ns = [n for n in api(c, "GET", "/notifications", tok1).json()
                  if n["type"] == "crew_joined" and n["actor_id"] == uid2]
            assert len(ns) == 1, "크루장에게 crew_joined 알림 1건"
            r = api(c, "POST", "/crews/join-by-code", tok2, json={"code": code1})
            assert r.status_code == 409, "이미 멤버 → 409"
            r = api(c, "POST", f"/crews/{crew_a}/join", tok3)
            assert r.status_code == 403, "비공개 크루 일반 join은 여전히 403"
            r = api(c, "POST", "/crews/join-by-code", tok3, json={"code": "AAAAAAAA"})
            assert r.status_code == 404, "잘못된 코드 404 (단일 응답)"
            ok("즉시 가입 200+CrewResponse ✓ 정규화 ✓ 알림 ✓ 이미멤버 409 ✓ 일반 join 403 유지 ✓")

            # ── 5. pending 자동 정리 ──────────────────────────────────────
            step("5. 승인제 pending 보유자가 코드 가입 → 신청 자동 정리")
            r = api(c, "POST", "/crews", tok1, json={
                "name": f"공개승인크루-{ts}", "join_policy": "approval"})
            crew_b = r.json()["id"]; crew_ids.append(crew_b)
            assert api(c, "POST", f"/crews/{crew_b}/join", tok3).status_code == 202  # pending
            code_b = api(c, "POST", f"/crews/{crew_b}/invite", tok1).json()["code"]
            assert api(c, "POST", "/crews/join-by-code", tok3,
                       json={"code": code_b}).status_code == 200
            pend = api(c, "GET", f"/crews/{crew_b}/join-requests", tok1).json()
            assert all(i["user_id"] != uid3 for i in pend), "pending 자동 삭제"
            assert api(c, "GET", f"/crews/{crew_b}/join-requests/me", tok3).status_code == 404
            ok("코드 가입 후 pending 정리 ✓")

            # ── 6. 정원 초과 ──────────────────────────────────────────────
            step("6. 정원 1명 크루 → 코드 가입 409 CrewFull")
            r = api(c, "POST", "/crews", tok1, json={"name": f"풀크루초대-{ts}", "max_members": 1})
            crew_c = r.json()["id"]; crew_ids.append(crew_c)
            code_c = api(c, "POST", f"/crews/{crew_c}/invite", tok1).json()["code"]
            r = api(c, "POST", "/crews/join-by-code", tok2, json={"code": code_c})
            assert r.status_code == 409 and "full" in r.text.lower()
            ok("정원 초과 409 ✓")

            # ── 7. 재생성 → 이전 코드 무효 ────────────────────────────────
            step("7. 재생성: 새 코드 발급 + 이전 코드 즉시 404")
            r = api(c, "POST", f"/crews/{crew_a}/invite", tok1)
            code2 = r.json()["code"]
            assert code2 != code1, "재생성은 항상 새 코드"
            r = api(c, "POST", "/crews/join-by-code", tok3, json={"code": code1})
            assert r.status_code == 404, "이전 코드는 무효 (404)"
            r = api(c, "GET", "/crews/preview-by-code", tok3, params={"code": code2})
            assert r.status_code == 200, "새 코드는 유효"
            r = api(c, "POST", "/crews/join-by-code", tok3, json={"code": code2})
            assert r.status_code == 200, "새 코드로 가입 성공"
            ok("재생성 ✓ 이전 코드 무효 ✓ 새 코드 유효 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "crews", "id", crew_ids)
            sb_del_in(c, "notifications", "user_id", [u for u in uids if u])
            sb_del_in(c, "notifications", "actor_id", [u for u in uids if u])
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("crews·notifications·profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
