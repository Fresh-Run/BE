"""
Integration test: CrewCreate·CrewUpdate extra="forbid" (M-7 확장, 크루 계열 정합)

미지·오타 필드 silent ignore(200) → 422 봉쇄. is_public/join_policy 오타로
프라이버시 설정이 무시되던 갭 제거. null 삭제 시맨틱과 공존 확인.

케이스:
 1. CrewCreate 오타 필드(is_publik) → 422 · 유효 필드만 → 생성 200/201
 2. CrewUpdate 오타 필드(sidoo) → 422 · 유효 필드(sido) → 200
 3. is_public/join_policy 오타(is_publik) → 422(silent ignore 아님 = 갭 봉쇄)
 4. 회귀: 유효 필드 조합 PATCH 200 + null 삭제 시맨틱(sido:null) forbid와 공존
 5. 권한: member PATCH(유효 필드) → 403 · 없는 크루 → 404 (게이트 불변)

Run: python tests/test_crew_extra_forbid_integration.py  (로컬 서버 필요)
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


def db_crew(c, crew_id, cols="sido,sigungu,lat,lng,is_public,join_policy,name"):
    r = c.get(f"{_SB}/rest/v1/crews", headers=_ADM, params={"id": f"eq.{crew_id}", "select": cols})
    return r.json()[0] if r.json() else None


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    crew = None
    try:
        step("0. O(owner)·M(member)")
        for k in ("o", "m"):
            uids[k] = sb_user(c, f"cef-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"cef-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CEF{k}{TS}"}).status_code == 200
        ok("유저 2명")

        step("1. CrewCreate — 오타 필드 422 (검증이 무료 한도보다 앞) · 유효만 200/201")
        # 오타 create: is_publik(오타) → 422. 스키마 검증이 핸들러(한도 체크)보다 앞이라
        # 크루 생성 안 됨(슬롯 미소모).
        r = api(c, "POST", "/crews", tk["o"], json={"name": f"오타크루{TS}", "is_publik": True})
        assert r.status_code == 422, f"CrewCreate 오타 필드 422 기대, got {r.status_code}: {r.text[:150]}"
        # 유효 필드만 → 정상 생성
        r = api(c, "POST", "/crews", tk["o"], json={
            "name": f"정상크루{TS}", "sido": "서울특별시", "sigungu": "성동구",
            "lat": 37.5445, "lng": 127.0374, "is_public": True, "join_policy": "open",
            "tags": ["새벽", "평지"]})
        assert r.status_code in (200, 201), f"유효 CrewCreate 생성 기대, got {r.status_code}: {r.text[:150]}"
        crew = r.json()["id"]
        ok("CrewCreate 오타 422 · 유효 필드 생성 성공")

        step("2. CrewUpdate — 오타 필드 422 · 유효 필드 200")
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"sidoo": "서울특별시"})  # 오타
        assert r.status_code == 422, f"CrewUpdate 오타 필드 422 기대, got {r.status_code}: {r.text[:150]}"
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"sido": "부산광역시"})  # 유효
        assert r.status_code == 200, f"유효 CrewUpdate 200, got {r.status_code}"
        assert db_crew(c, crew)["sido"] == "부산광역시", "유효 필드 저장 확인"
        ok("CrewUpdate 오타 422 · 유효 필드 200+저장")

        step("3. is_public/join_policy 오타 → 422 (silent ignore 아님 = 갭 봉쇄)")
        before = db_crew(c, crew)["is_public"]
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"is_publik": False})  # 오타
        assert r.status_code == 422, f"is_publik 오타 422 기대, got {r.status_code}"
        # 갭 봉쇄 증명: 오타가 silent ignore됐다면 200이었을 것 + is_public 그대로.
        # 이제 422로 거부되므로 클라가 오타를 인지. is_public도 안 바뀜(요청 거부).
        assert db_crew(c, crew)["is_public"] == before, "오타 거부 → is_public 무변경"
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"join_polcy": "approval"})  # 오타
        assert r.status_code == 422, f"join_polcy 오타 422 기대, got {r.status_code}"
        ok("is_publik·join_polcy 오타 → 422 (프라이버시 갭 봉쇄, 무변경)")

        step("4. 회귀 — 유효 조합 PATCH 200 + null 삭제 시맨틱 forbid와 공존")
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={
            "sido": "서울특별시", "sigungu": "용산구", "lat": 37.53, "lng": 126.97,
            "name": f"갱신{TS}", "description": "설명", "join_policy": "approval",
            "tags": ["저녁", "친목"]})
        assert r.status_code == 200, f"유효 다필드 PATCH 200, got {r.status_code}: {r.text[:150]}"
        p = db_crew(c, crew)
        assert p["sido"] == "서울특별시" and p["sigungu"] == "용산구" and p["join_policy"] == "approval", f"저장 확인 {p}"
        # null 삭제 시맨틱이 forbid와 공존: sido:null → 삭제(유효 키의 null이라 통과)
        r = api(c, "PATCH", f"/crews/{crew}", tk["o"], json={"sido": None})
        assert r.status_code == 200, f"sido null 삭제 200(forbid 공존), got {r.status_code}"
        assert db_crew(c, crew)["sido"] is None, "sido 삭제됨(null 시맨틱 유지)"
        assert db_crew(c, crew)["sigungu"] == "용산구", "sigungu 생략 유지"
        ok("유효 다필드 PATCH 200 · sido:null 삭제 forbid와 공존")

        step("5. 권한 회귀 — member PATCH(유효) 403 · 없는 크루 404 (validation 순서)")
        # 유효 필드를 보내 스키마 통과 → 핸들러 권한 체크 도달 → 403.
        r = api(c, "PATCH", f"/crews/{crew}", tk["m"], json={"sido": "서울특별시"})
        assert r.status_code == 403, f"member 유효 PATCH 403 기대, got {r.status_code}"
        ghost = "00000000-0000-0000-0000-000000000000"
        r = api(c, "PATCH", f"/crews/{ghost}", tk["o"], json={"sido": "서울특별시"})
        assert r.status_code == 404, f"없는 크루 404 기대, got {r.status_code}"
        ok("member 유효 PATCH 403 · 없는 크루 404 (forbid가 권한 게이트 안 가림)")

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
