"""
Integration test: 알림 삭제 (DELETE /notifications/{id} · DELETE /notifications)
- 개별 삭제 → 목록에서 사라짐 + unread_count 반영, 남의 알림 404, 없는 id 404
- 전체 삭제 → 0건 + 멱등
- 회귀: 목록·read 처리 정상
Run: python tests/test_notification_delete_integration.py
"""
from __future__ import annotations

import os
import sys
import time

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys():
    anon = svc = ""
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                svc = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(m): print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")


def mkuser(c, e):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": e, "password": "TestPass123!", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    uid = r.json()["id"]
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": e, "password": "TestPass123!"})
    return uid, r.json()["access_token"]


def api(c, m, p, tok, **k):
    return c.request(m, f"{BASE}{p}", headers={"Authorization": f"Bearer {tok}"}, **k)


def del_in(c, table, col, vals):
    if vals:
        c.delete(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "return=minimal"},
                 params={col: f"in.({','.join(vals)})"})


def mk_noti(c, recipient, actor, type_, target_id, target_type):
    """알림 직접 삽입 (admin) — 발송 경로 우회해 결정적으로 시딩."""
    r = c.post(f"{_SB}/rest/v1/notifications", headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": recipient, "actor_id": actor, "type": type_,
                     "target_id": target_id, "target_type": target_type})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()[0]["id"]


def run():
    ts = int(time.time())
    uids = []
    with httpx.Client(timeout=40) as c:
        try:
            step("공용: A(수신자)·B(타인)")
            A_id, A = mkuser(c, f"nd-a-{ts}@t.l"); uids.append(A_id)
            B_id, B = mkuser(c, f"nd-b-{ts}@t.l"); uids.append(B_id)

            # A에게 알림 3개(전부 unread), B에게 1개
            n1 = mk_noti(c, A_id, B_id, "user_followed", B_id, "user")
            n2 = mk_noti(c, A_id, B_id, "route_liked", B_id, "route")
            n3 = mk_noti(c, A_id, B_id, "run_kudoed", B_id, "run")
            nb = mk_noti(c, B_id, A_id, "user_followed", A_id, "user")
            ok("A 알림 3개(unread), B 알림 1개")

            step("1. 개별 삭제 → 목록·unread_count 반영")
            assert api(c, "GET", "/notifications/unread-count", A).json() == 3 or \
                   api(c, "GET", "/notifications/unread-count", A).json()["count"] == 3
            uc0 = api(c, "GET", "/notifications/unread-count", A).json()
            uc0 = uc0["count"] if isinstance(uc0, dict) else uc0
            assert uc0 == 3, uc0
            assert api(c, "DELETE", f"/notifications/{n2}", A).status_code == 204
            ids = {n["id"] for n in api(c, "GET", "/notifications", A).json()}
            assert n2 not in ids and n1 in ids and n3 in ids, "삭제된 것만 사라짐"
            uc1 = api(c, "GET", "/notifications/unread-count", A).json()
            uc1 = uc1["count"] if isinstance(uc1, dict) else uc1
            assert uc1 == 2, f"unread 3→2 기대, got {uc1}"
            ok("개별 삭제 204 ✓ 목록에서 제거 ✓ unread 3→2 ✓")

            step("2. 남의 알림 삭제 404 (존재 은닉) + 없는 id 404")
            assert api(c, "DELETE", f"/notifications/{nb}", A).status_code == 404, "A가 B알림 삭제 불가"
            # B 알림은 여전히 존재
            assert nb in {n["id"] for n in api(c, "GET", "/notifications", B).json()}
            assert api(c, "DELETE", f"/notifications/{n2}", A).status_code == 404, "이미 없는 id 404"
            import uuid
            assert api(c, "DELETE", f"/notifications/{uuid.uuid4()}", A).status_code == 404
            ok("남의 알림 404 ✓ (그대로 존재) 없는/이미삭제 id 404 ✓")

            step("3. read 처리 회귀 (삭제와 공존)")
            assert api(c, "PATCH", f"/notifications/{n1}/read", A).status_code == 204
            uc2 = api(c, "GET", "/notifications/unread-count", A).json()
            uc2 = uc2["count"] if isinstance(uc2, dict) else uc2
            assert uc2 == 1, f"n1 읽음 → unread 1, got {uc2}"
            ok("개별 read 204 ✓ unread 2→1 ✓")

            step("4. 전체 삭제 → 0건 + 멱등")
            assert api(c, "DELETE", "/notifications", A).status_code == 204
            assert api(c, "GET", "/notifications", A).json() == [], "A 알림 전부 삭제"
            uc3 = api(c, "GET", "/notifications/unread-count", A).json()
            uc3 = uc3["count"] if isinstance(uc3, dict) else uc3
            assert uc3 == 0
            # 멱등: 다시 호출해도 204
            assert api(c, "DELETE", "/notifications", A).status_code == 204
            # B 알림은 안 건드림
            assert len(api(c, "GET", "/notifications", B).json()) == 1, "B 알림 보존"
            ok("전체 삭제 204 ✓ 0건·unread 0 ✓ 멱등 재호출 204 ✓ B 격리 ✓")

            print("\n" + "=" * 50); print("  ALL TESTS PASSED"); print("=" * 50)
        finally:
            step("Cleanup")
            del_in(c, "notifications", "user_id", uids)
            del_in(c, "profiles", "user_id", uids)
            for u in uids:
                c.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM)
            ok("notifications·profiles·auth 삭제")


if __name__ == "__main__":
    run()
