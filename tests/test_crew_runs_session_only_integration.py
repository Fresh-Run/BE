"""
Integration test: GET /crews/{id}/runs?session_only (CREW_FEED_FIXES_DESIGN.md Part 1)

session_only 파라미터 additive — 기본 false는 파이어호스(현행 완전 불변),
true면 이 크루 태그런(정기런)만. 스키마 변경 없음(read-only).

케이스(설계 §테스트계획 8종):
 1. session_only 생략 → 파이어호스(태그+비태그 전부) — 기본 동작 불변
 2. session_only=false → 파이어호스(1과 동일)
 3. session_only=true → 태그런만(비태그런 제외)
 4. 태그런 0 크루 → session_only=true 시 빈 배열 200(404 아님)
 5. 배지: true 응답 전부 is_crew_session=true · session_participant_count 채워짐
 6. 격리: 크루A 태그런이 크루B의 session_only=true에 안 섞임(crew_id 명시)
 7. 필터 회귀: true에서도 private 제외·차단 멤버 제외
 8. 페이지네이션: true + limit/offset

Run: python tests/test_crew_runs_session_only_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timezone
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


def ok(m):         print(f"  ✓ {m}")
def fail(m, d=""):  print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):       print(f"\n[{t}]")


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


def save_run(c, token, **body):
    body.setdefault("distance_km", 3.0)
    body.setdefault("duration_sec", 1080)
    return api(c, "POST", "/runs", token, json=body)


def ids(rows):
    return {r["run_id"] for r in rows}


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    crewA = crewB = None
    try:
        step("0. O(owner)·M(member)·X(타인) + 크루A·크루B")
        for k in ("o", "m", "x"):
            uids[k] = sb_user(c, f"cso-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"cso-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CSO{k}{TS}"}).status_code == 200
        # O를 premium으로 승격(admin) — free는 크루 1개 한도라 A·B·C 다중 생성 불가.
        c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{uids['o']}", headers=_ADM, json={"tier": "premium"})
        crewA = api(c, "POST", "/crews", tk["o"], json={"name": f"크루A{TS}"}).json()["id"]
        crewB = api(c, "POST", "/crews", tk["o"], json={"name": f"크루B{TS}"}).json()["id"]
        assert api(c, "POST", f"/crews/{crewA}/join", tk["m"]).status_code == 200
        ok("크루A(O·M)·크루B(O) 준비")

        step("1. 데이터 심기 — 크루A에 태그런 2 + 비태그런 1, 크루B에 태그런 1")
        # 크루A 태그런: O 1건, M 1건 (같은 세션 → participant_count=2 기대)
        rA_o = save_run(c, tk["o"], crew_id=crewA, title="A정기런O").json()["id"]
        rA_m = save_run(c, tk["m"], crew_id=crewA, title="A정기런M").json()["id"]
        # 크루A 비태그런: O가 crew_id 없이 저장
        rA_plain = save_run(c, tk["o"], title="A일반런").json()["id"]
        # 크루B 태그런: O 1건
        rB_o = save_run(c, tk["o"], crew_id=crewB, title="B정기런O").json()["id"]
        ok(f"태그런 A:2·B:1 + 비태그런 A:1 저장")

        step("2. 기본 동작 불변 — session_only 생략 → 파이어호스(태그+비태그 전부)")
        feed = api(c, "GET", f"/crews/{crewA}/runs", tk["o"]).json()
        fids = ids(feed)
        assert rA_o in fids and rA_m in fids and rA_plain in fids, f"파이어호스: 태그·비태그 모두, got {fids}"
        ok(f"생략 → 파이어호스 {len(feed)}건(태그2+비태그1 포함)")

        step("3. session_only=false 명시 → 파이어호스(2와 동일)")
        feed_f = api(c, "GET", f"/crews/{crewA}/runs", tk["o"], params={"session_only": "false"}).json()
        assert rA_plain in ids(feed_f), "false도 파이어호스(비태그런 포함)"
        ok("false → 파이어호스 (비태그런 포함)")

        step("4. session_only=true → 태그런만 (비태그런 제외)")
        so = api(c, "GET", f"/crews/{crewA}/runs", tk["o"], params={"session_only": "true"}).json()
        soids = ids(so)
        assert rA_o in soids and rA_m in soids, f"태그런 포함, got {soids}"
        assert rA_plain not in soids, "비태그런 제외됨"
        ok(f"true → 태그런만 {len(so)}건 (비태그런 rA_plain 제외)")

        step("5. 배지 — true 응답 전부 is_crew_session=true + participant_count 채워짐")
        assert all(r["is_crew_session"] is True for r in so), "session_only=true면 전부 배지 true"
        # rA_o·rA_m은 같은 세션(crew+날짜) → participant_count=2
        for r in so:
            assert r["session_participant_count"] == 2, f"참여자 수 2 기대, got {r['session_participant_count']}"
        ok("전부 is_crew_session=true · session_participant_count=2")

        step("6. 격리 — 크루B의 session_only=true에 크루A 태그런 안 섞임")
        soB = api(c, "GET", f"/crews/{crewB}/runs", tk["o"], params={"session_only": "true"}).json()
        soBids = ids(soB)
        assert rB_o in soBids, "크루B 태그런 포함"
        assert rA_o not in soBids and rA_m not in soBids, "크루A 태그런 미포함(crew_id 명시)"
        ok(f"크루B true → {len(soB)}건, 크루A 태그런 격리 확인")

        step("7. 태그런 0 크루 → session_only=true 빈 배열 200 (404 아님)")
        # 새 크루C: 태그런 없음
        crewC = api(c, "POST", "/crews", tk["o"], json={"name": f"크루C{TS}"}).json()["id"]
        r = api(c, "GET", f"/crews/{crewC}/runs", tk["o"], params={"session_only": "true"})
        assert r.status_code == 200 and r.json() == [], f"빈 배열 200 기대, got {r.status_code} {r.json()}"
        c.delete(f"{_SB}/rest/v1/crews?id=eq.{crewC}", headers=_ADM)
        ok("태그런 0 → 빈 배열 200")

        step("8. 필터 회귀 — true에서도 private 제외 + 차단 멤버 제외")
        # private 태그런: M이 크루A 태그+private로 저장 → session_only=true에서도 제외
        rA_priv = save_run(c, tk["m"], crew_id=crewA, visibility="private", title="A정기런private").json()["id"]
        so2 = ids(api(c, "GET", f"/crews/{crewA}/runs", tk["o"], params={"session_only": "true"}).json())
        assert rA_priv not in so2, "private 태그런 제외(true에서도)"
        # 차단: O가 M 차단 → M의 태그런이 O의 session_only=true 응답에서 제외
        assert api(c, "POST", f"/users/{uids['m']}/block", tk["o"]).status_code == 204
        so3 = ids(api(c, "GET", f"/crews/{crewA}/runs", tk["o"], params={"session_only": "true"}).json())
        assert rA_m not in so3, "차단 멤버 태그런 제외"
        assert rA_o in so3, "본인 태그런은 유지"
        api(c, "DELETE", f"/users/{uids['m']}/block", tk["o"])  # 원복
        ok("true에서도 private 제외 · 차단 멤버 제외 (필터 상속)")

        step("9. 페이지네이션 — true + limit/offset")
        p1 = api(c, "GET", f"/crews/{crewA}/runs", tk["o"], params={"session_only": "true", "limit": "1", "offset": "0"}).json()
        p2 = api(c, "GET", f"/crews/{crewA}/runs", tk["o"], params={"session_only": "true", "limit": "1", "offset": "1"}).json()
        assert len(p1) == 1 and len(p2) == 1, f"limit=1 각 1건, got {len(p1)},{len(p2)}"
        assert ids(p1) != ids(p2), "offset으로 다른 페이지"
        ok("limit=1·offset 페이지네이션 정상")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for cr in (crewA, crewB):
            if cr:
                c.delete(f"{_SB}/rest/v1/crews?id=eq.{cr}", headers=_ADM)
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (crews·runs·crew_members cascade)")


if __name__ == "__main__":
    run_tests()
