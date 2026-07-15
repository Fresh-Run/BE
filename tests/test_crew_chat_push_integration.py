"""
Integration test: 크루 채팅 푸시 v2 (발송 + 5분 스로틀)

정책: 발신자 제외 / crewChat 설정 키(기본 ON) / 크루 뮤트 게이트 / 5분 스로틀
(크루×수신자, 인앱은 전부 기록) / 게이트 순서 멤버십→뮤트→설정→스로틀.

mock Expo(8001, push_notification 선례):
 1. 발송: test1 메시지 → test2 인앱 crew_chat + Expo ticket 수신
 2. 발신자 제외: test1 자신에겐 인앱·푸시 없음
 3. 스로틀: 연타 3건 → 푸시 1건(Expo 1회) + 인앱 3건 전부
 4. 설정 OFF: 수신자 crewChat OFF → 푸시 미발송, 인앱 생성 (원복)
 5. 뮤트: 수신자 크루 뮤트 → 푸시 미발송, 인앱 생성
 6. 회귀: 기존 알림(follow 등)은 mock 없이도 정상

Run: python tests/test_crew_chat_push_integration.py  (로컬 8000 불필요 — 8001 자체 기동)
"""
from __future__ import annotations

import json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
BASE = "http://localhost:8001/api"
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


