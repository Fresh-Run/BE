"""
Integration test: run kudos + activity feed
(POST/DELETE/GET /runs/{id}/kudos, GET /feed/activities)
Run: python tests/test_run_kudos_integration.py
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timedelta, timezone
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"
_NOBODY = "00000000-0000-4000-8000-000000000000"

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

def sb_insert_route(c, uid, summary, is_public):
    r = c.post(f"{_SB}/rest/v1/routes",
               headers={**_ADM, "Prefer":"return=representation"},
               json={"user_id": uid, "summary": summary,
                     "total_distance_km": 5.0, "is_public": is_public, "waypoints": []})
    if r.status_code not in (200,201): fail("insert route", r.text[:200])
    return r.json()[0]["id"]

def sb_insert_run(c, uid, ran_at, km, sec, route_id=None, notes=None):
    body = {"user_id": uid, "ran_at": ran_at, "distance_km": km, "duration_sec": sec}
    if route_id: body["route_id"] = route_id
    if notes: body["notes"] = notes
    r = c.post(f"{_SB}/rest/v1/runs",
               headers={**_ADM, "Prefer":"return=representation"}, json=body)
    if r.status_code not in (200,201): fail("insert run", r.text[:200])
    return r.json()[0]["id"]

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def feed(c, tok, **params):
    r = api(c, "GET", "/feed/activities", tok, params=params)
    if r.status_code != 200: fail("GET /feed/activities", r.text[:200])
    return r.json()


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"kd-u{i}-{ts}@t.l" for i in range(1,5)]
    uids: list[str] = []
    toks: list[str] = []
    route_ids: list[str] = []
    now = datetime.now(timezone.utc)

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 셋업 ──────────────────────────────────────────────────
            step("1. 유저 4명 + 코스 2개 + run 4개 (u1→u2 팔로우)")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2, uid3, uid4 = uids; tok1, tok2, tok3, tok4 = toks
            for i, tok in enumerate(toks[:3], start=1):
                assert api(c, "PATCH", "/me/profile", tok,
                           json={"nickname": f"쿠도u{i}-{ts%100000}",
                                 "avatar_url": f"https://a.test/k{i}.png"}).status_code == 200
            pub_route = sb_insert_route(c, uid2, "쿠도 공개 코스", True)
            priv_route = sb_insert_route(c, uid2, "쿠도 비공개 코스", False)
            route_ids += [pub_route, priv_route]
            run_a = sb_insert_run(c, uid2, (now - timedelta(hours=2)).isoformat(),
                                  5.0, 1500, route_id=pub_route, notes="비밀 메모")
            run_b = sb_insert_run(c, uid2, (now - timedelta(hours=1)).isoformat(),
                                  3.0, 1080, route_id=priv_route)
            run_c = sb_insert_run(c, uid3, (now - timedelta(hours=3)).isoformat(), 7.0, 2400)
            run_mine = sb_insert_run(c, uid1, (now - timedelta(minutes=30)).isoformat(),
                                     4.0, 1300)
            assert api(c, "POST", f"/users/{uid2}/follow", tok1).status_code == 204
            ok("u1→u2 팔로우, run 4개 (a:2h/b:1h/c:3h/mine:30m 전)")

            # ── 2. kudos 멱등 + 본인 400 + 404 ────────────────────────────
            step("2. kudos: 멱등 / 본인 400 / 없는 run 404")
            assert api(c, "POST", f"/runs/{run_a}/kudos", tok1).status_code == 204
            assert api(c, "POST", f"/runs/{run_a}/kudos", tok1).status_code == 204, "더블탭 204"
            r = api(c, "POST", f"/runs/{run_a}/kudos", tok2)
            assert r.status_code == 400, f"본인 run kudos → 400, got {r.status_code}"
            assert api(c, "POST", f"/runs/{_NOBODY}/kudos", tok1).status_code == 404
            assert api(c, "GET", f"/runs/{_NOBODY}/kudos", tok1).status_code == 404
            ok("멱등 204 ✓ 본인 400 ✓ 404 ✓")

            # ── 3. 알림: 새 kudos만 1건 ───────────────────────────────────
            step("3. run_kudoed 알림 (더블탭 중복 없음)")
            ns = [n for n in api(c, "GET", "/notifications", tok2).json()
                  if n["type"] == "run_kudoed"]
            assert len(ns) == 1, f"u2 알림 1건이어야 함 (더블탭 중복 금지), got {len(ns)}"
            assert ns[0]["actor_id"] == uid1 and ns[0]["target_id"] == run_a
            assert ns[0]["target_type"] == "run"
            ok("알림 1건 ✓ target=run ✓")

            # ── 4. 누른 사람 목록 ─────────────────────────────────────────
            # L1 게이트: kudos는 보이는 run만(본인·팔로우·크루) — u3도 u2를 팔로우해야 가능
            step("4. kudos 목록 (u3가 u2 팔로우 후 kudos)")
            assert api(c, "POST", f"/users/{uid2}/follow", tok3).status_code == 204
            assert api(c, "POST", f"/runs/{run_a}/kudos", tok3).status_code == 204
            users_list = api(c, "GET", f"/runs/{run_a}/kudos", tok2).json()
            assert [u["user_id"] for u in users_list] == [uid3, uid1], "최신순 [u3, u1]"
            assert users_list[1]["nickname"] == f"쿠도u1-{ts%100000}"
            assert users_list[1]["avatar_url"] == "https://a.test/k1.png"
            ok("팔로우 무관 kudos ✓ 최신순+닉네임·아바타 ✓")

            # ── 5. 활동 피드: 정렬·본인 제외·집계 (2026-07-20 스펙: 본인 run 제외) ──
            step("5. 피드: [b, a] (본인 run 제외) + is_mine 전부 False + kudos_count/my_kudos")
            items = feed(c, tok1)
            assert [i["run_id"] for i in items] == [run_b, run_a], \
                "ran_at 최신순 · 본인(run_mine) 제외 · u3의 run_c는 미팔로우라 제외"
            assert all(i["is_mine"] is False for i in items), "본인 제외라 is_mine 항상 False"
            by = {i["run_id"]: i for i in items}
            assert by[run_a]["kudos_count"] == 2 and by[run_a]["my_kudos"] is True
            assert by[run_b]["kudos_count"] == 0 and by[run_b]["my_kudos"] is False
            assert by[run_a]["nickname"] == f"쿠도u2-{ts%100000}"
            ok("정렬 ✓ 본인 제외·is_mine False ✓ kudos_count=2·my_kudos ✓")

            # ── 6. 상속 프라이버시 (CrewRunItem 규칙) ─────────────────────
            step("6. notes 미노출 + 비공개 route_summary null")
            raw = api(c, "GET", "/feed/activities", tok1).text
            for i in items:
                for banned in ("notes", "liked", "feedback_tags"):
                    assert banned not in i, f"{banned} 노출 금지"
            assert "비밀 메모" not in raw
            assert by[run_a]["route_summary"] == "쿠도 공개 코스"
            assert by[run_b]["route_summary"] is None and by[run_b]["route_id"] == priv_route
            ok("개인 필드 차단 ✓ 공개/비공개 route_summary 분기 ✓")

            # ── 7. kudos 취소 반영 ────────────────────────────────────────
            step("7. 취소: count 감소 + 재취소 멱등")
            assert api(c, "DELETE", f"/runs/{run_a}/kudos", tok1).status_code == 204
            assert api(c, "DELETE", f"/runs/{run_a}/kudos", tok1).status_code == 204
            by = {i["run_id"]: i for i in feed(c, tok1)}
            assert by[run_a]["kudos_count"] == 1 and by[run_a]["my_kudos"] is False
            ok("취소 후 count 1·my_kudos False ✓ 재취소 멱등 ✓")

            # ── 8. 페이지네이션 + 기존 /feed 회귀 ─────────────────────────
            step("8. limit=1 페이지네이션 + 기존 코스 피드(/feed) 회귀")
            p = [feed(c, tok1, limit=1, offset=o) for o in (0, 1, 2)]
            assert [x[0]["run_id"] for x in p[:2]] == [run_b, run_a]
            assert p[2] == []
            course_feed = api(c, "GET", "/feed", tok1).json()
            assert [f["id"] for f in course_feed] == [pub_route], \
                "기존 코스 피드는 여전히 route 단위로 동작해야 함"
            assert course_feed[0]["summary"] == "쿠도 공개 코스"
            ok("페이지네이션 ✓ /feed 회귀 (route 단위 유지) ✓")

            # ── 9. 언팔로우 반영 + 빈 피드 ────────────────────────────────
            step("9. 언팔로우 → [] (본인 run도 미포함) / u4(팔로우0) → []")
            assert api(c, "DELETE", f"/users/{uid2}/follow", tok1).status_code == 204
            assert feed(c, tok1) == [], "언팔 후 빈 배열 (본인 run 제외 — 2026-07-20 스펙)"
            assert feed(c, tok4) == [], "팔로우 0 → 빈 배열"
            # step 4에서 kudos 위해 걸어둔 u3→u2 팔로우 해제 (팔로우 0 전제 복원, kudos 행은 유지)
            assert api(c, "DELETE", f"/users/{uid2}/follow", tok3).status_code == 204
            assert feed(c, tok3) == [], "팔로우 0이면 본인 run(run_c) 있어도 빈 배열"
            ok("언팔 → [] ✓ 팔로우0 → [] ✓ 본인 run 미포함 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "runs", "user_id", [u for u in uids if u])   # kudos CASCADE
            sb_del_in(c, "routes", "id", route_ids)
            sb_del_in(c, "follows", "follower_id", [u for u in uids if u])
            sb_del_in(c, "follows", "following_id", [u for u in uids if u])
            sb_del_in(c, "notifications", "user_id", [u for u in uids if u])
            sb_del_in(c, "notifications", "actor_id", [u for u in uids if u])
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("runs(kudos CASCADE)·routes·follows·notifications·profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
