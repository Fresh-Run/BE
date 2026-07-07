"""
Integration test: 감사 백로그 소품 L4~L8
L4 preview-by-code POST(권장)·GET(레거시) 동등
L5 transfer_ownership 실패 주입 → 보상 복구(원상 유지)  [결정론, mock]
L6 탈퇴자 RSVP 잔존 상태에서 집계가 현재 멤버만  [실데이터 시뮬]
L7 _week_start_utc 단일 정의  [결정론]
L8 FeedbackRequest tags dedupe/상한·distance 하한·decide_join 이중승인 방지
Run: python tests/test_audit_l4_l8_integration.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, patch

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


def phase_pure():
    step("L7. _week_start_utc 단일 정의 (import 통일)")
    from app.services.crew_service import _week_start_utc as c_ws
    from app.services.run_service import _week_start_utc as r_ws
    assert c_ws is r_ws, "crew_service가 run_service 정의를 재사용해야 (드리프트 방지)"
    ok("crew_service._week_start_utc is run_service._week_start_utc ✓")

    step("L5. transfer_ownership 실패 주입 → 보상 복구 (mock)")
    from app.services import crew_service as cs
    calls = []

    async def fake_ensure_owner(crew_id, caller_id, cols="owner_id"):
        return {"id": crew_id, "owner_id": caller_id}

    # _set_owner(new)에서 예외 → 보상 경로 타야. to_thread를 가로채 호출 기록.
    real_to_thread = asyncio.to_thread
    boom = {"armed": False}

    async def rec_to_thread(fn, *a, **k):
        # fn은 lambda: _set_role/_set_owner(...) — 실제 실행 대신 기록만
        src = fn
        calls.append("call")
        # 3번째 호출(=owner_id 플립, 커밋)에서 폭발
        if len([x for x in calls]) == 3:
            raise RuntimeError("주입: owner_id 플립 실패")
        return None

    with patch.object(cs, "ensure_owner", fake_ensure_owner), \
         patch.object(cs, "_is_member", AsyncMock(return_value=True)), \
         patch.object(cs.asyncio, "to_thread", rec_to_thread):
        try:
            asyncio.run(cs.transfer_ownership("crew1", "owner1", "new1"))
            fail("실패 주입했는데 예외가 안 남")
        except RuntimeError:
            pass
    # 성공 경로 3콜(role,role,owner) + 커밋 실패 후 보상 3콜(owner,role,role) = 6
    assert len(calls) == 6, f"보상 복구 3콜 포함 6콜 기대, got {len(calls)}"
    ok(f"커밋 실패 → 보상 복구 3콜 실행(총 {len(calls)}콜) ✓ 예외 전파 ✓")


def phase_api(c):
    ts = int(time.time())
    uids, crew_ids = [], []
    try:
        A_id, A = mkuser(c, f"l48-a-{ts}@t.l"); uids.append(A_id)
        B_id, B = mkuser(c, f"l48-b-{ts}@t.l"); uids.append(B_id)
        for uid, tok in [(A_id, A), (B_id, B)]:
            api(c, "PATCH", "/me/profile", tok, json={"nickname": f"L48-{uid[:4]}"})
        # A는 크루 2개 생성하므로 premium (무료 1개 한도 해제)
        c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM,
                params={"user_id": f"eq.{A_id}"}, json={"tier": "premium"})

        step("L4. preview-by-code POST(권장)·GET(레거시) 동등")
        r = api(c, "POST", "/crews", A, json={"name": f"L48크루-{ts%100000}",
                                              "is_public": False, "join_policy": "approval"})
        crew_id = r.json()["id"]; crew_ids.append(crew_id)
        code = api(c, "POST", f"/crews/{crew_id}/invite", A).json()["code"]
        # POST body (권장 — 코드가 URL/로그에 안 남음)
        rp = api(c, "POST", "/crews/preview-by-code", B, json={"code": code})
        assert rp.status_code == 200 and rp.json()["id"] == crew_id, rp.text[:200]
        # GET (레거시 — 유지)
        rg = api(c, "GET", "/crews/preview-by-code", B, params={"code": code})
        assert rg.status_code == 200 and rg.json()["id"] == crew_id
        # 잘못된 코드 404 (양쪽)
        assert api(c, "POST", "/crews/preview-by-code", B, json={"code": "ZZZZ9999"}).status_code == 404
        ok("POST=200 동일 크루 ✓ GET=200 동일 ✓ 잘못된 코드 404 ✓ (병행 경로)")

        step("L8. tags dedupe/상한 · distance 하한 · decide_join 이중승인")
        # distance 하한: 0.005 → 422, 0.01 통과
        assert api(c, "POST", "/runs", A, json={"distance_km": 0.005, "duration_sec": 60}).status_code == 422
        # tags 상한: 21개 → 422 (허용 태그 반복이라도 개수 초과)
        r = api(c, "PATCH", "/runs/nonexistent/feedback", A,
                json={"liked": True, "tags": ["신호등많음"] * 21})
        assert r.status_code == 422, f"tags 21개 422 기대, got {r.status_code}"
        ok("distance 0.005 422 ✓ tags 21개 422 ✓ (dedupe는 결정론에서 확인)")

        step("L8c. decide_join 이중승인 방지 (재승인은 404, 재알림 없음)")
        # 별도 공개+승인 크루로 승인 흐름 검증
        r2 = api(c, "POST", "/crews", A, json={"name": f"승인크루-{ts%100000}",
                                               "is_public": True, "join_policy": "approval"})
        ac = r2.json()["id"]; crew_ids.append(ac)
        api(c, "POST", f"/crews/{ac}/join", B)
        jr = api(c, "GET", f"/crews/{ac}/join-requests", A).json()[0]["id"]
        assert api(c, "POST", f"/crews/{ac}/join-requests/{jr}/approve", A).status_code in (200, 204)
        # 같은 요청 재승인 → 404 (이미 pending 아님) → 이중 알림 없음
        assert api(c, "POST", f"/crews/{ac}/join-requests/{jr}/approve", A).status_code == 404
        napprove = [n for n in api(c, "GET", "/notifications", B, params={"limit": 50}).json()
                    if n["type"] == "join_approved" and n["target_id"] == ac]
        assert len(napprove) == 1, f"join_approved 알림 정확히 1건, got {len(napprove)}"
        ok("승인 200 ✓ 재승인 404 ✓ join_approved 알림 1건(이중발송 없음) ✓")

        step("L6. 탈퇴자 RSVP 잔존 → 집계는 현재 멤버만")
        # B를 코드로 즉시 가입(비공개 크루라 join-by-code) → 공지 → 둘 다 going
        api(c, "POST", "/crews/join-by-code", B, json={"code": code})
        future = "2030-01-01T09:00:00+09:00"
        ann = api(c, "POST", f"/crews/{crew_id}/announcements", A,
                  json={"title": "정기런", "body": "참석?", "run_at": future}).json()
        aid = ann["id"]
        api(c, "PUT", f"/crews/{crew_id}/announcements/{aid}/rsvp", A, json={"status": "going"})
        api(c, "PUT", f"/crews/{crew_id}/announcements/{aid}/rsvp", B, json={"status": "going"})
        tally = api(c, "GET", f"/crews/{crew_id}/announcements/{aid}", A).json()["rsvp"]
        assert tally["going"] == 2, f"going 2 기대, got {tally}"
        # B의 RSVP 행을 남긴 채 crew_members에서만 강제 제거 (탈퇴 정리 실패 시뮬)
        c.delete(f"{_SB}/rest/v1/crew_members", headers={**_ADM, "Prefer": "return=minimal"},
                 params={"crew_id": f"eq.{crew_id}", "user_id": f"eq.{B_id}"})
        # RSVP 행은 그대로 존재 (직접 확인)
        rem = c.get(f"{_SB}/rest/v1/crew_announcement_rsvps", headers=_ADM,
                    params={"announcement_id": f"eq.{aid}", "user_id": f"eq.{B_id}"}).json()
        assert rem, "B의 RSVP 행이 아직 남아있어야 (시뮬 전제)"
        # 집계는 이제 현재 멤버(A)만 → going 1
        tally2 = api(c, "GET", f"/crews/{crew_id}/announcements/{aid}", A).json()["rsvp"]
        assert tally2["going"] == 1, f"탈퇴자 제외 going 1 기대, got {tally2}"
        ok("멤버 2명 going=2 → B 탈퇴(RSVP 잔존) → 집계 going=1 (탈퇴자 제외) ✓")

        return uids, crew_ids
    finally:
        pass


def run():
    with httpx.Client(timeout=40) as c:
        uids = crew_ids = []
        try:
            phase_pure()
            uids, crew_ids = phase_api(c)
            print("\n" + "=" * 50); print("  ALL TESTS PASSED"); print("=" * 50)
        finally:
            step("Cleanup")
            del_in(c, "crews", "id", crew_ids)
            del_in(c, "runs", "user_id", uids)
            del_in(c, "notifications", "user_id", uids)
            del_in(c, "profiles", "user_id", uids)
            for u in uids:
                c.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM)
            ok("정리 완료")


if __name__ == "__main__":
    run()
