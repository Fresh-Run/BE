"""
Integration test: join_by_code 차단 관계 404 은닉 (감사 L1 수정, 2026-07-21)

가입 시도자가 크루 owner와 차단 관계(양방향)면 join_by_code가 404(CrewNotFound=
"Invalid invite code")로 은닉 — 초대코드 유효성도 차단 사실도 노출 안 함. 기준은
owner(크루 authority); owner 아닌 멤버와의 차단은 가입 무관.

케이스(T-map·Gemini 무관):
 1. owner→시도자 차단 → 404 (코드 유효성 은닉)
 2. 시도자→owner 차단(반대 방향) → 404 (양방향)
 3. 차단 없는 정상 유저 → 200 (회귀)
 4. owner 아닌 멤버와만 차단인 유저 → 200 (owner 기준만 — 멤버 차단 무관)

Run: python tests/test_crew_join_block_integration.py   (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8003/api"
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
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):      print(f"\n[{t}]")


def sb_user(c, email):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": "test1234", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]


def login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def api(c, m, p, tok, **kw):
    return c.request(m, f"{BASE}{p}", headers={"Authorization": f"Bearer {tok}"}, **kw)


def join(c, tok, code):
    return api(c, "POST", "/crews/join-by-code", tok, json={"code": code})


def notif_count(c, recipient, typ, actor, target):
    # target_id(크루)로 스코프 — 다른 크루의 정상 가입 알림과 섞이지 않게.
    r = c.get(f"{_SB}/rest/v1/notifications?user_id=eq.{recipient}&type=eq.{typ}"
              f"&actor_id=eq.{actor}&target_id=eq.{target}&select=id", headers=_ADM)
    return len(r.json()) if r.status_code == 200 else f"ERR{r.status_code}"


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    try:
        step("0. owner O · 차단자 X · 정상 N · 멤버 M · 멤버차단 J")
        for k in ("o", "x", "n", "m", "j"):
            uids[k] = sb_user(c, f"cjb-{k}-{TS}@test.com")
        tok = {k: login(c, f"cjb-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tok[k], json={"nickname": f"CJB{k}{TS}"}).status_code == 200
        # O는 여러 크루 생성(무료 한도 1 회피) — premium
        c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{uids['o']}", headers=_ADM, json={"tier": "premium"})
        crew = api(c, "POST", "/crews", tok["o"],
                   json={"name": f"JoinBlk{TS}", "is_public": True}).json()["id"]
        code = api(c, "POST", f"/crews/{crew}/invite", tok["o"]).json()["code"]
        ok(f"유저 5 + 크루 + 초대코드 발급")

        step("1. owner→시도자 차단 → 404 (코드 유효성 은닉)")
        assert api(c, "POST", f"/users/{uids['x']}/block", tok["o"]).status_code == 204
        r = join(c, tok["x"], code)
        assert r.status_code == 404, f"owner 차단 대상 404, got {r.status_code}: {r.text[:120]}"
        # 잘못된 코드와 동일 메시지(은닉 확인)
        bad = join(c, tok["x"], "ZZZZZZZZ")
        assert bad.status_code == 404 and bad.json()["detail"] == r.json()["detail"], \
            "차단 404가 '잘못된 코드' 404와 동일 응답(은닉)이어야"
        ok("owner→X 차단 → 404 · 잘못된 코드와 동일 응답(코드 존재·차단 사실 은닉)")

        step("2. 시도자→owner 차단(반대 방향) → 404 (양방향)")
        assert api(c, "DELETE", f"/users/{uids['x']}/block", tok["o"]).status_code == 204  # O의 차단 해제
        assert api(c, "POST", f"/users/{uids['o']}/block", tok["x"]).status_code == 204    # X가 O를 차단
        r = join(c, tok["x"], code)
        assert r.status_code == 404, f"시도자→owner 차단도 404, got {r.status_code}"
        api(c, "DELETE", f"/users/{uids['o']}/block", tok["x"])  # 정리
        ok("X→owner 차단(반대 방향)도 404 (is_blocked_either 양방향)")

        step("3. 차단 없는 정상 유저 → 200 (회귀)")
        r = join(c, tok["n"], code)
        assert r.status_code == 200, f"정상 가입 200, got {r.status_code}: {r.text[:120]}"
        assert r.json()["id"] == crew, "가입한 크루 반환"
        # 해제된 X도 이제 가입 가능(차단만이 게이트였음 확인)
        r2 = join(c, tok["x"], code)
        assert r2.status_code == 200, f"차단 해제 후 X 가입 200, got {r2.status_code}"
        ok("정상 N 200 · 차단 해제된 X도 200 (차단만이 게이트)")

        step("4. owner 아닌 멤버(M)와만 차단인 J → 200 (owner 기준만)")
        assert join(c, tok["m"], code).status_code == 200, "M 가입"
        assert api(c, "POST", f"/users/{uids['j']}/block", tok["m"]).status_code == 204  # 멤버 M이 J 차단
        r = join(c, tok["j"], code)
        assert r.status_code == 200, \
            f"owner와 무관한 멤버 차단은 가입 무관(200), got {r.status_code} — invite와 기준 다르면 플래그"
        ok("멤버 M이 J를 차단해도 J 가입 200 (owner 기준만 — 멤버 차단 무관)")

        step("5. open-join / approval-신청 — 차단하면 경로 불문 404 (L1 완전 일관)")
        # X 재차단 (step 3에서 해제됐음)
        assert api(c, "POST", f"/users/{uids['x']}/block", tok["o"]).status_code == 204
        open_crew = api(c, "POST", "/crews", tok["o"],
                        json={"name": f"OpenBlk{TS}", "is_public": True, "join_policy": "open"}).json()["id"]
        appr_crew = api(c, "POST", "/crews", tok["o"],
                        json={"name": f"ApprBlk{TS}", "is_public": True, "join_policy": "approval"}).json()["id"]
        # 차단 X: open-join·approval-신청 둘 다 404 (owner 존재 은닉)
        rc_open = api(c, "POST", f"/crews/{open_crew}/join", tok["x"]).status_code
        rc_appr = api(c, "POST", f"/crews/{appr_crew}/join", tok["x"]).status_code
        assert rc_open == 404, f"차단 X open-join 404, got {rc_open}"
        assert rc_appr == 404, f"차단 X approval-신청 404, got {rc_appr}"
        # owner에게 알림 0 (가입 자체가 막혀 crew_joined·join_requested 미발생)
        nj = notif_count(c, uids["o"], "crew_joined", uids["x"], open_crew)
        nr = notif_count(c, uids["o"], "join_requested", uids["x"], appr_crew)
        assert nj == 0 and nr == 0, f"차단 X발 알림 crew_joined={nj} join_requested={nr} (전 0)"
        # 정상 N 회귀: open 200 · approval 202(pending)
        assert api(c, "POST", f"/crews/{open_crew}/join", tok["n"]).status_code == 200, "정상 open-join 200"
        assert api(c, "POST", f"/crews/{appr_crew}/join", tok["n"]).status_code == 202, "정상 approval-신청 202"
        ok("차단 X open·approval 둘 다 404 · owner 알림 0 · 정상 N 200/202 회귀")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/rest/v1/crews?owner_id=eq.{uid}", headers=_ADM)
            c.delete(f"{_SB}/rest/v1/blocks?blocker_id=eq.{uid}", headers=_ADM)
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (크루·차단·유저 삭제)")


if __name__ == "__main__":
    run_tests()
