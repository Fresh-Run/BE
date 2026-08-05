"""
Integration: route 댓글 1-레벨 답글 (2026-08-06, Ivan 계약 — run 동형 이식)

1. 구계약 불변 — parent 미전송 일반 댓글 201·parent null·주인 알림 payload 없음
   [게이트] route_comments.parent_comment_id 미적용이면 명시 대기 exit 1
2. 답글 정상 — parent 실림 + 알림(주인 payload 없음 유지 + 부모 작성자 3키)
2b. (b) 일관성 — 주인=부모 작성자 답글은 주인 경로 1건에 3키 / 자기 답글 부모 알림 0
2c. 푸시 카피 — _render_body route_commented is_reply 분기 ko/en·일반 문구 불변
3. 깊이 2 → 422 reply_depth_exceeded / 4. 타 route 부모 → 422 comment_parent_invalid
5. cascade — 부모 삭제 → 답글 소멸 + count 동기 / 6. count 답글 포함
7. 플랫 페치 shape + parent 참조

Run: python tests/test_route_comment_replies_integration.py
임시 유저·route·댓글·알림 종료 시 전삭·잔여 0.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.main import app  # noqa: E402
from app.services import route_service  # noqa: E402

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_ADM = {"apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json"}
TS = int(time.time())
uids: list[str] = []
route_ids: list[str] = []


def ok(m):
    print(f"  ✓ {m}")


def sb_user(tag):
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                   json={"email": f"rtr-{tag}-{TS}@t.l", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    uid = r.json()["id"]
    uids.append(uid)
    httpx.post(f"{_SB}/rest/v1/profiles",
               headers={**_ADM, "Prefer": "resolution=merge-duplicates"},
               params={"on_conflict": "user_id"},
               json={"user_id": uid, "nickname": f"rt{tag[:2]}{TS % 100000}"},
               timeout=30).raise_for_status()
    return uid


def sb_login(tag):
    r = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                   headers={"apikey": settings.supabase_key,
                            "Content-Type": "application/json"},
                   json={"email": f"rtr-{tag}-{TS}@t.l", "password": "test1234"},
                   timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def sb_route(uid):
    r = httpx.post(f"{_SB}/rest/v1/routes",
                   headers={**_ADM, "Prefer": "return=representation"},
                   json={"user_id": uid, "summary": f"rtr-{TS}",
                         "total_distance_km": 5.0, "is_public": True,
                         "waypoints": []}, timeout=30)
    r.raise_for_status()
    route_ids.append(r.json()[0]["id"])
    return r.json()[0]["id"]


def _column_exists() -> bool:
    k = settings.supabase_service_role_key
    spec = httpx.get(f"{_SB}/rest/v1/", headers={"apikey": k, "Authorization": f"Bearer {k}"},
                     timeout=30).json()
    return "parent_comment_id" in spec["definitions"]["route_comments"]["properties"]


def run_tests():
    a, b, c_uid = sb_user("a"), sb_user("b"), sb_user("c")
    tok_a, tok_b, tok_c = sb_login("a"), sb_login("b"), sb_login("c")
    rt1, rt2 = sb_route(a), sb_route(a)
    cl = TestClient(app)
    sb = get_supabase_admin()

    def api(method, path, tok, **kw):
        return cl.request(method, f"/api{path}",
                          headers={"Authorization": f"Bearer {tok}"}, **kw)

    def notes(rt):
        return sb.table("notifications").select("user_id,payload") \
            .eq("target_id", rt).eq("type", "route_commented").execute().data

    print("[1. 구계약 불변 — parent 미전송(컬럼 유무 무관)]")
    r = api("POST", f"/routes/{rt1}/comments", tok_b, json={"content": "일반"})
    assert r.status_code == 201, r.text
    base = r.json()
    assert base.get("parent_comment_id") is None
    n = notes(rt1)
    assert len(n) == 1 and n[0]["user_id"] == a and n[0]["payload"] is None, n
    ok("일반 댓글 201 + parent null + 주인 알림 payload 없음(바이트 불변)")

    if not _column_exists():
        print("\n[검증 불가] route_comments.parent_comment_id 미적용 — 오너가 "
              "db/2026-08-06_route_comment_replies.sql 실행 후 재실행 필요:\n"
              "  python tests/test_route_comment_replies_integration.py")
        sys.exit(1)

    print("\n[2. 답글 — parent 실림 + 알림(주인 플레인·부모 작성자 3키)]")
    r = api("POST", f"/routes/{rt1}/comments", tok_c,
            json={"content": "답글", "parent_comment_id": base["id"]})
    assert r.status_code == 201, r.text
    reply = r.json()
    assert reply["parent_comment_id"] == base["id"]
    rows = notes(rt1)
    a_rows = [x for x in rows if x["user_id"] == a]
    b_rows = [x for x in rows if x["user_id"] == b]
    assert len(a_rows) == 2 and all(x["payload"] is None for x in a_rows), a_rows
    assert len(b_rows) == 1 and b_rows[0]["payload"] == {
        "route_id": rt1, "is_reply": True, "parent_comment_id": base["id"]}, b_rows
    ok("주인 수신 2건 전부 payload 없음 불변 ✓ 부모 작성자 1건 3키 ✓")

    print("\n[2b. (b) 일관성 — 주인=부모 작성자·자기 답글 (rt2 격리)]")
    r = api("POST", f"/routes/{rt2}/comments", tok_a, json={"content": "주인 댓글"})
    assert r.status_code == 201
    a_parent = r.json()
    assert notes(rt2) == [], "본인 댓글 무알림(self-skip)"
    r = api("POST", f"/routes/{rt2}/comments", tok_c,
            json={"content": "주인 댓글에 답글", "parent_comment_id": a_parent["id"]})
    assert r.status_code == 201, r.text
    rows = notes(rt2)
    assert len(rows) == 1 and rows[0]["user_id"] == a
    assert rows[0]["payload"] == {"route_id": rt2, "is_reply": True,
                                  "parent_comment_id": a_parent["id"]}, rows
    r = api("POST", f"/routes/{rt2}/comments", tok_c, json={"content": "c 댓글"})
    c_parent = r.json()
    r = api("POST", f"/routes/{rt2}/comments", tok_c,
            json={"content": "c 자기 답글", "parent_comment_id": c_parent["id"]})
    assert r.status_code == 201
    rows = notes(rt2)
    assert len(rows) == 3 and all(x["user_id"] == a for x in rows)
    assert sum(1 for x in rows if x["payload"] is None) == 2, rows
    ok("주인=부모 답글 1건 3키(b) ✓ 자기 답글 부모 알림 0·주인 플레인 ✓")

    print("\n[2c. 푸시 카피 — route_commented is_reply 분기]")
    from app.services import push_service as ps
    pay = {"route_id": rt1, "is_reply": True, "parent_comment_id": base["id"]}
    assert ps._render_body("route_commented", "ko", pay, "철수") \
        == "철수님이 내 댓글에 답글을 남겼어요"
    assert ps._render_body("route_commented", "en", pay, "Sue") \
        == "Sue replied to your comment"
    assert ps._render_body("route_commented", "ko", None, "철수") \
        == "철수님이 회원님의 코스에 댓글을 남겼어요", "일반 문구 불변"
    assert ps._render_body("run_commented", "ko", {"run_id": "x", "is_reply": True,
                                                   "parent_comment_id": "y"}, "철수") \
        == "철수님이 내 댓글에 답글을 남겼어요", "run 분기 회귀 불변"
    ok("route 답글 ko/en 세분 ✓ 일반·run 문구 불변 ✓")

    print("\n[3. 깊이 2 → 422 reply_depth_exceeded]")
    r = api("POST", f"/routes/{rt1}/comments", tok_b,
            json={"content": "답답글", "parent_comment_id": reply["id"]})
    assert r.status_code == 422 and r.json()["error_code"] == "reply_depth_exceeded", r.text
    ok("서버 1-레벨 강제 + error_code 승격")

    print("\n[4. 타 route 부모·부재 부모 → 422 comment_parent_invalid]")
    r = api("POST", f"/routes/{rt2}/comments", tok_b,
            json={"content": "x", "parent_comment_id": base["id"]})
    assert r.status_code == 422 and r.json()["error_code"] == "comment_parent_invalid", r.text
    r = api("POST", f"/routes/{rt1}/comments", tok_b,
            json={"content": "x", "parent_comment_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 422 and r.json()["error_code"] == "comment_parent_invalid", r.text
    ok("타 route 소속·부재 부모 둘 다 422")

    print("\n[6. count 답글 포함(행 수 기반)]")
    counts = asyncio.run(route_service._comment_counts([rt1]))
    assert counts.get(rt1) == 2, counts   # 부모 1 + 답글 1
    ok("comment_count 2(부모+답글)")

    print("\n[7. 플랫 페치 — shape 불변 + parent 참조]")
    r = api("GET", f"/routes/{rt1}/comments", tok_a)
    items = r.json()
    assert len(items) == 2
    for k in ("id", "route_id", "user_id", "nickname", "content", "created_at",
              "parent_comment_id"):
        assert k in items[0], k
    parents = {x["id"]: x["parent_comment_id"] for x in items}
    assert parents[reply["id"]] == base["id"] and parents[base["id"]] is None
    ok("플랫 리스트 + parent 참조 스레딩 가능")

    print("\n[5. cascade — 부모 삭제 → 답글 소멸 + count 동기]")
    r = api("DELETE", f"/routes/{rt1}/comments/{base['id']}", tok_b)
    assert r.status_code == 204, r.text
    left = sb.table("route_comments").select("id").eq("route_id", rt1).execute().data
    assert left == [], f"답글 cascade 소멸 실패: {left}"
    counts = asyncio.run(route_service._comment_counts([rt1]))
    assert counts.get(rt1, 0) == 0
    ok("부모 삭제 → 답글 cascade 소멸 ✓ count 0 ✓")


def cleanup():
    sb = get_supabase_admin()
    if route_ids:
        sb.table("notifications").delete().in_("target_id", route_ids).execute()
        sb.table("routes").delete().in_("id", route_ids).execute()  # 댓글 FK cascade
    for u in uids:
        httpx.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM, timeout=30)
    for t, col in (("routes", "id"), ("route_comments", "route_id")):
        left = sb.table(t).select("*").in_(col, route_ids).execute().data if route_ids else []
        assert left == [], (t, left)
    print(f"\n[cleanup] routes {len(route_ids)}·댓글·알림·유저 {len(uids)} 삭제·잔여 0")


if __name__ == "__main__":
    try:
        run_tests()
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
