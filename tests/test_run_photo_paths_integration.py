"""
Integration test: GET /runs/{id} owner-only photo_paths (Ivan own-run 사진 편집 블로커 해제)

본인(소유자) 상세에만 photo_paths[](storage 경로) 추가 — photos(서명 URL)와 같은
순서·길이. 타인 응답엔 필드 자체 없음(경로 미노출). PATCH /runs {photos}에 재사용.

케이스(T-map·Gemini 무관):
 1. 본인 조회 → photo_paths 존재 + photos(URL)와 순서·길이 일치
 2. 타인 조회(public run) → photo_paths 키 자체 부재
 3. 사진 없는 run(본인) → photo_paths == []
 4. PATCH {photos} 재사용 라운드트립 — 교체(p0→p2)+순서 + 삭제(→[]) 반영

Run: python tests/test_run_photo_paths_integration.py   (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8003/api"
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


def save_run(c, tok, vis="public"):
    r = api(c, "POST", "/runs", tok,
            json={"distance_km": 5.0, "duration_sec": 1800, "avg_pace_sec_per_km": 360,
                  "visibility": vis})
    assert r.status_code == 200, r.text[:200]
    return r.json()["id"]


def upload_slot(c, run_id, tok, slot):
    """3-step 업로드 → storage 경로 반환 (실제 객체 생성 — 서명 URL 발급 성공용)."""
    r = api(c, "POST", f"/runs/{run_id}/photos/upload-url", tok,
            json={"slot": slot, "content_type": "image/jpeg"})
    assert r.status_code == 200, r.text[:200]
    up = r.json()
    pr = c.put(up["upload_url"], content=b"\xff\xd8\xff-pp-test" + bytes([slot]),
               headers={"Content-Type": "image/jpeg"})
    assert pr.status_code in (200, 201), pr.text[:150]
    return up["path"]


def storage_names(c, prefix):
    r = c.post(f"{_SB}/storage/v1/object/list/run-photos", headers=_ADM,
               json={"prefix": prefix})
    return [o["name"] for o in r.json()] if r.status_code == 200 else []


def run_tests():
    c = httpx.Client(timeout=60)
    uids = {}
    runs = []
    try:
        step("0. 소유자 O + 뷰어 V")
        for k in ("o", "v"):
            uids[k] = sb_user(c, f"pp-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"pp-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"PP{k}{TS}"}).status_code == 200
        ok("유저 2 생성")

        step("1. 본인 조회 → photo_paths 존재 + photos와 순서·길이 일치")
        run = save_run(c, tk["o"], vis="public"); runs.append(run)
        p0 = upload_slot(c, run, tk["o"], 1)
        p1 = upload_slot(c, run, tk["o"], 2)
        assert api(c, "PATCH", f"/runs/{run}", tk["o"], json={"photos": [p0, p1]}).status_code == 200
        d = api(c, "GET", f"/runs/{run}", tk["o"]).json()
        assert "photo_paths" in d, "본인 응답에 photo_paths 존재"
        assert d["photo_paths"] == [p0, p1], f"경로·순서, got {d['photo_paths']}"
        assert len(d["photos"]) == len(d["photo_paths"]) == 2, "photos·photo_paths 길이 일치"
        assert all(pp in url for pp, url in zip(d["photo_paths"], d["photos"])), \
            "순서 정합 — photo_paths[i]가 photos[i] 서명 URL에 포함"
        ok(f"photo_paths={d['photo_paths']} · photos 2개와 순서·길이 일치")

        step("2. 타인 조회(public run) → photo_paths 키 자체 부재")
        dv = api(c, "GET", f"/runs/{run}", tk["v"])
        assert dv.status_code == 200, "public run은 타인 조회 가능"
        djv = dv.json()
        assert "photo_paths" not in djv, "타인 응답엔 photo_paths 키 자체 부재"
        assert len(djv["photos"]) == 2, "타인도 서명 URL(photos)은 봄"
        # ⚠️ 경로는 서명 URL(photos) 안에 내재됨(.../run-photos/{path}?token=) — 이는
        # 의도된 노출이라 "값 문자열 부재" 이중검증은 부적절. 별도 photo_paths 배열이
        # 없다는 것(원시 경로를 URL 밖으로 따로 주지 않음)만이 계약.
        ok("타인: photo_paths 키 부재(원시 경로 배열 미노출) · photos(서명 URL)만 노출")

        step("3. 사진 없는 run(본인) → photo_paths == []")
        run2 = save_run(c, tk["o"], vis="private"); runs.append(run2)
        d2 = api(c, "GET", f"/runs/{run2}", tk["o"]).json()
        assert d2.get("photo_paths") == [], f"빈 배열, got {d2.get('photo_paths')}"
        assert d2["photos"] == [], "사진 없음"
        ok("사진 없는 본인 run → photo_paths == [] (빈 배열 존재)")

        step("4. PATCH {photos} 재사용 라운드트립 — 교체(p0→p2)+순서 · 삭제(→[])")
        p2 = upload_slot(c, run, tk["o"], 3)
        # 교체+순서: [p0,p1] → [p2,p1] (p0(slot1) 삭제·p2(slot3) 추가, 순서 p2 먼저)
        assert api(c, "PATCH", f"/runs/{run}", tk["o"], json={"photos": [p2, p1]}).status_code == 200
        d3 = api(c, "GET", f"/runs/{run}", tk["o"]).json()
        assert d3["photo_paths"] == [p2, p1], f"교체·순서 반영, got {d3['photo_paths']}"
        assert all(pp in url for pp, url in zip(d3["photo_paths"], d3["photos"])), "재정렬 후 정합"
        names = storage_names(c, run)
        assert "1.jpg" not in names, f"삭제된 p0(1.jpg) Storage 소멸, got {names}"
        # 전체 삭제
        assert api(c, "PATCH", f"/runs/{run}", tk["o"], json={"photos": []}).status_code == 200
        d4 = api(c, "GET", f"/runs/{run}", tk["o"]).json()
        assert d4["photo_paths"] == [] and d4["photos"] == [], "전체 삭제 → 빈 배열"
        ok("교체+순서 반영 · 삭제분 Storage 소멸 · 전체 삭제 → [] (경로 재사용 라운드트립)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for rid in runs:
            names = storage_names(c, rid)
            if names:
                c.request("DELETE", f"{_SB}/storage/v1/object/run-photos", headers=_ADM,
                          json={"prefixes": [f"{rid}/{n}" for n in names]})
        for uid in uids.values():
            c.delete(f"{_SB}/rest/v1/runs?user_id=eq.{uid}", headers=_ADM)
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (Storage·run·유저 삭제)")


if __name__ == "__main__":
    run_tests()
