"""
Integration test: 러닝 기록 삭제 DELETE /runs/{run_id} (docs/RUN_DELETE_DESIGN.md)

하드 삭제 — kudos·댓글·트랙 FK cascade + Storage 사진·run 대상 알림 best-effort
정리. 집계(PB·주간/월간·세션·챌린지)는 라이브 계산이라 자동 반영을 실증.

케이스:
 1. 본인 삭제 204 + cascade 전수(runs·kudos·댓글·트랙 0) + 사진 Storage 정리
 2. 재삭제 404 / 타인 404+행 불변 / 없는 id 404
 3. 차단 관계 무관(본인 run — 소유권만)
 4. PB 승계: PB run 삭제 → records 차순위 자동
 5. 통계 라이브 차감: week 거리·횟수 즉시 감소
 6. 세션 카운트: 태그런 삭제 → participant_count 2→1, 전부 삭제 → 배지 소멸
 7. 알림 정리: run 대상(run_kudoed) 소멸 + 무관(user_followed) 잔존
 8. run_share 스냅샷 잔존 + 원본 404 (기존 계약 회귀)
 9. 코스 연결: run 삭제 후 코스 잔존
10. 레이스: 동시 2발 → [204,404] + 행 0

Run: python tests/test_run_delete_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import asyncio
import os, sys, time
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


def ok(m):         print(f"  ✓ {m}")
def fail(m, d=""):  print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):       print(f"\n[{t}]")


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


def gps(n=12):
    return [{"lat": round(37.5445 + i * 0.0001, 7), "lng": 127.0374,
             "t": 1_783_300_000_000 + i * 4000, "acc": 8.0} for i in range(n)]


def rows(c, table, **eqs):
    p = {k: f"eq.{v}" for k, v in eqs.items()}; p["select"] = "*"
    return c.get(f"{_SB}/rest/v1/{table}", headers=_ADM, params=p).json()


def storage_list(c, prefix):
    r = c.post(f"{_SB}/storage/v1/object/list/run-photos", headers=_ADM,
               json={"prefix": prefix})
    return r.json() if r.status_code == 200 else []


def save_run(c, tok, km=5.0, pace=360, **extra):
    body = {"distance_km": km, "duration_sec": round(km * pace),
            "avg_pace_sec_per_km": pace, "visibility": "public", **extra}
    r = api(c, "POST", "/runs", tok, json=body)
    assert r.status_code == 200, r.text[:200]
    return r.json()["id"]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    crew = None
    try:
        step("0. O(소유)·M(멤버/kudos)·X(타인) + 크루")
        for k in ("o", "m", "x"):
            uids[k] = sb_user(c, f"rdel-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"rdel-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"RDEL{k}{TS}"}).status_code == 200
        crew = api(c, "POST", "/crews", tk["o"], json={"name": f"삭제크루{TS}"}).json()["id"]
        assert api(c, "POST", f"/crews/{crew}/join", tk["m"]).status_code == 200
        ok("유저 3명 + 크루(O·M)")

        step("1. 풀장착 run 삭제 — cascade 전수 + 사진 Storage 정리")
        r1 = save_run(c, tk["o"], km=5.0, pace=360, gps_track=gps(), notes="삭제대상")
        # kudos 2 + 댓글 1
        assert api(c, "POST", f"/runs/{r1}/kudos", tk["m"]).status_code == 204
        assert api(c, "POST", f"/runs/{r1}/kudos", tk["x"]).status_code == 204
        assert api(c, "POST", f"/runs/{r1}/comments", tk["m"], json={"content": "댓글"}).status_code in (200, 201)
        # 사진 1장 (3-step)
        up = api(c, "POST", f"/runs/{r1}/photos/upload-url", tk["o"],
                 json={"slot": 1, "content_type": "image/jpeg"}).json()
        pr = httpx.put(up["upload_url"], content=b"\xff\xd8\xff\xe0fakejpeg",
                       headers={"Content-Type": "image/jpeg"}, timeout=30)
        assert pr.status_code in (200, 201), pr.text[:150]
        assert api(c, "PATCH", f"/runs/{r1}", tk["o"], json={"photos": [up["path"]]}).status_code == 200
        assert storage_list(c, r1), "사진 업로드 확인(전제)"
        assert rows(c, "run_tracks", run_id=r1), "트랙 존재(전제)"
        # 삭제
        assert api(c, "DELETE", f"/runs/{r1}", tk["o"]).status_code == 204, "삭제 204"
        assert rows(c, "runs", id=r1) == [], "runs 행 소멸"
        assert rows(c, "run_kudos", run_id=r1) == [], "kudos cascade 소멸"
        assert rows(c, "run_comments", run_id=r1) == [], "댓글 cascade 소멸"
        assert rows(c, "run_tracks", run_id=r1) == [], "트랙 cascade 소멸"
        assert storage_list(c, r1) == [], "사진 Storage 정리"
        ok("204 · runs/kudos/댓글/트랙 소멸 · Storage 정리 (cascade 전수)")

        step("2. 재삭제/타인/없는 id → 404")
        assert api(c, "DELETE", f"/runs/{r1}", tk["o"]).status_code == 404, "재삭제 404"
        r2 = save_run(c, tk["o"], km=3.0, pace=400)
        assert api(c, "DELETE", f"/runs/{r2}", tk["x"]).status_code == 404, "타인 404 은닉"
        assert rows(c, "runs", id=r2) != [], "타인 시도 후 행 불변"
        ghost = "00000000-0000-4000-8000-000000000000"
        assert api(c, "DELETE", f"/runs/{ghost}", tk["o"]).status_code == 404, "없는 id 404"
        ok("재삭제 404 · 타인 404+불변 · 없는 id 404")

        step("3. 차단 관계 무관 — 본인 run은 소유권만")
        assert api(c, "POST", f"/users/{uids['x']}/block", tk["o"]).status_code == 204
        assert api(c, "DELETE", f"/runs/{r2}", tk["o"]).status_code == 204, "차단 중에도 본인 삭제 204"
        api(c, "DELETE", f"/users/{uids['x']}/block", tk["o"])  # 원복
        ok("차단 관계 존재해도 본인 삭제 정상 (소유권 게이트만)")

        step("4. PB 승계 — PB run 삭제 → 차순위 자동 (라이브 계산 실증)")
        fast = save_run(c, tk["m"], km=5.0, pace=330)   # PB(best_pace 330)
        slow = save_run(c, tk["m"], km=5.0, pace=380)
        # PB 자격은 verified만(_compute_records 오염 방지 정책) — admin으로 부여
        # (트랙 파이프라인 경유 시 distance/pace가 실측 대체돼 정확값 assert 불가).
        for rid in (fast, slow):
            c.patch(f"{_SB}/rest/v1/runs?id=eq.{rid}", headers=_ADM,
                    json={"verification": "verified"})
        rec = api(c, "GET", "/me/stats", tk["m"]).json()["records"]
        assert rec["best_pace"]["value"] == 330 and rec["best_pace"]["run_id"] == fast, f"PB=fast, got {rec['best_pace']}"
        assert api(c, "DELETE", f"/runs/{fast}", tk["m"]).status_code == 204
        rec = api(c, "GET", "/me/stats", tk["m"]).json()["records"]
        assert rec["best_pace"]["value"] == 380 and rec["best_pace"]["run_id"] == slow, \
            f"차순위 승계, got {rec['best_pace']}"
        ok("PB 330(fast) → 삭제 → 380(slow) 자동 승계 (재계산 코드 0)")

        step("5. 통계 라이브 차감 — week 거리·횟수 즉시 감소")
        before = api(c, "GET", "/me/stats", tk["m"]).json()["week"]
        assert api(c, "DELETE", f"/runs/{slow}", tk["m"]).status_code == 204
        after = api(c, "GET", "/me/stats", tk["m"]).json()["week"]
        assert after["run_count"] == before["run_count"] - 1, f"횟수 -1: {before['run_count']}→{after['run_count']}"
        assert round(before["total_distance_km"] - after["total_distance_km"], 1) == 5.0, \
            f"거리 -5.0: {before['total_distance_km']}→{after['total_distance_km']}"
        ok(f"week {before['run_count']}회/{before['total_distance_km']}km → "
           f"{after['run_count']}회/{after['total_distance_km']}km (즉시 차감)")

        step("6. 세션 카운트 — 2→1 감소, 전부 삭제 시 배지 소멸")
        so = save_run(c, tk["o"], km=4.0, pace=360, crew_id=crew)
        sm = save_run(c, tk["m"], km=4.0, pace=370, crew_id=crew)
        feed = api(c, "GET", f"/crews/{crew}/runs", tk["o"]).json()
        card = next(x for x in feed if x["run_id"] == so)
        assert card["is_crew_session"] and card["session_participant_count"] == 2, card
        assert api(c, "DELETE", f"/runs/{sm}", tk["m"]).status_code == 204
        feed = api(c, "GET", f"/crews/{crew}/runs", tk["o"]).json()
        card = next(x for x in feed if x["run_id"] == so)
        assert card["session_participant_count"] == 1, f"2→1, got {card['session_participant_count']}"
        assert api(c, "DELETE", f"/runs/{so}", tk["o"]).status_code == 204
        feed = api(c, "GET", f"/crews/{crew}/runs", tk["o"]).json()
        assert not any(x["is_crew_session"] for x in feed), "태그런 전부 삭제 → 배지 소멸"
        ok("participant_count 2→1 · 전부 삭제 → 세션 배지 소멸 (라이브)")

        step("7. 알림 정리 — run 대상 소멸 + 무관 잔존")
        r7 = save_run(c, tk["o"], km=2.0, pace=400)
        assert api(c, "POST", f"/runs/{r7}/kudos", tk["m"]).status_code == 204   # → O에게 run_kudoed(target=r7)
        assert api(c, "POST", f"/users/{uids['o']}/follow", tk["m"]).status_code == 204  # → user_followed(무관)
        assert rows(c, "notifications", target_id=r7) != [], "run_kudoed 알림 존재(전제)"
        assert api(c, "DELETE", f"/runs/{r7}", tk["o"]).status_code == 204
        assert rows(c, "notifications", target_id=r7) == [], "run 대상 알림 소멸"
        o_notifs = [n["type"] for n in rows(c, "notifications", user_id=uids["o"])]
        assert "user_followed" in o_notifs, "무관 알림(user_followed) 잔존"
        ok("run_kudoed 소멸 · user_followed 잔존")

        step("8. run_share 스냅샷 잔존 + 원본 404 (기존 계약)")
        r8 = save_run(c, tk["o"], km=3.5, pace=380, title="공유런")
        assert api(c, "POST", f"/crews/{crew}/chat/share-run", tk["o"],
                   json={"run_id": r8, "caption": "오늘 기록!"}).status_code in (200, 201, 204)
        assert api(c, "DELETE", f"/runs/{r8}", tk["o"]).status_code == 204
        msgs = api(c, "GET", f"/crews/{crew}/chat/messages", tk["o"], params={"limit": 20}).json()
        share = next((m for m in msgs if m["type"] == "run_share"), None)
        assert share and share["payload"]["run_id"] == r8, "스냅샷 카드 잔존"
        assert share["payload"].get("distance_km") == 3.5, "박제 요약 유지"
        assert api(c, "GET", f"/runs/{r8}", tk["o"]).status_code == 404, "원본 탭 404"
        ok("채팅 카드 잔존(박제) · 원본 404 (계약 유지)")

        step("9. 코스 연결 — run 삭제 후 코스 잔존")
        route = c.post(f"{_SB}/rest/v1/routes", headers={**_ADM, "Prefer": "return=representation"},
                       json={"user_id": uids["o"], "summary": f"삭제테스트코스{TS}",
                             "target_distance_km": 3.0, "total_distance_km": 3.0,
                             "estimated_duration_min": 20, "waypoints": [], "polyline": [],
                             "start_lat": 37.5, "start_lng": 127.0, "is_public": False}).json()[0]["id"]
        r9 = save_run(c, tk["o"], km=3.0, pace=400, route_id=route)
        assert api(c, "DELETE", f"/runs/{r9}", tk["o"]).status_code == 204
        assert rows(c, "routes", id=route) != [], "코스 잔존(연결만 소멸)"
        ok("run 삭제 후 코스 잔존")

        step("10. 레이스 — 동시 삭제 2발 → [204, 404] + 행 0")
        r10 = save_run(c, tk["o"], km=2.0, pace=420)
        async def burst():
            async with httpx.AsyncClient(timeout=30) as ac:
                async def one():
                    return await ac.delete(f"{BASE}/runs/{r10}",
                                           headers={"Authorization": f"Bearer {tk['o']}"})
                return await asyncio.gather(one(), one(), return_exceptions=True)
        results = asyncio.run(burst())
        codes = sorted(r.status_code for r in results if not isinstance(r, Exception))
        assert codes == [204, 404], f"동시 2발 [204,404], got {codes}"
        assert rows(c, "runs", id=r10) == [], "행 정확히 0"
        ok(f"동시 2발 → {codes} · 행 0 (불변식)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        if crew:
            c.delete(f"{_SB}/rest/v1/crews?id=eq.{crew}", headers=_ADM)
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (runs·routes·notifications cascade)")


if __name__ == "__main__":
    run_tests()
