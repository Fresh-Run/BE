"""
Integration test: run 상세 개방(가시성 매트릭스 + 타인 필드 정제) + 러닝 사진 3-step
(docs/RUN_DETAIL_AND_PHOTOS_DESIGN.md)

② 상세: 3×3 매트릭스 / notes 값 부재 이중검증 / verification·is_flagged 미노출 /
   route_id는 공개 코스만 / 피드↔상세 일관성.
① 사진: 발급(타인 404)→PUT→PATCH→서명 URL 왕복 / 목록 photo_thumb /
   private run 사진 은닉 / prefix 422 / 4장 422 / 제거 시 Storage 소멸 /
   계정 삭제 시 사진 정리.

Run: python tests/test_run_detail_photos_integration.py  (로컬 서버 필요)
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
SECRET_NOTE = f"비밀메모{TS}절대노출금지"


def ok(m):        print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):      print(f"\n[{t}]")


def sb_user(c, email):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": "test1234", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]


def sb_login(c, email):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": "test1234"})
    return r.json()["access_token"]


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {token}"}, **kw)


def storage_list(c, prefix):
    r = c.post(f"{_SB}/storage/v1/object/list/run-photos", headers=_ADM,
               json={"prefix": prefix, "limit": 10})
    return [o["name"] for o in r.json()] if r.status_code == 200 else []


def iso_hours_ago(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def run_tests():
    c = httpx.Client(timeout=60)
    users, runs = {}, {}
    try:
        step("0. A(주인)·F(팔로워)·S(무관계) + A의 run 3종")
        for k in ("a", "f", "s"):
            users[k] = sb_user(c, f"rdp-{k}-{TS}@test.com")
        tok_a, tok_f, tok_s = (sb_login(c, f"rdp-{k}-{TS}@test.com") for k in ("a", "f", "s"))
        for k, tok in (("a", tok_a), ("f", tok_f), ("s", tok_s)):
            assert api(c, "PATCH", "/me/profile", tok,
                       json={"nickname": f"RDP{k}{TS}"}).status_code == 200
        assert api(c, "POST", f"/users/{users['a']}/follow", tok_f).status_code == 204
        for i, vis in enumerate(("public", "followers", "private")):
            r = api(c, "POST", "/runs", tok_a, json={
                "distance_km": 5.0, "duration_sec": 1800, "visibility": vis,
                "notes": SECRET_NOTE, "ran_at": iso_hours_ago(3 - i)})
            assert r.status_code == 200, r.text[:200]
            runs[vis] = r.json()["id"]
        ok("유저 3명 + run 3종(전부 비밀 메모 포함)")

        step("1. 상세 가시성 매트릭스 (3 visibility × 본인/팔로워/무관계)")
        matrix = [
            (tok_a, "본인", "public", 200), (tok_a, "본인", "followers", 200), (tok_a, "본인", "private", 200),
            (tok_f, "팔로워", "public", 200), (tok_f, "팔로워", "followers", 200), (tok_f, "팔로워", "private", 404),
            (tok_s, "무관계", "public", 200), (tok_s, "무관계", "followers", 404), (tok_s, "무관계", "private", 404),
        ]
        for tok, who, vis, want in matrix:
            r = api(c, "GET", f"/runs/{runs[vis]}", tok)
            assert r.status_code == want, f"{who}×{vis}: {want} 기대, got {r.status_code}"
            if want == 404:
                assert SECRET_NOTE not in r.text, f"{who}×{vis}: 404인데 메모 노출"
        ok("9칸 매트릭스 ✓")

        step("2. 타인 응답 필드 정제 (이중검증)")
        r = api(c, "GET", f"/runs/{runs['public']}", tok_s)
        d = r.json()
        assert SECRET_NOTE not in r.text, "타인 응답 전체에 메모 값이 없어야 (이중검증)"
        assert d["notes"] is None and d["feedback_tags"] == [] and d["liked"] is None
        assert d["verification"] == "unverified" and d["is_flagged"] is False, \
            "내부 상태는 기본값이어야 (실값 미노출)"
        assert d["distance_km_reported"] is None and d["visibility"] is None
        assert d["distance_km"] == 5.0 and d["kudos_count"] == 0 and "photos" in d
        own = api(c, "GET", f"/runs/{runs['public']}", tok_a).json()
        assert own["notes"] == SECRET_NOTE and own["visibility"] == "public", "본인은 전체 필드"
        ok("notes·feedback·내부상태 미노출 + 값 부재 + 본인 무변경 ✓")

        step("3. route_id — 연결 코스가 public일 때만")
        route_base = {"summary": f"rdp-route-{TS}", "target_distance_km": 5.0,
                      "total_distance_km": 5.0, "estimated_duration_min": 30,
                      "waypoints": [], "polyline": [], "start_lat": 37.5,
                      "start_lng": 127.0, "is_public": False, "user_id": users["a"]}
        rt = c.post(f"{_SB}/rest/v1/routes", headers={**_ADM, "Prefer": "return=representation"},
                    json=route_base).json()[0]["id"]
        c.patch(f"{_SB}/rest/v1/runs", headers=_ADM, params={"id": f"eq.{runs['public']}"},
                json={"route_id": rt})
        d = api(c, "GET", f"/runs/{runs['public']}", tok_s).json()
        assert d["route_id"] is None, f"비공개 코스 id가 타인에게 노출: {d['route_id']}"
        c.patch(f"{_SB}/rest/v1/routes", headers=_ADM, params={"id": f"eq.{rt}"},
                json={"is_public": True})
        d = api(c, "GET", f"/runs/{runs['public']}", tok_s).json()
        assert d["route_id"] == rt, "공개 코스면 노출돼야"
        ok("비공개 코스 은닉 → 공개 전환 시 노출 ✓")

        step("4. 피드↔상세 일관성 (공개 프로필 기준)")
        feed = api(c, "GET", f"/users/{users['a']}/runs", tok_s).json()
        feed_ids = {x["run_id"] for x in feed}
        assert feed_ids == {runs["public"]}, f"무관계에겐 public만: {len(feed_ids)}건"
        for rid in feed_ids:
            assert api(c, "GET", f"/runs/{rid}", tok_s).status_code == 200, "보이면 상세도 200"
        assert api(c, "GET", f"/runs/{runs['followers']}", tok_s).status_code == 404
        ok("피드에 보이는 run ⇔ 상세 200 ✓")

        step("5. 사진 3-step (public run) + 타인 발급 404")
        assert api(c, "POST", f"/runs/{runs['public']}/photos/upload-url", tok_f,
                   json={"slot": 1, "content_type": "image/jpeg"}).status_code == 404, \
            "타인 발급은 404 은닉"
        paths = []
        for slot in (1, 2):
            r = api(c, "POST", f"/runs/{runs['public']}/photos/upload-url", tok_a,
                    json={"slot": slot, "content_type": "image/jpeg"})
            assert r.status_code == 200, r.text[:200]
            up = r.json()
            assert up["path"] == f"{runs['public']}/{slot}.jpg", up["path"]
            pr = c.put(up["upload_url"], content=b"\xff\xd8\xff-rdp-test" + bytes([slot]),
                       headers={"Content-Type": "image/jpeg"})
            assert pr.status_code == 200, f"PUT {pr.status_code}: {pr.text[:150]}"
            paths.append(up["path"])
        r = api(c, "PATCH", f"/runs/{runs['public']}", tok_a, json={"photos": paths})
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert len(d["photos"]) == 2 and all(u.startswith("http") for u in d["photos"])
        assert c.get(d["photos"][0]).status_code == 200, "서명 URL 실제 접근"
        ok("발급→PUT→PATCH→서명 URL 접근 (2장) ✓")

        step("6. 노출 — 타인 상세 photos·목록 photo_thumb / private 은닉")
        d = api(c, "GET", f"/runs/{runs['public']}", tok_s).json()
        assert len(d["photos"]) == 2 and c.get(d["photos"][0]).status_code == 200, \
            "public run 사진은 타인도 서명 URL로 접근"
        lst = api(c, "GET", "/runs", tok_a).json()
        me = next(x for x in lst if x["id"] == runs["public"])
        assert me["photo_thumb"] and me["photo_thumb"].startswith("http")
        feed = api(c, "GET", f"/users/{users['a']}/runs", tok_s).json()
        assert feed[0]["photo_thumb"], "공개 프로필 카드에도 썸네일"
        # private run 사진: 업로드 후 타인 상세 404 (사진 URL 접근 경로 자체 없음)
        r = api(c, "POST", f"/runs/{runs['private']}/photos/upload-url", tok_a,
                json={"slot": 1, "content_type": "image/png"})
        pu = r.json()
        assert c.put(pu["upload_url"], content=b"\x89PNG-rdp",
                     headers={"Content-Type": "image/png"}).status_code == 200
        assert api(c, "PATCH", f"/runs/{runs['private']}", tok_a,
                   json={"photos": [pu["path"]]}).status_code == 200
        assert api(c, "GET", f"/runs/{runs['private']}", tok_s).status_code == 404
        ok("타인 photos 접근 ✓ 썸네일 2경로 ✓ private 사진 은닉 ✓")

        step("7. 검증 — prefix 밖 422 / 4장 422 / 제거 시 Storage 소멸")
        r = api(c, "PATCH", f"/runs/{runs['public']}", tok_a,
                json={"photos": [f"{runs['private']}/1.png"]})
        assert r.status_code == 422, f"남의(다른) run 경로는 422, got {r.status_code}"
        r = api(c, "PATCH", f"/runs/{runs['public']}", tok_a,
                json={"photos": [f"{runs['public']}/{i}.jpg" for i in range(1, 5)]})
        assert r.status_code == 422, f"4장은 422, got {r.status_code}"
        r = api(c, "PATCH", f"/runs/{runs['public']}", tok_a, json={"photos": [paths[0]]})
        assert r.status_code == 200 and len(r.json()["photos"]) == 1
        time.sleep(1)
        names = storage_list(c, runs["public"])
        assert "2.jpg" not in names and "1.jpg" in names, f"제거분 소멸/유지분 잔존: {names}"
        ok("prefix 422 ✓ 상한 422 ✓ 교체 시 객체 정리 ✓")

        step("8. 계정 삭제 연동 — run-photos prefix 정리")
        assert api(c, "DELETE", "/me", tok_a).status_code == 204
        time.sleep(1)
        left = storage_list(c, runs["public"]) + storage_list(c, runs["private"])
        assert left == [], f"탈퇴 후 사진 잔존: {left}"
        users.pop("a")
        ok("탈퇴 시 사진 전량 소멸 ✓")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in users.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        # 실패 시 잔존 대비: run-photos 객체 정리 (성공 경로면 이미 0)
        for rid in runs.values():
            names = storage_list(c, rid)
            if names:
                c.delete(f"{_SB}/storage/v1/object/run-photos", headers=_ADM,
                         json={"prefixes": [f"{rid}/{n}" for n in names]})
        print("  유저·잔존 객체 정리 완료")


if __name__ == "__main__":
    run_tests()
