"""
Integration test: PB 축하 푸시 (백로그 소품)

Part A (HTTP): PB 발생(new_records 비지 않음) 시 인앱 pb_achieved 생성,
              미발생 시 무생성. (db CHECK 'pb_achieved' 선행 필요.)
Part B (in-process): send_for_notification 게이트 — 기본 발송(기록 종류별 문구)·
              pb 토글 OFF 스킵·master OFF 스킵. Expo POST mock.

Run: python tests/test_pb_push_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import asyncio, os, sys, time
from datetime import datetime, timezone
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
    return c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                  json={"email": email, "password": "test1234", "email_confirm": True}).json()["id"]


def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


def make_run(c, token, n_points, duration_sec):
    """트랙 포인트 수로 거리를 조절(많을수록 김). duration으로 페이스 조절."""
    now = datetime.now(timezone.utc)
    track = [{"lat": 37.5445 + i * 0.0003, "lng": 127.0374, "t": int(now.timestamp() * 1000) + i * 10000,
              "acc": 5.0} for i in range(n_points)]
    r = api(c, "POST", "/runs", token, json={
        "distance_km": 1.0, "duration_sec": duration_sec, "visibility": "public",
        "gps_track": track, "ran_at": now.isoformat()})
    assert r.status_code == 200, r.text[:200]
    return r.json()


def pb_count(c, uid):
    r = c.get(f"{_SB}/rest/v1/notifications", headers={**_ADM, "Prefer": "count=exact"},
              params={"user_id": f"eq.{uid}", "type": "eq.pb_achieved", "select": "id", "limit": 1})
    return int(r.headers.get("content-range", "?/0").split("/")[-1])


# --- Expo POST mock (Part B) ---
_posts: list = []
class _FakeResp:
    status_code = 200
    def json(self): return {"data": [{"status": "ok"}]}
async def _fake_post(self, url, **kw):
    _posts.append(kw.get("json"))
    return _FakeResp()


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. 유저")
        uids["a"] = sb_user(c, f"pbp-a-{TS}@test.com")
        ta = sb_login(c, f"pbp-a-{TS}@test.com")
        assert api(c, "PATCH", "/me/profile", ta, json={"nickname": f"PBP{TS}"}).status_code == 200
        ok("유저 준비")

        step("A1. 첫 run — PB 아님(new_records []), 인앱 pb 없음")
        r1 = make_run(c, ta, 15, 900)   # 짧고 느림 (baseline)
        assert r1["new_records"] == [], f"첫 run은 [], got {r1['new_records']}"
        assert pb_count(c, uids["a"]) == 0, "첫 run 후 pb 알림 없음"
        ok("첫 run new_records=[]·pb 알림 0")

        step("A2. 더 긴 run — PB 발생 → 인앱 pb_achieved 1건")
        r2 = make_run(c, ta, 40, 2400)  # 훨씬 김 → longest_distance 등 경신
        assert len(r2["new_records"]) > 0, f"긴 run은 new_records 발생 기대, got {r2['new_records']}"
        assert pb_count(c, uids["a"]) == 1, f"PB 발생 시 인앱 1건, got {pb_count(c, uids['a'])}"
        # 딥링크: target=run2, self 대상(actor=user)
        row = c.get(f"{_SB}/rest/v1/notifications", headers=_ADM,
                    params={"user_id": f"eq.{uids['a']}", "type": "eq.pb_achieved",
                            "select": "actor_id,target_id,target_type,payload"}).json()[0]
        assert row["actor_id"] == uids["a"] and row["target_type"] == "run", "self 대상·run 딥링크"
        assert "record_types" in (row["payload"] or {}), "payload에 record_types"
        ok("PB 발생 → 인앱 pb_achieved 1건·self 대상·run 딥링크·payload")

        step("A3. 짧고 느린 run — PB 미발생 → 인앱 pb 그대로 1")
        r3 = make_run(c, ta, 12, 1200)  # 더 짧고 느림 → 경신 없음
        assert r3["new_records"] == [], f"경신 없는 run은 [], got {r3['new_records']}"
        assert pb_count(c, uids["a"]) == 1, "미발생 시 pb 알림 증가 없음"
        ok("미발생 run new_records=[]·pb 알림 1 유지")

        step("B. 푸시 게이트 (in-process, Expo mock)")
        import app.services.push_service as ps
        orig_post = httpx.AsyncClient.post
        httpx.AsyncClient.post = _fake_post
        # 토큰 등록
        asyncio.run(ps.register_token(uids["a"], f"ExponentPushToken[pbp{TS}]", "ios"))

        def set_notif(**kw):
            cur = c.get(f"{_SB}/rest/v1/profiles", headers=_ADM,
                        params={"user_id": f"eq.{uids['a']}", "select": "settings"}).json()[0]["settings"] or {}
            cur["notif"] = {**cur.get("notif", {}), **kw}
            c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM,
                    params={"user_id": f"eq.{uids['a']}"}, json={"settings": cur})

        def send(record_types):
            _posts.clear()
            asyncio.run(ps.send_for_notification(
                uids["a"], uids["a"], "pb_achieved", "run-id", "run",
                {"record_types": record_types}))
            return list(_posts)

        try:
            # 기본(ON) → 발송 + 기록 종류별 문구
            posts = send(["best_pace"])
            assert len(posts) == 1, f"기본 발송 1건, got {len(posts)}"
            body = posts[0][0]["body"]
            assert "최고 페이스" in body, f"기록 종류별 문구, got {body!r}"
            # 복수 기록 → 제네릭
            posts = send(["best_pace", "longest_distance"])
            assert "새 기록" in posts[0][0]["body"], "복수 기록 제네릭 문구"
            # pb 토글 OFF → 스킵
            set_notif(pb=False)
            assert len(send(["best_pace"])) == 0, "pb OFF → 푸시 스킵"
            # master OFF → 스킵
            set_notif(pb=True, master=False)
            assert len(send(["best_pace"])) == 0, "master OFF → 푸시 스킵"
        finally:
            httpx.AsyncClient.post = orig_post
        ok("기본 발송·종류별 문구·복수 제네릭·pb OFF 스킵·master OFF 스킵")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        from app.core.supabase_client import get_supabase_admin
        try:
            get_supabase_admin().table("push_tokens").delete().eq("user_id", uids.get("a", "")).execute()
        except Exception:
            pass
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
