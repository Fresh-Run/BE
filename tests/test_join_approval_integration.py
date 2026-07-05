"""
Integration test: crew join approval flow
(join_policy, POST /join 200/202 분기, join-requests me/list/approve/reject)
Run: python tests/test_join_approval_integration.py
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"

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

def ok(m):   print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")

def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200,201): fail("create user", r.text[:200])
    return r.json()["id"]

def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type":"application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]

def sb_del_user(c, uid): c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)

def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer":"return=minimal"},
             params={col: f"in.({',' .join(vals)})"})

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def notis(c, tok, type_):
    r = api(c, "GET", "/notifications", tok, params={"limit": 50})
    return [n for n in r.json() if n["type"] == type_]


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"ja-u{i}-{ts}@t.l" for i in range(1,5)]
    uids: list[str] = []
    toks: list[str] = []
    crew_ids: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 4명 + 크루 3개 ───────────────────────────────────
            step("1. u1(크루장)~u4 + 크루 3개 (open/approval/비공개-approval)")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2, uid3, uid4 = uids; tok1, tok2, tok3, tok4 = toks
            for i, tok in enumerate(toks, start=1):
                assert api(c, "PATCH", "/me/profile", tok,
                           json={"nickname": f"승인u{i}-{ts%100000}"}).status_code == 200
            def make_crew(body):
                r = api(c, "POST", "/crews", tok1, json=body)
                assert r.status_code in (200, 201), r.text[:200]
                crew_ids.append(r.json()["id"])
                return r.json()
            open_crew = make_crew({"name": f"오픈크루-{ts}"})
            appr_crew = make_crew({"name": f"승인크루-{ts}", "join_policy": "approval"})
            priv_crew = make_crew({"name": f"비공개크루-{ts}", "join_policy": "approval",
                                   "is_public": False})
            assert open_crew["join_policy"] == "open", "기본값 open"
            assert appr_crew["join_policy"] == "approval"
            OPEN, APPR, PRIV = open_crew["id"], appr_crew["id"], priv_crew["id"]
            ok("기본 open ✓ 생성 시 approval 지정 ✓")

            # ── 2. open 크루 회귀: 기존 동작 그대로 ──────────────────────
            step("2. open 크루: 200 즉시 가입 + crew_joined 알림 (회귀)")
            r = api(c, "POST", f"/crews/{OPEN}/join", tok2)
            assert r.status_code == 200, f"open join → 200, got {r.status_code}"
            body = r.json()
            assert body["member_count"] == 2 and body["id"] == OPEN, "기존 CrewResponse 그대로"
            assert len(notis(c, tok1, "crew_joined")) == 1, "크루장에게 crew_joined"
            ok("200 + CrewResponse ✓ crew_joined 알림 ✓")

            # ── 3. approval 크루: 202 신청 + 중복 409 ────────────────────
            step("3. approval: 202 pending + join_requested 알림 + 중복 409")
            r = api(c, "POST", f"/crews/{APPR}/join", tok2)
            assert r.status_code == 202, f"approval join → 202, got {r.status_code}"
            jr = r.json()
            assert jr["status"] == "pending" and jr["user_id"] == uid2
            assert jr["nickname"] == f"승인u2-{ts%100000}"
            ns = notis(c, tok1, "join_requested")
            assert len(ns) == 1 and ns[0]["actor_id"] == uid2 and ns[0]["target_id"] == APPR
            r = api(c, "POST", f"/crews/{APPR}/join", tok2)
            assert r.status_code == 409 and r.json()["detail"]["error"] == "already_requested"
            ok("202 pending ✓ 크루장 알림 ✓ 중복 신청 409 ✓")

            # ── 4. 신청자: 상태 조회 + 취소(멱등) + 재신청 ────────────────
            step("4. me 조회/취소/재신청")
            r = api(c, "GET", f"/crews/{APPR}/join-requests/me", tok2)
            assert r.status_code == 200 and r.json()["status"] == "pending"
            assert api(c, "DELETE", f"/crews/{APPR}/join-requests/me", tok2).status_code == 204
            assert api(c, "GET", f"/crews/{APPR}/join-requests/me", tok2).status_code == 404
            assert api(c, "DELETE", f"/crews/{APPR}/join-requests/me", tok2).status_code == 204, "재취소 멱등"
            r = api(c, "POST", f"/crews/{APPR}/join", tok2)   # 재신청
            assert r.status_code == 202
            req_u2 = r.json()["id"]
            r = api(c, "POST", f"/crews/{APPR}/join", tok3)   # u3도 신청
            assert r.status_code == 202
            req_u3 = r.json()["id"]
            ok("상태 조회 ✓ 취소 204+404 ✓ 재취소 멱등 ✓ 재신청 ✓")

            # ── 5. 크루장: 목록 + 승인 + 거절 ────────────────────────────
            step("5. 목록(비크루장 403) → u2 승인 → u3 거절")
            assert api(c, "GET", f"/crews/{APPR}/join-requests", tok3).status_code == 403
            r = api(c, "GET", f"/crews/{APPR}/join-requests", tok1)
            items = r.json()
            assert [i["id"] for i in items] == [req_u3, req_u2], "최신순 [u3, u2]"
            assert items[1]["nickname"] == f"승인u2-{ts%100000}", "닉네임 배치"
            # 승인
            joined_before = len(notis(c, tok1, "crew_joined"))
            assert api(c, "POST", f"/crews/{APPR}/join-requests/{req_u2}/approve", tok1).status_code == 204
            r = api(c, "POST", f"/crews/{APPR}/join", tok2)
            assert r.status_code == 409 and "Already a member" in r.text, "승인 후 이미 멤버"
            ns = notis(c, tok2, "join_approved")
            assert len(ns) == 1 and ns[0]["actor_id"] == uid1 and ns[0]["target_id"] == APPR
            assert len(notis(c, tok1, "crew_joined")) == joined_before, \
                "승인 가입은 crew_joined 알림 생략"
            assert api(c, "GET", f"/crews/{APPR}/join-requests/me", tok2).json()["status"] == "approved"
            # 이미 결정된 신청 재승인/거절 → 404
            assert api(c, "POST", f"/crews/{APPR}/join-requests/{req_u2}/approve", tok1).status_code == 404
            assert api(c, "POST", f"/crews/{APPR}/join-requests/{req_u2}/reject", tok1).status_code == 404
            # 거절 (무알림)
            assert api(c, "POST", f"/crews/{APPR}/join-requests/{req_u3}/reject", tok1).status_code == 204
            assert api(c, "GET", f"/crews/{APPR}/join-requests/me", tok3).json()["status"] == "rejected"
            assert notis(c, tok3, "join_approved") == [], "거절은 무알림"
            ok("목록 최신순+닉네임 ✓ 승인→멤버+알림 ✓ crew_joined 생략 ✓ 결정된 건 404 ✓ 거절 무알림 ✓")

            # ── 6. 거절 후 재신청 ─────────────────────────────────────────
            step("6. u3 거절 후 재신청 → 202")
            r = api(c, "POST", f"/crews/{APPR}/join", tok3)
            assert r.status_code == 202, f"거절 후 재신청 → 202, got {r.status_code}"
            ok("재신청 허용 ✓ (거절 이력 유지)")

            # ── 7. 정원: 신청은 되고 승인 시점 409 ────────────────────────
            step("7. 정원 1명 크루: 신청 202, 승인 409, pending 유지")
            r = api(c, "POST", "/crews", tok1,
                    json={"name": f"풀크루-{ts}", "join_policy": "approval", "max_members": 1})
            FULL = r.json()["id"]; crew_ids.append(FULL)
            r = api(c, "POST", f"/crews/{FULL}/join", tok4)
            assert r.status_code == 202, "정원 차도 신청은 가능"
            req_u4_full = r.json()["id"]
            r = api(c, "POST", f"/crews/{FULL}/join-requests/{req_u4_full}/approve", tok1)
            assert r.status_code == 409, f"정원 초과 승인 → 409, got {r.status_code}"
            assert api(c, "GET", f"/crews/{FULL}/join-requests/me", tok4).json()["status"] == "pending", \
                "승인 실패 시 pending 유지"
            ok("신청 202 ✓ 승인 시점 CrewFull 409 ✓ pending 유지 ✓")

            # ── 8. approval → open 전환 ──────────────────────────────────
            step("8. 전환: 대기자 직접 가입 + pending 자동 삭제 + 잔여 신청 승인 가능")
            r = api(c, "POST", f"/crews/{APPR}/join", tok4)   # 전환 전 u4 신청 (잔여용)
            assert r.status_code == 202
            req_u4 = r.json()["id"]
            r = api(c, "PATCH", f"/crews/{APPR}", tok1, json={"join_policy": "open"})
            assert r.status_code == 200 and r.json()["join_policy"] == "open"
            # u3(pending 보유)가 그냥 join → 즉시 가입 + 본인 pending 자동 삭제
            r = api(c, "POST", f"/crews/{APPR}/join", tok3)
            assert r.status_code == 200, f"open 전환 후 join → 200, got {r.status_code}"
            pend = [i["user_id"] for i in api(c, "GET", f"/crews/{APPR}/join-requests", tok1).json()]
            assert uid3 not in pend, "가입 성공 시 본인 pending 자동 삭제"
            assert uid4 in pend, "u4 신청은 남아 있어야 함"
            # 크루장은 남은 신청 계속 처리 가능 (policy와 무관)
            assert api(c, "POST", f"/crews/{APPR}/join-requests/{req_u4}/approve", tok1).status_code == 204
            assert len(notis(c, tok4, "join_approved")) == 1
            ok("전환 후 직접 가입 200 ✓ pending 자동 삭제 ✓ 잔여 신청 승인 ✓")

            # ── 9. 비공개 크루: 기존 403 유지 ─────────────────────────────
            step("9. 비공개 크루 join → 403 (join_policy 무관)")
            r = api(c, "POST", f"/crews/{PRIV}/join", tok2)
            assert r.status_code == 403, f"비공개 → 403, got {r.status_code}"
            ok("CrewAccessDenied 유지 ✓")

            # ── 10. 회귀 보강: 멤버 join → 409 + DB에 행이 안 생겼는지 ────
            step("10. approval 크루 멤버 join → 409 + 신청 테이블 행 미생성 (DB 확인)")
            # 8번에서 open으로 바꿨으니 리포트 시나리오(승인제) 그대로 복원
            assert api(c, "PATCH", f"/crews/{APPR}", tok1,
                       json={"join_policy": "approval"}).status_code == 200
            r = api(c, "POST", f"/crews/{APPR}/join", tok2)   # u2는 5번에서 승인된 멤버
            assert r.status_code == 409 and "Already a member" in r.text
            rows = c.get(f"{_SB}/rest/v1/crew_join_requests", headers=_ADM,
                         params={"crew_id": f"eq.{APPR}", "user_id": f"eq.{uid2}",
                                 "select": "status"}).json()
            assert [x["status"] for x in rows] == ["approved"], \
                f"409일 때 새 pending이 생기면 안 됨, got {rows}"
            ok("멤버 join 409 ✓ approved 1행만 존재 (pending 미생성) ✓")

            # ── 11. 레이스 방어: 멤버십 체크와 insert 사이에 승인이 끼는 경우 ──
            # 순차 HTTP로는 재현 불가한 TOCTOU — _is_member를 [False, True]로
            # 패치해 "pre-check 시점엔 비멤버, insert 직후엔 멤버"를 시뮬레이션.
            step("11. 레이스 시뮬레이션: pre-check 통과 후 승인 끼어듦 → 409 + 보상 삭제")
            import asyncio as _aio
            from unittest.mock import AsyncMock as _AM, patch as _patch
            ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            if ROOT not in sys.path:
                sys.path.insert(0, ROOT)
            from app.services import crew_service as _cs
            with _patch.object(_cs, "_is_member", _AM(side_effect=[False, True])):
                try:
                    _aio.run(_cs.join_crew(APPR, uid2))
                    fail("레이스에서 AlreadyMember가 나와야 함")
                except _cs.AlreadyMember:
                    pass
            rows = c.get(f"{_SB}/rest/v1/crew_join_requests", headers=_ADM,
                         params={"crew_id": f"eq.{APPR}", "user_id": f"eq.{uid2}",
                                 "select": "status"}).json()
            assert [x["status"] for x in rows] == ["approved"], \
                f"레이스로 삽입된 pending은 보상 삭제돼야 함, got {rows}"
            ok("레이스 → AlreadyMember ✓ 삽입된 pending 보상 삭제 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "crews", "id", crew_ids)   # members/join_requests CASCADE
            ok("crews 삭제 (CASCADE)")
            sb_del_in(c, "notifications", "user_id", [u for u in uids if u])
            sb_del_in(c, "notifications", "actor_id", [u for u in uids if u])
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("notifications·profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
