"""
Integration test: 승인받았던 비공개 계정 재팔로우 스턱 수정 (2026-07-14 버그픽스)

버그: decide 승인이 follow_requests를 approved UPDATE로 남기는데 revive 분기가
rejected만 커버 → 승인→언팔 후 재팔로우가 409 follow_request_pending 영구 스턱.
수정: revive 필터를 rejected+approved로 확장(잔존 approved 행 자가 치유).

케이스:
 1. 승인→언팔→재팔 → 202 (스턱 해소 핵심) + fr 행 pending 부활
 2. 재승인 풀사이클: 승인 → follows 재생성 + approved 알림
 3. 승인→remove follower→재팔 → 202 (팔로워제거 조합)
 4. 거절→재요청 202 (기존 rejected revive 회귀)
 5. 레이스: approved 잔존 상태에서 동시 재팔 2발 → 202×1·409×1 + pending 1행
 6. cancel 시맨틱 회귀: 승인+팔로우중 상태에서 cancel → no-op(approved 행 보존)

Run: python tests/test_follow_reapproval_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import asyncio
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


def ok(m):         print(f"  ✓ {m}")
def fail(m, d=""):  print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):       print(f"\n[{t}]")


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


def fr_status(c, req, tgt):
    rows = c.get(f"{_SB}/rest/v1/follow_requests", headers=_ADM,
                 params={"requester_id": f"eq.{req}", "target_id": f"eq.{tgt}",
                         "select": "status"}).json()
    return [r["status"] for r in rows]


def follows(c, a, b):
    return bool(c.get(f"{_SB}/rest/v1/follows", headers=_ADM,
                      params={"follower_id": f"eq.{a}", "following_id": f"eq.{b}",
                              "select": "follower_id"}).json())


def notif_types(c, token):
    return [n["type"] for n in api(c, "GET", "/notifications", token).json()]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. A(비공개)·B·D(팔로워제거 페어)·R(거절 페어) 준비")
        for k in ("a", "b", "d", "rr"):
            uids[k] = sb_user(c, f"fra-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"fra-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"FRA{k}{TS}"}).status_code == 200
        assert api(c, "PATCH", "/me/profile", tk["a"], json={"visibility": "private"}).status_code == 200
        A, B, D, R = uids["a"], uids["b"], uids["d"], uids["rr"]
        ok("유저 4명 (A=비공개)")

        step("1. 스턱 해소 핵심 — 승인→언팔→재팔 202")
        assert api(c, "POST", f"/users/{A}/follow", tk["b"]).status_code == 202
        assert api(c, "PATCH", f"/me/follow-requests/{B}", tk["a"], json={"approve": True}).status_code == 204
        assert follows(c, B, A), "승인 후 follows"
        assert api(c, "DELETE", f"/users/{A}/follow", tk["b"]).status_code == 204  # 언팔
        assert not follows(c, B, A)
        assert fr_status(c, B, A) == ["approved"], "approved 행 잔존(전제)"
        r = api(c, "POST", f"/users/{A}/follow", tk["b"])
        assert r.status_code == 202, f"재팔로우 202 기대(스턱 해소), got {r.status_code}: {r.text[:120]}"
        assert fr_status(c, B, A) == ["pending"], "approved → pending 부활"
        ok("승인→언팔→재팔 202 · approved 행 pending 부활 (스턱 해소)")

        step("2. 재승인 풀사이클 — 승인 → follows 재생성 + 알림")
        assert api(c, "PATCH", f"/me/follow-requests/{B}", tk["a"], json={"approve": True}).status_code == 204
        assert follows(c, B, A), "재승인 후 follows 재생성"
        assert notif_types(c, tk["b"]).count("follow_request_approved") >= 2, "재승인 알림도 발송"
        ok("재승인 204 · follows 재생성 · approved 알림 (풀사이클 왕복)")

        step("6. cancel 시맨틱 회귀 — 승인+팔로우중 상태에서 cancel → no-op")
        assert api(c, "DELETE", f"/users/{A}/follow-request", tk["b"]).status_code == 204  # 멱등 no-op
        assert fr_status(c, B, A) == ["approved"], "approved 행 보존(팔로우중 — cancel은 pending만)"
        assert follows(c, B, A), "팔로우 관계 불변"
        ok("cancel no-op · approved 행·관계 보존 (pending-only 시맨틱 유지)")

        step("3. 승인→remove follower→재팔 202 (팔로워제거 조합)")
        assert api(c, "POST", f"/users/{A}/follow", tk["d"]).status_code == 202
        assert api(c, "PATCH", f"/me/follow-requests/{D}", tk["a"], json={"approve": True}).status_code == 204
        assert follows(c, D, A)
        # A가 D를 팔로워에서 제거 (오늘 배포한 remove follower)
        assert api(c, "DELETE", f"/me/followers/{D}", tk["a"]).status_code == 204
        assert not follows(c, D, A)
        r = api(c, "POST", f"/users/{A}/follow", tk["d"])
        assert r.status_code == 202, f"remove 후 재팔로우 202, got {r.status_code}: {r.text[:120]}"
        assert fr_status(c, D, A) == ["pending"], "pending 부활"
        ok("승인→팔로워제거→재팔 202 (remove follower 조합 정상)")

        step("4. 거절→재요청 202 (기존 rejected revive 회귀)")
        assert api(c, "POST", f"/users/{A}/follow", tk["rr"]).status_code == 202
        assert api(c, "PATCH", f"/me/follow-requests/{R}", tk["a"], json={"approve": False}).status_code == 204
        assert fr_status(c, R, A) == ["rejected"]
        r = api(c, "POST", f"/users/{A}/follow", tk["rr"])
        assert r.status_code == 202, f"거절 후 재요청 202(기존 동작), got {r.status_code}"
        ok("거절→재요청 202 (rejected revive 회귀 불변)")

        step("5. 레이스 — approved 잔존 상태에서 동시 재팔 2발")
        # B를 다시 스턱 전제 상태로: 현재 approved+팔로우중 → 언팔
        assert api(c, "DELETE", f"/users/{A}/follow", tk["b"]).status_code == 204
        assert fr_status(c, B, A) == ["approved"] and not follows(c, B, A), "approved 잔존 전제"
        async def burst():
            async with httpx.AsyncClient(timeout=30) as ac:
                async def one():
                    return await ac.post(f"{BASE}/users/{A}/follow",
                                         headers={"Authorization": f"Bearer {tk['b']}"})
                return await asyncio.gather(one(), one(), return_exceptions=True)
        results = asyncio.run(burst())
        codes = sorted(r.status_code for r in results if not isinstance(r, Exception))
        assert codes.count(202) == 1 and all(cc in (202, 409) for cc in codes), \
            f"202×1 + 409(패자), got {codes}"
        assert fr_status(c, B, A) == ["pending"], "pending 정확히 1행 (PK+원자 UPDATE 불변식)"
        ok(f"동시 2발 → {codes} · pending 1행 (레이스 불변식)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (follows·follow_requests cascade)")


if __name__ == "__main__":
    run_tests()
