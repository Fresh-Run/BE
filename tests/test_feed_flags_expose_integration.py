"""
Integration test: allow_likes·allow_comments 렌더 힌트 노출 (additive)

3곳: ①PublicProfileResponse ②타인 RunResponse(상세) ③ActivityFeedItem.
ON/OFF 반영 + 잠금 프로필 응답엔 null(부재) + N+1 없음(feed_flags_batch 1회).

Run: python tests/test_feed_flags_expose_integration.py  (로컬 서버 필요)
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


def insert_run(c, uid, vis="public"):
    now = datetime.now(timezone.utc)
    return c.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=representation"},
                  json={"user_id": uid, "distance_km": 3.0, "duration_sec": 1080,
                        "ran_at": now.isoformat(), "verification": "verified",
                        "visibility": vis}).json()[0]["id"]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. A(owner)·B(viewer, A·D 팔로우)·C(비공개)·D(2nd owner)")
        for k in ("a", "b", "c", "d"):
            uids[k] = sb_user(c, f"ffx-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"ffx-{k}-{TS}@test.com") for k in ("a", "b", "c", "d")}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"FFX{k}{TS}"}).status_code == 200
        # B가 A·D 팔로우, C는 비공개(비팔로워 B에겐 잠금)
        assert api(c, "POST", f"/users/{uids['a']}/follow", tk["b"]).status_code == 204
        assert api(c, "POST", f"/users/{uids['d']}/follow", tk["b"]).status_code == 204
        assert api(c, "PATCH", "/me/profile", tk["c"], json={"visibility": "private"}).status_code == 200
        run_a = insert_run(c, uids["a"])
        insert_run(c, uids["d"])
        ok("관계·run 준비")

        step("1. 기본값(ON) — 3곳 노출")
        prof = api(c, "GET", f"/users/{uids['a']}/profile", tk["b"]).json()
        assert prof["allow_likes"] is True and prof["allow_comments"] is True, f"프로필 기본 ON, got {prof.get('allow_likes')}"
        detail = api(c, "GET", f"/runs/{run_a}", tk["b"]).json()
        assert detail["allow_likes"] is True and detail["allow_comments"] is True, "타인 상세 기본 ON"
        feed = api(c, "GET", "/feed/activities?limit=50", tk["b"]).json()
        item_a = next((i for i in feed if i["run_id"] == run_a), None)
        assert item_a and item_a["allow_likes"] is True and item_a["allow_comments"] is True, "피드 아이템 기본 ON"
        ok("프로필·타인상세·피드 3곳 allow_likes/comments 노출(기본 True)")

        step("2. OFF 반영 — A가 allow_likes·allow_comments 끄기 → 3곳 false")
        assert api(c, "PATCH", "/me/settings", tk["a"],
                   json={"feed": {"allow_likes": False, "allow_comments": False}}).status_code == 200
        prof = api(c, "GET", f"/users/{uids['a']}/profile", tk["b"]).json()
        assert prof["allow_likes"] is False and prof["allow_comments"] is False, "프로필 OFF 반영"
        detail = api(c, "GET", f"/runs/{run_a}", tk["b"]).json()
        assert detail["allow_likes"] is False and detail["allow_comments"] is False, "상세 OFF 반영"
        feed = api(c, "GET", "/feed/activities?limit=50", tk["b"]).json()
        item_a = next((i for i in feed if i["run_id"] == run_a), None)
        assert item_a["allow_likes"] is False and item_a["allow_comments"] is False, "피드 OFF 반영"
        ok("3곳 모두 OFF 반영(false)")

        step("3. 본인 응답에도 참값 노출 (분기 없음)")
        prof_self = api(c, "GET", f"/users/{uids['a']}/profile", tk["a"]).json()
        assert prof_self["allow_likes"] is False, "본인 프로필에도 참값"
        detail_self = api(c, "GET", f"/runs/{run_a}", tk["a"]).json()
        assert detail_self["allow_likes"] is False, "본인 상세에도 참값"
        ok("본인 응답도 소유자 참값 노출")

        step("4. 잠금 프로필 — allow_* 미노출(null)")
        locked = api(c, "GET", f"/users/{uids['c']}/profile", tk["b"]).json()
        assert locked["locked"] is True, "C는 B에게 잠금"
        assert locked.get("allow_likes") is None and locked.get("allow_comments") is None, \
            f"잠금 응답엔 affordance 없음(null), got likes={locked.get('allow_likes')}"
        ok("잠금 프로필 allow_likes/comments = null")

        step("5. N+1 없음 — 다owner 피드에서 feed_flags_batch 1회 호출")
        import app.services.profile_service as ps
        import app.services.run_service as rs
        orig = ps.feed_flags_batch
        calls = {"n": 0}
        async def spy(ids):
            calls["n"] += 1
            return await orig(ids)
        ps.feed_flags_batch = spy
        try:
            feed_items = asyncio.run(rs.list_activity_feed(uids["b"]))  # A·D 2 owner
        finally:
            ps.feed_flags_batch = orig
        owners = {i.user_id for i in feed_items}
        assert uids["a"] in owners and uids["d"] in owners, f"2 owner 피드, got {owners}"
        assert calls["n"] == 1, f"feed_flags_batch는 owner 수 무관 1회여야(N+1 아님), got {calls['n']}"
        # owner별 값 정확: A=false, D=true(기본)
        by = {i.user_id: i for i in feed_items}
        assert by[uids["a"]].allow_likes is False and by[uids["d"]].allow_likes is True, "owner별 매핑 정확"
        ok(f"2 owner 피드 feed_flags_batch 1회(N+1 없음)·owner별 매핑 정확")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
