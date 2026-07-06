"""
Integration test: run visibility + 공개 프로필 (저장 화면 확장)
1) 저장 왕복 — title/visibility, 422, 페이스 비교 필드
2) 노출 매트릭스 — A의 public/followers/private run × B(팔로워)·C(비팔로워)·
   D(크루원) 시점에서 활동피드/크루피드/GET users/A/runs/kudos 전수 검증
3) 공개 프로필 — public_run_count, /users/{id}/runs 가시성
Run: python tests/test_run_visibility_integration.py
"""
from __future__ import annotations

import os
import sys
import time

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys():
    anon = svc = ""
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                svc = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(m): print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")


def mkuser(c, e):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": e, "password": "TestPass123!", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    uid = r.json()["id"]
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": e, "password": "TestPass123!"})
    tok = r.json()["access_token"]
    return uid, tok


def api(c, m, p, tok, **k):
    return c.request(m, f"{BASE}{p}", headers={"Authorization": f"Bearer {tok}"}, **k)


def del_in(c, table, col, vals):
    if vals:
        c.delete(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "return=minimal"},
                 params={col: f"in.({','.join(vals)})"})


def run():
    ts = int(time.time())
    uids, crew_ids = [], []
    with httpx.Client(timeout=40) as c:
        try:
            step("공용: A(대상) · B(팔로워) · C(비팔로워) · D(크루원)")
            A_id, A = mkuser(c, f"va-{ts}@t.l"); uids.append(A_id)
            B_id, B = mkuser(c, f"vb-{ts}@t.l"); uids.append(B_id)
            C_id, C = mkuser(c, f"vc-{ts}@t.l"); uids.append(C_id)
            D_id, D = mkuser(c, f"vd-{ts}@t.l"); uids.append(D_id)
            for uid, tok, nn in [(A_id, A, "A러너"), (B_id, B, "B러너"),
                                 (C_id, C, "C러너"), (D_id, D, "D러너")]:
                api(c, "PATCH", "/me/profile", tok, json={"nickname": f"{nn}-{ts%100000}"})
            # B → A 팔로우 (C는 안 함)
            api(c, "POST", f"/users/{A_id}/follow", B)
            # A·D 같은 크루 (D는 A 팔로우 안 함 — 크루 관계만)
            api(c, "PATCH", "/me/profile", A, json={"nickname": f"A러너-{ts%100000}"})
            r = api(c, "POST", "/crews", A, json={"name": f"가시성크루-{ts%100000}", "max_members": 10})
            crew_id = r.json()["id"]; crew_ids.append(crew_id)
            # D를 크루에 추가 (open 크루면 join, 아니면 admin insert)
            c.post(f"{_SB}/rest/v1/crew_members", headers={**_ADM, "Prefer": "return=minimal"},
                   json={"crew_id": crew_id, "user_id": D_id, "role": "member"})
            ok("A·B(팔로워)·C(비팔로워)·D(크루원) + B→A 팔로우 + A·D 크루")

            step("1. 저장 왕복 — title/visibility/페이스 비교 + 422")
            r = api(c, "POST", "/runs", A, json={
                "distance_km": 5.0, "duration_sec": 1800, "title": "야간 러닝",
                "visibility": "public", "notes": "개인 메모"})
            assert r.status_code in (200, 201), r.text[:300]
            d = r.json()
            assert d["title"] == "야간 러닝" and d["visibility"] == "public"
            assert d["notes"] == "개인 메모"
            # 첫 run이라 페이스 비교 null
            assert d["recent_avg_pace_sec_per_km"] is None and d["pace_delta_sec"] is None
            pub_run = d["id"]
            # 422: 잘못된 visibility, 긴 title
            assert api(c, "POST", "/runs", A, json={"distance_km": 5, "duration_sec": 1800,
                       "visibility": "secret"}).status_code == 422
            assert api(c, "POST", "/runs", A, json={"distance_km": 5, "duration_sec": 1800,
                       "title": "가" * 61}).status_code == 422
            ok("title·visibility·notes(메모) 왕복 ✓ 첫 run 페이스 비교 null ✓ 422 2건 ✓")

            step("2. 페이스 비교 — 두 번째 run은 최근 평균 대비 delta")
            # A의 2번째 run: 더 빠른 페이스(4:00/km=240) → delta 음수
            r = api(c, "POST", "/runs", A, json={
                "distance_km": 5.0, "duration_sec": 1200, "title": "빠른 러닝",
                "visibility": "followers"})
            d = r.json(); fol_run = d["id"]
            assert d["recent_avg_pace_sec_per_km"] is not None, "이제 히스토리 있음"
            assert d["pace_delta_sec"] is not None and d["pace_delta_sec"] < 0, \
                f"빠른 run이라 음수여야: {d['pace_delta_sec']}"
            ok(f"최근평균 {d['recent_avg_pace_sec_per_km']}s/km, delta {d['pace_delta_sec']}s (빠름) ✓")

            # A의 private run
            r = api(c, "POST", "/runs", A, json={
                "distance_km": 3.0, "duration_sec": 1080, "visibility": "private"})
            priv_run = r.json()["id"]
            runs = {"public": pub_run, "followers": fol_run, "private": priv_run}

            step("3. 노출 매트릭스 — GET /users/A/runs (조회자별)")
            def user_runs(tok):
                return {x["run_id"] for x in api(c, "GET", f"/users/{A_id}/runs", tok).json()}
            seen_A = user_runs(A)   # 본인: 전부
            seen_B = user_runs(B)   # 팔로워: public+followers
            seen_C = user_runs(C)   # 비팔로워: public만
            seen_D = user_runs(D)   # 크루원(비팔로워): public만 (프로필은 follow 기준)
            assert seen_A == set(runs.values()), f"본인 전부 기대, got {seen_A}"
            assert seen_B == {pub_run, fol_run}, f"팔로워 public+followers, got {seen_B}"
            assert seen_C == {pub_run}, f"비팔로워 public만, got {seen_C}"
            assert seen_D == {pub_run}, f"크루원(비팔로워) 프로필엔 public만, got {seen_D}"
            ok("본인=3 ✓ 팔로워=public+followers ✓ 비팔로워=public ✓ 크루원=public ✓")
            # 본인 프로필엔 visibility 뱃지, 타인엔 null
            mine = api(c, "GET", f"/users/{A_id}/runs", A).json()
            assert all(x["visibility"] for x in mine), "본인 프로필 visibility 있어야"
            others = api(c, "GET", f"/users/{A_id}/runs", B).json()
            assert all(x["visibility"] is None for x in others), "타인엔 visibility null"
            ok("본인 프로필 visibility 뱃지 ✓ 타인 프로필 null ✓")

            step("4. 활동 피드 — B(팔로워)는 A의 public+followers, private 제외")
            feed_B = {x["run_id"] for x in api(c, "GET", "/feed/activities", B,
                                               params={"limit": 100}).json()}
            assert pub_run in feed_B and fol_run in feed_B, "팔로워 활동피드에 public/followers"
            assert priv_run not in feed_B, "private는 활동피드 제외"
            # 제목 전달 확인
            items = api(c, "GET", "/feed/activities", B, params={"limit": 100}).json()
            assert any(x["run_id"] == pub_run and x["title"] == "야간 러닝" for x in items)
            ok("팔로워 활동피드 public+followers ✓ private 제외 ✓ title 전달 ✓")

            step("5. 크루 피드 — D는 A의 public+followers, private만 제외")
            crew_feed = {x["run_id"] for x in api(c, "GET", f"/crews/{crew_id}/runs", D,
                                                  params={"limit": 100}).json()}
            assert pub_run in crew_feed and fol_run in crew_feed, "크루원은 public+followers 봄"
            assert priv_run not in crew_feed, "private는 크루 피드도 제외"
            ok("크루 피드 public+followers 노출 ✓ private만 제외 ✓")

            step("6. kudos 게이트 — visibility 반영")
            # C(비팔로워·비크루) → A의 public run: 가능 (public=anyone)
            assert api(c, "POST", f"/runs/{pub_run}/kudos", C).status_code == 204
            # C → A의 followers run: 불가 (404 은닉)
            assert api(c, "POST", f"/runs/{fol_run}/kudos", C).status_code == 404
            # C → A의 private run: 불가
            assert api(c, "POST", f"/runs/{priv_run}/kudos", C).status_code == 404
            # B(팔로워) → followers run: 가능
            assert api(c, "POST", f"/runs/{fol_run}/kudos", B).status_code == 204
            # D(크루원) → followers run: 가능 (크루 공유)
            assert api(c, "POST", f"/runs/{fol_run}/kudos", D).status_code == 204
            # 아무도 → private run(본인 아님): 불가
            assert api(c, "POST", f"/runs/{priv_run}/kudos", D).status_code == 404
            ok("public=anyone ✓ followers=팔로워·크루원만 ✓ private=차단 ✓")

            step("7. 공개 프로필 — public_run_count")
            prof = api(c, "GET", f"/users/{A_id}/profile", C).json()
            assert prof["public_run_count"] == 1, f"A의 public run 1개, got {prof['public_run_count']}"
            assert prof["follower_count"] == 1  # B
            ok(f"public_run_count=1 (public run만) ✓ follower_count=1 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            del_in(c, "crews", "id", crew_ids)
            del_in(c, "runs", "user_id", uids)
            del_in(c, "follows", "follower_id", uids)
            del_in(c, "profiles", "user_id", uids)
            for u in uids:
                c.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM)
            ok("crews·runs·follows·profiles·auth 삭제")


if __name__ == "__main__":
    run()
