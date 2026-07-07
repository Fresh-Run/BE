"""
Integration test: run 댓글 (route 댓글 동형) + comment_count + run_commented 알림
1) 가시성 매트릭스 — private/followers/public × 팔로워/비팔로워
2) 작성 → comment_count 반영(목록·단건·활동피드), 삭제 권한(작성자/run주인/타인),
   알림 1건(run 주인)·본인 댓글 미발송
Run: python tests/test_run_comments_integration.py
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
    return uid, r.json()["access_token"]


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
            step("공용: A(주인)·B(팔로워)·C(비팔로워)·D(크루원)")
            A_id, A = mkuser(c, f"rc-a-{ts}@t.l"); uids.append(A_id)
            B_id, B = mkuser(c, f"rc-b-{ts}@t.l"); uids.append(B_id)
            C_id, C = mkuser(c, f"rc-c-{ts}@t.l"); uids.append(C_id)
            D_id, D = mkuser(c, f"rc-d-{ts}@t.l"); uids.append(D_id)
            for uid, tok, nn in [(A_id, A, "댓A"), (B_id, B, "댓B"), (C_id, C, "댓C"), (D_id, D, "댓D")]:
                api(c, "PATCH", "/me/profile", tok, json={"nickname": f"{nn}-{ts%100000}"})
            api(c, "POST", f"/users/{A_id}/follow", B)  # B→A 팔로우, C는 안 함
            r = api(c, "POST", "/crews", A, json={"name": f"댓글크루-{ts%100000}", "max_members": 10})
            crew_id = r.json()["id"]; crew_ids.append(crew_id)
            c.post(f"{_SB}/rest/v1/crew_members", headers={**_ADM, "Prefer": "return=minimal"},
                   json={"crew_id": crew_id, "user_id": D_id, "role": "member"})
            ok("관계: B팔로워·C비팔로워·D크루원")

            # A의 run 3개 (public/followers/private)
            runs = {}
            for vis in ("public", "followers", "private"):
                r = api(c, "POST", "/runs", A, json={"distance_km": 5, "duration_sec": 1800,
                                                     "visibility": vis, "title": vis})
                runs[vis] = r.json()["id"]

            step("1. 가시성 — 댓글 조회/작성 게이트 (_can_see_run)")
            # public: 아무나(C 비팔로워) 조회·작성 OK
            assert api(c, "GET", f"/runs/{runs['public']}/comments", C).status_code == 200
            assert api(c, "POST", f"/runs/{runs['public']}/comments", C,
                       json={"content": "공개런 좋아요"}).status_code == 200
            # followers: B(팔로워)·D(크루원) OK, C(비팔로워) 404
            assert api(c, "POST", f"/runs/{runs['followers']}/comments", B,
                       json={"content": "팔로워 댓글"}).status_code == 200
            assert api(c, "POST", f"/runs/{runs['followers']}/comments", D,
                       json={"content": "크루원 댓글"}).status_code == 200
            assert api(c, "GET", f"/runs/{runs['followers']}/comments", C).status_code == 404
            assert api(c, "POST", f"/runs/{runs['followers']}/comments", C,
                       json={"content": "막혀야"}).status_code == 404
            # private: A(본인)만, 남은 다 404
            assert api(c, "POST", f"/runs/{runs['private']}/comments", A,
                       json={"content": "내 비공개 메모런"}).status_code == 200
            assert api(c, "GET", f"/runs/{runs['private']}/comments", B).status_code == 404
            assert api(c, "POST", f"/runs/{runs['private']}/comments", D,
                       json={"content": "막혀야"}).status_code == 404
            ok("public=anyone ✓ followers=팔로워·크루원(비팔로워 404) ✓ private=본인만 ✓")

            step("2. comment_count 반영 — 목록·단건·활동피드")
            # public run: C 1개, followers run: B·D 2개
            mine = {x["id"]: x for x in api(c, "GET", "/runs", A, params={"limit": 50}).json()}
            assert mine[runs["public"]]["comment_count"] == 1, mine[runs["public"]]["comment_count"]
            assert mine[runs["followers"]]["comment_count"] == 2
            assert mine[runs["private"]]["comment_count"] == 1
            single = api(c, "GET", f"/runs/{runs['followers']}", A).json()
            assert single["comment_count"] == 2
            # 활동 피드(B 시점): A의 followers run 카드에 comment_count=2
            feed = {x["run_id"]: x for x in api(c, "GET", "/feed/activities", B, params={"limit": 100}).json()}
            assert feed[runs["followers"]]["comment_count"] == 2
            ok("목록 pub=1·fol=2·priv=1 ✓ 단건=2 ✓ 활동피드=2 ✓")

            step("3. 목록 최신순 + 닉네임")
            lst = api(c, "GET", f"/runs/{runs['followers']}/comments", A).json()
            assert len(lst) == 2 and lst[0]["created_at"] >= lst[1]["created_at"], "최신순"
            assert all(x["nickname"] for x in lst), "닉네임 채워짐"
            assert all("run_id" in x and x["run_id"] == runs["followers"] for x in lst)
            ok(f"최신순 2개 ✓ 닉네임 ✓ run_id 포함 ✓")

            step("4. 삭제 권한 — 작성자/run주인/타인")
            cid = lst[0]["id"]  # B 또는 D가 쓴 것
            author = lst[0]["user_id"]
            other = D if author == B_id else B
            # 타인(작성자도 run주인도 아님) 403
            assert api(c, "DELETE", f"/runs/{runs['followers']}/comments/{cid}", other).status_code == 403
            # run 주인(A) 삭제 OK
            assert api(c, "DELETE", f"/runs/{runs['followers']}/comments/{cid}", A).status_code == 204
            # 남은 1개는 작성자 본인이 삭제 OK
            rest = api(c, "GET", f"/runs/{runs['followers']}/comments", A).json()
            cid2 = rest[0]["id"]; who = B if rest[0]["user_id"] == B_id else D
            assert api(c, "DELETE", f"/runs/{runs['followers']}/comments/{cid2}", who).status_code == 204
            # 이제 0개 → count 0
            assert api(c, "GET", f"/runs/{runs['followers']}", A).json()["comment_count"] == 0
            ok("타인 403 ✓ run주인 삭제 ✓ 작성자 삭제 ✓ count 0 반영 ✓")

            step("5. 알림 — run_commented (run 주인에게, 본인 댓글 미발송)")
            notis = api(c, "GET", "/notifications", A, params={"limit": 50}).json()
            rc = [n for n in notis if n["type"] == "run_commented"]
            assert rc, "A가 run_commented 알림 받아야 (C·B·D 댓글)"
            assert all(n.get("payload", {}).get("run_id") for n in rc), "payload.run_id 포함"
            assert all(n["target_type"] == "run" for n in rc)
            # A 본인이 private run에 단 댓글은 self → 알림 없음(A→A)
            a_self = [n for n in rc if n["target_id"] == runs["private"]]
            assert not a_self, "본인 댓글은 알림 미발송"
            ok(f"run_commented {len(rc)}건(payload.run_id·target_type=run) ✓ 본인 댓글 미발송 ✓")

            step("6. 422 — 빈 댓글·과길이")
            assert api(c, "POST", f"/runs/{runs['public']}/comments", A, json={"content": ""}).status_code == 422
            assert api(c, "POST", f"/runs/{runs['public']}/comments", A,
                       json={"content": "가" * 501}).status_code == 422
            ok("빈 댓글·501자 422 ✓")

            print("\n" + "=" * 50); print("  ALL TESTS PASSED"); print("=" * 50)
        finally:
            step("Cleanup")
            del_in(c, "crews", "id", crew_ids)
            del_in(c, "runs", "user_id", uids)         # run CASCADE로 run_comments도 삭제
            del_in(c, "notifications", "user_id", uids)
            del_in(c, "follows", "follower_id", uids)
            del_in(c, "profiles", "user_id", uids)
            for u in uids:
                c.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM)
            ok("crews·runs·notifications·follows·profiles·auth 삭제")


if __name__ == "__main__":
    run()
