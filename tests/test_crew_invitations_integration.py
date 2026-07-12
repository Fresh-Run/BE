"""
Integration test: 인앱 개인 초대 (crew_invited, SQL 0 — 선등록 type)

발송(204)·비크루원 발송자 404·이미 크루원 409·차단 관계 404·없는 유저 404·
알림 payload(초대코드·crew_id·crew_name)·수신자 preview→join 왕복.

Run: python tests/test_crew_invitations_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time, uuid
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
    return c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                  json={"email": email, "password": "test1234", "email_confirm": True}).json()["id"]


def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


def invited_notif(c, uid):
    r = c.get(f"{_SB}/rest/v1/notifications", headers=_ADM,
              params={"user_id": f"eq.{uid}", "type": "eq.crew_invited",
                      "select": "actor_id,target_id,target_type,payload", "order": "created_at.desc"})
    return r.json()


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. A(크루장)·B(멤버)·C(초대 대상, 비크루원)·D(차단 대상)·E(비크루원 발송자)")
        for k in ("a", "b", "c", "d", "e"):
            uids[k] = sb_user(c, f"cinv-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"cinv-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CINV{k}{TS}"}).status_code == 200
        crew = api(c, "POST", "/crews", tk["a"], json={"name": f"CINV크루{TS}", "is_public": False}).json()["id"]
        # 비공개 크루 — B는 코드로 가입(A가 코드 발급 후)
        code0 = api(c, "POST", f"/crews/{crew}/invite", tk["a"]).json()["code"]
        assert api(c, "POST", "/crews/join-by-code", tk["b"], json={"code": code0}).status_code == 200
        ok("비공개 크루 + A(장)·B(멤버), C·D·E 비크루원")

        step("1. 크루원(B)이 C 초대 → 204 + crew_invited 알림 payload")
        r = api(c, "POST", f"/crews/{crew}/invitations", tk["b"], json={"user_id": uids["c"]})
        assert r.status_code == 204, f"초대 204 기대, got {r.status_code}: {r.text[:200]}"
        notifs = invited_notif(c, uids["c"])
        assert len(notifs) == 1, f"C에게 crew_invited 1건, got {len(notifs)}"
        n = notifs[0]
        assert n["actor_id"] == uids["b"] and n["target_type"] == "crew" and n["target_id"] == crew
        pl = n["payload"] or {}
        assert pl.get("invite_code") and pl.get("crew_id") == crew and pl.get("crew_name") == f"CINV크루{TS}", \
            f"payload 초대코드·crew_id·crew_name, got {pl}"
        invite_code = pl["invite_code"]
        ok("초대 204·crew_invited 알림·payload(초대코드·crew_id·crew_name)")

        step("2. 수신자(C) preview→join 왕복 (payload 초대코드로)")
        prev = api(c, "POST", "/crews/preview-by-code", tk["c"], json={"code": invite_code})
        assert prev.status_code == 200 and prev.json()["id"] == crew, "preview로 크루 확인"
        joined = api(c, "POST", "/crews/join-by-code", tk["c"], json={"code": invite_code})
        assert joined.status_code == 200, f"코드로 즉시 가입(비공개 무관), got {joined.status_code}"
        ok("preview→join 왕복 — 초대코드로 비공개 크루 즉시 가입")

        step("3. 이미 크루원(C) 재초대 → 409")
        r = api(c, "POST", f"/crews/{crew}/invitations", tk["b"], json={"user_id": uids["c"]})
        assert r.status_code == 409, f"이미 크루원 → 409, got {r.status_code}"
        ok("이미 크루원 재초대 409")

        step("4. 비크루원 발송자(E) 초대 시도 → 404 은닉")
        r = api(c, "POST", f"/crews/{crew}/invitations", tk["e"], json={"user_id": uids["d"]})
        assert r.status_code == 404, f"비크루원 발송자 → 404, got {r.status_code}"
        ok("비크루원 발송자 404 은닉")

        step("5. 차단 관계 대상 → 404 은닉 (알림 미생성)")
        # B가 D를 차단 → B가 D 초대 시 404
        assert api(c, "POST", f"/users/{uids['d']}/block", tk["b"]).status_code == 204
        r = api(c, "POST", f"/crews/{crew}/invitations", tk["b"], json={"user_id": uids["d"]})
        assert r.status_code == 404, f"차단 대상 초대 → 404, got {r.status_code}"
        assert len(invited_notif(c, uids["d"])) == 0, "차단 대상에게 알림 미생성"
        ok("차단 관계 대상 404·알림 미생성")

        step("6. 없는 유저 초대 → 404")
        r = api(c, "POST", f"/crews/{crew}/invitations", tk["b"], json={"user_id": str(uuid.uuid4())})
        assert r.status_code == 404, f"없는 유저 → 404, got {r.status_code}"
        ok("없는 유저 초대 404")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
