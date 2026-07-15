"""
Integration test: 신고 v1 + run 오픈 v1.1 (docs/REPORT_DESIGN.md)

POST /reports(유저·run 신고, 204·self 400·404 은닉·중복 멱등·레이스) +
GET/PATCH /admin/reports(운영진 게이트 404·목록 brief(user/run)·단방향 처리).

자가완결형(2026-07-15 갱신): 임시 admin 유저를 만들고 **자체 uvicorn(8002)**을
ADMIN_USER_IDS=<임시 uid> env로 기동해 전 스텝을 8002로 실행 — 로컬 .env·운영
secret(실 ADMIN_USER_IDS)·실기기 계정 무접촉. (push_notification의 8001 선례.)
secret 미설정 fail-safe(전원 404)는 메인 8000이 실운영 uid만 가지므로 이 테스트의
비운영진 404 스텝이 사실상 함께 커버.

케이스:
 1. 유저 신고 정상 → 204 + reports 행 생성(pending)
 2. self 신고 → 400
 3. 차단 관계 신고 → 404 + 행 미생성
 4. 없는 유저 → 404
 5. target_type='route'(미오픈) → 422  (run은 v1.1에서 오픈 — 11~14로 이동)
 6. 중복 pending 재신고 → 204 + 행 1개 유지(멱등)
 7. 레이스: 동시 2발 → 둘 다 204 + 행 정확히 1개(부분 유니크 불변식)
 8. admin 조회: 운영진 200+brief / 비운영진 404
 9. PATCH: reviewed 204+reviewed_at / 재처리 404 / pending 되돌리기 422 /
    dismissed 204 / 비운영진 404
10. detail 501자 → 422
+  무알림: 신고당한 B의 notifications 개수 불변

run 신고 (v1.1, 2026-07-15 오픈):
11. B의 public run 신고(A, 비팔로우) → 204 + target_type='run' 행 생성
    / 중복 pending 멱등(부분 유니크 타입 무관 자동 적용) / 자기 run → 400
12. B의 private run 신고(A 비가시) → 404 은닉 + 행 미생성 / 없는 run → 404
13. 차단 소유자(C)의 public run → 404 은닉 + 행 미생성
14. admin 조회: target_run{run_id,title,owner.nickname} brief · target은 null
    → B가 run 삭제 후 재조회: 200 안 깨짐 + 신고 행 잔존 + target_run null

Run: python tests/test_report_integration.py  (로컬 서버 + ADMIN_USER_IDS 필요)
"""
from __future__ import annotations

import asyncio
import os, subprocess, sys, time
import httpx

BASE = "http://localhost:8002/api"   # 자체 기동 서버(admin env 오버라이드)
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


def db_reports(c, reporter, target):
    r = c.get(f"{_SB}/rest/v1/reports", headers=_ADM,
              params={"reporter_id": f"eq.{reporter}", "target_id": f"eq.{target}",
                      "select": "id,status,reason,detail,reviewed_at"})
    return r.json()


