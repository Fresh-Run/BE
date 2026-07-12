"""
Integration test: 세션 잔여 소품 2종
  1) 공지 집결 좌표 place_lat/place_lng — 저장·서빙 + 한국 bbox 검증(422)
  3) 크루 멤버 응답 challenge_km — 진행 챌린지 멤버별 기여 배치 집계
       (주간 랭킹 km와 별개, 챌린지 없으면 null)

Run: python tests/test_crew_announce_challenge_km_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timezone, timedelta
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


def ok(m):        print(f"  ✓ {m}")
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


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


def insert_run(c, user_id, distance_km, ran_at, verification="verified"):
    """runs 직접 적재(admin) — API create_run은 ran_at을 무시(now 고정)하므로
    챌린지 창(과거/미래)·verified 필터를 정확히 검증하려면 직접 제어가 필요."""
    r = c.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": user_id, "distance_km": distance_km,
                     "duration_sec": int(distance_km * 360), "ran_at": ran_at.isoformat(),
                     "verification": verification, "visibility": "public"})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()[0]["id"]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. 크루장 A + 멤버 B")
        for k in ("a", "b"):
            uids[k] = sb_user(c, f"acck-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"acck-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"ACK{k}{TS}"}).status_code == 200
        crew = api(c, "POST", "/crews", tk["a"], json={"name": f"ACK크루{TS}"}).json()["id"]
        assert api(c, "POST", f"/crews/{crew}/join", tk["b"]).status_code == 200
        ok("크루 생성 + B 가입")

        # ===== 1) 공지 집결 좌표 =====
        step("1a. 공지 생성 — place_name + 유효 좌표 저장/서빙")
        r = api(c, "POST", f"/crews/{crew}/announcements", tk["a"], json={
            "title": f"집결{TS}", "body": "뚝섬유원지 3번 출구",
            "place_name": "뚝섬한강공원", "place_lat": 37.5311, "place_lng": 127.0668})
        assert r.status_code == 201, f"공지 생성 201 기대, got {r.status_code}: {r.text[:200]}"
        ann = r.json()
        assert ann["place_name"] == "뚝섬한강공원" and ann["place_lat"] == 37.5311 and ann["place_lng"] == 127.0668, \
            f"좌표 응답 서빙 확인, got {ann.get('place_lat')},{ann.get('place_lng')}"
        # DB 원천 확인
        db = c.get(f"{_SB}/rest/v1/crew_announcements", headers=_ADM,
                   params={"id": f"eq.{ann['id']}", "select": "place_lat,place_lng,place_name"}).json()[0]
        assert db["place_lat"] == 37.5311 and db["place_lng"] == 127.0668, f"DB 저장 확인, got {db}"
        ok("place_name + 좌표 저장·서빙 + DB 원천 일치")

        step("1b. 한국 bbox 밖 좌표 → 422 (검증 재사용)")
        r = api(c, "POST", f"/crews/{crew}/announcements", tk["a"], json={
            "title": f"밖{TS}", "body": "동경 좌표", "place_lat": 35.6, "place_lng": 139.7})  # 도쿄
        assert r.status_code == 422, f"bbox 밖 → 422 기대, got {r.status_code}"
        r = api(c, "POST", f"/crews/{crew}/announcements", tk["a"], json={
            "title": f"밖2{TS}", "body": "위도만 밖", "place_lat": 40.5, "place_lng": 127.0})  # lat>39
        assert r.status_code == 422, f"lat>39 → 422 기대, got {r.status_code}"
        ok("도쿄·위도상한 밖 좌표 422")

        step("1c. 좌표 없는 공지 — place null 유지(하위호환)")
        r = api(c, "POST", f"/crews/{crew}/announcements", tk["a"], json={"title": f"무좌표{TS}", "body": "장소 미정"})
        assert r.status_code == 201, r.text[:200]
        a2 = r.json()
        assert a2["place_lat"] is None and a2["place_lng"] is None and a2["place_name"] is None, \
            f"좌표 없는 공지 null 유지, got {a2}"
        ok("좌표 생략 공지 null 유지")

        step("1d. 부분 수정 — 좌표만 갱신")
        r = api(c, "PATCH", f"/crews/{crew}/announcements/{a2['id']}", tk["a"],
                json={"place_name": "성수역", "place_lat": 37.5445, "place_lng": 127.0557})
        assert r.status_code == 200, r.text[:200]
        assert r.json()["place_lat"] == 37.5445, "좌표 수정 반영"
        # 수정에도 bbox 검증
        r = api(c, "PATCH", f"/crews/{crew}/announcements/{a2['id']}", tk["a"], json={"place_lat": 10.0, "place_lng": 127.0})
        assert r.status_code == 422, "수정도 bbox 검증"
        ok("좌표 부분 수정 + 수정 시 bbox 422")

        # ===== 3) 멤버 challenge_km =====
        step("3a. 챌린지 없을 때 — challenge_km null")
        members = api(c, "GET", f"/crews/{crew}/members", tk["a"]).json()
        assert all(m.get("challenge_km") is None for m in members), \
            f"챌린지 없으면 challenge_km null, got {[(m['nickname'], m.get('challenge_km')) for m in members]}"
        ok("진행 챌린지 없음 → 전원 challenge_km null")

        step("3b. 챌린지 개설 + A·B run 적재 → 멤버별 기여 집계")
        now = datetime.now(timezone.utc)
        starts = now - timedelta(days=1)
        ends = now + timedelta(days=5)
        rc = api(c, "POST", f"/crews/{crew}/challenges", tk["a"], json={
            "title": f"챌{TS}", "goal_km": 50.0,
            "starts_at": starts.isoformat(), "ends_at": ends.isoformat()})
        assert rc.status_code in (200, 201), f"챌린지 생성, got {rc.status_code}: {rc.text[:200]}"
        # 창 안(verified): A 5+3, B 2  →  A=8.0, B=2.0
        # 제외돼야: A 창 밖 4(now-3d<starts), A 창 안 suspect 9(verified-only 정책)
        insert_run(c, uids["a"], 5.0, now)
        insert_run(c, uids["a"], 3.0, now - timedelta(hours=2))
        insert_run(c, uids["b"], 2.0, now - timedelta(hours=1))
        insert_run(c, uids["a"], 4.0, now - timedelta(days=3))              # 창 밖 → 제외
        insert_run(c, uids["a"], 9.0, now, verification="suspect")           # verified 아님 → 제외

        members = api(c, "GET", f"/crews/{crew}/members", tk["a"]).json()
        by = {m["user_id"]: m for m in members}
        a_km, b_km = by[uids["a"]]["challenge_km"], by[uids["b"]]["challenge_km"]
        assert a_km == 8.0, f"A 창 안 verified 5+3=8.0 기대(창 밖 4·suspect 9 제외), got {a_km}"
        assert b_km == 2.0, f"B 기여 2.0 기대, got {b_km}"
        ok(f"멤버별 challenge_km: A={a_km}(창 안 verified만) B={b_km} — 창 밖·suspect 제외")

        step("3c. 주간 랭킹 km와 별개 값 확인")
        ranking = api(c, "GET", f"/crews/{crew}/ranking", tk["a"]).json()
        # 랭킹은 이번 주 월 KST 창 → 창 밖(3일 전) run 포함 여부가 challenge와 다를 수 있음.
        # 핵심: 두 값이 독립 필드로 서빙되는지(멤버 응답에 challenge_km, 랭킹은 별 엔드포인트).
        assert "challenge_km" not in (ranking[0] if ranking else {}), "랭킹 엔드포인트는 challenge_km 미포함(별개)"
        ok("challenge_km(멤버)·주간 랭킹(별 엔드포인트) 독립 확인")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
