"""
Integration test: PATCH /me/profile 부분 갱신 시맨틱 (nickname Optional化)

프론트 리포트 원인 2 수정: visibility/follow_approval 단독 PATCH가 nickname
필수 때문에 422로 튕겨 저장 실패하던 문제. nickname 생략=유지, 최초 생성만
필수(생성 분기), 명시 null·"" 거부.

검증:
- visibility 단독 PATCH 200 + DB 저장 확인
- follow_approval 단독 PATCH 200 + DB 저장 확인
- nickname 생략 시 기존값 유지(덮어쓰기 안 됨)
- 신규 유저 nickname 없이 PATCH → 422 (생성 분기)
- nickname 명시 null → 422 / "" → 422
- 하위호환: nickname 동봉 PATCH 무영향(기존 클라)

Run: python tests/test_profile_partial_patch_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
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
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
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


def db_profile(c, uid, cols="visibility,follow_approval,nickname"):
    r = c.get(f"{_SB}/rest/v1/profiles", headers=_ADM,
              params={"user_id": f"eq.{uid}", "select": cols})
    return r.json()[0] if r.json() else None


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. 유저 2명 (A=기존 프로필 보유, B=프로필 미생성)")
        for k in ("a", "b"):
            uids[k] = sb_user(c, f"ppatch-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"ppatch-{k}-{TS}@test.com") for k in uids}
        nick_a = f"PPA{TS}"
        r = api(c, "PATCH", "/me/profile", tk["a"], json={"nickname": nick_a})
        assert r.status_code == 200, r.text[:200]
        ok("A 프로필 생성(nickname), B는 미생성 상태 유지")

        step("1. 신규 유저 B — nickname 없이 PATCH → 422 (생성 분기)")
        r = api(c, "PATCH", "/me/profile", tk["b"], json={"visibility": "private"})
        assert r.status_code == 422, f"신규 nickname 없이 → 422 기대, got {r.status_code}"
        assert db_profile(c, uids["b"]) is None, "B 프로필 여전히 미생성(저장 안 됨)"
        ok("신규 유저 nickname 생략 → 422 + 프로필 미생성")

        step("2. A — visibility 단독 PATCH (nickname 생략) → 200 + 저장")
        r = api(c, "PATCH", "/me/profile", tk["a"], json={"visibility": "private"})
        assert r.status_code == 200, f"visibility 단독 200 기대, got {r.status_code}: {r.text[:200]}"
        assert r.json()["visibility"] == "private"
        p = db_profile(c, uids["a"])
        assert p["visibility"] == "private", f"DB 저장 확인, got {p}"
        assert p["nickname"] == nick_a, f"nickname 유지(덮어쓰기 없음), got {p['nickname']!r}"
        ok("visibility 단독 200 + DB private + nickname 보존")

        step("3. A — follow_approval 단독 PATCH → 200 + 저장")
        r = api(c, "PATCH", "/me/profile", tk["a"], json={"follow_approval": True})
        assert r.status_code == 200, r.text[:200]
        assert r.json()["follow_approval"] is True
        p = db_profile(c, uids["a"])
        assert p["follow_approval"] is True and p["nickname"] == nick_a and p["visibility"] == "private", \
            f"follow_approval 저장 + 다른 필드 보존, got {p}"
        ok("follow_approval 단독 200 + DB 저장 + visibility·nickname 보존")

        step("4. nickname 명시 null → 422 / \"\" → 422")
        r = api(c, "PATCH", "/me/profile", tk["a"], json={"nickname": None})
        assert r.status_code == 422, f"명시 null → 422 기대, got {r.status_code}"
        r = api(c, "PATCH", "/me/profile", tk["a"], json={"nickname": ""})
        assert r.status_code == 422, f"빈 문자열 → 422 기대(min_length), got {r.status_code}"
        r = api(c, "PATCH", "/me/profile", tk["a"], json={"nickname": "x"})  # 1자
        assert r.status_code == 422, f"1자 → 422 기대(min_length), got {r.status_code}"
        assert db_profile(c, uids["a"])["nickname"] == nick_a, "거부되어 nickname 불변"
        ok("명시 null·빈문자열·1자 전부 422 + nickname 불변")

        step("5. 하위호환 — nickname 동봉 PATCH(기존 클라) 무영향")
        new_nick = f"PPA2{TS}"
        r = api(c, "PATCH", "/me/profile", tk["a"], json={"nickname": new_nick, "visibility": "public"})
        assert r.status_code == 200, r.text[:200]
        p = db_profile(c, uids["a"])
        assert p["nickname"] == new_nick and p["visibility"] == "public", f"동봉 정상 갱신, got {p}"
        ok("nickname+visibility 동봉 → 정상 갱신(기존 클라 계약 불변)")

        step("6. 신규 유저 B — nickname 포함 최초 생성 → 200")
        r = api(c, "PATCH", "/me/profile", tk["b"], json={"nickname": f"PPB{TS}", "visibility": "private"})
        assert r.status_code == 200, r.text[:200]
        p = db_profile(c, uids["b"])
        assert p["nickname"] == f"PPB{TS}" and p["visibility"] == "private", f"생성 성공, got {p}"
        ok("신규 유저 nickname 포함 생성 → 200 (생성 분기 정상)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
