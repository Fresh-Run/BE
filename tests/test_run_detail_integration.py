"""
Integration test: run 단건 조회 (GET /runs/{run_id}) — 가시성 매트릭스 전수

2026-07-14 재작성: 초기 커밋 버전은 "run은 본인 것만(타인 404)" 시절 계약이라
visibility v1(public/followers/private, 2026-07-12~) 이후 낡음 — 미지정 run이
public 기본이 되며 타인 200이 정답이 됐는데 404를 기대해 실패하던 것.

현 계약(API_GUIDE §기록 단건): 본인 전체 / 타인은 공개범위 내 정제 응답 /
범위 밖 404 은닉. profile visibility AND 합성(비공개 계정의 public run도
비팔로워에겐 404) + 차단 전부 404.

매트릭스: run visibility × (본인/무관계/팔로워/차단) 전수
 public    → 200 / 200 / 200 / 404
 followers → 200 / 404 / 200 / 404
 private   → 200 / 404 / 404 / 404
+ AND 합성: 비공개 계정의 public run → 무관계 404
+ 타인 응답 정제: notes·visibility null (프라이버시 이중검증)
+ 본인 필드 일치 · 없는 id 404 (구 테스트 커버리지 보존)

Run: python tests/test_run_detail_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"
_NOBODY = "00000000-0000-4000-8000-000000000000"

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
TS = int(time.time())

def ok(m):   print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")

def sb_user(c, email):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": "test1234", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]

def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {tok}"}, **kw)


SECRET_NOTE = f"비밀메모{TS}"


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    try:
        step("0. O(공개 owner)·S(무관계)·F(팔로워)·X(차단)·OP(비공개 owner) 준비")
        for k in ("o", "s", "f", "x", "op"):
            uids[k] = sb_user(c, f"rd-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"rd-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"RD{k}{TS}"}).status_code == 200
        assert api(c, "POST", f"/users/{uids['o']}/follow", tk["f"]).status_code == 204  # F→O 팔로우
        assert api(c, "POST", f"/users/{uids['x']}/block", tk["o"]).status_code == 204   # O가 X 차단
        assert api(c, "PATCH", "/me/profile", tk["op"], json={"visibility": "private"}).status_code == 200
        ok("유저 5명 + F 팔로우 + X 차단 + OP 비공개")

        step("1. O의 run 3종 저장 (visibility 명시) + 본인 필드 일치")
        runs = {}
        for vis in ("public", "followers", "private"):
            r = api(c, "POST", "/runs", tk["o"], json={
                "distance_km": 5.2, "duration_sec": 1800, "avg_pace_sec_per_km": 346,
                "notes": SECRET_NOTE, "visibility": vis})
            assert r.status_code in (200, 201), r.text[:200]
            runs[vis] = r.json()["id"]
        d = api(c, "GET", f"/runs/{runs['public']}", tk["o"]).json()
        assert d["id"] == runs["public"] and d["user_id"] == uids["o"]
        assert d["distance_km"] == 5.2 and d["duration_sec"] == 1800
        assert d["avg_pace_sec_per_km"] == 346 and d["notes"] == SECRET_NOTE
        assert d["ran_at"], "ran_at 존재"
        ok("run 3종 저장 · 본인 조회 200 + 필드 일치")

        step("2. 가시성 매트릭스 전수 — visibility × 관계")
        EXPECT = {  # (본인, 무관계, 팔로워, 차단)
            "public":    (200, 200, 200, 404),
            "followers": (200, 404, 200, 404),
            "private":   (200, 404, 404, 404),
        }
        for vis, rid in runs.items():
            got = tuple(api(c, "GET", f"/runs/{rid}", tk[k]).status_code
                        for k in ("o", "s", "f", "x"))
            assert got == EXPECT[vis], f"{vis}: 기대 {EXPECT[vis]}, got {got}"
            ok(f"{vis:10} → 본인/무관계/팔로워/차단 = {got}")

        step("3. AND 합성 — 비공개 계정(OP)의 public run → 무관계 404")
        rp = api(c, "POST", "/runs", tk["op"], json={
            "distance_km": 2.0, "duration_sec": 720, "visibility": "public"}).json()["id"]
        r = api(c, "GET", f"/runs/{rp}", tk["s"])
        assert r.status_code == 404, f"profile gate AND — 404 기대, got {r.status_code}"
        ok("비공개 계정 public run → 무관계 404 (profile_gate AND run_gate)")

        step("4. 타인 응답 정제 — 프라이버시 이중검증")
        r = api(c, "GET", f"/runs/{runs['public']}", tk["s"])
        d, raw = r.json(), r.text
        assert d.get("notes") is None, "타인에게 notes(개인 메모) null"
        assert d.get("visibility") is None, "타인에게 visibility null"
        assert SECRET_NOTE not in raw, "응답 전문에 메모 문자열 부재 (이중검증)"
        ok("타인 응답: notes·visibility null + 메모 문자열 부재")

        step("5. 없는 id → 404")
        assert api(c, "GET", f"/runs/{_NOBODY}", tk["o"]).status_code == 404
        ok("없는 id 404")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (runs·follows·blocks cascade)")


if __name__ == "__main__":
    run_tests()
