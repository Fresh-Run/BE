"""
Integration test: DELETE /me (계정 삭제/회원 탈퇴)

docs/ACCOUNT_DELETION_DESIGN.md §7 시나리오 전체:
(e) 크루장 차단 409 + DB 무변화 → 위임 후 (a) 본인 데이터 전량 부재(닉네임
이중검증·아바타 404 포함) (b) 타인 화면 무손상(복사본 보존·공지 author null)
(c) 재가입 (d) 데모 계정 403 (+ 1인 크루 자동 삭제, preferences cascade 회귀).

Run: python tests/test_account_deletion_integration.py  (로컬 서버 필요)
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


def ok(m):        print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):      print(f"\n[{t}]")


def sb_create_user(c, email):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": "test1234", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]


def sb_login(c, email, pw="test1234"):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    assert r.status_code == 200, r.text[:200]
    return r.json()["access_token"]


def sb_delete_user(c, uid):
    return c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {token}"}, **kw)


def rest_insert(c, table, row):
    r = c.post(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "return=representation"},
               json=row)
    assert r.status_code in (200, 201), f"{table} insert: {r.status_code} {r.text[:200]}"
    body = r.json()
    return body[0].get("id") if isinstance(body, list) and body else None


def rest_count(c, table, params):
    r = c.get(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "count=exact"},
              params={**params, "select": "*", "limit": 1})
    cr = r.headers.get("content-range", "?/?").split("/")[-1]
    return int(cr) if cr.isdigit() else -1


def make_track(n=30, start=(37.5445, 127.0374)):
    """직선 궤적 n포인트 — 4초 간격, 포인트당 ~22m(페이스 ~3분/km, 필터 통과)."""
    t0 = TS * 1000
    return [{"lat": start[0] + i * 0.0002, "lng": start[1], "t": t0 + i * 4000, "acc": 5.0}
            for i in range(n)]


ROUTE_ROW = {"summary": "", "target_distance_km": 5.0, "total_distance_km": 5.0,
             "estimated_duration_min": 30, "waypoints": [], "polyline": [],
             "start_lat": 37.5, "start_lng": 127.0, "is_public": True}


def run_tests():
    c = httpx.Client(timeout=60)
    nick_a = f"탈퇴자A{TS}"
    email_a = f"acctdel-a-{TS}@test.com"
    a_uid = b_uid = a2_uid = None
    try:
        step("0. 유저 A(탈퇴 대상)·B(관찰자) 준비")
        a_uid = sb_create_user(c, email_a)
        b_uid = sb_create_user(c, f"acctdel-b-{TS}@test.com")
        tok_a = sb_login(c, email_a)
        tok_b = sb_login(c, f"acctdel-b-{TS}@test.com")
        r = api(c, "PATCH", "/me/profile", tok_a, json={"nickname": nick_a})
        assert r.status_code == 200, r.text[:200]
        r = api(c, "PATCH", "/me/profile", tok_b, json={"nickname": f"관찰자B{TS}"})
        assert r.status_code == 200, r.text[:200]
        ok("유저·프로필 생성")

        step("1. A의 콘텐츠 풀 배치")
        rest_insert(c, "preferences", {"user_id": a_uid, "distance_pref": 5})
        r = api(c, "POST", "/runs", tok_a, json={
            "distance_km": 2.0, "duration_sec": 480, "visibility": "public",
            "ran_at": "2026-07-08T10:00:00+09:00", "gps_track": make_track()})
        assert r.status_code in (200, 201), r.text[:300]
        run_a = r.json()["id"]
        assert rest_count(c, "run_tracks", {"run_id": f"eq.{run_a}"}) == 1, "GPS 궤적 저장 확인"
        route_a = rest_insert(c, "routes", {**ROUTE_ROW, "user_id": a_uid,
                                            "summary": f"A코스{TS}"})
        route_b = rest_insert(c, "routes", {**ROUTE_ROW, "user_id": b_uid,
                                            "summary": f"B코스{TS}"})
        route_b_copy = rest_insert(c, "routes", {**ROUTE_ROW, "user_id": b_uid,
                                                 "summary": f"B복사본{TS}",
                                                 "copied_from": route_a})
        # 상호작용: A→B 콘텐츠 (댓글·좋아요 → B에게 알림, actor=A)
        assert api(c, "POST", f"/routes/{route_b}/comments", tok_a,
                   json={"content": f"A의 흔적 {nick_a}"}).status_code in (200, 201)
        assert api(c, "POST", f"/routes/{route_b}/like", tok_a).status_code in (200, 201, 204)
        # 상호작용: B→A 콘텐츠 (A 삭제 시 함께 소멸해야 할 것들)
        assert api(c, "POST", f"/routes/{route_a}/comments", tok_b,
                   json={"content": "B의 댓글"}).status_code in (200, 201)
        assert api(c, "POST", f"/runs/{run_a}/kudos", tok_b).status_code in (200, 201, 204)
        assert api(c, "POST", f"/users/{b_uid}/follow", tok_a).status_code == 204
        # 아바타 업로드 (public URL 200 확인)
        r = api(c, "POST", "/me/avatar/upload-url", tok_a)
        assert r.status_code == 200, r.text[:200]
        up = r.json()
        pr = c.put(up["upload_url"], content=b"\x89PNG-test-bytes",
                   headers={"Content-Type": "image/png"})
        assert pr.status_code == 200, f"avatar PUT {pr.status_code}: {pr.text[:150]}"
        avatar_url = up["public_url"]
        assert c.get(avatar_url).status_code == 200, "업로드 직후 아바타 접근 가능해야"
        ok(f"run+GPS·route·댓글·좋아요·kudos·팔로우·아바타 배치 (run={run_a[:8]}…)")

        step("2. A의 크루 (B 가입) + 공지")
        r = api(c, "POST", "/crews", tok_a, json={"name": f"탈퇴테스트크루{TS}"})
        assert r.status_code in (200, 201), r.text[:200]
        crew = r.json()["id"]
        assert api(c, "POST", f"/crews/{crew}/join", tok_b).status_code == 200
        r = api(c, "POST", f"/crews/{crew}/announcements", tok_a,
                json={"title": "공지(작성자 A)", "body": "탈퇴 후에도 보존되어야 함"})
        assert r.status_code == 201, r.text[:200]
        annc = r.json()["id"]
        ok("크루(A 소유, B 멤버) + 공지 작성")

        step("3. (e) 크루장 상태로 DELETE /me → 409 + DB 무변화")
        r = api(c, "DELETE", "/me", tok_a)
        assert r.status_code == 409, f"409 기대, got {r.status_code}: {r.text[:200]}"
        d = r.json()["detail"]
        assert d["error"] == "crew_owner" and crew in d["crew_ids"], d
        assert "message" in d, d
        assert rest_count(c, "profiles", {"user_id": f"eq.{a_uid}"}) == 1
        assert rest_count(c, "runs", {"user_id": f"eq.{a_uid}"}) == 1
        assert rest_count(c, "crews", {"id": f"eq.{crew}"}) == 1
        ok("409 crew_owner (crew_ids·message 구조화) + 데이터 무변화")

        step("4. 위임 후 1인 크루 생성 (자동 삭제 경로 검증용)")
        r = api(c, "PATCH", f"/crews/{crew}/transfer", tok_a,
                json={"new_owner_id": b_uid})
        assert r.status_code == 200, f"transfer {r.status_code}: {r.text[:300]}"
        r = api(c, "POST", "/crews", tok_a, json={"name": f"1인크루{TS}"})
        assert r.status_code in (200, 201), r.text[:200]
        solo_crew = r.json()["id"]
        ok("위임 완료 + 1인 크루 생성")

        step("5. DELETE /me → 204")
        r = api(c, "DELETE", "/me", tok_a)
        assert r.status_code == 204, f"204 기대, got {r.status_code}: {r.text[:300]}"
        ok("탈퇴 성공")

        step("6. (a) 본인 데이터 전량 부재")
        for label, table, params in [
            ("profiles", "profiles", {"user_id": f"eq.{a_uid}"}),
            ("preferences(FK fix 회귀)", "preferences", {"user_id": f"eq.{a_uid}"}),
            ("runs", "runs", {"user_id": f"eq.{a_uid}"}),
            ("run_tracks(GPS)", "run_tracks", {"run_id": f"eq.{run_a}"}),
            ("routes", "routes", {"user_id": f"eq.{a_uid}"}),
            ("route_comments", "route_comments", {"user_id": f"eq.{a_uid}"}),
            ("route_likes", "route_likes", {"user_id": f"eq.{a_uid}"}),
            ("run_kudos(B→A런도 소멸)", "run_kudos", {"run_id": f"eq.{run_a}"}),
            ("follows", "follows", {"or": f"(follower_id.eq.{a_uid},following_id.eq.{a_uid})"}),
            ("notifications", "notifications", {"or": f"(user_id.eq.{a_uid},actor_id.eq.{a_uid})"}),
            ("crew_members", "crew_members", {"user_id": f"eq.{a_uid}"}),
            ("crews(1인 크루 자동삭제)", "crews", {"id": f"eq.{solo_crew}"}),
        ]:
            n = rest_count(c, table, params)
            assert n == 0, f"{label}: {n}건 잔존"
        assert c.get(avatar_url).status_code != 200, "아바타가 여전히 접근 가능"
        # 닉네임 이중검증: B가 보는 화면(크루 상세·B코스 댓글)에 값 자체가 없어야
        for path in (f"/crews/{crew}/members", f"/routes/{route_b}/comments"):
            r = api(c, "GET", path, tok_b)
            assert r.status_code == 200, f"{path}: {r.status_code}"
            assert nick_a not in r.text, f"{path} 응답에 탈퇴자 닉네임 잔존"
        ok("12개 지점 0건 + 아바타 접근 불가 + 닉네임 값 부재(이중검증)")

        step("7. (b) 타인(B) 화면 무손상")
        assert rest_count(c, "routes", {"id": f"eq.{route_b}"}) == 1
        r = c.get(f"{_SB}/rest/v1/routes", headers=_ADM,
                  params={"id": f"eq.{route_b_copy}", "select": "id,copied_from"})
        rows = r.json()
        assert rows and rows[0]["copied_from"] is None, f"복사본 보존 실패: {rows}"
        r = c.get(f"{_SB}/rest/v1/crews", headers=_ADM,
                  params={"id": f"eq.{crew}", "select": "owner_id"})
        assert r.json()[0]["owner_id"] == b_uid, "위임된 크루 소유자"
        r = c.get(f"{_SB}/rest/v1/crew_announcements", headers=_ADM,
                  params={"id": f"eq.{annc}", "select": "id,author_id"})
        rows = r.json()
        assert rows and rows[0]["author_id"] is None, f"공지 보존(author null) 실패: {rows}"
        r = api(c, "GET", f"/crews/{crew}/announcements", tok_b)
        assert r.status_code == 200, f"공지 목록 {r.status_code}: {r.text[:200]}"
        assert api(c, "GET", "/notifications", tok_b).status_code == 200
        ok("B 코스·복사본(copied_from null)·크루·공지(author null)·알림 목록 정상")

        step("8. (c) 같은 이메일 재가입 + 닉네임 재사용")
        a2_uid = sb_create_user(c, email_a)
        assert a2_uid != a_uid, "재가입은 새 user_id여야"
        tok_a2 = sb_login(c, email_a)
        r = api(c, "PATCH", "/me/profile", tok_a2, json={"nickname": nick_a})
        assert r.status_code == 200, f"닉네임 재사용 실패: {r.text[:200]}"
        ok("재가입 + 이전 닉네임 등록 성공")

        step("9. (d) 데모 계정 보호")
        tok_demo = sb_login(c, "test2@freshrun.com")
        demo_uid = api(c, "GET", "/me", tok_demo).json()["user_id"]
        r = api(c, "DELETE", "/me", tok_demo)
        assert r.status_code == 403, f"403 기대, got {r.status_code}"
        assert r.json()["detail"]["error"] == "demo_account", r.text[:200]
        assert rest_count(c, "profiles", {"user_id": f"eq.{demo_uid}"}) == 1, "test2 프로필 무변화"
        ok("test2 탈퇴 403 demo_account + 프로필 무변화")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup: 테스트 데이터 삭제")
        # A2(재가입)·B는 auth 삭제가 cascade로 전부 정리 (이번 기능의 산물)
        for uid in (a2_uid, b_uid):
            if uid:
                sb_delete_user(c, uid)
        if a_uid:  # 시나리오 실패로 A가 남았을 때만 유효
            c.delete(f"{_SB}/rest/v1/preferences", headers=_ADM,
                     params={"user_id": f"eq.{a_uid}"})
            sb_delete_user(c, a_uid)
        leftover = sum(rest_count(c, t, {"user_id": f"eq.{u}"}) or 0
                       for t in ("profiles", "runs", "routes")
                       for u in (a_uid, b_uid, a2_uid) if u)
        print(f"  잔존 확인: {leftover}건" + (" ✓" if leftover == 0 else " ⚠️ 수동 확인 필요"))


if __name__ == "__main__":
    run_tests()
