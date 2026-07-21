"""
Integration test: 코스 삭제 DELETE /routes/{route_id} (Ivan 리포트 C, run-delete 동생)

하드 삭제 — 북마크·좋아요·댓글·오디오코치 FK cascade + route 대상 알림 best-effort
정리. 연결 러닝(runs.route_id)·복사본(copied_from)은 set null로 잔존을 실증.

케이스:
 1. 본인 삭제 204 + cascade 전수(bookmarks·likes·comments·coach 0) +
    run 잔존(route_id=null) + 복사본 잔존(copied_from=null)
 2. 재삭제 404 / 타인 404+행 불변 / 없는 id 404
 3. 알림 정리: route_liked(route 대상) 소멸 + 무관(user_followed) 잔존
 4. 레이스: 동시 2발 → [204,404] + 행 0
 5. is_one_way 필드 존재(리포트 D — 컬럼 미적용 시 default false)

Run: python tests/test_route_delete_integration.py  (로컬 서버 필요)
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
_ADMR = {**_ADM, "Prefer": "return=representation"}
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


def mk_route(c, user_id, **extra):
    """admin REST로 임시 route insert (실 Gemini 호출 회피)."""
    body = {"user_id": user_id, "summary": f"임시코스{TS}", "total_distance_km": 5.0,
            "waypoints": [], "is_public": True, **extra}
    r = c.post(f"{_SB}/rest/v1/routes", headers=_ADMR, json=body)
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()[0]["id"]


def db_count(c, tbl, **filt):
    q = "&".join(f"{k}=eq.{v}" for k, v in filt.items())
    return c.get(f"{_SB}/rest/v1/{tbl}?{q}&select=*", headers=_ADM).json()


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    try:
        step("0. 유저 A(소유자)·B(타인) 생성")
        for k in ("a", "b"):
            uids[k] = sb_user(c, f"rtd-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"rtd-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"RTD{k}{TS}"}).status_code == 200
        ok("A·B + 프로필")

        step("1. cascade + set-null 실증 — 참조 6종 세팅 후 삭제")
        route = mk_route(c, uids["a"])
        # B가 좋아요·북마크·댓글 (API 경로 — 가시성 게이트 통과 확인 겸)
        assert api(c, "POST", f"/routes/{route}/like", tk["b"]).status_code == 204
        assert api(c, "POST", f"/routes/{route}/bookmark", tk["b"]).status_code == 204
        assert api(c, "POST", f"/routes/{route}/comments", tk["b"],
                   json={"content": "좋은 코스"}).status_code in (200, 201)
        # coach_scripts는 admin insert(프리미엄 게이트 회피 — cascade만 검증)
        c.post(f"{_SB}/rest/v1/coach_scripts", headers=_ADM,
               json={"route_id": route, "user_id": uids["a"], "script": {"cues": []}, "model": "x"})
        # A가 이 코스로 러닝 기록 (route_id 연결)
        run = api(c, "POST", "/runs", tk["a"],
                  json={"distance_km": 5.0, "duration_sec": 1800, "route_id": route}).json()["id"]
        # B가 복사본 생성 (copied_from)
        copy = api(c, "POST", f"/routes/{route}/copy", tk["b"]).json()["id"]
        # like 알림(route 대상) 존재 확인
        assert len(db_count(c, "notifications", target_type="route", target_id=route)) >= 1, "route_liked 알림"
        assert len(db_count(c, "route_likes", route_id=route)) == 1
        assert len(db_count(c, "route_comments", route_id=route)) == 1
        assert len(db_count(c, "coach_scripts", route_id=route)) == 1
        ok("좋아요·북마크·댓글·coach·run연결·복사본·알림 세팅")

        # 삭제
        assert api(c, "DELETE", f"/routes/{route}", tk["a"]).status_code == 204, "본인 삭제 204"
        assert db_count(c, "routes", id=route) == [], "route 행 소멸"
        for t in ("route_likes", "route_bookmarks", "route_comments", "coach_scripts"):
            assert db_count(c, t, route_id=route) == [], f"{t} cascade 소멸"
        run_row = db_count(c, "runs", id=run)
        assert len(run_row) == 1 and run_row[0]["route_id"] is None, f"run 잔존+route_id null, got {run_row}"
        copy_row = db_count(c, "routes", id=copy)
        assert len(copy_row) == 1 and copy_row[0]["copied_from"] is None, f"복사본 잔존+copied_from null, got {copy_row}"
        ok("204 · cascade 4종 0 · run 잔존(route_id null) · 복사본 잔존(copied_from null)")

        step("2. 재삭제 404 / 타인 404+불변 / 없는 id 404")
        assert api(c, "DELETE", f"/routes/{route}", tk["a"]).status_code == 404, "재삭제 404"
        route2 = mk_route(c, uids["a"])
        assert api(c, "DELETE", f"/routes/{route2}", tk["b"]).status_code == 404, "타인 삭제 404"
        assert len(db_count(c, "routes", id=route2)) == 1, "타인 삭제 시도 후 행 불변"
        ghost = "00000000-0000-0000-0000-000000000000"
        assert api(c, "DELETE", f"/routes/{ghost}", tk["a"]).status_code == 404, "없는 id 404"
        ok("재삭제 404 · 타인 404+불변 · 없는 id 404")

        step("3. 알림 정리 — route 대상 소멸 + 무관 잔존")
        route3 = mk_route(c, uids["a"])
        assert api(c, "POST", f"/routes/{route3}/like", tk["b"]).status_code == 204
        # 무관 알림: B가 A를 팔로우 → user_followed(A 대상)
        assert api(c, "POST", f"/users/{uids['a']}/follow", tk["b"]).status_code == 204
        assert len(db_count(c, "notifications", target_type="route", target_id=route3)) >= 1
        follow_before = len(db_count(c, "notifications", type="user_followed", target_id=uids["a"]))
        assert api(c, "DELETE", f"/routes/{route3}", tk["a"]).status_code == 204
        assert db_count(c, "notifications", target_type="route", target_id=route3) == [], "route 알림 소멸"
        assert len(db_count(c, "notifications", type="user_followed", target_id=uids["a"])) == follow_before, \
            "무관 알림(user_followed) 잔존"
        ok("route 대상 알림 소멸 · user_followed 잔존")

        step("4. 레이스 — 동시 2발 → [204, 404] + 행 0")
        route4 = mk_route(c, uids["a"])
        async def burst():
            async with httpx.AsyncClient(timeout=30) as ac:
                async def one():
                    return await ac.delete(f"{BASE}/routes/{route4}",
                                           headers={"Authorization": f"Bearer {tk['a']}"})
                return await asyncio.gather(one(), one(), return_exceptions=True)
        codes = sorted(r.status_code for r in asyncio.run(burst()) if not isinstance(r, Exception))
        assert codes == [204, 404], f"동시 2발 [204,404] 기대, got {codes}"
        assert db_count(c, "routes", id=route4) == [], "레이스 후 행 0"
        ok("동시 2발 → [204,404] · 행 0 (레이스 불변식)")

        step("5. is_one_way 필드 (리포트 D) — 응답 존재·default false")
        route5 = mk_route(c, uids["a"])
        r = api(c, "GET", f"/routes/{route5}", tk["a"]).json()
        assert "is_one_way" in r, "StoredRoute에 is_one_way 필드"
        assert r["is_one_way"] is False, "admin insert(end 없음)·컬럼 미적용 → default false"
        api(c, "DELETE", f"/routes/{route5}", tk["a"])
        ok("is_one_way 필드 존재 · default false (컬럼 적용+생성 경로 검증은 배포 후)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for t in ("route_likes", "route_bookmarks", "route_comments", "coach_scripts", "runs"):
            for uid in uids.values():
                c.delete(f"{_SB}/rest/v1/{t}?user_id=eq.{uid}", headers=_ADM)
        for uid in uids.values():
            c.delete(f"{_SB}/rest/v1/routes?user_id=eq.{uid}", headers=_ADM)
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (임시 유저·코스·참조 전량)")


if __name__ == "__main__":
    run_tests()
