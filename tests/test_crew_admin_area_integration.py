"""
Integration test: 크루 admin role v1 + run 지역명(area) + 트랙 거리 버그 수정
(docs/CREW_ADMIN_AND_RUN_AREA_DESIGN.md)

- role API 규칙(owner 전용·target=owner 422·비멤버 404·멱등)
- 권한 매트릭스: owner/admin/member × (공지 CRUD·챌린지 생성·강퇴·transfer·
  크루 수정·삭제·초대 코드·role 변경) + 강등 후 권한 소멸
- run.area 왕복(저장·편집·타인 상세·크루 피드 카드·51자 422)
- 0.2km 미만 트랙의 server_distance_km > 0 (§1 수정 검증)

Run: python tests/test_crew_admin_area_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timedelta, timezone
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
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {token}"}, **kw)


def short_track(n=12, step_m=15.0, pace=360):
    t0 = (TS - 7200) * 1000
    return [{"lat": 37.5445 + i * step_m / 110540.0, "lng": 127.0374,
             "t": t0 + i * round(step_m * pace), "acc": 5.0} for i in range(n)]


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    try:
        step("0. O(owner)·A(→admin)·M·M2(member) + 크루")
        for k in ("o", "a", "m", "m2"):
            uids[k] = sb_user(c, f"adm-{k}-{TS}@test.com")
        tok = {k: sb_login(c, f"adm-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tok[k],
                       json={"nickname": f"ADM{k}{TS}"}).status_code == 200
        r = api(c, "POST", "/crews", tok["o"], json={"name": f"운영진크루{TS}"})
        assert r.status_code in (200, 201), r.text[:200]
        crew = r.json()["id"]
        for k in ("a", "m", "m2"):
            assert api(c, "POST", f"/crews/{crew}/join", tok[k]).status_code == 200
        ok("크루 + 멤버 4명")

        step("1. role API — 승격·멱등·정렬·규칙")
        r = api(c, "PATCH", f"/crews/{crew}/members/{uids['a']}/role", tok["o"],
                json={"role": "admin"})
        assert r.status_code == 200 and r.json() == {"user_id": uids["a"], "role": "admin"}, r.text[:200]
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a']}/role", tok["o"],
                   json={"role": "admin"}).status_code == 200, "멱등"
        members = api(c, "GET", f"/crews/{crew}/members", tok["o"]).json()
        roles = [m["role"] for m in members]
        assert roles[0] == "owner" and roles[1] == "admin", f"정렬 owner→admin→member: {roles}"
        # 규칙: 비owner 403 / target=owner 422 / 비멤버 404 / role enum 422
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['m']}/role", tok["a"],
                   json={"role": "admin"}).status_code == 403, "admin도 role 변경 불가"
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['o']}/role", tok["o"],
                   json={"role": "member"}).status_code == 422, "owner role 불변"
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['o']}/role", tok["o"],
                   json={"role": "owner"}).status_code == 422, "owner로 변경 자체가 enum 밖"
        ghost = "00000000-0000-4000-8000-000000000000"
        assert api(c, "PATCH", f"/crews/{crew}/members/{ghost}/role", tok["o"],
                   json={"role": "admin"}).status_code == 404, "비멤버 404"
        ok("승격·멱등·정렬 + 403/422/404 규칙 ✓")

        step("2. 권한 매트릭스 — admin 확장 3종")
        # 공지: admin 생성/수정/삭제 가능, member 403
        r = api(c, "POST", f"/crews/{crew}/announcements", tok["a"],
                json={"title": "admin 공지", "body": "운영진이 씁니다"})
        assert r.status_code == 201, f"admin 공지 생성: {r.status_code}"
        ann = r.json()["id"]
        assert api(c, "PATCH", f"/crews/{crew}/announcements/{ann}", tok["a"],
                   json={"title": "admin 수정"}).status_code == 200
        assert api(c, "POST", f"/crews/{crew}/announcements", tok["m"],
                   json={"title": "x", "body": "y"}).status_code == 403, "member 공지 403"
        assert api(c, "DELETE", f"/crews/{crew}/announcements/{ann}", tok["a"]).status_code == 204
        # 챌린지: admin 생성 가능, member 403
        now = datetime.now(timezone.utc)
        ch_body = {"title": "운영진 챌린지", "goal_km": 100.0,
                   "starts_at": (now - timedelta(hours=1)).isoformat(),
                   "ends_at": (now + timedelta(days=7)).isoformat()}
        assert api(c, "POST", f"/crews/{crew}/challenges", tok["m"],
                   json=ch_body).status_code == 403, "member 챌린지 403"
        assert api(c, "POST", f"/crews/{crew}/challenges", tok["a"],
                   json=ch_body).status_code in (200, 201), "admin 챌린지 생성"
        # 강퇴: v2 — kick_members 권한 필요(신규 admin 기본 OFF라 부여 후 테스트).
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a']}/permissions", tok["o"],
                   json={"kick_members": True}).status_code == 200
        # admin(kick 보유)이 member 강퇴 OK / admin·owner 강퇴 403 / member 강퇴 403
        assert api(c, "DELETE", f"/crews/{crew}/members/{uids['o']}", tok["a"]).status_code == 403
        assert api(c, "DELETE", f"/crews/{crew}/members/{uids['m']}", tok["m2"]).status_code == 403
        assert api(c, "DELETE", f"/crews/{crew}/members/{uids['m2']}", tok["a"]).status_code == 204
        assert api(c, "POST", f"/crews/{crew}/join", tok["m2"]).status_code == 200  # 재가입
        # admin이 admin 강퇴 403: m2를 admin 승격 후 시도
        api(c, "PATCH", f"/crews/{crew}/members/{uids['m2']}/role", tok["o"], json={"role": "admin"})
        assert api(c, "DELETE", f"/crews/{crew}/members/{uids['m2']}", tok["a"]).status_code == 403
        api(c, "PATCH", f"/crews/{crew}/members/{uids['m2']}/role", tok["o"], json={"role": "member"})
        ok("공지 CRUD·챌린지·강퇴(제약 포함) 매트릭스 ✓")

        step("3. 권한 매트릭스 — owner 전용 유지 3종 + edit_crew(v2)")
        assert api(c, "PATCH", f"/crews/{crew}/transfer", tok["a"],
                   json={"new_owner_id": uids["m"]}).status_code == 403, "위임 owner 전용"
        assert api(c, "DELETE", f"/crews/{crew}", tok["a"]).status_code == 403, "삭제 owner 전용"
        assert api(c, "POST", f"/crews/{crew}/invite", tok["a"]).status_code == 403, "초대 코드 owner 전용"
        # v2: 크루 수정은 edit_crew 게이트(owner 전용 아님) — a는 기본 미보유라 403,
        # 부여하면 200(owner 전용에서 이관됨).
        assert api(c, "PATCH", f"/crews/{crew}", tok["a"], json={"description": "x"}).status_code == 403, "edit_crew 미보유 403"
        assert api(c, "PATCH", f"/crews/{crew}/members/{uids['a']}/permissions", tok["o"],
                   json={"edit_crew": True}).status_code == 200
        assert api(c, "PATCH", f"/crews/{crew}", tok["a"], json={"description": "x"}).status_code == 200, "edit_crew 부여 후 수정 200"
        ok("transfer·삭제·초대 owner 전용 유지 / 크루 수정은 edit_crew로 이관(v2) ✓")

        step("4. 강등 → 권한 즉시 소멸")
        api(c, "PATCH", f"/crews/{crew}/members/{uids['a']}/role", tok["o"], json={"role": "member"})
        assert api(c, "POST", f"/crews/{crew}/announcements", tok["a"],
                   json={"title": "x", "body": "y"}).status_code == 403, "강등 후 공지 403"
        ok("member 강등 후 공지 생성 403 ✓")

        step("5. run.area — 저장·편집·타인 상세·크루 피드·검증")
        r = api(c, "POST", "/runs", tok["m"], json={
            "distance_km": 3.0, "duration_sec": 1200, "visibility": "public",
            "area": "성수동"})
        assert r.status_code == 200 and r.json()["area"] == "성수동", r.text[:200]
        rid = r.json()["id"]
        assert api(c, "GET", f"/runs/{rid}", tok["o"]).json()["area"] == "성수동", \
            "타인 상세 화이트리스트에 area 포함"
        r = api(c, "PATCH", f"/runs/{rid}", tok["m"], json={"area": "뚝섬"})
        assert r.status_code == 200 and r.json()["area"] == "뚝섬", "편집"
        feed = api(c, "GET", f"/crews/{crew}/runs", tok["o"]).json()
        card = next(x for x in feed if x["run_id"] == rid)
        assert card["area"] == "뚝섬", f"크루 피드 카드 area: {card.get('area')}"
        assert api(c, "POST", "/runs", tok["m"], json={
            "distance_km": 1.0, "duration_sec": 400, "area": "가" * 51}).status_code == 422, "51자 422"
        ok("저장→타인 상세→편집→크루 카드 + 51자 422 ✓")

        step("6. 트랙 거리 수정 — 0.2km 미만 server_distance_km > 0")
        r = api(c, "POST", "/runs", tok["m"], json={
            "distance_km": 0.17, "duration_sec": 60, "visibility": "public",
            "gps_track": short_track()})
        assert r.status_code == 200, r.text[:250]
        d = r.json()
        assert d["has_track"], "짧은 트랙도 저장"
        t = api(c, "GET", f"/runs/{d['id']}/track", tok["m"]).json()
        assert 0.1 <= t["server_distance_km"] <= 0.25, \
            f"0.2km 미만도 실거리 반환(구버그 0.0): {t['server_distance_km']}"
        ok(f"server_distance_km={t['server_distance_km']} (>0, 저장 컬럼 사용) ✓")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup: DELETE /me cascade (O는 크루 삭제 후)")
        try:
            api(c, "DELETE", f"/crews/{crew}", tok["o"])
        except Exception:
            pass
        for k in list(uids):
            c.delete(f"{_SB}/auth/v1/admin/users/{uids[k]}", headers=_ADM)
        print("  유저 4명 + cascade 정리")


if __name__ == "__main__":
    run_tests()
