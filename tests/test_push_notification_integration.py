"""
Integration test: 원격 푸시 (Expo) — docs/PUSH_NOTIFICATION_DESIGN.md

1) 토큰 CRUD (본 서버 8000): 등록 멱등 / 같은 토큰 재로그인 소유 이전 /
   형식 422 / 해제 멱등·남의 토큰 불가
2) 발송 훅 (mock Expo + uvicorn 8001): 팔로우 → 푸시 수신(제목·닉네임 본문·
   딥링크 data) / lang=en 영어 문구 / mock 500이어도 본 요청 정상 + 인앱 알림
   존재(비차단) / DeviceNotRegistered 티켓 → 토큰 자동 정리
3) 실 Expo 1회: 유효 형식 가짜 토큰 → 티켓 응답 체계 확인

Run: python tests/test_push_notification_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
    anon = svc = ""
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):              anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}
TS = int(time.time())


def ok(m):        print(f"  ✓ {m}")
def warn(m):      print(f"  ⚠ {m}")
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


def api(c, method, path, token, base=BASE, **kw):
    return c.request(method, f"{base}{path}",
                     headers={"Authorization": f"Bearer {token}"}, **kw)


def token_rows(c, token):
    return c.get(f"{_SB}/rest/v1/push_tokens", headers=_ADM,
                 params={"token": f"eq.{token}", "select": "user_id,platform"}).json()


TOK1 = f"ExponentPushToken[pytest-{TS}-1]"
TOK2 = f"ExponentPushToken[pytest-{TS}-2]"


class MockExpo(BaseHTTPRequestHandler):
    received: list = []
    mode = "ok"  # ok | dead | boom

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        MockExpo.received.append(body)
        if MockExpo.mode == "boom":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"{}")
            return
        tickets = []
        for _ in body:
            if MockExpo.mode == "dead":
                tickets.append({"status": "error", "message": "gone",
                                "details": {"error": "DeviceNotRegistered"}})
            else:
                tickets.append({"status": "ok", "id": "ticket-id"})
        out = json.dumps({"data": tickets}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def run_tests():
    c = httpx.Client(timeout=60)
    uids, toks = {}, {}
    proc = None
    httpd = HTTPServer(("127.0.0.1", 0), MockExpo)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    mock_url = f"http://127.0.0.1:{httpd.server_address[1]}/push"
    try:
        step("0. 유저 A(행위자)·B(수신자)·C(소유 이전용)")
        for k in ("a", "b", "cc"):
            uids[k] = sb_user(c, f"push-{k}-{TS}@test.com")
            toks[k] = sb_login(c, f"push-{k}-{TS}@test.com")
            assert api(c, "PATCH", "/me/profile", toks[k],
                       json={"nickname": f"푸시{k}{TS}"}).status_code == 200
        ok("유저 3명")

        step("1. 토큰 CRUD (본 서버)")
        for _ in range(2):  # 멱등
            assert api(c, "POST", "/me/push-token", toks["b"],
                       json={"token": TOK1, "platform": "ios"}).status_code == 204
        rows = token_rows(c, TOK1)
        assert len(rows) == 1 and rows[0]["user_id"] == uids["b"], rows
        # 같은 기기 다른 계정 → 소유 이전
        assert api(c, "POST", "/me/push-token", toks["cc"],
                   json={"token": TOK1, "platform": "ios"}).status_code == 204
        rows = token_rows(c, TOK1)
        assert len(rows) == 1 and rows[0]["user_id"] == uids["cc"], "소유 이전"
        # B로 원복 + 형식 422 + 남의 토큰 삭제 불가 + 해제 멱등
        api(c, "POST", "/me/push-token", toks["b"], json={"token": TOK1, "platform": "ios"})
        assert api(c, "POST", "/me/push-token", toks["b"],
                   json={"token": "garbage", "platform": "ios"}).status_code == 422
        assert api(c, "DELETE", "/me/push-token", toks["cc"],
                   json={"token": TOK1, "platform": "ios"}).status_code == 204
        assert len(token_rows(c, TOK1)) == 1, "남의 토큰 삭제는 no-op"
        ok("멱등 ✓ 소유 이전 ✓ 422 ✓ 타인 해제 no-op ✓")

        # 감사 M-B: 유저당 10대 초과 등록 → 오래된 것 정리
        for i in range(12):
            assert api(c, "POST", "/me/push-token", toks["cc"],
                       json={"token": f"ExponentPushToken[cap-{TS}-{i}]",
                             "platform": "ios"}).status_code == 204
        cnt = c.get(f"{_SB}/rest/v1/push_tokens", headers={**_ADM, "Prefer": "count=exact"},
                    params={"user_id": f"eq.{uids['cc']}", "select": "token", "limit": 1}
                    ).headers.get("content-range", "?").split("/")[-1]
        assert cnt == "10", f"유저당 토큰 상한 10 유지: {cnt}"
        ok("12개 등록 → 10개 유지 (상한 정리) ✓")

        step("2. mock Expo 서버로 발송 훅 검증 (uvicorn 8001)")
        env = {**os.environ, "EXPO_PUSH_URL": mock_url}
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8001",
             "--log-level", "warning"],
            cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        B8001 = "http://localhost:8001/api"
        for _ in range(30):
            try:
                if httpx.get("http://localhost:8001/docs", timeout=2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            fail("uvicorn(8001) 기동 실패")

        # 2-1. 정상 발송: A가 B를 팔로우 → user_followed 푸시
        MockExpo.mode, MockExpo.received = "ok", []
        r = api(c, "POST", f"/users/{uids['b']}/follow", toks["a"], base=B8001)
        assert r.status_code == 204, r.text[:200]
        time.sleep(2)  # fire-and-forget 태스크 대기
        assert MockExpo.received, "mock Expo가 발송을 받아야"
        msg = MockExpo.received[-1][0]
        assert msg["to"] == TOK1 and msg["title"] == "FreshRun"
        assert f"푸시a{TS}" in msg["body"] and "팔로우" in msg["body"], msg["body"]
        assert msg["data"]["type"] == "user_followed" and msg["data"]["target_id"] == uids["a"]
        ok(f"발송 ✓ 본문 '{msg['body']}' ✓ 딥링크 data ✓")

        # 2-2. lang=en 수신자 → 영어 문구
        assert api(c, "PATCH", "/me/settings", toks["b"], base=B8001,
                   json={"lang": "en"}).status_code == 200
        MockExpo.received = []
        api(c, "DELETE", f"/users/{uids['b']}/follow", toks["a"], base=B8001)
        r = api(c, "POST", f"/users/{uids['b']}/follow", toks["a"], base=B8001)
        assert r.status_code == 204
        time.sleep(2)
        msg = MockExpo.received[-1][0]
        assert "following you" in msg["body"], msg["body"]
        ok(f"영어 문구 ✓ '{msg['body']}'")

        # 2-3. 비차단: mock 500이어도 본 요청 정상 + 인앱 알림 존재
        MockExpo.mode, MockExpo.received = "boom", []
        r = api(c, "POST", f"/runs", toks["b"], base=B8001, json={
            "distance_km": 3.0, "duration_sec": 1200, "visibility": "public",
            "ran_at": "2026-07-11T10:00:00+09:00"})
        run_id = r.json()["id"]
        r = api(c, "POST", f"/runs/{run_id}/kudos", toks["a"], base=B8001)
        assert r.status_code == 204, f"Expo 500이어도 kudos 정상: {r.status_code}"
        time.sleep(2)
        notifs = api(c, "GET", "/notifications", toks["b"], base=B8001).json()
        assert any(n["type"] == "run_kudoed" for n in notifs), "인앱 알림은 존재해야"
        assert MockExpo.received, "발송 시도는 있었어야 (500으로 드랍)"
        ok("Expo 500 → 본 요청 204 + 인앱 알림 존재 (비차단) ✓")

        # 2-4. DeviceNotRegistered → 토큰 자동 정리
        MockExpo.mode, MockExpo.received = "dead", []
        api(c, "DELETE", f"/runs/{run_id}/kudos", toks["a"], base=B8001)
        r = api(c, "POST", f"/runs/{run_id}/kudos", toks["a"], base=B8001)
        assert r.status_code == 204
        time.sleep(2)
        assert token_rows(c, TOK1) == [], "DeviceNotRegistered 토큰은 삭제돼야"
        ok("죽은 토큰 자동 정리 ✓")

        step("3. 실 Expo 티켓 스모크 1회 (가짜 유효 형식 토큰)")
        real = httpx.post("https://exp.host/--/api/v2/push/send",
                          json=[{"to": TOK2, "title": "t", "body": "b"}], timeout=15)
        tickets = real.json().get("data")
        assert real.status_code == 200 and isinstance(tickets, list) and len(tickets) == 1, \
            f"티켓 응답 체계: {real.status_code} {str(real.json())[:150]}"
        ok(f"실 Expo 200 + 티켓 1건 (status={tickets[0].get('status')}) — 왕복·체계 검증")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        httpd.shutdown()
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  uvicorn(8001)·mock·유저 3명 정리 (push_tokens는 cascade)")


if __name__ == "__main__":
    run_tests()
