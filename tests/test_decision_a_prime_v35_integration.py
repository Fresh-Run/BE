"""
Integration test: 결정 A′ + 엣지 ⓑ + v3.5 크루 서피스 차단 필터

A′: 비팔로워 크루원 → 프로필 locked·러닝 히스토리 빈 목록 / 크루 랭킹·명단은 보임 /
    팔로워는 기존대로 locked=false.
ⓑ: 잠금 계정 크루메이트의 followers run → 크루 피드 카드 + 상세 200(정제) /
    private run은 카드·상세 모두 불가(404).
v3.5: 차단 후 채팅 blocked=true·content null·기존 반응 유지·새 반응 404 /
    크루 피드 카드 제외 / 랭킹 잔존.

Run: python tests/test_decision_a_prime_v35_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timezone
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


def make_run(c, token, visibility, dist=2.0):
    now = datetime.now(timezone.utc)
    track = [{"lat": 37.5445 + i * 0.0002, "lng": 127.0374, "t": int(now.timestamp() * 1000) + i * 8000,
              "acc": 5.0} for i in range(20)]
    r = api(c, "POST", "/runs", token, json={
        "distance_km": dist, "duration_sec": int(dist * 400), "visibility": visibility,
        "gps_track": track})
    assert r.status_code == 200, r.text[:200]
    return r.json()["id"]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. V(뷰어·크루장)·O(비팔로워 크루원, 비공개)·F(O 팔로워)·B(차단 대상)")
        for k in ("v", "o", "f", "b"):
            uids[k] = sb_user(c, f"aprm-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"aprm-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"APRM{k}{TS}"}).status_code == 200
        crew = api(c, "POST", "/crews", tk["v"], json={"name": f"APRM크루{TS}"}).json()["id"]
        for k in ("o", "f", "b"):
            assert api(c, "POST", f"/crews/{crew}/join", tk[k]).status_code == 200
        assert api(c, "POST", f"/users/{uids['o']}/follow", tk["f"]).status_code == 204  # F가 O 팔로우
        assert api(c, "PATCH", "/me/profile", tk["o"], json={"visibility": "private"}).status_code == 200
        run_foll = make_run(c, tk["o"], "followers")   # 크루 노출 대상
        run_priv = make_run(c, tk["o"], "private")     # 크루도 못 봄
        make_run(c, tk["b"], "public")                 # B의 크루 피드 카드용
        ok("크루 4인 + F→O 팔로우 + O 비공개 + O run(followers·private) + B run")

        step("1. A′ — 비팔로워 크루원(V)에게 O 프로필 locked·히스토리 빈 / 팔로워(F)는 locked=false")
        pv = api(c, "GET", f"/users/{uids['o']}/profile", tk["v"]).json()
        assert pv["locked"] is True, f"A′: 비팔로워 크루원에게 프로필 locked, got {pv['locked']}"
        assert api(c, "GET", f"/users/{uids['o']}/runs", tk["v"]).json() == [], "A′: 히스토리 잠김(빈 목록)"
        pf = api(c, "GET", f"/users/{uids['o']}/profile", tk["f"]).json()
        assert pf["locked"] is False, "팔로워 F는 기존대로 locked=false"
        ok("A′: 크루원이어도 비팔로워는 프로필 locked·히스토리 빈 / 팔로워 정상")

        step("2. A′ — 크루 서피스(랭킹·명단)는 O 여전히 노출")
        ranking = api(c, "GET", f"/crews/{crew}/ranking", tk["v"]).json()
        assert any(e["user_id"] == uids["o"] for e in ranking), "랭킹엔 O 노출(크루 서피스)"
        members = api(c, "GET", f"/crews/{crew}/members", tk["v"]).json()
        assert any(m["user_id"] == uids["o"] for m in members), "명단엔 O 노출"
        ok("A′: 랭킹·명단은 크루 예외 유지(게이트 미경유)")

        step("3. 엣지 ⓑ — 크루 피드 카드 + 상세 탭스루 (private은 불가)")
        feed = api(c, "GET", f"/crews/{crew}/runs", tk["v"]).json()
        feed_run_ids = {i["run_id"] for i in feed}
        assert run_foll in feed_run_ids, "ⓑ: O의 followers run 카드가 크루 피드에 보임"
        assert run_priv not in feed_run_ids, "private run은 크루 피드 제외"
        detail = api(c, "GET", f"/runs/{run_foll}", tk["v"])
        assert detail.status_code == 200, f"ⓑ: 크루 카드 상세 탭 200, got {detail.status_code}"
        assert detail.json()["visibility"] is None, "타인 상세 정제(visibility null) 유지"
        assert api(c, "GET", f"/runs/{run_priv}", tk["v"]).status_code == 404, "private run 상세는 404(ⓑ 제외)"
        ok("ⓑ: followers run 카드+상세 200(정제)·private run 카드/상세 불가")

        step("4. v3.5 채팅 — B 메시지 반응(F) 후 V가 B 차단 → blocked 플래그·content null·반응 유지")
        msg = api(c, "POST", f"/crews/{crew}/chat/messages", tk["b"], json={"content": "안녕하세요"}).json()
        mid = msg["id"]
        assert api(c, "POST", f"/crews/{crew}/chat/messages/{mid}/react", tk["f"], json={"emoji": "👍"}).status_code == 204
        assert api(c, "POST", f"/users/{uids['b']}/block", tk["v"]).status_code == 204  # V가 B 차단
        msgs = api(c, "GET", f"/crews/{crew}/chat/messages", tk["v"]).json()
        bm = next((m for m in msgs if m["id"] == mid), None)
        assert bm is not None, "차단해도 메시지 행은 잔존(가려진 렌더)"
        assert bm["blocked"] is True, f"blocked=true, got {bm.get('blocked')}"
        assert bm["content"] is None and bm["payload"] is None, "content·payload 서버가 null"
        assert bm["sender_nickname"] is None, "차단 발신자 신원(닉네임)도 가림"
        assert bm["reactions"].get("👍") == 1, f"기존 반응 집계 유지(왜곡 방지), got {bm['reactions']}"
        ok("v3.5: blocked=true·content/payload null·신원 가림·반응 집계 유지")

        step("5. v3.5 — 차단 메시지에 새 반응 404 / 크루 피드 B 카드 제외 / 랭킹 B 잔존")
        assert api(c, "POST", f"/crews/{crew}/chat/messages/{mid}/react", tk["v"], json={"emoji": "🔥"}).status_code == 404, \
            "차단 상대 메시지 새 반응 404"
        feed = api(c, "GET", f"/crews/{crew}/runs", tk["v"]).json()
        assert not any(i["user_id"] == uids["b"] for i in feed), "v3.5: 크루 피드에서 B 카드 제외"
        ranking = api(c, "GET", f"/crews/{crew}/ranking", tk["v"]).json()
        assert any(e["user_id"] == uids["b"] for e in ranking), "랭킹엔 B 잔존(순위 왜곡 방지 — 차단 무시)"
        ok("v3.5: 새 반응 404·크루 피드 B 제외·랭킹 B 잔존")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