def notif_count(c, token):
    return len(api(c, "GET", "/notifications", token).json())


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    proc = None
    try:
        step("0. A(신고자)·B(대상)·C(차단페어/비운영진) + 임시 admin + 서버 8002")
        for k in ("a", "b", "cc", "adm"):
            uids[k] = sb_user(c, f"rpt-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"rpt-{k}-{TS}@test.com") for k in uids}
        # 자체 서버: ADMIN_USER_IDS=임시 admin uid (로컬 .env·운영 secret 무접촉)
        env = {**os.environ, "ADMIN_USER_IDS": uids["adm"]}
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8002",
             "--log-level", "warning"],
            cwd=os.path.join(os.path.dirname(__file__), ".."), env=env)
        for _ in range(40):
            try:
                if httpx.get("http://localhost:8002/health", timeout=2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            fail("8002 서버 기동 실패")
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"RPT{k}{TS}"}).status_code == 200
        adm_tok = tk["adm"]   # 임시 운영진(이 서버의 ADMIN_USER_IDS)
        ok("임시 유저 4명 + admin env 서버 8002 기동")

        step("1. 유저 신고 정상 — A→B → 204 + pending 행 생성")
        b_notif_before = notif_count(c, tk["b"])
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "user", "target_id": uids["b"],
                      "reason": "spam", "detail": "스팸 계정 같아요"})
        assert r.status_code == 204, f"204 기대, got {r.status_code}: {r.text[:150]}"
        rows = db_reports(c, uids["a"], uids["b"])
        assert len(rows) == 1 and rows[0]["status"] == "pending", f"pending 행 1개, got {rows}"
        assert rows[0]["reason"] == "spam" and rows[0]["detail"] == "스팸 계정 같아요"
        report_ab = rows[0]["id"]
        ok("204 · reports 행 생성(pending, reason·detail 저장)")

        step("무알림 — 신고당한 B의 알림 개수 불변")
        assert notif_count(c, tk["b"]) == b_notif_before, "신고는 무알림(대상에게 안 알림)"
        ok(f"B 알림 불변({b_notif_before})")

        step("2. self 신고 → 400")
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "user", "target_id": uids["a"], "reason": "spam"})
        assert r.status_code == 400, f"self 400, got {r.status_code}"
        ok("self 신고 400")

        step("3. 차단 관계 신고 → 404 + 행 미생성")
        assert api(c, "POST", f"/users/{uids['cc']}/block", tk["a"]).status_code == 204
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "user", "target_id": uids["cc"], "reason": "abuse"})
        assert r.status_code == 404, f"차단 관계 404 은닉, got {r.status_code}"
        assert db_reports(c, uids["a"], uids["cc"]) == [], "행 미생성"
        api(c, "DELETE", f"/users/{uids['cc']}/block", tk["a"])  # 원복
        ok("차단 관계 404 · 행 미생성")

        step("4. 없는 유저 → 404")
        ghost = "00000000-0000-0000-0000-000000000000"
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "user", "target_id": ghost, "reason": "spam"})
        assert r.status_code == 404, f"없는 유저 404, got {r.status_code}"
        ok("없는 유저 404")

        step("5. target_type='route'(미오픈) → 422")
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "route", "target_id": uids["b"], "reason": "spam"})
        assert r.status_code == 422, f"미오픈 타입 422, got {r.status_code}"
        ok("target_type='route' 422 (user·run만 오픈)")

        step("10. detail 501자 → 422")
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "user", "target_id": uids["cc"],
                      "reason": "other", "detail": "가" * 501})
        assert r.status_code == 422, f"detail 501자 422, got {r.status_code}"
        ok("detail 501자 422 (앱 Pydantic 검증)")

        step("6. 중복 pending 재신고 → 204 멱등 + 행 1개 유지")
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "user", "target_id": uids["b"], "reason": "abuse"})
        assert r.status_code == 204, f"재신고 멱등 204, got {r.status_code}"
        rows = db_reports(c, uids["a"], uids["b"])
        assert len(rows) == 1, f"pending 1행 유지, got {len(rows)}"
        assert rows[0]["reason"] == "spam", "기존 행 불변(재신고가 덮어쓰지 않음)"
        ok("재신고 204 · 행 1개 · 기존 내용 불변")

        step("7. 레이스 — B→A 동시 2발 → 둘 다 204 + 행 정확히 1개")
        async def burst():
            async with httpx.AsyncClient(timeout=30) as ac:
                async def one():
                    return await ac.post(f"{BASE}/reports",
                                         headers={"Authorization": f"Bearer {tk['b']}"},
                                         json={"target_type": "user", "target_id": uids["a"],
                                               "reason": "impersonation"})
                return await asyncio.gather(one(), one(), return_exceptions=True)
        results = asyncio.run(burst())
        codes = [r.status_code for r in results if not isinstance(r, Exception)]
        assert codes == [204, 204], f"동시 2발 둘 다 204, got {codes}"
        rows_ba = db_reports(c, uids["b"], uids["a"])
        assert len(rows_ba) == 1, f"부분 유니크 불변식: 행 1개, got {len(rows_ba)}"
        report_ba = rows_ba[0]["id"]
        ok("동시 2발 → 204×2 · pending 정확히 1행 (TOCTOU DB 봉쇄)")

        step("8. admin 조회 — 운영진 200+brief / 비운영진 404")
        r = api(c, "GET", "/admin/reports", adm_tok, params={"status": "pending", "limit": "100"})
        assert r.status_code == 200, f"운영진 200, got {r.status_code}: {r.text[:150]}"
        items = {x["id"]: x for x in r.json()}
        assert report_ab in items, "A→B 신고가 목록에"
        it = items[report_ab]
        assert it["reporter"]["user_id"] == uids["a"] and it["reporter"]["nickname"], "reporter brief"
        assert it["target"]["user_id"] == uids["b"] and it["target"]["nickname"], "target brief"
        assert it["reason"] == "spam" and it["status"] == "pending"
        # 비운영진 → 404 은닉
        assert api(c, "GET", "/admin/reports", tk["a"]).status_code == 404, "비운영진 404"
        ok("운영진 200 + reporter/target brief · 비운영진 404 은닉")

        step("9. PATCH 처리 — reviewed/dismissed 단방향")
        r = api(c, "PATCH", f"/admin/reports/{report_ab}", adm_tok, json={"status": "reviewed"})
        assert r.status_code == 204, f"reviewed 204, got {r.status_code}: {r.text[:150]}"
        row = db_reports(c, uids["a"], uids["b"])[0]
        assert row["status"] == "reviewed" and row["reviewed_at"], f"status·reviewed_at 기록, got {row}"
        # pending 목록에서 빠짐
        r = api(c, "GET", "/admin/reports", adm_tok, params={"status": "pending", "limit": "100"})
        assert report_ab not in {x["id"] for x in r.json()}, "처리 후 pending에서 제외"
        # 재처리(이미 reviewed) → 404
        assert api(c, "PATCH", f"/admin/reports/{report_ab}", adm_tok,
                   json={"status": "dismissed"}).status_code == 404, "이미 처리됨 404"
        # pending 되돌리기 → 422 (Literal 밖)
        assert api(c, "PATCH", f"/admin/reports/{report_ba}", adm_tok,
                   json={"status": "pending"}).status_code == 422, "되돌리기 422"
        # dismissed 정상
        assert api(c, "PATCH", f"/admin/reports/{report_ba}", adm_tok,
                   json={"status": "dismissed"}).status_code == 204
        assert db_reports(c, uids["b"], uids["a"])[0]["status"] == "dismissed"
        # 비운영진 PATCH → 404
        assert api(c, "PATCH", f"/admin/reports/{report_ba}", tk["a"],
                   json={"status": "reviewed"}).status_code == 404, "비운영진 PATCH 404"
        # 없는 id → 404
        assert api(c, "PATCH", f"/admin/reports/{ghost}", adm_tok,
                   json={"status": "reviewed"}).status_code == 404, "없는 id 404"
        ok("reviewed 204+reviewed_at · 재처리 404 · 되돌리기 422 · dismissed 204 · 비운영진 404")

        step("11. run 신고 — B의 public run(A 비팔로우) → 204 + 행 / 멱등 / 자기 run 400")
        r = api(c, "POST", "/runs", tk["b"],
                json={"distance_km": 5.0, "duration_sec": 1800,
                      "title": f"공개런{TS}", "visibility": "public"})
        assert r.status_code == 200, f"run 생성, got {r.status_code}: {r.text[:150]}"
        run_pub = r.json()["id"]
        r = api(c, "POST", "/runs", tk["b"],
                json={"distance_km": 3.0, "duration_sec": 1200, "visibility": "private"})
        assert r.status_code == 200
        run_priv = r.json()["id"]
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "run", "target_id": run_pub,
                      "reason": "inappropriate", "detail": "부적절한 기록 같아요"})
        assert r.status_code == 204, f"run 신고 204, got {r.status_code}: {r.text[:150]}"
        rows = db_reports(c, uids["a"], run_pub)
        assert len(rows) == 1 and rows[0]["status"] == "pending", f"run 신고 행 1개, got {rows}"
        report_run = rows[0]["id"]
        # 중복 pending 멱등 — 부분 유니크 (reporter, target_type, target_id) 타입 무관 적용
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "run", "target_id": run_pub, "reason": "spam"})
        assert r.status_code == 204, f"재신고 멱등 204, got {r.status_code}"
        assert len(db_reports(c, uids["a"], run_pub)) == 1, "멱등 1행 유지"
        # 자기 run 신고 → 400 (user self 선례)
        r = api(c, "POST", "/reports", tk["b"],
                json={"target_type": "run", "target_id": run_pub, "reason": "spam"})
        assert r.status_code == 400, f"자기 run 400, got {r.status_code}"
        ok("public run 신고 204·행 생성 · 중복 멱등 1행 · 자기 run 400")

        step("12. 비가시 run — B의 private run(A) 404 은닉 / 없는 run 404")
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "run", "target_id": run_priv, "reason": "spam"})
        assert r.status_code == 404, f"private run 404 은닉, got {r.status_code}"
        assert db_reports(c, uids["a"], run_priv) == [], "행 미생성"
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "run", "target_id": ghost, "reason": "spam"})
        assert r.status_code == 404, f"없는 run 404, got {r.status_code}"
        ok("private run 404 은닉·행 미생성 · 없는 run 404")

        step("13. 차단 소유자(C)의 public run → 404 은닉 + 행 미생성")
        r = api(c, "POST", "/runs", tk["cc"],
                json={"distance_km": 4.0, "duration_sec": 1500, "visibility": "public"})
        assert r.status_code == 200
        run_cc = r.json()["id"]
        assert api(c, "POST", f"/users/{uids['cc']}/block", tk["a"]).status_code == 204
        r = api(c, "POST", "/reports", tk["a"],
                json={"target_type": "run", "target_id": run_cc, "reason": "abuse"})
        assert r.status_code == 404, f"차단 소유자 run 404, got {r.status_code}"
        assert db_reports(c, uids["a"], run_cc) == [], "행 미생성"
        api(c, "DELETE", f"/users/{uids['cc']}/block", tk["a"])  # 원복
        ok("차단 소유자 run 404 은닉 · 행 미생성")

        step("14. admin 조회 run brief + run 삭제 후 잔존 처리")
        r = api(c, "GET", "/admin/reports", adm_tok, params={"status": "pending", "limit": "100"})
        assert r.status_code == 200, f"운영진 200, got {r.status_code}: {r.text[:150]}"
        items = {x["id"]: x for x in r.json()}
        assert report_run in items, "run 신고가 목록에"
        it = items[report_run]
        assert it["target_type"] == "run" and it["target"] is None, "run 신고는 target(user) null"
        tr = it["target_run"]
        assert tr and tr["run_id"] == run_pub and tr["title"] == f"공개런{TS}", f"target_run brief, got {tr}"
        assert tr["owner"]["user_id"] == uids["b"] and tr["owner"]["nickname"], "owner brief"
        assert all(x.get("target_run") is None for x in r.json()
                   if x["target_type"] == "user"), "user 신고는 target_run null(회귀)"
        # run 삭제 → 신고 행 잔존(폴리모픽 FK 없음) + admin 조회 안 깨짐 + brief null
        assert api(c, "DELETE", f"/runs/{run_pub}", tk["b"]).status_code == 204, "run 삭제"
        r = api(c, "GET", "/admin/reports", adm_tok, params={"status": "pending", "limit": "100"})
        assert r.status_code == 200, f"삭제 후 admin 조회 200, got {r.status_code}: {r.text[:150]}"
        items = {x["id"]: x for x in r.json()}
        assert report_run in items, "신고 행 잔존"
        assert items[report_run]["target_run"] is None, "삭제된 run은 target_run null"
        assert items[report_run]["target_id"] == run_pub, "target_id 원본 보존"
        ok("target_run brief(제목·owner) · run 삭제 후 200·행 잔존·brief null")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        if proc:
            proc.terminate()
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (8002 종료 · reports는 reporter_id FK cascade)")


if __name__ == "__main__":
    run_tests()
