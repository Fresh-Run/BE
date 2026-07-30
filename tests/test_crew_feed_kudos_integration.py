"""
Integration: 크루 러닝 피드 kudos_count·my_kudos (2026-07-31, Ivan c)

K1 활동 피드와 동일 시맨틱(v120 자기 kudos 포함). 매트릭스:
- 멤버 B(비팔로워) 피드: public·followers 노출/private 제외 + count·my_kudos 정합
- followers 런에 비팔로우 크루원 kudos 성공 — _can_see_run 엣지 ⓑ(크루 탭스루) 실증
- 자기 kudos(v120) 카운트·my_kudos 반영
- 비멤버 C: 403 members_only(실계약 — routes.py "Members only", 404 아님)
- 쿼리 수 고정: 피드 1페이지당 kudos 배치 헬퍼 각 정확히 1회 호출(N+1 금지)

Run: python tests/test_crew_feed_kudos_integration.py  (서버 불필요 — TestClient 인프로세스)
종료 시 생성 데이터 전삭·잔여 0 assert.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services import run_service  # noqa: E402

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_SVC = settings.supabase_service_role_key
_ANON = settings.supabase_key
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}
TS = int(time.time())
PW = "test1234"

uids: list[str] = []
run_ids: list[str] = []
crew_id: str | None = None


def ok(m):
    print(f"  ✓ {m}")


def step(t):
    print(f"\n[{t}]")


def sb_user(email):
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                   json={"email": email, "password": PW, "email_confirm": True}, timeout=30)
    r.raise_for_status()
    uids.append(r.json()["id"])
    return r.json()["id"]


def sb_login(email):
    r = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                   headers={"apikey": _ANON, "Content-Type": "application/json"},
                   json={"email": email, "password": PW}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def sb_run(uid, visibility, ran_at):
    r = httpx.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=representation"},
                   json={"user_id": uid, "distance_km": 3.0, "duration_sec": 1200,
                         "visibility": visibility, "ran_at": ran_at,
                         "title": f"feedkudos-{visibility}"}, timeout=30)
    r.raise_for_status()
    run_ids.append(r.json()[0]["id"])
    return r.json()[0]["id"]


def run_tests():
    global crew_id
    a = sb_user(f"cfk-a-{TS}@t.l")
    b = sb_user(f"cfk-b-{TS}@t.l")
    c_uid = sb_user(f"cfk-c-{TS}@t.l")
    tok_a, tok_b, tok_c = (sb_login(f"cfk-{x}-{TS}@t.l") for x in "abc")
    c = TestClient(app)

    def api(method, path, tok, **kw):
        return c.request(method, f"/api{path}",
                         headers={"Authorization": f"Bearer {tok}"}, **kw)

    step("셋업 — 크루(A 오너)+B 멤버 직삽입, A 런 3종(B는 A 비팔로우)")
    r = api("POST", "/crews", tok_a, json={"name": f"cfk-{TS}"})
    assert r.status_code in (200, 201), r.text
    crew_id = r.json()["id"]
    httpx.post(f"{_SB}/rest/v1/crew_members", headers=_ADM,
               json={"crew_id": crew_id, "user_id": b, "role": "member"},
               timeout=30).raise_for_status()
    prv = sb_run(a, "private", "2026-07-31T01:00:00Z")
    fol = sb_run(a, "followers", "2026-07-31T02:00:00Z")
    pub = sb_run(a, "public", "2026-07-31T03:00:00Z")

    step("kudos — B→public·B→followers(엣지 ⓑ, 비팔로우 크루원)·A→자기 런(v120)")
    assert api("POST", f"/runs/{pub}/kudos", tok_b).status_code == 204
    r = api("POST", f"/runs/{fol}/kudos", tok_b)
    assert r.status_code == 204, f"followers 런 + 비팔로우 크루원 = 엣지 ⓑ 허용이어야: {r.text}"
    assert api("POST", f"/runs/{pub}/kudos", tok_a).status_code == 204, "자기 kudos(v120)"
    ok("3건 전송 — 크루 탭스루로 followers 런도 kudos 성공(권한 공백 없음 실증)")

    step("쿼리 수 고정 — 배치 헬퍼 각 1회/페이지(N+1 금지)")
    calls = {"counts": 0, "myset": 0}
    orig_counts, orig_myset = run_service._kudos_counts, run_service._my_kudos_set

    async def spy_counts(run_ids_):
        calls["counts"] += 1
        return await orig_counts(run_ids_)

    async def spy_myset(run_ids_, user_id_):
        calls["myset"] += 1
        return await orig_myset(run_ids_, user_id_)

    run_service._kudos_counts, run_service._my_kudos_set = spy_counts, spy_myset
    try:
        r = api("GET", f"/crews/{crew_id}/runs", tok_b)
    finally:
        run_service._kudos_counts, run_service._my_kudos_set = orig_counts, orig_myset
    assert r.status_code == 200, r.text
    items = [x for x in r.json() if str(x.get("title", "")).startswith("feedkudos-")]
    assert calls == {"counts": 1, "myset": 1}, f"페이지당 각 1쿼리여야: {calls}"
    ok(f"아이템 {len(items)}개 페이지에 kudos 쿼리 정확히 2회(카운트 1+my 1) — 고정")

    step("가시성 매트릭스 — B(멤버·비팔로워) 피드 정합")
    by_id = {x["run_id"]: x for x in items}
    assert set(by_id) == {pub, fol}, f"public·followers만 노출(private 제외): {set(by_id)}"
    assert by_id[pub]["kudos_count"] == 2 and by_id[pub]["my_kudos"] is True, by_id[pub]
    assert by_id[fol]["kudos_count"] == 1 and by_id[fol]["my_kudos"] is True, by_id[fol]
    ok("private 제외 ✓ pub: count 2(자기 kudos 포함)·my true ✓ fol: count 1·my true ✓")

    step("A(소유자) 피드 — 자기 kudos 반영")
    r = api("GET", f"/crews/{crew_id}/runs", tok_a)
    by_id = {x["run_id"]: x for x in r.json() if str(x.get("title", "")).startswith("feedkudos-")}
    assert by_id[pub]["my_kudos"] is True and by_id[pub]["kudos_count"] == 2, by_id[pub]
    assert by_id[fol]["my_kudos"] is False and by_id[fol]["kudos_count"] == 1, by_id[fol]
    ok("자기 kudos my_kudos=true(v120) ✓ 미전송 런 false ✓")

    step("비멤버 C — 403 members_only(실계약 유지)")
    r = api("GET", f"/crews/{crew_id}/runs", tok_c)
    assert r.status_code == 403 and r.json().get("error_code") == "members_only", r.text
    ok("403 + error_code=members_only (기존 에러 계약 불변)")

    step("기존 키 무접촉 — comment_count 등 기존 필드 공존")
    sample = list(by_id.values())[0]
    for k in ("run_id", "comment_count", "is_crew_session", "distance_km"):
        assert k in sample, k
    ok("기존 필드 유지 + kudos 2필드 additive")


def cleanup():
    def _del(table, col, vals):
        if vals:
            httpx.delete(f"{_SB}/rest/v1/{table}", headers=_ADM,
                         params={col: f"in.({','.join(vals)})"}, timeout=30)
    _del("notifications", "target_id", run_ids)
    _del("runs", "id", run_ids)          # run_kudos FK CASCADE
    if crew_id:
        _del("crews", "id", [crew_id])   # crew_members CASCADE
    for u in uids:
        httpx.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM, timeout=30)
    for table, col, vals in (("runs", "id", run_ids),
                             ("run_kudos", "run_id", run_ids),
                             ("crew_members", "crew_id", [crew_id] if crew_id else []),
                             ("notifications", "target_id", run_ids)):
        if not vals:
            continue
        left = httpx.get(f"{_SB}/rest/v1/{table}", headers=_ADM,
                         params={"select": "*" if table != "runs" else "id",
                                 col: f"in.({','.join(vals)})"}, timeout=30).json()
        assert left == [], f"{table} 잔여: {left}"
    print(f"\n[cleanup] runs {len(run_ids)}·crew·kudos·알림·유저 {len(uids)} 삭제, 잔여 0")


if __name__ == "__main__":
    try:
        run_tests()
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
