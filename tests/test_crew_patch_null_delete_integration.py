"""
Integration test: 크루 PATCH null 삭제 버그 수정 (docs/CREW_FEED_FIXES_DESIGN.md Part 2)

exclude_none 일괄 제거 → model_fields_set 선별 포함. "생략=유지 / 명시 null=삭제
(sido·sigungu·lat·lng 4개만) / 값=설정" 3분기.

매트릭스(설계 §테스트계획 전수):
 1. sido/sigungu/lat/lng 각각 — 명시 null=삭제(DB null)·생략=유지·값=설정
 2. 생략 vs 명시 null 구분: sido만 null + sigungu 생략 → sido만 삭제·sigungu 유지
 3. tags: 명시 null=유지(삭제 안 됨) / []=비워짐
 4. name: 명시 null=유지(삭제 불가, 화이트리스트 밖)
 5. cover/icon 회귀: 기존 명시 null=삭제 동작 그대로 (리팩터로 안 깨짐)
 6. 값+검증 회귀: sido enum 위반 422·lat/lng bbox 위반 422 (null 삭제 경로가 우회 안 함)
 7. 권한 회귀: member PATCH 403 · 없는 크루 404

Run: python tests/test_crew_patch_null_delete_integration.py  (로컬 서버 필요)
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


def db_crew(c, crew_id, cols="sido,sigungu,lat,lng,tags,name,cover_url,icon_url"):
    """크루 row 직접 조회 — DB 부수효과 assert용."""
    r = c.get(f"{_SB}/rest/v1/crews", headers=_ADM,
              params={"id": f"eq.{crew_id}", "select": cols})
    return r.json()[0]


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    crew = None
    try:
        step("0. O(owner)·M(member) + 크루(지역 필드 채워서 생성)")
        for k in ("o", "m"):
            uids[k] = sb_user(c, f"cpnd-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"cpnd-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CPND{k}{TS}"}).status_code == 200
        r = api(c, "POST", "/crews", tk["o"], json={
            "name": f"지역크루{TS}", "sido": "서울특별시", "sigungu": "성동구",
            "lat": 37.5445, "lng": 127.0374, "tags": ["새벽", "평지"]})
        assert r.status_code in (200, 201), r.text[:200]
        crew = r.json()["id"]
        assert api(c, "POST", f"/crews/{crew}/join", tk["m"]).status_code == 200
        p = db_crew(c, crew)
        assert p["sido"] == "서울특별시" and p["sigungu"] == "성동구" and p["lat"] == 37.5445, f"초기 지역값, got {p}"
        ok(f"크루 생성(sido/sigungu/lat/lng/tags 채움) + member 가입")

        step("1a. sido 명시 null → 삭제(DB null) + 다른 필드 유지")
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"sido": None})
        assert r.status_code == 200, r.text[:200]
        p = db_crew(c, crew)
        assert p["sido"] is None, f"sido 삭제(null)됨, got {p['sido']!r}"
        assert p["sigungu"] == "성동구" and p["lat"] == 37.5445 and p["lng"] == 127.0374, \
            f"sido만 삭제·나머지 유지, got {p}"
        ok("sido 명시 null → DB null · sigungu/lat/lng 유지")

        step("1b. 생략 → 유지 (sido 재설정 후 다른 필드 PATCH가 sido 안 건드림)")
        api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"sido": "서울특별시"})  # 복원
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"description": "설명만"})
        assert r.status_code == 200
        p = db_crew(c, crew)
        assert p["sido"] == "서울특별시", f"sido 생략 → 유지, got {p['sido']!r}"
        ok("sido 생략(다른 필드 PATCH) → 유지")

        step("1c. sigungu/lat/lng 각각 명시 null → 삭제")
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"sigungu": None}).status_code == 200
        assert db_crew(c, crew)["sigungu"] is None, "sigungu 삭제"
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"lat": None}).status_code == 200
        assert db_crew(c, crew)["lat"] is None, "lat 삭제"
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"lng": None}).status_code == 200
        assert db_crew(c, crew)["lng"] is None, "lng 삭제"
        ok("sigungu·lat·lng 각각 명시 null → DB null")

        step("1d. 값 전송 → 설정 (4필드 복원)")
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={
            "sido": "부산광역시", "sigungu": "해운대구", "lat": 35.16, "lng": 129.16})
        assert r.status_code == 200
        p = db_crew(c, crew)
        assert p["sido"] == "부산광역시" and p["sigungu"] == "해운대구" and p["lat"] == 35.16 and p["lng"] == 129.16, \
            f"값 전송 → 설정, got {p}"
        ok("sido/sigungu/lat/lng 값 전송 → 설정")

        step("2. 생략 vs 명시 null 혼합 — sido만 null + sigungu 생략 + name 갱신")
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"sido": None, "name": f"새이름{TS}"})
        assert r.status_code == 200
        p = db_crew(c, crew)
        assert p["sido"] is None, "sido 삭제"
        assert p["sigungu"] == "해운대구", "sigungu 생략 → 유지(안 지워짐)"
        assert p["name"] == f"새이름{TS}", "name 갱신"
        ok("혼합 PATCH: sido 삭제 · sigungu 유지 · name 갱신 동시")

        step("3. tags — 명시 null=유지(삭제 안 됨) / []=비워짐")
        # 현재 tags=["새벽","평지"]. null 보내도 화이트리스트 밖이라 유지.
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"tags": None})
        assert r.status_code == 200
        assert db_crew(c, crew)["tags"] == ["새벽", "평지"], f"tags 명시 null → 유지, got {db_crew(c, crew)['tags']}"
        # [] 보내면 비워짐
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"tags": []})
        assert r.status_code == 200
        assert db_crew(c, crew)["tags"] == [], f"tags [] → 비워짐, got {db_crew(c, crew)['tags']}"
        ok("tags 명시 null=유지(화이트리스트 밖) · []=비워짐")

        step("4. name 명시 null → 유지 (삭제 불가, 화이트리스트 밖)")
        before_name = db_crew(c, crew)["name"]
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"name": None})
        # name None은 Optional 통과 → exclude_none이 떨굼 → 유지(무시). 200 예상.
        assert r.status_code == 200, f"name null 200(무시) 기대, got {r.status_code}: {r.text[:150]}"
        assert db_crew(c, crew)["name"] == before_name, f"name 유지(삭제 안 됨), got {db_crew(c, crew)['name']!r}"
        ok(f"name 명시 null → 유지({before_name}) — 삭제 불가")

        step("5. cover/icon 회귀 — 기존 null=삭제 동작 (리팩터로 안 깨짐)")
        # 업로드 없이 cover_url을 직접 세팅할 순 없음(경로 검증) → admin으로 심고 null 삭제 확인.
        c.patch(f"{_SB}/rest/v1/crews?id=eq.{crew}", headers=_ADM,
                json={"cover_url": "https://example.com/x", "icon_url": "https://example.com/y"})
        assert db_crew(c, crew)["cover_url"] is not None, "admin 심기 확인"
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"cover_url": None, "icon_url": None})
        assert r.status_code == 200, f"cover/icon null 삭제 200, got {r.status_code}: {r.text[:150]}"
        p = db_crew(c, crew)
        assert p["cover_url"] is None and p["icon_url"] is None, f"cover/icon 명시 null → 삭제, got {p}"
        ok("cover_url·icon_url 명시 null → 삭제 (기존 동작 회귀 통과)")

        step("6. 값+검증 회귀 — 잘못된 sido enum·bbox 밖 lat/lng → 422")
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"sido": "화성시"}).status_code == 422, "잘못된 sido 422"
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"lat": 10.0}).status_code == 422, "bbox 밖 lat 422"
        assert api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"lng": 200.0}).status_code == 422, "bbox 밖 lng 422"
        # 삭제 경로가 검증을 우회하지 않는지: 값 검증은 여전히 살아있음(위 3건이 증명)
        ok("잘못된 sido/lat/lng 값 → 422 (null 삭제 경로가 검증 우회 안 함)")

        step("7. 권한 회귀 — member PATCH 403 · 없는 크루 404")
        assert api(c, "PATCH", f"/crews/{crew}", tk["m"], json={"sido": None}).status_code == 403, "member 403"
        ghost = "00000000-0000-0000-0000-000000000000"
        assert api(c, "PATCH", f"/crews/{ghost}", tk["o"], json={"sido": None}).status_code == 404, "없는 크루 404"
        ok("member PATCH 403 · 없는 크루 404 (게이트 불변)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        if crew:
            c.delete(f"{_SB}/rest/v1/crews?id=eq.{crew}", headers=_ADM)
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (crews·crew_members cascade)")


if __name__ == "__main__":
    run_tests()
