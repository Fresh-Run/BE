"""
Integration test: 크루 러닝 세션 태깅 L1 (docs/CREW_RUN_SESSION_L1_DESIGN.md)

태깅(멤버 crew_id·비멤버 400·미태그 null) + session_key 파생(크루+날짜 버킷·
공지 연결) + 크루 피드 배지/참여자수(private 제외·unverified 포함·차단 전역).

Run: python tests/test_crew_run_session_l1_integration.py  (로컬 서버 필요)
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


def save_run(c, token, visibility="public", crew_id=None, announcement_id=None):
    body = {"distance_km": 3.0, "duration_sec": 1200, "visibility": visibility}
    if crew_id: body["crew_id"] = crew_id
    if announcement_id: body["announcement_id"] = announcement_id
    return api(c, "POST", "/runs", token, json=body)


def run_row(c, run_id):
    return c.get(f"{_SB}/rest/v1/runs", headers=_ADM,
                 params={"id": f"eq.{run_id}", "select": "crew_id,session_key,verification"}).json()[0]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. O(장)·M1·M2·M3(멤버)·X(비멤버) + 크루")
        for k in ("o", "m1", "m2", "m3", "x"):
            uids[k] = sb_user(c, f"crs-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"crs-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CRS{k}{TS}"}).status_code == 200
        crew = api(c, "POST", "/crews", tk["o"], json={"name": f"CRS크루{TS}"}).json()["id"]
        for k in ("m1", "m2", "m3"):
            assert api(c, "POST", f"/crews/{crew}/join", tk[k]).status_code == 200
        ok("크루 + O·M1·M2·M3 멤버, X 비멤버")

        step("1. 태깅 — 멤버 crew_id 저장 → crew_id·session_key 기록 / 미태그 null")
        r1 = save_run(c, tk["m1"], crew_id=crew)
        assert r1.status_code == 200, r1.text[:200]
        row1 = run_row(c, r1.json()["id"])
        today = datetime.now(timezone(__import__("datetime").timedelta(hours=9))).date().isoformat()
        assert row1["crew_id"] == crew, "crew_id 태그"
        assert row1["session_key"] == f"c:{crew}:{today}", f"날짜 버킷 session_key, got {row1['session_key']}"
        # 미태그 저장
        r_plain = save_run(c, tk["o"])
        assert run_row(c, r_plain.json()["id"])["crew_id"] is None, "미태그 run crew_id null"
        ok("멤버 태그 crew_id·session_key(크루:날짜) / 미태그 null")

        step("2. 비멤버 crew_id 태그 → 400 (남의 크루 태그 방지)")
        assert save_run(c, tk["x"], crew_id=crew).status_code == 400, "비멤버 태그 400"
        ok("비멤버 crew_id 태그 400")

        step("3. session_key 파생 — 같은 크루·같은 날 2인 동일 키 / 공지 연결 = a:{ann}")
        r2 = save_run(c, tk["m2"], crew_id=crew)
        assert run_row(c, r2.json()["id"])["session_key"] == f"c:{crew}:{today}", "M2 같은 세션 키"
        ann = api(c, "POST", f"/crews/{crew}/announcements", tk["o"],
                  json={"title": f"정모{TS}", "body": "x", "place_lat": 37.54, "place_lng": 127.05}).json()["id"]
        r_ann = save_run(c, tk["m1"], crew_id=crew, announcement_id=ann)
        assert run_row(c, r_ann.json()["id"])["session_key"] == f"a:{ann}", "공지 연결 세션 키"
        ok("크루+날짜 버킷 동일 키(M1·M2) / 공지 연결 a:{ann}")

        step("4. 참여자 집계 — M3 private 제외, M1·M2 unverified 포함")
        save_run(c, tk["m3"], visibility="private", crew_id=crew)  # private 참여 → 카운트 제외
        # 크루 피드에서 c:{crew}:{today} 세션 참여자 = M1·M2 (M3 private 제외) = 2
        feed = api(c, "GET", f"/crews/{crew}/runs?limit=50", tk["o"]).json()
        sess = [i for i in feed if i["is_crew_session"] and i.get("session_participant_count")]
        # c:today 세션 카드(M1·M2)의 참여자 수 확인 (a:{ann} 세션은 M1 1명 별개)
        c_today = [i for i in sess if i["user_id"] in (uids["m1"], uids["m2"])]
        assert c_today, "정기런 카드 존재"
        # M1·M2 unverified지만 attendance로 카운트, M3 private 제외 → 2
        counts = {i["session_participant_count"] for i in c_today}
        assert 2 in counts, f"c:today 참여자=2(M1·M2, private M3 제외), got {counts}"
        # 미태그 run은 배지 없음
        plain = next((i for i in feed if i["user_id"] == uids["o"] and not i["is_crew_session"]), None)
        assert plain is not None and plain["session_participant_count"] is None, "미태그 run 배지 없음·카운트 null"
        ok("private 참여자 제외·unverified 포함(카운트 2)·미태그 배지 없음")

        step("5. 차단 전역 카운트 — O가 M2 차단 → M2 카드 제외되나 카운트는 2 유지")
        assert api(c, "POST", f"/users/{uids['m2']}/block", tk["o"]).status_code == 204
        feed = api(c, "GET", f"/crews/{crew}/runs?limit=50", tk["o"]).json()
        assert not any(i["user_id"] == uids["m2"] for i in feed), "차단 M2 카드 제외(v3.6)"
        m1_card = next((i for i in feed if i["user_id"] == uids["m1"] and i["is_crew_session"]
                        and i["session_participant_count"] == 2), None)
        assert m1_card is not None, "M1 카드 참여자 수 전역 유지(2 — 차단 M2 포함, v3.6 '숫자 전역')"
        ok("차단 M2 카드 제외·참여자 카운트 전역 유지(2)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
