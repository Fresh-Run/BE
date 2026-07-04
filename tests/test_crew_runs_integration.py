"""
Integration test: crew running feed (GET /crews/{crew_id}/runs)
Run: python tests/test_crew_runs_integration.py
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
    body = {"user_id": uid, "ran_at": ran_at, "distance_km": km,
            "duration_sec": sec, "avg_pace_sec_per_km": round(sec/km)}
    if route_id: body["route_id"] = route_id
    if notes: body["notes"] = notes
    r = c.post(f"{_SB}/rest/v1/runs",
               headers={**_ADM, "Prefer":"return=representation"}, json=body)
    if r.status_code not in (200,201): fail("insert run", r.text[:200])
    return r.json()[0]["id"]

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"cr-u{i}-{ts}@t.l" for i in range(1,4)]
    uids: list[str] = []
    toks: list[str] = []
    crew_ids: list[str] = []
    route_ids: list[str] = []
    now = datetime.now(timezone.utc)

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 셋업 ──────────────────────────────────────────────────
            step("1. u1(크루장)·u2(멤버)·u3(비멤버) + 크루 + 코스 2개 + run 3개")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2, uid3 = uids; tok1, tok2, tok3 = toks
            for i, tok in enumerate(toks, start=1):
                assert api(c, "PATCH", "/me/profile", tok,
                           json={"nickname": f"피드u{i}-{ts%100000}",
                                 "avatar_url": f"https://a.test/u{i}.png"}).status_code == 200
            r = api(c, "POST", "/crews", tok1, json={"name": f"러닝피드크루-{ts}"})
            crew_id = r.json()["id"]; crew_ids.append(crew_id)
            assert api(c, "POST", f"/crews/{crew_id}/join", tok2).status_code == 200

            pub_route = sb_insert_route(c, uid2, "한강 공개 코스", True)
            priv_route = sb_insert_route(c, uid2, "우리집 앞 비공개 코스", False)
            route_ids += [pub_route, priv_route]

            run1 = sb_insert_run(c, uid2, (now - timedelta(hours=3)).isoformat(),
                                 5.0, 1500, route_id=pub_route, notes="개인 메모 비밀")
            run3 = sb_insert_run(c, uid1, (now - timedelta(hours=2)).isoformat(),
                                 10.0, 3600)
            run2 = sb_insert_run(c, uid2, (now - timedelta(hours=1)).isoformat(),
                                 3.0, 1080, route_id=priv_route)
            ok(f"crew={crew_id[:8]}… runs 3개 (ran_at 3h/2h/1h 전)")

            # ── 2. 피드: 최신순 + 필드 ────────────────────────────────────
            step("2. 최신순 정렬 + 러너 정보 + 개인 필드 미노출")
            r = api(c, "GET", f"/crews/{crew_id}/runs", tok1)
            assert r.status_code == 200, r.text[:200]
            items = r.json()
            assert [i["run_id"] for i in items] == [run2, run3, run1], \
                f"ran_at 최신순 [run2,run3,run1]이어야 함"
            it = items[1]  # u1의 run3
            assert it["user_id"] == uid1 and it["nickname"] == f"피드u1-{ts%100000}"
            assert it["avatar_url"] == "https://a.test/u1.png"
            assert it["distance_km"] == 10.0 and it["duration_sec"] == 3600
            for i in items:
                for banned in ("notes", "liked", "feedback_tags", "feedback_at"):
                    assert banned not in i, f"개인 필드 {banned} 노출 금지"
            assert "비밀" not in r.text, "notes 내용이 응답 어디에도 없어야 함"
            ok("최신순 ✓ 닉네임·아바타 ✓ notes/liked/feedback 미노출 ✓")

            # ── 3. route_summary 공개/비공개 분기 ─────────────────────────
            step("3. route_summary: 공개 코스만")
            by_id = {i["run_id"]: i for i in items}
            assert by_id[run1]["route_summary"] == "한강 공개 코스"
            assert by_id[run2]["route_id"] == priv_route
            assert by_id[run2]["route_summary"] is None, "비공개 코스 요약 누출 금지"
            assert "비공개 코스" not in r.text
            assert by_id[run3]["route_id"] is None and by_id[run3]["route_summary"] is None
            ok("공개 코스 요약 ✓ 비공개 null ✓ 코스 없는 run null ✓")

            # ── 4. 권한 + 빈 크루 ─────────────────────────────────────────
            step("4. 비멤버 403 / 없는 크루 404 / 빈 크루 []")
            assert api(c, "GET", f"/crews/{crew_id}/runs", tok3).status_code == 403
            assert api(c, "GET", f"/crews/{_NOBODY}/runs", tok1).status_code == 404
            # run이 없는 u3가 크루장인 신생 크루 → 빈 피드
            r = api(c, "POST", "/crews", tok3, json={"name": f"빈크루-{ts}"})
            empty_crew = r.json()["id"]; crew_ids.append(empty_crew)
            assert api(c, "GET", f"/crews/{empty_crew}/runs", tok3).json() == []
            ok("403 ✓ 404 ✓ 빈 배열 ✓")

            # ── 5. 페이지네이션 ───────────────────────────────────────────
            step("5. limit=1 페이지네이션")
            p = [api(c, "GET", f"/crews/{crew_id}/runs", tok2,
                     params={"limit": 1, "offset": o}).json() for o in (0, 1, 2, 3)]
            assert [x[0]["run_id"] for x in p[:3]] == [run2, run3, run1]
            assert p[3] == [], "범위 밖 빈 배열"
            ok("offset 0→run2, 1→run3, 2→run1, 3→[] ✓")

            # ── 6. 탈퇴 멤버 run 제거 ─────────────────────────────────────
            step("6. u2 탈퇴 → u2의 run이 피드에서 사라짐")
            assert api(c, "DELETE", f"/crews/{crew_id}/leave", tok2).status_code == 204
            items = api(c, "GET", f"/crews/{crew_id}/runs", tok1).json()
            assert [i["run_id"] for i in items] == [run3], \
                f"u1의 run만 남아야 함, got {len(items)}건"
            ok("탈퇴 멤버의 과거 run 자동 제외 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "runs", "user_id", [u for u in uids if u])
            sb_del_in(c, "routes", "id", route_ids)
            sb_del_in(c, "crews", "id", crew_ids)
            sb_del_in(c, "notifications", "user_id", [u for u in uids if u])
            sb_del_in(c, "notifications", "actor_id", [u for u in uids if u])
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("runs·routes·crews·notifications·profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
