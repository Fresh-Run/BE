"""
Integration test: 팔로우 승인제 v2 (docs/PRIVATE_PROFILE_DESIGN.md §2)

승인제 OFF(즉시 204)/ON(202 요청) × 승인/거절/취소/재신청 + pending 중복 레이스
(PK TOCTOU) + 기존 팔로워 무영향 + 승인 후 가시성 게이트 통과(v1 합성) +
알림(follow_requested/approved) assert.

Run: python tests/test_follow_approval_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import asyncio
import os, sys, time
from datetime import datetime, timedelta, timezone
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


def notif_types(c, token):
    return [n["type"] for n in api(c, "GET", "/notifications", token).json()]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. O(대상)·A·B·E(기존 팔로워) 준비")
        for k in ("o", "a", "b", "e"):
            uids[k] = sb_user(c, f"fa-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"fa-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"FA{k}{TS}"}).status_code == 200
        # E는 승인제 켜기 전에 팔로우(기존 팔로워)
        assert api(c, "POST", f"/users/{uids['o']}/follow", tk["e"]).status_code == 204
        # O 러닝 (followers 공개 — 승인된 팔로워만 봄)
        run = api(c, "POST", "/runs", tk["o"], json={
            "distance_km": 2.0, "duration_sec": 720, "visibility": "followers",
            "ran_at": datetime.now(timezone.utc).isoformat()}).json()["id"]
        ok("유저 4명 + E 선팔로우 + O followers run")

        step("1. 승인제 OFF일 때 — 즉시 204 (현행)")
        assert api(c, "POST", f"/users/{uids['o']}/follow", tk["a"]).status_code == 204
        api(c, "DELETE", f"/users/{uids['o']}/follow", tk["a"])  # 원복
        ok("승인제 OFF: 즉시 팔로우 204")

        step("2. 요청제(비공개) ON — A 팔로우 시 202 + pending + O에게 알림")
        # 승인제 통합(Part B): 요청제 진입 = visibility='private'(구 follow_approval 토글 제거).
        assert api(c, "PATCH", "/me/profile", tk["o"],
                   json={"nickname": f"FAo{TS}", "visibility": "private"}).status_code == 200
        assert api(c, "GET", "/me/profile", tk["o"]).json()["visibility"] == "private"
        r = api(c, "POST", f"/users/{uids['o']}/follow", tk["a"])
        assert r.status_code == 202, f"승인제 팔로우 202, got {r.status_code}"
        # 아직 팔로워 아님 (follows 없음)
        pa = api(c, "GET", f"/users/{uids['o']}/profile", tk["a"]).json()
        assert pa["is_following"] is False, "승인 전엔 미팔로우"
        # O 요청 목록에 A
        reqs = api(c, "GET", "/me/follow-requests", tk["o"]).json()
        assert any(x["user_id"] == uids["a"] for x in reqs), reqs
        assert "follow_requested" in notif_types(c, tk["o"]), "follow_requested 알림"
        # 재요청 409 (멱등이나 명시)
        assert api(c, "POST", f"/users/{uids['o']}/follow", tk["a"]).status_code == 409
        ok("202 · pending 목록 · follow_requested 알림 · 재요청 409")

        step("3. 승인 — follows 생성 + A에게 approved 알림 + 가시성 통과")
        assert api(c, "PATCH", f"/me/follow-requests/{uids['a']}", tk["o"],
                   json={"approve": True}).status_code == 204
        assert api(c, "GET", f"/users/{uids['o']}/profile", tk["a"]).json()["is_following"] is True
        # 승인 후 A는 O의 followers run 볼 수 있음 (v1 게이트 합성 확인)
        assert api(c, "GET", f"/runs/{run}", tk["a"]).status_code == 200, "승인 후 followers run 접근"
        assert "follow_request_approved" in notif_types(c, tk["a"])
        # 요청 목록에서 사라짐
        assert not any(x["user_id"] == uids["a"] for x in api(c, "GET", "/me/follow-requests", tk["o"]).json())
        # 처리된 요청 재승인 404
        assert api(c, "PATCH", f"/me/follow-requests/{uids['a']}", tk["o"],
                   json={"approve": True}).status_code == 404
        ok("승인 204 · is_following · followers run 200 · approved 알림 · 재승인 404")

        step("4. 거절 + 재신청 (rejected→pending 부활)")
        assert api(c, "POST", f"/users/{uids['o']}/follow", tk["b"]).status_code == 202
        assert api(c, "PATCH", f"/me/follow-requests/{uids['b']}", tk["o"],
                   json={"approve": False}).status_code == 204
        assert api(c, "GET", f"/users/{uids['o']}/profile", tk["b"]).json()["is_following"] is False
        # 재신청 → 다시 202 (rejected 부활)
        assert api(c, "POST", f"/users/{uids['o']}/follow", tk["b"]).status_code == 202
        assert any(x["user_id"] == uids["b"] for x in api(c, "GET", "/me/follow-requests", tk["o"]).json())
        ok("거절 204·미팔로우 · 재신청 202 부활")

        step("5. 요청 취소 (본인)")
        assert api(c, "DELETE", f"/users/{uids['o']}/follow-request", tk["b"]).status_code == 204
        assert not any(x["user_id"] == uids["b"] for x in api(c, "GET", "/me/follow-requests", tk["o"]).json())
        assert api(c, "DELETE", f"/users/{uids['o']}/follow-request", tk["b"]).status_code == 204  # 멱등
        ok("취소 204 · 목록 제거 · 멱등")

        step("6. pending 중복 레이스 (PK TOCTOU) — 동시 5요청, 결과 1 pending")
        api(c, "DELETE", f"/users/{uids['o']}/follow-request", tk["b"])  # clean
        async def burst():
            async with httpx.AsyncClient(timeout=30) as ac:
                async def one():
                    return await ac.post(f"{BASE}/users/{uids['o']}/follow",
                                         headers={"Authorization": f"Bearer {tk['b']}"})
                return await asyncio.gather(*[one() for _ in range(5)], return_exceptions=True)
        results = asyncio.run(burst())
        codes = [r.status_code for r in results if not isinstance(r, Exception)]
        assert codes.count(202) == 1 and all(cc in (202, 409) for cc in codes), \
            f"동시 5요청 → 202 정확히 1, 나머지 409: {codes}"
        rows = api(c, "GET", "/me/follow-requests", tk["o"]).json()
        assert len([x for x in rows if x["user_id"] == uids["b"]]) == 1, "pending 1행만"
        ok(f"동시 5 → 202×1·409×{codes.count(409)} · pending 1행 (TOCTOU 봉쇄)")

        step("7. 기존 팔로워 E 무영향")
        assert api(c, "GET", f"/users/{uids['o']}/profile", tk["e"]).json()["is_following"] is True
        assert api(c, "GET", f"/runs/{run}", tk["e"]).status_code == 200, "기존 팔로워는 계속 접근"
        ok("승인제 켜도 기존 팔로워 관계·접근 불변 (소급 무영향)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (follow_requests cascade)")


if __name__ == "__main__":
    run_tests()
