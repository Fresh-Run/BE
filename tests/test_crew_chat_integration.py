"""
Integration test: 크루 채팅 v1 (docs/CREW_CHAT_DESIGN.md)

멤버십 게이트(비크루원 404) / 역순 커서 / 반응 멱등·집계·my_reactions /
안읽은수 파생(본인 제외·읽음 후 0) / mute 토글 / 삭제 권한 매트릭스
(본인·운영진 O, 타 멤버 X, soft=content null) / 탈퇴 작성자 익명화.

Run: python tests/test_crew_chat_integration.py  (로컬 서버 필요)
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


def ok(m):        print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
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
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {token}"}, **kw)


def run_tests():
    c = httpx.Client(timeout=60)
    uids, tok = {}, {}
    try:
        step("0. O(owner)·M(member)·A(→admin)·X(비크루원)")
        for k in ("o", "m", "a", "x"):
            uids[k] = sb_user(c, f"chat-{k}-{TS}@test.com")
            tok[k] = sb_login(c, f"chat-{k}-{TS}@test.com")
            assert api(c, "PATCH", "/me/profile", tok[k],
                       json={"nickname": f"CHAT{k}{TS}"}).status_code == 200
        crew = api(c, "POST", "/crews", tok["o"], json={"name": f"채팅크루{TS}"}).json()["id"]
        for k in ("m", "a"):
            assert api(c, "POST", f"/crews/{crew}/join", tok[k]).status_code == 200
        api(c, "PATCH", f"/crews/{crew}/members/{uids['a']}/role", tok["o"], json={"role": "admin"})
        ok("크루 + 멤버(owner·member·admin) + 비크루원 X")

        step("1. 멤버십 게이트 — 비크루원은 전 채팅 경로 404")
        for method, path, body in [
            ("GET", f"/crews/{crew}/chat/messages", None),
            ("POST", f"/crews/{crew}/chat/messages", {"content": "몰래"}),
            ("GET", f"/crews/{crew}/chat/unread", None),
            ("POST", f"/crews/{crew}/chat/read", None),
        ]:
            r = api(c, method, path, tok["x"], **({"json": body} if body else {}))
            assert r.status_code == 404, f"{method} {path}: 비크루원 404 기대, got {r.status_code}"
        ok("목록·전송·안읽은수·읽음 전부 404 은닉 ✓")

        step("2. 전송 + 역순 커서")
        ids = []
        for i in range(5):
            r = api(c, "POST", f"/crews/{crew}/chat/messages", tok["m"],
                    json={"content": f"메시지{i}"})
            assert r.status_code == 201, r.text[:200]
            ids.append(r.json()["id"])
            time.sleep(0.05)  # created_at 분리
        page1 = api(c, "GET", f"/crews/{crew}/chat/messages?limit=2", tok["o"]).json()
        assert [m["content"] for m in page1] == ["메시지4", "메시지3"], page1
        before = page1[-1]["created_at"]
        page2 = api(c, "GET", f"/crews/{crew}/chat/messages?limit=2&before={before.replace('+00:00','Z')}", tok["o"]).json()
        assert [m["content"] for m in page2] == ["메시지2", "메시지1"], page2
        assert len({m["id"] for m in page1 + page2}) == 4, "커서 중복 없음"
        ok("전송 201 · 역순 최신 우선 · 커서 중복 0 ✓")

        step("3. 반응 — 멱등·집계·my_reactions·취소")
        mid = ids[4]
        assert api(c, "POST", f"/crews/{crew}/chat/messages/{mid}/react", tok["o"],
                   json={"emoji": "🔥"}).status_code == 204
        assert api(c, "POST", f"/crews/{crew}/chat/messages/{mid}/react", tok["o"],
                   json={"emoji": "🔥"}).status_code == 204  # 멱등
        assert api(c, "POST", f"/crews/{crew}/chat/messages/{mid}/react", tok["a"],
                   json={"emoji": "🔥"}).status_code == 204
        assert api(c, "POST", f"/crews/{crew}/chat/messages/{mid}/react", tok["o"],
                   json={"emoji": "👍"}).status_code == 204
        msgs = api(c, "GET", f"/crews/{crew}/chat/messages?limit=5", tok["o"]).json()
        top = next(m for m in msgs if m["id"] == mid)
        assert top["reactions"] == {"🔥": 2, "👍": 1}, top["reactions"]
        assert set(top["my_reactions"]) == {"🔥", "👍"}, top["my_reactions"]
        # 잘못된 이모지 422
        assert api(c, "POST", f"/crews/{crew}/chat/messages/{mid}/react", tok["o"],
                   json={"emoji": "😀"}).status_code == 422
        # 취소
        assert api(c, "DELETE", f"/crews/{crew}/chat/messages/{mid}/react", tok["o"],
                   json={"emoji": "🔥"}).status_code == 204
        top = next(m for m in api(c, "GET", f"/crews/{crew}/chat/messages", tok["o"]).json()
                   if m["id"] == mid)
        assert top["reactions"] == {"🔥": 1, "👍": 1}, top["reactions"]
        ok("멱등 · 집계 {🔥2,👍1} · my_reactions · 422 · 취소 ✓")

        step("4. 안 읽은 수 — 파생·본인 제외·읽음 후 0")
        # O 관점: M이 5개 보냄 → O는 5 안읽음(본인 것 아님)
        u = api(c, "GET", f"/crews/{crew}/chat/unread", tok["o"]).json()
        assert u["unread_count"] == 5 and u["muted"] is False, u
        # M 관점: 본인이 보낸 5개는 안읽음 아님 → 0
        um = api(c, "GET", f"/crews/{crew}/chat/unread", tok["m"]).json()
        assert um["unread_count"] == 0, f"본인 메시지는 제외: {um}"
        # O 읽음 처리 → 0
        assert api(c, "POST", f"/crews/{crew}/chat/read", tok["o"]).status_code == 204
        assert api(c, "GET", f"/crews/{crew}/chat/unread", tok["o"]).json()["unread_count"] == 0
        # M이 1개 더 → O는 1
        api(c, "POST", f"/crews/{crew}/chat/messages", tok["m"], json={"content": "새 메시지"})
        assert api(c, "GET", f"/crews/{crew}/chat/unread", tok["o"]).json()["unread_count"] == 1
        ok("파생 5 · 본인 제외 0 · 읽음 후 0 · 증가 1 ✓")

        step("5. mute — 토글·독립·유지")
        assert api(c, "PATCH", f"/crews/{crew}/chat/mute", tok["o"], json={"muted": True}).status_code == 204
        u = api(c, "GET", f"/crews/{crew}/chat/unread", tok["o"]).json()
        assert u["muted"] is True and u["unread_count"] == 1, "mute는 안읽은수와 독립"
        assert api(c, "PATCH", f"/crews/{crew}/chat/mute", tok["o"], json={"muted": False}).status_code == 204
        assert api(c, "GET", f"/crews/{crew}/chat/unread", tok["o"]).json()["muted"] is False
        ok("mute on/off · 안읽은수 독립 유지 ✓")

        step("6. 삭제 권한 매트릭스 + soft")
        target = ids[0]  # M이 쓴 메시지
        # 타 멤버(A, admin 아닌 관점? A는 admin이라 됨) — 순수 member가 남의 메시지 삭제 시도
        # O가 admin O 만들었으니 순수 member는 없음 → X는 비크루원. member 케이스는 M이 A 메시지.
        a_msg = api(c, "POST", f"/crews/{crew}/chat/messages", tok["a"],
                    json={"content": "admin 메시지"}).json()["id"]
        assert api(c, "DELETE", f"/crews/{crew}/chat/messages/{a_msg}", tok["m"]).status_code == 403, \
            "일반 멤버는 남의 메시지 삭제 불가"
        # 본인 삭제 O
        assert api(c, "DELETE", f"/crews/{crew}/chat/messages/{target}", tok["m"]).status_code == 204
        # 운영진(admin) 남의 메시지 삭제 O
        m_msg = api(c, "POST", f"/crews/{crew}/chat/messages", tok["m"],
                    json={"content": "지워질 메시지"}).json()["id"]
        assert api(c, "DELETE", f"/crews/{crew}/chat/messages/{m_msg}", tok["a"]).status_code == 204
        # soft 확인: content null·deleted true, 행은 남음
        allm = api(c, "GET", f"/crews/{crew}/chat/messages?limit=50", tok["o"]).json()
        deleted = {m["id"] for m in allm if m["deleted"]}
        assert target in deleted and m_msg in deleted, "soft 삭제 행 잔존"
        assert all(m["content"] is None for m in allm if m["id"] in deleted)
        ok("멤버 403 · 본인 204 · 운영진 204 · soft(content null·행 잔존) ✓")

        step("7. 탈퇴 작성자 익명화")
        # A(admin) 위임 없이 leave (owner 아니라 가능) → A 메시지 sender null
        assert api(c, "DELETE", f"/crews/{crew}/leave", tok["a"]).status_code == 204
        # A 계정 삭제 → set null
        assert api(c, "DELETE", "/me", tok["a"]).status_code == 204
        uids.pop("a")
        allm = api(c, "GET", f"/crews/{crew}/chat/messages?limit=50", tok["o"]).json()
        a_msgs = [m for m in allm if m["id"] == a_msg]  # a_msg는 위에서 삭제 안 됨
        assert a_msgs and a_msgs[0]["sender_id"] is None and a_msgs[0]["sender_nickname"] is None, \
            f"탈퇴 작성자 익명화: {a_msgs}"
        ok("탈퇴 후 sender_id·nickname null (본문 보존) ✓")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup: 탈퇴 cascade (크루 삭제 포함)")
        if "o" in uids:
            api(c, "DELETE", f"/crews/{crew}", tok["o"])  # 크루 삭제 → 메시지 cascade
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
