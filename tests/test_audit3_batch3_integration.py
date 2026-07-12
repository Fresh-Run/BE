"""
Integration test: 감사 3차 배치3 — M-9·M-11·M-12

M-9 : soft-deleted 채팅 메시지엔 새 반응 불가(404). 살아있는 메시지는 204.
M-11: 로드 시 _TEMPLATES ⊆ _CATEGORY 정합(카테고리 없는 발송 type 없음) — in-process.
M-12: 프로필 최초 생성이 upsert(on_conflict)라 재시도/재PATCH 멱등(레이스 흡수).

Run: python tests/test_audit3_batch3_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("M-11. _TEMPLATES ⊆ _CATEGORY 정합 (in-process, 로드 시 assert)")
        from app.services import push_service
        missing = set(push_service._TEMPLATES) - set(push_service._CATEGORY)
        assert not missing, f"카테고리 없는 발송 type: {missing}"
        # 모든 카테고리 키가 NotifSettings 필드에 존재하는지도 확인(getattr 안전)
        from app.models.schemas import NotifSettings
        fields = set(NotifSettings.model_fields)
        bad = {v for v in push_service._CATEGORY.values() if v not in fields}
        assert not bad, f"NotifSettings에 없는 카테고리: {bad}"
        ok(f"발송 {len(push_service._TEMPLATES)}종 전부 카테고리 매핑 + 필드 존재")

        step("0. 크루장 A")
        uids["a"] = sb_user(c, f"a3b3-a-{TS}@test.com")
        ta = sb_login(c, f"a3b3-a-{TS}@test.com")
        assert api(c, "PATCH", "/me/profile", ta, json={"nickname": f"A3B3{TS}"}).status_code == 200
        crew = api(c, "POST", "/crews", ta, json={"name": f"A3B3크루{TS}"}).json()["id"]
        ok("크루장 + 크루")

        step("M-9. soft-deleted 메시지 반응 → 404 (살아있는 메시지는 204)")
        msg = api(c, "POST", f"/crews/{crew}/chat/messages", ta, json={"content": "안녕"}).json()
        mid = msg["id"]
        # 살아있는 메시지엔 반응 204
        assert api(c, "POST", f"/crews/{crew}/chat/messages/{mid}/react", ta,
                   json={"emoji": "🔥"}).status_code == 204, "살아있는 메시지 반응 204"
        # soft-delete
        assert api(c, "DELETE", f"/crews/{crew}/chat/messages/{mid}", ta).status_code == 204
        # 삭제된 메시지에 새 반응 → 404
        r = api(c, "POST", f"/crews/{crew}/chat/messages/{mid}/react", ta, json={"emoji": "👍"})
        assert r.status_code == 404, f"soft-deleted 반응 → 404 기대, got {r.status_code}"
        # 기존 반응은 유지(삭제가 반응을 지우지 않음) — DB 확인
        cnt = c.get(f"{_SB}/rest/v1/crew_message_reactions", headers={**_ADM, "Prefer": "count=exact"},
                    params={"message_id": f"eq.{mid}", "select": "emoji", "limit": 1})
        n = int(cnt.headers.get("content-range", "?/0").split("/")[-1])
        assert n == 1, f"기존 🔥 반응은 유지(신규만 차단), got {n}"
        ok("soft-deleted 신규 반응 404 · 기존 반응 유지 · 살아있는 메시지 204")

        step("M-12. 프로필 최초 생성 멱등 (upsert on_conflict — 재PATCH 안전)")
        uids["b"] = sb_user(c, f"a3b3-b-{TS}@test.com")
        tb = sb_login(c, f"a3b3-b-{TS}@test.com")
        nick = f"A3B3B{TS}"
        r1 = api(c, "PATCH", "/me/profile", tb, json={"nickname": nick, "visibility": "private"})
        assert r1.status_code == 200 and r1.json()["visibility"] == "private", "최초 생성 200"
        # 재PATCH(이제 갱신 경로) — 멱등, 500/409 없이 200
        r2 = api(c, "PATCH", "/me/profile", tb, json={"nickname": nick})
        assert r2.status_code == 200, f"재PATCH 200 기대, got {r2.status_code}: {r2.text[:150]}"
        assert r2.json()["visibility"] == "private", "생략 필드(visibility) 보존"
        # 프로필 행은 정확히 1개(중복 생성 없음)
        cnt = c.get(f"{_SB}/rest/v1/profiles", headers={**_ADM, "Prefer": "count=exact"},
                    params={"user_id": f"eq.{uids['b']}", "select": "user_id", "limit": 1})
        assert int(cnt.headers.get("content-range", "?/0").split("/")[-1]) == 1, "프로필 행 1개"
        ok("최초 생성 200 · 재PATCH 멱등 200 · 행 1개 · 생략 필드 보존")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
