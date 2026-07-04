"""
Integration test: route comments (POST/GET /routes/{id}/comments,
DELETE /routes/{id}/comments/{comment_id})
Run: python tests/test_comments_integration.py
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):             anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(m):      print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):    print(f"\n[{t}]")

def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201): fail("create user", r.text[:200])
    return r.json()["id"]

def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]

def sb_del_user(c, uid): c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)

def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})

def sb_insert_route(c, uid, summary, is_public):
    r = c.post(f"{_SB}/rest/v1/routes",
               headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": uid, "summary": summary,
                     "total_distance_km": 5.0, "is_public": is_public, "waypoints": []})
    if r.status_code not in (200, 201): fail("insert route", r.text[:200])
    return r.json()[0]["id"]

def sb_set_nickname(c, uid, nickname):
    c.post(f"{_SB}/rest/v1/profiles",
           headers={**_ADM, "Prefer": "resolution=merge-duplicates,return=minimal"},
           json={"user_id": uid, "nickname": nickname})

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def get_route_from_feed(c, tok, route_id, limit=50):
    r = api(c, "GET", "/routes/public", tok, params={"sort": "newest", "limit": limit})
    if r.status_code != 200: fail("GET feed", r.text[:200])
    return {item["id"]: item for item in r.json()}.get(route_id)


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"cm-u{i}-{ts}@t.c" for i in range(1, 4)]
    uids: list[str] = []; toks: list[str] = []
    all_routes: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 3명 생성 + 로그인 ──────────────────────────────────
            step("1. 유저 3명 생성 + 로그인")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2, uid3 = uids; tok1, tok2, tok3 = toks
            sb_set_nickname(c, uid2, f"댓글러{ts % 10000}")
            ok(f"u1={uid1[:8]}(코스주인)  u2={uid2[:8]}(댓글러)  u3={uid3[:8]}(제3자)")

            # ── 2. 공개 코스 A + 비공개 코스 B ────────────────────────────
            step("2. 공개 코스 A + 비공개 코스 B 삽입")
            route_a = sb_insert_route(c, uid1, "댓글테스트A(공개)", True)
            route_b = sb_insert_route(c, uid1, "댓글테스트B(비공개)", False)
            all_routes += [route_a, route_b]
            ok(f"route_a={route_a[:8]}(공개)  route_b={route_b[:8]}(비공개)")

            # ── 3. 공개 코스에 댓글 작성 → 201, 필드 확인 ─────────────────
            step("3. 공개 코스 댓글 작성 → 201")
            r = api(c, "POST", f"/routes/{route_a}/comments", tok2,
                    json={"content": "좋은 코스네요!"})
            assert r.status_code == 201, f"POST comment → 201 이어야 함, got {r.status_code}: {r.text[:200]}"
            comment1 = r.json()
            assert comment1["route_id"] == route_a, "route_id 불일치"
            assert comment1["user_id"] == uid2, "user_id 불일치"
            assert comment1["content"] == "좋은 코스네요!", "content 불일치"
            assert comment1["nickname"] == f"댓글러{ts % 10000}", f"nickname 불일치: {comment1['nickname']}"
            assert "id" in comment1 and "created_at" in comment1, "id/created_at 누락"
            comment1_id = comment1["id"]
            ok(f"댓글 작성 201 ✓  id={comment1_id[:8]}  nickname={comment1['nickname']}")

            # ── 4. 댓글 목록 조회 → 오래된순, 2개 (댓글 하나 더 추가) ────
            step("4. 댓글 목록 → 오래된순 확인")
            r2 = api(c, "POST", f"/routes/{route_a}/comments", tok1,
                     json={"content": "감사합니다~"})
            assert r2.status_code == 201, f"두 번째 댓글 → 201 이어야 함, got {r2.status_code}"
            comment2_id = r2.json()["id"]

            r = api(c, "GET", f"/routes/{route_a}/comments", tok3)
            assert r.status_code == 200, f"GET comments → 200 이어야 함, got {r.status_code}"
            comments = r.json()
            assert len(comments) == 2, f"댓글 2개 이어야 함, got {len(comments)}"
            assert comments[0]["id"] == comment1_id, "첫 번째 댓글이 오래된 것이어야 함"
            assert comments[1]["id"] == comment2_id, "두 번째 댓글이 나중 것이어야 함"
            ok(f"목록 2개, 오래된순 ✓")

            # ── 5. 피드에서 comment_count 반영 확인 ────────────────────────
            step("5. 피드(list_public_routes) → comment_count=2")
            item = get_route_from_feed(c, tok1, route_a)
            assert item is not None, "route_a 피드에 없음"
            assert item["comment_count"] == 2, f"comment_count 2 이어야 함, got {item['comment_count']}"
            ok(f"comment_count=2 ✓")

            # ── 6. 비공개 코스 댓글 → 404 ──────────────────────────────────
            step("6. 비공개 코스 댓글 → 404")
            r = api(c, "POST", f"/routes/{route_b}/comments", tok2,
                    json={"content": "안 보여야 함"})
            assert r.status_code == 404, f"비공개 코스 댓글 → 404 이어야 함, got {r.status_code}"
            ok("비공개 코스 댓글 → 404 ✓")

            # ── 7. 작성자 본인 댓글 삭제 → 204 ─────────────────────────────
            step("7. 작성자(u2) 본인 댓글 삭제 → 204")
            r = api(c, "DELETE", f"/routes/{route_a}/comments/{comment1_id}", tok2)
            assert r.status_code == 204, f"작성자 삭제 → 204 이어야 함, got {r.status_code}"
            # 목록 다시 조회 → 1개
            r = api(c, "GET", f"/routes/{route_a}/comments", tok2)
            assert len(r.json()) == 1, f"삭제 후 댓글 1개 이어야 함, got {len(r.json())}"
            ok("작성자 삭제 204 ✓  남은 댓글 1개 ✓")

            # ── 8. 코스 주인(u1)이 타인 댓글 삭제 → 204 ──────────────────
            step("8. 코스 주인(u1)이 u1 본인 댓글 삭제 → 204")
            r = api(c, "DELETE", f"/routes/{route_a}/comments/{comment2_id}", tok1)
            assert r.status_code == 204, f"코스 주인 삭제 → 204 이어야 함, got {r.status_code}"
            r = api(c, "GET", f"/routes/{route_a}/comments", tok1)
            assert len(r.json()) == 0, f"삭제 후 댓글 0개 이어야 함, got {len(r.json())}"
            ok("코스 주인 삭제 204 ✓  남은 댓글 0개 ✓")

            # ── 9(보너스). 권한 없는 삭제 → 403 ───────────────────────────
            step("9. 제3자(u3)가 존재하지 않는 댓글 삭제 → 404")
            r = api(c, "DELETE", f"/routes/{route_a}/comments/{comment1_id}", tok3)
            assert r.status_code == 404, f"삭제된 댓글 → 404 이어야 함, got {r.status_code}"
            ok("삭제된 댓글 재삭제 → 404 ✓")

            # 권한 없는 삭제(u2 댓글, u3가 삭제시도) 테스트
            step("10. u1이 신규 댓글 작성 후 u3가 삭제 시도 → 403")
            r_new = api(c, "POST", f"/routes/{route_a}/comments", tok2,
                        json={"content": "권한 테스트용"})
            assert r_new.status_code == 201
            new_cid = r_new.json()["id"]
            r = api(c, "DELETE", f"/routes/{route_a}/comments/{new_cid}", tok3)
            assert r.status_code == 403, f"제3자 삭제 → 403 이어야 함, got {r.status_code}"
            ok("제3자 삭제 → 403 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)

        finally:
            step("Cleanup")
            sb_del_in(c, "route_comments", "route_id", all_routes)
            ok("route_comments 삭제")
            sb_del_in(c, "routes", "id", all_routes)
            ok("routes 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")


if __name__ == "__main__":
    run()
