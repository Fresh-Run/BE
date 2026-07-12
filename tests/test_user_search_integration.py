"""
Integration test: 유저 검색 GET /users/search (통합 검색 화면 백엔드)

부분 일치·대소문자 무관 / 차단 상호 제외 / 잠금 계정 포함+bio null / 본인 제외 /
q 최소 2자 422 / limit 캡. 승인제 계정 정상 노출.

Run: python tests/test_user_search_integration.py  (로컬 서버 필요)
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
TS = int(time.time()) % 100000  # 닉네임 길이 여유(≤20)


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
        TOK = f"U{TS}"   # 공통 검색 토큰 (닉네임 접두)
        step("0. V(검색자)·A·B·C(비공개)·D(공개+bio) — 닉네임 공통 접두")
        nick = {"v": f"{TOK}v", "a": f"{TOK}a", "b": f"{TOK}b", "c": f"{TOK}c", "d": f"{TOK}d"}
        emails = {k: f"usrch-{k}-{TS}@test.com" for k in nick}
        for k in nick:
            uids[k] = sb_user(c, emails[k])
        tk = {k: sb_login(c, emails[k]) for k in nick}
        for k in nick:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": nick[k]}).status_code == 200
        # C 비공개, D 공개+bio, C도 bio 설정(잠금이라 검색엔 null 나와야)
        assert api(c, "PATCH", "/me/profile", tk["c"], json={"visibility": "private", "bio": "C비밀소개"}).status_code == 200
        assert api(c, "PATCH", "/me/profile", tk["d"], json={"bio": "D공개소개"}).status_code == 200
        ok("V·A·B·C(비공개)·D(공개) 준비")

        def search(token, q, limit=20):
            r = api(c, "GET", f"/users/search?q={q}&limit={limit}", token)
            return r

        step("1. 부분 일치 + 대소문자 무관 + 본인 제외")
        r = search(tk["v"], TOK.lower())   # 소문자로 검색(닉네임은 대문자 U)
        assert r.status_code == 200, r.text[:200]
        found = {i["user_id"] for i in r.json()}
        assert uids["a"] in found and uids["b"] in found and uids["d"] in found, "부분+대소문자 매치"
        assert uids["v"] not in found, "본인(V) 제외"
        ok("부분 일치·대소문자 무관·본인 제외")

        step("2. 잠금(비공개) 계정 — 결과 포함 + bio null / 공개는 bio 노출")
        items = {i["user_id"]: i for i in search(tk["v"], TOK).json()}
        assert uids["c"] in items, "비공개 계정도 검색 결과에 포함(친구 찾기)"
        assert items[uids["c"]]["bio"] is None, f"잠금 계정 bio=null, got {items[uids['c']]['bio']!r}"
        assert items[uids["c"]]["nickname"] == nick["c"], "잠금이어도 닉네임 노출"
        assert items[uids["d"]]["bio"] == "D공개소개", "공개 계정 bio 노출"
        ok("비공개 계정 포함·bio null·닉네임 노출 / 공개 bio 노출")

        step("3. 차단 상호 제외")
        assert api(c, "POST", f"/users/{uids['b']}/block", tk["a"]).status_code == 204  # A가 B 차단
        a_found = {i["user_id"] for i in search(tk["a"], TOK).json()}
        assert uids["b"] not in a_found, "A 검색에서 차단한 B 제외"
        b_found = {i["user_id"] for i in search(tk["b"], TOK).json()}
        assert uids["a"] not in b_found, "B 검색에서 A(차단자) 제외(양방향)"
        assert uids["d"] in a_found, "차단 무관 D는 여전히 노출"
        ok("차단 상호 제외(양방향)·비차단 정상")

        step("4. q 최소 길이 422 / limit 캡")
        assert search(tk["v"], "a").status_code == 422, "1자 → 422"
        assert len(search(tk["v"], TOK, limit=1).json()) <= 1, "limit=1 캡(≤1건)"
        assert search(tk["v"], TOK, limit=50).status_code == 200, "limit=50 허용"
        assert search(tk["v"], TOK, limit=51).status_code == 422, "limit>50 → 422"
        ok("q<2자 422·limit=1 캡·limit 상한(50)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
