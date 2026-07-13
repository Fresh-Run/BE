"""
Integration test: 승인제 통합 (docs/FOLLOW_CHANGES_DESIGN.md Part B)

별도 토글(follow_approval) 제거 → visibility='private'이면 무조건 팔로우 요청제.
followers·public은 즉시. follow_approval은 DEPRECATED(요청 no-op·응답 false 고정).

매트릭스(설계 §테스트계획 9종):
 1. visibility=private + 신규 → 202 + follow_requests pending 생성
 2. visibility=public  + 신규 → 204 즉시 + follows 생성
 3. visibility=followers + 신규 → 204 즉시 (private만 요청제 확정)
 4. visibility=private + 이미 팔로워 → 204 (소급 무영향, pending 미생성)
 5. follow_approval=True(admin 심음) + public → 즉시 204 (승인제 상실 = 분기 무시)
 6. no-op: PATCH {follow_approval:true} → 200 + DB 불변(false) + 응답 false 고정
 7. 승인 경로 불변(회귀): pending → 승인 → follows + follow_request_approved 알림
 8. 프라이버시 이중검증: private 계정 잠금 응답에 내부 상태(follow_approval 등) 부재
 9. 차단 선행: 차단 상대 팔로우 → 404 은닉 (승인 분기보다 앞섬)

Run: python tests/test_follow_approval_unify_integration.py  (로컬 서버 필요)
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
    r = c.get(f"{_SB}/rest/v1/follows", headers=_ADM,
              params={"follower_id": f"eq.{follower}", "following_id": f"eq.{following}", "select": "follower_id"})
    return bool(r.json())


def fr_count(c, requester, target, status=None) -> int:
    params = {"requester_id": f"eq.{requester}", "target_id": f"eq.{target}", "select": "status"}
    if status:
        params["status"] = f"eq.{status}"
    return len(c.get(f"{_SB}/rest/v1/follow_requests", headers=_ADM, params=params).json())


def admin_set_profile(c, uid, fields):
    return c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{uid}", headers=_ADM, json=fields)


def admin_get_col(c, uid, col):
    r = c.get(f"{_SB}/rest/v1/profiles", headers=_ADM, params={"user_id": f"eq.{uid}", "select": col})
    return r.json()[0][col] if r.json() else None


def notif_types(c, token):
    return [n["type"] for n in api(c, "GET", "/notifications", token).json()]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. 타깃 4종(priv/pub/fol/app) + 액터(a/b/e/g) 준비")
        for k in ("priv", "pub", "fol", "app", "a", "b", "e", "g"):
            uids[k] = sb_user(c, f"fu-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"fu-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"FU{k}{TS}"}).status_code == 200
        # visibility 세팅
        assert api(c, "PATCH", "/me/profile", tk["priv"], json={"visibility": "private"}).status_code == 200
        assert api(c, "PATCH", "/me/profile", tk["fol"], json={"visibility": "followers"}).status_code == 200
        # 'app' 타깃: public + follow_approval=True를 admin으로 직접 심음(API는 no-op이므로)
        assert admin_set_profile(c, uids["app"], {"visibility": "public", "follow_approval": True}).status_code in (200, 204)
        assert admin_get_col(c, uids["app"], "follow_approval") is True, "admin 심기 확인"
        ok("타깃 priv=private · fol=followers · app=public+approval(admin) · pub=public")

        step("1. private + 신규 → 202 + pending 생성")
        r = api(c, "POST", f"/users/{uids['priv']}/follow", tk["a"])
        assert r.status_code == 202, f"private 팔로우 202 기대, got {r.status_code}"
        assert fr_count(c, uids["a"], uids["priv"], "pending") == 1, "pending 1행 생성"
        assert not follows_has(c, uids["a"], uids["priv"]), "아직 follows 없음(승인 전)"
        ok("202 · follow_requests pending 생성 · follows 미생성")

        step("8. 프라이버시 이중검증 — private 잠금 응답에 내부 상태 부재")
        prof = api(c, "GET", f"/users/{uids['priv']}/profile", tk["a"])
        pj, ptext = prof.json(), prof.text
        assert pj.get("locked") is True, "비팔로워에게 잠금"
        assert "follow_approval" not in pj, "공개 프로필에 follow_approval 키 부재"
        assert pj.get("bio") is None, "잠금 시 bio 미노출"
        # 내부 상태 문자열(승인제 토글 흔적) 응답 전체에 부재
        assert "follow_approval" not in ptext, "응답 전체 문자열에도 부재"
        ok("locked · follow_approval 키·문자열 부재 · bio null (이중검증)")

        step("7. 승인 경로 불변(회귀) — 승인 → follows + approved 알림")
        assert api(c, "PATCH", f"/me/follow-requests/{uids['a']}", tk["priv"],
                   json={"approve": True}).status_code == 204
        assert follows_has(c, uids["a"], uids["priv"]), "승인 후 follows 생성"
        assert "follow_request_approved" in notif_types(c, tk["a"]), "approved 알림"
        ok("승인 204 · follows 생성 · follow_request_approved 알림 (플로우 불변)")

        step("4. private + 이미 팔로워 → 204 (소급 무영향, pending 미생성)")
        r = api(c, "POST", f"/users/{uids['priv']}/follow", tk["a"])  # a는 이제 팔로워
        assert r.status_code == 204, f"이미 팔로워 재팔로우 204 기대, got {r.status_code}"
        assert fr_count(c, uids["a"], uids["priv"], "pending") == 0, "새 pending 미생성"
        ok("204 · pending 미생성 (기존 팔로워는 요청 경로 안 탐)")

        step("2. public + 신규 → 204 즉시 + follows 생성")
        r = api(c, "POST", f"/users/{uids['pub']}/follow", tk["b"])
        assert r.status_code == 204, f"public 팔로우 204 기대, got {r.status_code}"
        assert follows_has(c, uids["b"], uids["pub"]), "follows 생성"
        assert fr_count(c, uids["b"], uids["pub"]) == 0, "요청 행 없음"
        ok("204 즉시 · follows 생성 · 요청 없음")

        step("3. followers + 신규 → 204 즉시 (private만 요청제 확정)")
        r = api(c, "POST", f"/users/{uids['fol']}/follow", tk["e"])
        assert r.status_code == 204, f"followers 팔로우 204 기대(즉시), got {r.status_code}"
        assert follows_has(c, uids["e"], uids["fol"]), "follows 생성"
        assert fr_count(c, uids["e"], uids["fol"]) == 0, "요청 행 없음(followers는 즉시)"
        ok("204 즉시 · follows 생성 · pending 없음 (followers ≠ 요청제)")

        step("5. follow_approval=True + public → 즉시 204 (승인제 상실 = 분기 무시)")
        r = api(c, "POST", f"/users/{uids['app']}/follow", tk["g"])
        assert r.status_code == 204, f"approval=True여도 public이면 즉시 204, got {r.status_code}"
        assert follows_has(c, uids["g"], uids["app"]), "follows 즉시 생성"
        assert fr_count(c, uids["g"], uids["app"]) == 0, "pending 없음(follow_approval 무시)"
        ok("204 즉시 · follows 생성 · follow_approval 컬럼 무시 (visibility만 분기)")

        step("6. no-op — PATCH {follow_approval:true} → 200 + DB 불변 + 응답 false")
        before = admin_get_col(c, uids["b"], "follow_approval")  # 기본 false
        r = api(c, "PATCH", "/me/profile", tk["b"], json={"follow_approval": True})
        assert r.status_code == 200, r.text[:150]
        assert r.json()["follow_approval"] is False, "응답 follow_approval false 고정"
        assert admin_get_col(c, uids["b"], "follow_approval") == before, f"DB 불변(no-op), before={before}"
        ok(f"200 · 응답 false 고정 · DB follow_approval 불변({before}) — no-op")

        step("9. 차단 선행 — 차단 상대 팔로우 → 404 은닉 (승인 분기보다 앞)")
        assert api(c, "POST", f"/users/{uids['b']}/block", tk["priv"]).status_code == 204  # priv가 b 차단
        r = api(c, "POST", f"/users/{uids['priv']}/follow", tk["b"])
        assert r.status_code == 404, f"차단 상대 팔로우 404 기대, got {r.status_code}"
        assert fr_count(c, uids["b"], uids["priv"]) == 0, "pending 미생성(차단 선행)"
        api(c, "DELETE", f"/users/{uids['b']}/block", tk["priv"])  # 정리
        ok("404 은닉 · pending 미생성 (차단이 승인 분기보다 앞섬)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (follows·follow_requests·blocks cascade)")


if __name__ == "__main__":
    run_tests()
