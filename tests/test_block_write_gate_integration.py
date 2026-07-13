"""
Integration test: 배치1 — 차단 게이트를 write 표면으로 확장 (감사 3차 H-1·2·3 + M-8)

차단 상대에게 코스 좋아요·댓글·팔로우·승인요청이 불가(404 은닉)한지, 그리고
차단 404가 피드설정 403보다 선행(은닉 우선)하는지 검증. approve×block 레이스
봉쇄(decide_follow_request 재검증)도 결정론적으로 확인.

Run: python tests/test_block_write_gate_integration.py  (로컬 서버 필요)
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


def make_route(c, owner_id, summary):
    r = c.post(f"{_SB}/rest/v1/routes", headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": owner_id, "summary": summary, "target_distance_km": 3.0,
                     "total_distance_km": 3.0, "estimated_duration_min": 20, "waypoints": [],
                     "polyline": [], "start_lat": 37.5, "start_lng": 127.0, "is_public": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()[0]["id"]


def count(c, table, **eq):
    p = {k: f"eq.{v}" for k, v in eq.items()}
    p.update({"select": "*", "limit": 1})
    r = c.get(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "count=exact"}, params=p)
    return int(r.headers.get("content-range", "?/0").split("/")[-1])


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. A·B·C + 프로필, A·B 코스")
        for k in ("a", "b", "c"):
            uids[k] = sb_user(c, f"bwg-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"bwg-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"BWG{k}{TS}"}).status_code == 200
        route_a = make_route(c, uids["a"], f"BWG코스A{TS}")
        route_b = make_route(c, uids["b"], f"BWG코스B{TS}")
        ok("A·B·C 준비 + A·B 공개 코스")

        step("1. 차단 전 정상 (positive control) — B가 A 코스에 좋아요·댓글")
        assert api(c, "POST", f"/routes/{route_a}/like", tk["b"]).status_code == 204
        assert api(c, "POST", f"/routes/{route_a}/comments", tk["b"], json={"content": "좋네요"}).status_code == 201
        # 정리(차단 후 재검증 위해)
        api(c, "DELETE", f"/routes/{route_a}/like", tk["b"])
        ok("차단 전 좋아요 204·댓글 201")

        step("2. A가 B 차단 → 코스 좋아요·댓글 404 (양방향)")
        assert api(c, "POST", f"/users/{uids['b']}/block", tk["a"]).status_code == 204
        assert api(c, "POST", f"/routes/{route_a}/like", tk["b"]).status_code == 404, "B→A코스 좋아요 404"
        assert api(c, "POST", f"/routes/{route_a}/comments", tk["b"], json={"content": "막힘"}).status_code == 404
        assert api(c, "POST", f"/routes/{route_b}/like", tk["a"]).status_code == 404, "A→B코스 좋아요 404(양방향)"
        assert api(c, "POST", f"/routes/{route_b}/comments", tk["a"], json={"content": "막힘"}).status_code == 404
        # 좋아요·댓글 행 미생성
        assert count(c, "route_likes", route_id=route_a, user_id=uids["b"]) == 0, "차단 좋아요 행 없음"
        ok("차단 상대 코스 좋아요·댓글 양방향 404 + 행 미생성")

        step("3. 차단 404가 피드설정 403보다 선행 (은닉 우선)")
        # A가 좋아요 OFF → 비차단 C는 403, 차단 B는 404 (404가 먼저)
        assert api(c, "PATCH", "/me/settings", tk["a"], json={"feed": {"allow_likes": False}}).status_code == 200
        assert api(c, "POST", f"/routes/{route_a}/like", tk["c"]).status_code == 403, "비차단 C는 피드설정 403"
        assert api(c, "POST", f"/routes/{route_a}/like", tk["b"]).status_code == 404, "차단 B는 404(403 아님 — 은닉 우선)"
        api(c, "PATCH", "/me/settings", tk["a"], json={"feed": {"allow_likes": True}})
        ok("차단 404 > 피드 403 순서 확인 (C=403, B=404)")

        step("4. follow_user 차단 게이트 — 404 + 관계 행 미생성 (양방향)")
        assert api(c, "POST", f"/users/{uids['a']}/follow", tk["b"]).status_code == 404, "B→A 팔로우 404"
        assert api(c, "POST", f"/users/{uids['b']}/follow", tk["a"]).status_code == 404, "A→B 팔로우 404(양방향)"
        assert count(c, "follows", follower_id=uids["b"], following_id=uids["a"]) == 0, "follows 행 없음"
        assert count(c, "follow_requests", requester_id=uids["b"], target_id=uids["a"]) == 0, "요청 행 없음"
        ok("차단 상대 팔로우 404 + follows·follow_requests 행 미생성")

        step("5. 요청제(비공개) 분기도 차단 선행 — pending 요청 미생성")
        # 승인제 통합(Part B): 요청제 진입 = visibility='private'. (구 follow_approval 토글 제거)
        assert api(c, "DELETE", f"/users/{uids['b']}/block", tk["a"]).status_code == 204  # 해제
        assert api(c, "PATCH", "/me/profile", tk["a"], json={"visibility": "private"}).status_code == 200
        assert api(c, "POST", f"/users/{uids['b']}/block", tk["a"]).status_code == 204  # 재차단
        assert api(c, "POST", f"/users/{uids['a']}/follow", tk["b"]).status_code == 404, "비공개+차단 → 404"
        assert count(c, "follow_requests", requester_id=uids["b"], target_id=uids["a"]) == 0, "pending 미생성"
        ok("비공개(요청제) 계정 차단 시 팔로우 404 + pending 미생성")

        step("6. approve×block 레이스 봉쇄 (M-8) — pending 잔존 시뮬레이션 후 approve 404")
        # 차단(A,B) 존재 상태에서 pending 요청 행을 직접 삽입(레이스로 살아남은 상황 재현)
        r = c.post(f"{_SB}/rest/v1/follow_requests", headers=_ADM,
                   json={"requester_id": uids["b"], "target_id": uids["a"], "status": "pending"})
        assert r.status_code in (200, 201), r.text[:200]
        # A가 승인 시도 → decide_follow_request의 차단 재검증으로 404, follows 미생성
        r = api(c, "PATCH", f"/me/follow-requests/{uids['b']}", tk["a"], json={"approve": True})
        assert r.status_code == 404, f"차단 상태 approve → 404 기대, got {r.status_code}"
        assert count(c, "follows", follower_id=uids["b"], following_id=uids["a"]) == 0, "레이스에도 follows 엣지 미생성"
        ok("approve×block 레이스 — follows 엣지 봉쇄(404, 미생성)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