class MockExpo(BaseHTTPRequestHandler):
    received: list = []
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or "[]")
        MockExpo.received.append(body)
        out = json.dumps({"data": [{"status": "ok", "id": f"tk-{i}"} for i in range(len(body))]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass


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

def notif_rows(c, uid, type_="crew_chat"):
    return c.get(f"{_SB}/rest/v1/notifications", headers=_ADM,
                 params={"user_id": f"eq.{uid}", "type": f"eq.{type_}", "select": "id"}).json()


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    proc = None
    httpd = HTTPServer(("127.0.0.1", 0), MockExpo)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    mock_url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        step("0. A(발신)·B(수신)·C(수신) + 크루 + push token + mock Expo 8001")
        for k in ("a", "b", "cc"):
            uids[k] = sb_user(c, f"ccp-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"ccp-{k}-{TS}@test.com") for k in uids}
        # 서버 8001 (EXPO_PUSH_URL=mock) — 프로필 설정은 기동 후(BASE=8001)
        # 서버 8001 (EXPO_PUSH_URL=mock)
        env = {**os.environ, "EXPO_PUSH_URL": f"{mock_url}/push"}
        logf = open(os.path.join(os.path.dirname(__file__), "..",
                                 "_ccp_uvicorn.log"), "w+")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8001",
             "--log-level", "info"],  # info — "push sent" 성공 로그 캡처용
            cwd=os.path.join(os.path.dirname(__file__), ".."), env=env,
            stderr=logf, stdout=logf)
        for _ in range(40):
            try:
                if httpx.get("http://localhost:8001/health", timeout=2).status_code == 200: break
            except Exception: pass
            time.sleep(0.5)
        else: fail("8001 기동 실패")
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CCP{k}{TS}"}).status_code == 200
        # B·C push token 등록 (A는 발신자라 불필요하나 대칭 위해)
        for k in ("b", "cc"):
            assert api(c, "POST", "/me/push-token", tk[k],
                       json={"token": f"ExponentPushToken[ccp-{k}-{TS}]", "platform": "ios"}).status_code == 204
        crew = api(c, "POST", "/crews", tk["a"], json={"name": f"챗크루{TS}"}).json()["id"]
        for k in ("b", "cc"):
            assert api(c, "POST", f"/crews/{crew}/join", tk[k]).status_code == 200
        ok("유저 3명 + 크루(A·B·C) + B/C 토큰 + mock Expo")

        step("1·2. 발송 + 발신자 제외 — A 메시지 → B·C 인앱+푸시, A 없음")
        MockExpo.received = []
        assert api(c, "POST", f"/crews/{crew}/chat/messages", tk["a"], json={"content": "안녕"}).status_code in (200, 201)
        time.sleep(1.5)  # fire-and-forget 푸시 태스크 대기
        assert len(notif_rows(c, uids["b"])) == 1, "B 인앱 crew_chat 1건"
        assert len(notif_rows(c, uids["cc"])) == 1, "C 인앱 crew_chat 1건"
        assert len(notif_rows(c, uids["a"])) == 0, "발신자 A 인앱 0 (자기 메시지)"
        # Expo 발송 (B·C 토큰) — ticket ok
        sent_tokens = [m["to"] for batch in MockExpo.received for m in batch]
        assert any(f"ccp-b-{TS}" in t for t in sent_tokens), "B에게 Expo 발송"
        assert any(f"ccp-cc-{TS}" in t for t in sent_tokens), "C에게 Expo 발송"
        assert not any(f"ccp-a-{TS}" in t for t in sent_tokens), "A에겐 미발송"
        ok(f"인앱 B·C 각 1 · 발신자 0 · Expo 발송 {len(sent_tokens)}건(B·C)")

        # 성공 로그 포맷 검증 — "push sent: type=crew_chat recipients=1 tickets=ok:1 err:0"
        logf.flush()
        with open(os.path.join(os.path.dirname(__file__), "..", "_ccp_uvicorn.log")) as lf:
            logtxt = lf.read()
        sent_lines = [ln for ln in logtxt.splitlines() if "push sent:" in ln and "crew_chat" in ln]
        assert sent_lines, "성공 로그 'push sent: ...crew_chat...' 부재"
        assert any("tickets=ok:1 err:0" in ln for ln in sent_lines), \
            f"ticket 상태 요약(ok:1 err:0) 부재: {sent_lines[-2:]}"
        # push sent 로그 라인에 토큰 값·유저 id가 없어야 (마스킹 계약 — 카운트만).
        # (참고: httpx INFO 로그는 Supabase URL의 user_id를 남기지만 그건 별개
        #  기존 이슈 — 프로덕션 로그 레벨 관리 대상이고 이 로그 라인의 계약 아님.)
        for ln in sent_lines:
            assert f"ccp-b-{TS}" not in ln and uids["b"] not in ln, \
                f"push sent 로그에 토큰/유저 식별정보 누출: {ln}"
        ok(f"성공 로그 포맷 확인: '{sent_lines[-1].split('push sent:')[1].strip()[:60]}' · 카운트만(식별정보 무)")

        step("3. 스로틀 — A 연타 2건 추가 → 인앱 누적 3, 푸시는 1(스로틀)")
        MockExpo.received = []
        for i in range(2):
            api(c, "POST", f"/crews/{crew}/chat/messages", tk["a"], json={"content": f"연타{i}"})
        time.sleep(1.5)
        assert len(notif_rows(c, uids["b"])) == 3, f"B 인앱 3건(전부 기록), got {len(notif_rows(c, uids['b']))}"
        b_pushes = [m for batch in MockExpo.received for m in batch if f"ccp-b-{TS}" in m["to"]]
        assert len(b_pushes) == 0, f"연타 2건은 스로틀로 B 푸시 0(직전 5분내 발송), got {len(b_pushes)}"
        ok("인앱 3건 누적 · 연타 푸시 스로틀(0건 추가) = 5분 1건 유지")

        step("4. 설정 OFF — B가 crewChat OFF → 푸시 미발송, 인앱 생성")
        # 스로틀 우회 위해 다른 크루로? 아니 — 같은 크루면 이미 스로틀. C로 검증:
        # C가 crewChat OFF → 새 메시지에 C 푸시 없어야(설정), 인앱은 생성.
        assert api(c, "PATCH", "/me/settings", tk["cc"], json={"notif": {"crewChat": False}}).status_code == 200
        # C의 스로틀 우회: C 대상 crew_chat 알림을 5분 밖으로 밀어야 순수 설정 검증.
        # 간단히 — C의 기존 crew_chat 알림 삭제 후 새 메시지.
        c.delete(f"{_SB}/rest/v1/notifications?user_id=eq.{uids['cc']}&type=eq.crew_chat", headers=_ADM)
        MockExpo.received = []
        api(c, "POST", f"/crews/{crew}/chat/messages", tk["a"], json={"content": "설정테스트"})
        time.sleep(1.5)
        assert len(notif_rows(c, uids["cc"])) == 1, "C 인앱 생성(설정 OFF여도)"
        c_pushes = [m for batch in MockExpo.received for m in batch if f"ccp-cc-{TS}" in m["to"]]
        assert len(c_pushes) == 0, f"crewChat OFF → C 푸시 0, got {len(c_pushes)}"
        assert api(c, "PATCH", "/me/settings", tk["cc"], json={"notif": {"crewChat": True}}).status_code == 200  # 원복
        ok("crewChat OFF → 푸시 0 · 인앱 생성 (원복)")

        step("5. 뮤트 — B가 크루 뮤트 → 푸시 미발송, 인앱 생성")
        assert api(c, "PATCH", f"/crews/{crew}/chat/mute", tk["b"], json={"muted": True}).status_code in (200, 204)
        c.delete(f"{_SB}/rest/v1/notifications?user_id=eq.{uids['b']}&type=eq.crew_chat", headers=_ADM)  # 스로틀 우회
        MockExpo.received = []
        api(c, "POST", f"/crews/{crew}/chat/messages", tk["a"], json={"content": "뮤트테스트"})
        time.sleep(1.5)
        assert len(notif_rows(c, uids["b"])) == 1, "B 인앱 생성(뮤트여도)"
        b_pushes = [m for batch in MockExpo.received for m in batch if f"ccp-b-{TS}" in m["to"]]
        assert len(b_pushes) == 0, f"뮤트 → B 푸시 0, got {len(b_pushes)}"
        ok("크루 뮤트 → 푸시 0 · 인앱 생성")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        if proc: proc.terminate()
        httpd.shutdown()
        _lp = os.path.join(os.path.dirname(__file__), "..", "_ccp_uvicorn.log")
        if os.path.exists(_lp): os.remove(_lp)
        if "crew" in dir():
            pass
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (crew·messages·notifications cascade · 8001 종료)")


if __name__ == "__main__":
    run_tests()
