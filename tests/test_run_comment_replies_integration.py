"""
Integration: run 댓글 1-레벨 답글 (2026-08-01, Ivan 계약)

1. 일반 댓글 — parent null (컬럼 유무 무관: 미전송 키 생략)
   [게이트] run_comments.parent_comment_id 미적용이면 명시 대기 exit 1
2. 답글 정상 — parent 실림 + 알림(런 주인 + 부모 작성자, 기존 run_commented 타입)
2b. payload 구분(2026-08-04 additive) — 부모 작성자 건만 is_reply·parent_comment_id,
    주인 건 키 셋 {run_id} 바이트 불변(is_reply:false 금지)
2c. dedup 불변 — self-skip·주인=부모 작성자 1건(주인 경로)·자기 답글 부모 알림 0
2d. 푸시 카피 분기 — _render_body ko/en 답글 세분, 주인·폴백·pb 문구 불변
3. 깊이 2 → 422 reply_depth_exceeded / 4. 타 run 부모 → 422 comment_parent_invalid
5. cascade — 부모 삭제 → 답글 DB 소멸 + comment_count 동기
6. count 답글 포함(행 수 기반) / 7. 플랫 페치 shape 불변 + parent 참조

Run: python tests/test_run_comment_replies_integration.py
임시 유저·run·댓글·알림 종료 시 전삭·잔여 0.
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
from app.services import run_service  # noqa: E402

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_ADM = {"apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json"}
TS = int(time.time())
uids: list[str] = []
run_ids: list[str] = []


def ok(m):
    print(f"  ✓ {m}")


def sb_user(tag):
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                   json={"email": f"rcr-{tag}-{TS}@t.l", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    uids.append(r.json()["id"])
    return r.json()["id"]


def sb_login(tag):
    r = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                   headers={"apikey": settings.supabase_key,
                            "Content-Type": "application/json"},
                   json={"email": f"rcr-{tag}-{TS}@t.l", "password": "test1234"},
                   timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def sb_run(uid):
    r = httpx.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=representation"},
                   json={"user_id": uid, "distance_km": 2.0, "duration_sec": 900,
                         "visibility": "public", "title": f"rcr-{TS}"}, timeout=30)
    r.raise_for_status()
    run_ids.append(r.json()[0]["id"])
    return r.json()[0]["id"]


def _column_exists() -> bool:
    k = settings.supabase_service_role_key
    spec = httpx.get(f"{_SB}/rest/v1/", headers={"apikey": k, "Authorization": f"Bearer {k}"},
                     timeout=30).json()
    return "parent_comment_id" in spec["definitions"]["run_comments"]["properties"]


def run_tests():
    a, b, c_uid = sb_user("a"), sb_user("b"), sb_user("c")
    tok_a, tok_b, tok_c = sb_login("a"), sb_login("b"), sb_login("c")
    run1, run2 = sb_run(a), sb_run(a)
    cl = TestClient(app)

    def api(method, path, tok, **kw):
        return cl.request(method, f"/api{path}",
                          headers={"Authorization": f"Bearer {tok}"}, **kw)

    print("[1. 일반 댓글 — parent null(컬럼 유무 무관)]")
    r = api("POST", f"/runs/{run1}/comments", tok_b, json={"content": "일반"})
    assert r.status_code == 200, r.text
    base = r.json()
    assert base.get("parent_comment_id") is None
    ok("일반 댓글 200 + parent_comment_id null")

    if not _column_exists():
        print("\n[검증 불가] run_comments.parent_comment_id 미적용 — 오너가 "
              "db/2026-08-01_run_comment_replies.sql 실행 후 재실행 필요:\n"
              "  python tests/test_run_comment_replies_integration.py")
        sys.exit(1)

    print("\n[2. 답글 — parent 실림 + 알림 2건(주인·부모 작성자, 기존 타입)]")
    r = api("POST", f"/runs/{run1}/comments", tok_c,
            json={"content": "답글", "parent_comment_id": base["id"]})
    assert r.status_code == 200, r.text
    reply = r.json()
    assert reply["parent_comment_id"] == base["id"]
    sb = get_supabase_admin()
    # 수신자 컬럼 실명은 user_id (recipient_id는 서비스 파라미터명 — §B 실스키마)
    notes = sb.table("notifications").select("user_id,type,payload") \
        .eq("target_id", run1).eq("type", "run_commented").execute().data
    recips = sorted(n["user_id"] for n in notes)
    # B(일반 댓글)→A 1건 + C(답글)→A 1건 + C(답글)→B(부모 작성자) 1건
    assert recips.count(a) == 2 and recips.count(b) == 1, recips
    ok("parent 실림 ✓ 알림: 주인 A 2건(각 댓글)·부모 작성자 B 1건 — 전부 run_commented(표 무변경)")

    print("\n[2b. payload 구분(2026-08-04 additive) — 부모 작성자만 is_reply 2종]")
    b_rows = [n for n in notes if n["user_id"] == b]
    a_rows = [n for n in notes if n["user_id"] == a]
    assert len(b_rows) == 1
    assert b_rows[0]["payload"] == {"run_id": run1, "is_reply": True,
                                    "parent_comment_id": base["id"]}, b_rows[0]
    # 주인 발송 건은 바이트 불변 — 키 셋 정확히 {run_id}(is_reply:false 금지 계약)
    for n in a_rows:
        assert n["payload"] == {"run_id": run1}, n["payload"]
    ok("부모 작성자 행 is_reply·parent_comment_id ✓ 주인 행 키 셋 {run_id} 불변 ✓")

    print("\n[2c. dedup 불변 — 주인=부모 작성자 1건(신필드 무)·자기 답글 무알림]")
    # run2(깨끗한 A 소유 run)에서 격리 검증 — run1의 후속 카운트 절 무교란.
    r = api("POST", f"/runs/{run2}/comments", tok_a, json={"content": "주인 댓글"})
    assert r.status_code == 200, r.text
    a_parent = r.json()

    def run2_notes():
        return sb.table("notifications").select("user_id,payload") \
            .eq("target_id", run2).eq("type", "run_commented").execute().data

    assert run2_notes() == [], "본인 댓글은 무알림(self-skip)"
    # C가 주인(A)의 댓글에 답글 — 주인=부모 작성자 → 정확히 1건(주인 경로만)
    r = api("POST", f"/runs/{run2}/comments", tok_c,
            json={"content": "주인 댓글에 답글", "parent_comment_id": a_parent["id"]})
    assert r.status_code == 200, r.text
    rows = run2_notes()
    assert len(rows) == 1 and rows[0]["user_id"] == a, rows
    # 그 1건은 주인 경로 — 신필드 미부착 바이트 불변이 계약(판단 플래그로 보고)
    assert rows[0]["payload"] == {"run_id": run2}, rows[0]["payload"]
    # C 일반 댓글 → C 자기 답글: 부모 작성자==caller → 부모 알림 0, 주인 +1만
    r = api("POST", f"/runs/{run2}/comments", tok_c, json={"content": "c 댓글"})
    c_parent = r.json()
    r = api("POST", f"/runs/{run2}/comments", tok_c,
            json={"content": "c 자기 답글", "parent_comment_id": c_parent["id"]})
    assert r.status_code == 200, r.text
    rows = run2_notes()
    assert len(rows) == 3 and all(n["user_id"] == a for n in rows), rows
    assert all(n["payload"] == {"run_id": run2} for n in rows), "주인 수신 전수 불변"
    ok("주인=부모 작성자 1건(주인 경로·신필드 무) ✓ 자기 답글 부모 알림 0 ✓ self-skip ✓")

    print("\n[2d. 푸시 카피 분기 — _render_body 순수 함수(ko/en, 발송 무접촉)]")
    from app.services import push_service as ps
    pay_reply = {"run_id": run1, "is_reply": True, "parent_comment_id": base["id"]}
    assert ps._render_body("run_commented", "ko", pay_reply, "철수") \
        == "철수님이 내 댓글에 답글을 남겼어요"
    assert ps._render_body("run_commented", "en", pay_reply, "Sue") \
        == "Sue replied to your comment"
    assert ps._render_body("run_commented", "ko", {"run_id": run1}, "철수") \
        == "철수님이 회원님의 러닝에 댓글을 남겼어요", "주인 건 기존 문구 불변"
    assert ps._render_body("run_commented", "en", None, None) \
        == "A runner commented on your run", "payload None·닉 폴백 안전"
    assert ps._render_body("pb_achieved", "ko",
                           {"record_types": ["best_5k"]}, None) \
        == "5km 최고 기록! 🏅", "pb 분기 회귀 불변"
    ok("답글 ko/en 세분 ✓ 주인·폴백·pb 기존 문구 불변 ✓")

    print("\n[3. 깊이 2 → 422 reply_depth_exceeded]")
    r = api("POST", f"/runs/{run1}/comments", tok_b,
            json={"content": "답답글", "parent_comment_id": reply["id"]})
    assert r.status_code == 422 and r.json()["error_code"] == "reply_depth_exceeded", r.text
    ok("서버 1-레벨 강제 + error_code 승격")

    print("\n[4. 타 run 부모 → 422 comment_parent_invalid]")
    r = api("POST", f"/runs/{run2}/comments", tok_b,
            json={"content": "x", "parent_comment_id": base["id"]})
    assert r.status_code == 422 and r.json()["error_code"] == "comment_parent_invalid", r.text
    r = api("POST", f"/runs/{run1}/comments", tok_b,
            json={"content": "x", "parent_comment_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 422 and r.json()["error_code"] == "comment_parent_invalid", r.text
    ok("타 run 소속·부재 부모 둘 다 422 comment_parent_invalid")

    print("\n[6. count 답글 포함(행 수 기반)]")
    counts = asyncio.run(run_service._comment_counts([run1]))
    assert counts.get(run1) == 2, counts   # 부모 1 + 답글 1
    ok("comment_count 2(부모+답글) — 자동 포함 확인")

    print("\n[7. 플랫 페치 — shape 불변 + parent 참조]")
    r = api("GET", f"/runs/{run1}/comments", tok_a)
    items = r.json()
    assert len(items) == 2
    for k in ("id", "run_id", "user_id", "nickname", "content", "created_at",
              "parent_comment_id"):
        assert k in items[0], k
    parents = {x["id"]: x["parent_comment_id"] for x in items}
    assert parents[reply["id"]] == base["id"] and parents[base["id"]] is None
    ok("플랫 리스트 그대로 + parent 참조로 스레딩 가능")

    print("\n[5. cascade — 부모 삭제 → 답글 소멸 + count 동기]")
    r = api("DELETE", f"/runs/{run1}/comments/{base['id']}", tok_b)
    assert r.status_code == 204, r.text
    left = sb.table("run_comments").select("id").eq("run_id", run1).execute().data
    assert left == [], f"답글 cascade 소멸 실패: {left}"
    counts = asyncio.run(run_service._comment_counts([run1]))
    assert counts.get(run1, 0) == 0
    ok("부모 삭제 → 답글 DB cascade 소멸 ✓ count 0 동기 ✓")


def cleanup():
    sb = get_supabase_admin()
    if run_ids:
        sb.table("notifications").delete().in_("target_id", run_ids).execute()
        sb.table("runs").delete().in_("id", run_ids).execute()   # 댓글 FK cascade
    for u in uids:
        httpx.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM, timeout=30)
    for t, col in (("runs", "id"), ("run_comments", "run_id")):
        left = sb.table(t).select("*").in_(col, run_ids).execute().data if run_ids else []
        assert left == [], (t, left)
    print(f"\n[cleanup] runs {len(run_ids)}·댓글·알림·유저 {len(uids)} 삭제·잔여 0")


if __name__ == "__main__":
    try:
        run_tests()
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
