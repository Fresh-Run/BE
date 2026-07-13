"""
Integration test: 크루 상설 집결지 meet_place (docs/CREW_MEET_PLACE_DESIGN.md)

crews additive 3컬럼(meet_place_name/meet_lat/meet_lng — 공지 place_*와 독립).
검증은 공지 규칙 복제(≤100자·한국 bbox). null=clear는 _NULL_DELETABLE 확장.
권한은 기존 PATCH 게이트(edit_crew) 상속.

케이스:
 1. 생성 시 설정 → 응답 노출 + DB 저장
 2. PATCH 설정 → 200 + DB 반영 + 응답 노출 · 일부만(name만)도 그 필드만
 3. null=clear 3필드 각각 + 생략=유지
 4. 혼합: {meet_lat:null, meet_place_name:"새 장소"} → 동시 clear+set
 5. 검증 422: 101자 / lat 32.9·39.1 / lng bbox 밖
 6. 권한: member 403 / edit_crew admin 200 (게이트 상속)
 7. forbid 공존: 오타(meet_place_nam) 422 · 유효 3필드 통과
 8. 응답 노출: 상세·mine·browse에 meet_* 포함(미설정 크루 null) — 스프레드 자동

Run: python tests/test_crew_meet_place_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
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


def db_meet(c, crew_id):
    r = c.get(f"{_SB}/rest/v1/crews", headers=_ADM,
              params={"id": f"eq.{crew_id}", "select": "meet_place_name,meet_lat,meet_lng"})
    return r.json()[0]


PLACE = "서울숲 공원 정문"


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    crews = []
    try:
        step("0. O(owner)·A(→edit_crew admin)·M(member) 준비")
        for k in ("o", "a", "m"):
            uids[k] = sb_user(c, f"cmp-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"cmp-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CMP{k}{TS}"}).status_code == 200
        ok("유저 3명")

        step("1. 생성 시 설정 — POST /crews에 meet_* 3필드")
        r = api(c, "POST", "/crews", tk["o"], json={
            "name": f"집결지크루{TS}", "meet_place_name": PLACE,
            "meet_lat": 37.5445, "meet_lng": 127.0374,
            "active_days": ["화", "목"], "active_time": "06:00"})
        assert r.status_code in (200, 201), r.text[:200]
        d = r.json(); crew = d["id"]; crews.append(crew)
        assert d["meet_place_name"] == PLACE and d["meet_lat"] == 37.5445 and d["meet_lng"] == 127.0374, \
            f"생성 응답 노출, got {d.get('meet_place_name')}, {d.get('meet_lat')}, {d.get('meet_lng')}"
        p = db_meet(c, crew)
        assert p["meet_place_name"] == PLACE and p["meet_lat"] == 37.5445, f"DB 저장, got {p}"
        # A·M 가입
        for k in ("a", "m"):
            assert api(c, "POST", f"/crews/{crew}/join", tk[k]).status_code == 200
        ok("생성 시 meet_* 설정 · 응답 노출 · DB 저장")

        step("2. PATCH 설정/수정 — 전체 + 일부만")
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={
            "meet_place_name": "뚝섬유원지역 3번 출구", "meet_lat": 37.5311, "meet_lng": 127.0668})
        assert r.status_code == 200, r.text[:150]
        assert r.json()["meet_place_name"] == "뚝섬유원지역 3번 출구", "응답 반영"
        assert db_meet(c, crew)["meet_lat"] == 37.5311, "DB 반영"
        # 일부만: name만 변경 → 좌표 유지
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"meet_place_name": PLACE})
        assert r.status_code == 200
        p = db_meet(c, crew)
        assert p["meet_place_name"] == PLACE and p["meet_lat"] == 37.5311, f"name만 갱신·좌표 유지, got {p}"
        ok("PATCH 전체·일부 설정 (생략 필드 유지)")

        step("3. null=clear — 3필드 각각 + 생략 유지")
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"meet_place_name": None}).status_code == 200
        p = db_meet(c, crew)
        assert p["meet_place_name"] is None and p["meet_lat"] == 37.5311, f"name만 clear·lat 유지, got {p}"
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"meet_lat": None}).status_code == 200
        assert db_meet(c, crew)["meet_lat"] is None, "meet_lat clear"
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"meet_lng": None}).status_code == 200
        assert db_meet(c, crew)["meet_lng"] is None, "meet_lng clear"
        ok("3필드 각각 명시 null=clear · 생략=유지")

        step("4. 혼합 — {meet_lat:null 은 이미 null, meet_lng:127.0 set + name set}")
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={
            "meet_place_name": "새 장소", "meet_lat": 37.5, "meet_lng": 127.0})
        assert r.status_code == 200
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={
            "meet_lat": None, "meet_place_name": "혼합 장소"})
        assert r.status_code == 200
        p = db_meet(c, crew)
        assert p["meet_lat"] is None and p["meet_place_name"] == "혼합 장소" and p["meet_lng"] == 127.0, \
            f"lat clear + name set + lng 유지 동시, got {p}"
        ok("혼합 PATCH: clear+set+유지 동시")

        step("5. 검증 422 — 101자·bbox 밖")
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"],
                   json={"meet_place_name": "가" * 101}).status_code == 422, "101자 422"
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"meet_lat": 32.9}).status_code == 422, "lat 32.9 422"
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"meet_lat": 39.1}).status_code == 422, "lat 39.1 422"
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"meet_lng": 123.9}).status_code == 422, "lng 123.9 422"
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"meet_lng": 132.1}).status_code == 422, "lng 132.1 422"
        ok("길이 101자·lat/lng bbox 밖 → 422 (공지 규칙 복제)")

        step("6. 권한 — member 403 · edit_crew admin 200 (게이트 상속)")
        r = api(c, "PATCH", f"/crews/{crew}", tk["m"], json={"meet_place_name": "몰래"})
        assert r.status_code == 403, f"member 403, got {r.status_code}"
        # A를 admin 승격 + edit_crew 부여
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a']}/role", tk["o"],
                   json={"role": "admin"}).status_code in (200, 204)
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a']}/permissions", tk["o"],
                   json={"edit_crew": True}).status_code in (200, 204)
        r = api(c, "PATCH", f"/crews/{crew}", tk["a"], json={"meet_place_name": "관리자설정"})
        assert r.status_code == 200, f"edit_crew admin 200, got {r.status_code}: {r.text[:150]}"
        assert db_meet(c, crew)["meet_place_name"] == "관리자설정", "admin 설정 반영"
        ok("member 403 · edit_crew admin 200 (기존 게이트 상속)")

        step("7. forbid 공존 — 오타 422 · 유효 통과")
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"],
                   json={"meet_place_nam": "오타"}).status_code == 422, "오타 필드 422"
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"],
                   json={"meet_place_name": PLACE, "meet_lat": 37.5445, "meet_lng": 127.0374}).status_code == 200
        ok("오타 meet_place_nam 422 · 유효 3필드 통과 (forbid 공존)")

        step("8. 응답 노출 — 상세·mine·browse + 미설정 크루 null")
        d = api(c, "GET", f"/crews/{crew}", tk["o"]).json()
        assert d["meet_place_name"] == PLACE and d["meet_lat"] == 37.5445, "상세 노출"
        mine = api(c, "GET", "/crews/mine", tk["o"]).json()
        mc = next(x for x in mine if x["id"] == crew)
        assert mc["meet_place_name"] == PLACE, "mine 노출"
        # 미설정 크루: M이 새 크루 생성(meet 없음) → null
        r = api(c, "POST", "/crews", tk["m"], json={"name": f"무집결크루{TS}"})
        crew2 = r.json()["id"]; crews.append(crew2)
        d2 = api(c, "GET", f"/crews/{crew2}", tk["m"]).json()
        assert d2["meet_place_name"] is None and d2["meet_lat"] is None, "미설정 크루 null"
        # browse(공개 목록)에서도 필드 존재 확인
        br = api(c, "GET", "/crews", tk["o"]).json()
        if br and isinstance(br, list):
            assert "meet_place_name" in br[0], "browse 응답에 필드 존재(스프레드 자동)"
        ok("상세·mine·browse 노출 · 미설정 크루 null")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for cid in crews:
            c.delete(f"{_SB}/rest/v1/crews?id=eq.{cid}", headers=_ADM)
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (crews·crew_members cascade)")


if __name__ == "__main__":
    run_tests()
