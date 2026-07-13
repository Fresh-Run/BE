"""
Integration test: Remove Follower (docs/FOLLOW_CHANGES_DESIGN.md Part A)

DELETE /me/followers/{user_id} — 내 팔로워 목록에서 상대 떼기.
언팔로우(follower=me)와 **정반대 방향**의 엣지 (follower=target, following=me) 삭제.
무알림 · 재팔로우 허용(block과 구분) · 멱등.

케이스(설계 §테스트계획 8종):
 1. B→A 팔로우 후 A가 remove → 204 + follows(B→A) 삭제 assert + 역방향(A→B) 불변
 2. 방향 불변식: remove 후 A→B 유지 (자리바뀜 회귀 방어)
 3. 멱등: 팔로워 아닌 C remove → 204 + A 팔로워 수 불변(0 삭제)
 4. self → 400
 5. 없는 user_id → 404
 6. 차단(A↔B block) → 404 은닉 + 행 미변경
 7. 무알림: remove 전후 상대(B) notifications 개수 불변
 8. 재팔로우: remove 후 B가 다시 A(public) 팔로우 → 204 + follows(B→A) 재생성

Run: python tests/test_remove_follower_integration.py  (로컬 서버 필요)
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


def follows_has(c, follower, following) -> bool:
    """DB 부수효과 직접 조회: (follower_id, following_id) 엣지 존재 여부."""
    r = c.get(f"{_SB}/rest/v1/follows", headers=_ADM,
              params={"follower_id": f"eq.{follower}", "following_id": f"eq.{following}",
                      "select": "follower_id"})
    return bool(r.json())


def followers_count(c, uid) -> int:
    """uid를 팔로우하는 행 수 (following_id = uid)."""
    r = c.get(f"{_SB}/rest/v1/follows", headers=_ADM,
              params={"following_id": f"eq.{uid}", "select": "follower_id"})
    return len(r.json())


def notif_count(c, token) -> int:
    return len(api(c, "GET", "/notifications", token).json())


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. A(나)·B(팔로워/제거대상)·C(팔로워 아닌 제3자) 준비")
        for k in ("a", "b", "cc"):
            uids[k] = sb_user(c, f"rf-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"rf-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"RF{k}{TS}"}).status_code == 200
        # B→A 팔로우, A→B 팔로우(역방향) — 둘 다 public 즉시 204
        assert api(c, "POST", f"/users/{uids['a']}/follow", tk["b"]).status_code == 204
        assert api(c, "POST", f"/users/{uids['b']}/follow", tk["a"]).status_code == 204
        assert follows_has(c, uids["b"], uids["a"]), "B→A 선행 팔로우"
        assert follows_has(c, uids["a"], uids["b"]), "A→B 역방향 팔로우"
        ok("유저 3명 + B→A·A→B 상호 팔로우")

        step("1. A가 B를 팔로워에서 제거 → 204 + (B→A) 삭제 + 역방향 불변")
        b_notif_before = notif_count(c, tk["b"])   # 케이스7 스냅샷(remove 직전)
        r = api(c, "DELETE", f"/me/followers/{uids['b']}", tk["a"])
        assert r.status_code == 204, f"remove 204, got {r.status_code}"
        assert not follows_has(c, uids["b"], uids["a"]), "제거 후 (B→A) 엣지 삭제됨"
        ok("204 · follows(B→A) 삭제 assert")

        step("2. 방향 불변식 — A→B 팔로우는 유지 (자리바뀜 회귀 방어)")
        assert follows_has(c, uids["a"], uids["b"]), "역방향 A→B 불변"
        # 상대 관점 확인: A의 프로필에서 B는 여전히 A를 팔로우당함(is_followed_by)
        ok("A→B 유지 — remove는 (target→me) 방향만 지운다")

        step("7. 무알림 — remove로 상대(B) 알림 개수 불변")
        # remove follower는 알림을 만들지 않는다(unfollow·block 관성).
        assert notif_count(c, tk["b"]) == b_notif_before, \
            f"remove 후 B 알림 개수 불변, before={b_notif_before} after={notif_count(c, tk['b'])}"
        ok(f"B 알림 개수 불변({b_notif_before}) — 무알림 확인")

        step("3. 멱등 — 팔로워 아닌 C remove → 204 + A 팔로워 수 불변")
        before = followers_count(c, uids["a"])
        assert not follows_has(c, uids["cc"], uids["a"]), "C는 A 팔로워 아님(전제)"
        assert api(c, "DELETE", f"/me/followers/{uids['cc']}", tk["a"]).status_code == 204, "멱등 204"
        assert followers_count(c, uids["a"]) == before, f"A 팔로워 수 불변 {before}"
        # 이미 뗀 B를 다시 remove — 재차 멱등 204
        assert api(c, "DELETE", f"/me/followers/{uids['b']}", tk["a"]).status_code == 204, "재-remove 멱등"
        ok(f"멱등 204 · 팔로워 수 불변({before}) · 재-remove 204")

        step("4. self → 400")
        assert api(c, "DELETE", f"/me/followers/{uids['a']}", tk["a"]).status_code == 400, "self 400"
        ok("self remove 400")

        step("5. 없는 user_id → 404")
        ghost = "00000000-0000-0000-0000-000000000000"
        assert api(c, "DELETE", f"/me/followers/{ghost}", tk["a"]).status_code == 404, "없는 유저 404"
        ok("존재하지 않는 user 404")

        step("6. 차단(A↔B block) → 404 은닉 + 행 미변경")
        # B가 다시 A를 팔로우해 엣지 생성 후, A가 B를 차단 → 차단 시 follows 자동정리.
        assert api(c, "POST", f"/users/{uids['a']}/follow", tk["b"]).status_code == 204
        assert api(c, "POST", f"/users/{uids['b']}/block", tk["a"]).status_code == 204  # 차단(양방향 follows 정리)
        before_edge = follows_has(c, uids["b"], uids["a"])   # 차단이 이미 정리 → False 기대
        r = api(c, "DELETE", f"/me/followers/{uids['b']}", tk["a"])
        assert r.status_code == 404, f"차단 관계 remove 404 은닉, got {r.status_code}"
        assert follows_has(c, uids["b"], uids["a"]) == before_edge, "차단 관계에서 행 미변경(은닉 우선)"
        api(c, "DELETE", f"/users/{uids['b']}/block", tk["a"])  # 원복
        ok("차단 관계 remove 404 · 행 미변경")

        step("8. 재팔로우 허용 — remove 후 B가 다시 A(public) 팔로우 → 204 재생성")
        # 6에서 unblock 했으니 재팔로우 가능. B→A 팔로우.
        assert api(c, "POST", f"/users/{uids['a']}/follow", tk["b"]).status_code == 204, "재팔로우 즉시 204(public)"
        assert follows_has(c, uids["b"], uids["a"]), "재팔로우로 (B→A) 재생성"
        # 다시 제거되는지도 확인(관계만 끊고 차단 아님)
        assert api(c, "DELETE", f"/me/followers/{uids['b']}", tk["a"]).status_code == 204
        assert not follows_has(c, uids["b"], uids["a"]), "재제거 정상"
        ok("재팔로우 204 · 엣지 재생성 · 재제거 — block과 구분(관계만 끊음)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (follows·blocks cascade)")


if __name__ == "__main__":
    run_tests()
