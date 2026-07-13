"""
Integration test: 채팅 v1.5 — 시스템 메시지 + run_share (CREW_CHAT_DESIGN §3·4·8)

시스템: 공지 생성→채팅 유입·content 렌더키·payload(announcement_id+title)·
        sender_id=작성자(null 아님)·비크루원 404 / 반응 가능·삭제 불가(403).
run_share: 본인 run 공유(201·스냅샷 필드)·타인 run 404·private 422·notes 미박제·
        원본 삭제 후 카드 잔존+상세 404 재평가·반응 가능·삭제 본인 가능.

Run: python tests/test_chat_v15_integration.py  (로컬 서버 필요)
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


def make_run(c, token, distance_km, visibility, notes=None):
    dur = int(distance_km * 360)  # 6'00"/km — 물리 하한 위
    now = datetime.now(timezone.utc)
    track = [{"lat": 37.5445 + i * 0.0002, "lng": 127.0374, "t": int(now.timestamp() * 1000) + i * 8000,
              "acc": 5.0} for i in range(20)]
    body = {"distance_km": distance_km, "duration_sec": dur, "visibility": visibility,
            "gps_track": track, "title": f"런{TS}"}
    if notes:
        body["notes"] = notes
    r = api(c, "POST", "/runs", token, json=body)
    assert r.status_code == 200, r.text[:200]
    return r.json()["id"]


def chat(c, crew, token):
    return api(c, "GET", f"/crews/{crew}/chat/messages?limit=50", token).json()


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. A(크루장)·B(멤버)·C(비크루원) + 크루")
        for k in ("a", "b", "c"):
            uids[k] = sb_user(c, f"cv15-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"cv15-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CV15{k}{TS}"}).status_code == 200
        crew = api(c, "POST", "/crews", tk["a"], json={"name": f"CV15크루{TS}"}).json()["id"]
        assert api(c, "POST", f"/crews/{crew}/join", tk["b"]).status_code == 200
        ok("크루 + A·B 멤버, C 비크루원")

        step("1. 시스템 메시지 — 공지 생성 → 채팅 유입")
        ann = api(c, "POST", f"/crews/{crew}/announcements", tk["a"],
                  json={"title": f"공지{TS}", "body": "정모 안내"}).json()
        msgs = chat(c, crew, tk["b"])
        sysmsg = next((m for m in msgs if m["type"] == "system"), None)
        assert sysmsg is not None, "시스템 메시지 유입"
        assert sysmsg["content"] == "announcement", f"렌더 키, got {sysmsg['content']}"
        assert sysmsg["payload"]["announcement_id"] == ann["id"], "payload announcement_id"
        assert sysmsg["payload"]["title"] == f"공지{TS}", "payload title"
        assert sysmsg["sender_id"] == uids["a"], f"sender=작성자(null 아님), got {sysmsg['sender_id']}"
        ok("공지→system 메시지·렌더키·payload(id+title)·sender=작성자")

        step("2. 시스템 메시지 — 비크루원 404 / 반응 가능·삭제 불가")
        assert api(c, "GET", f"/crews/{crew}/chat/messages", tk["c"]).status_code == 404, "비크루원 404"
        sid = sysmsg["id"]
        assert api(c, "POST", f"/crews/{crew}/chat/messages/{sid}/react", tk["b"],
                   json={"emoji": "👍"}).status_code == 204, "system 반응 허용"
        assert api(c, "DELETE", f"/crews/{crew}/chat/messages/{sid}", tk["a"]).status_code == 403, \
            "system 삭제 불가(작성자·운영진도)"
        ok("비크루원 404 · system 반응 204 · 삭제 403")

        step("3. run_share — 본인 public run 공유 + 스냅샷 필드")
        run_pub = make_run(c, tk["a"], 5.0, "public", notes="비밀 메모")
        r = api(c, "POST", f"/crews/{crew}/chat/share-run", tk["a"], json={"run_id": run_pub, "caption": "오늘 5km!"})
        assert r.status_code == 201, f"공유 201 기대, got {r.status_code}: {r.text[:200]}"
        card = r.json()
        assert card["type"] == "run_share" and card["content"] == "오늘 5km!"
        p = card["payload"]
        for f in ("run_id", "distance_km", "duration_sec", "avg_pace_sec_per_km", "title", "area", "ran_at", "polyline_thumb", "photo_thumb"):
            assert f in p, f"스냅샷 필드 {f} 누락"
        assert p["run_id"] == run_pub
        assert "notes" not in p, "notes는 박제 안 됨(화이트리스트)"
        assert "verification" not in p and "is_flagged" not in p, "내부 필드 미박제"
        ok("본인 run 공유 201·스냅샷 필드 정확·notes/내부필드 미박제")

        step("4. run_share — 타인 run 404 / private run 422")
        run_b = make_run(c, tk["b"], 3.0, "public")
        assert api(c, "POST", f"/crews/{crew}/chat/share-run", tk["a"],
                   json={"run_id": run_b}).status_code == 404, "타인 run → 404 은닉"
        run_priv = make_run(c, tk["a"], 2.0, "private")
        assert api(c, "POST", f"/crews/{crew}/chat/share-run", tk["a"],
                   json={"run_id": run_priv}).status_code == 422, "private run → 422"
        ok("타인 run 404 · private run 422")

        step("5. 원본 삭제 후 카드 잔존 + 상세 404 재평가")
        c.delete(f"{_SB}/rest/v1/runs", headers=_ADM, params={"id": f"eq.{run_pub}"})  # 원본 삭제
        msgs = chat(c, crew, tk["b"])
        card2 = next((m for m in msgs if m["type"] == "run_share" and m["payload"]["run_id"] == run_pub), None)
        assert card2 is not None, "원본 삭제돼도 채팅 카드 잔존(스냅샷 박제)"
        assert card2["payload"]["distance_km"] is not None, "스냅샷 값 보존"
        assert api(c, "GET", f"/runs/{run_pub}", tk["a"]).status_code == 404, "상세 진입은 현재 권한 재평가(삭제→404)"
        ok("카드 잔존(스냅샷)·상세 GET 404 재평가")

        step("6. run_share 반응·삭제 정책")
        cid = card["id"]
        assert api(c, "POST", f"/crews/{crew}/chat/messages/{cid}/react", tk["b"],
                   json={"emoji": "🔥"}).status_code == 204, "run_share 반응 허용"
        assert api(c, "DELETE", f"/crews/{crew}/chat/messages/{cid}", tk["a"]).status_code == 204, \
            "run_share 본인 삭제 가능(soft)"
        ok("run_share 반응 204 · 본인 삭제 204")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
