"""
Integration test: IAP 구독 검증 + tier 전환 (전부 mock 모드 — Apple 실호출 0)
1) mock 서버(8002, IAP_MODE=mock): verify→전환→멱등→위조 400→재사용 409→
   만료 lazy 강등→갱신 복귀→admin premium 보호→웹훅 raw 저장
2) 안전장치: production+mock 부팅 거부 / 본 서버(apple 모드) 503
Run: python tests/test_iap_integration.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"       # 본 서버 (apple 모드)
MOCK = "http://localhost:8002/api"       # mock 모드 서버 (이 테스트가 기동)
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
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


def ok(m):
    print(f"  ✓ {m}")


def fail(m, d=""):
    print(f"  ✗ {m}" + (f": {d}" if d else ""))
    sys.exit(1)


def step(t):
    print(f"\n[{t}]")


def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201):
        fail("create user", r.text[:200])
    return r.json()["id"]


def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200:
        fail("login", r.text[:200])
    return r.json()["access_token"]


def sb_del_user(c, uid):
    c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)


def sb_del_in(c, table, col, vals):
    if not vals:
        return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})


def api(c, base, method, path, tok, **kw):
    return c.request(method, f"{base}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


def iso_in(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def start_server(port: int, env_extra: dict) -> subprocess.Popen:
    env = {**os.environ, **env_extra}
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def wait_up(port: int, timeout_s: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://localhost:{port}/docs", timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


# ═══ Phase 1: 안전장치 ═══════════════════════════════════════════════════════

def phase1_guards(c, tok_free):
    step("1-1. production + IAP_MODE=mock → 부팅 거부")
    proc = start_server(8003, {"IAP_MODE": "mock", "ENVIRONMENT": "production"})
    try:
        deadline = time.monotonic() + 15
        exited = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                exited = True
                break
            time.sleep(0.5)
        assert exited and proc.returncode != 0, \
            "production+mock 조합은 부팅이 거부돼야 함"
        try:
            httpx.get("http://localhost:8003/docs", timeout=2)
            fail("8003이 응답하면 안 됨")
        except httpx.HTTPError:
            pass
    finally:
        if proc.poll() is None:
            proc.kill()
    ok("RuntimeError로 기동 실패 (returncode != 0) ✓ 포트 미개방 ✓")

    step("1-2. 본 서버(8000, IAP_MODE 미설정=apple) → 503 iap_not_configured")
    r = api(c, BASE, "POST", "/iap/verify", tok_free,
            json={"jws": "a.b.c"})
    assert r.status_code == 503, r.text[:200]
    assert r.json()["detail"]["error"] == "iap_not_configured"
    # jws 없이 → 400 (apple 모드 페이로드 검증이 503보다 먼저)
    r = api(c, BASE, "POST", "/iap/verify", tok_free, json={})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "invalid_transaction"
    ok("apple 모드 503 ✓ jws 누락 400 ✓ (기본값이 안전하게 닫힘)")


# ═══ Phase 2: mock 모드 전체 흐름 ═════════════════════════════════════════════

def phase2(c, uids, toks):
    uid1, uid2, uid3 = uids
    tok1, tok2, tok3 = toks

    def verify(tok, otid, days=30.0, product="freshrun.premium.monthly", base=MOCK):
        return api(c, base, "POST", "/iap/verify", tok, json={
            "mock": {"original_transaction_id": otid, "product_id": product,
                     "expires_at": iso_in(days)}})

    def quota_tier(tok):
        return api(c, MOCK, "GET", "/me/quota", tok).json()["tier"]

    step("2-1. verify 성공 → tier 전환 + 만료일 저장")
    assert quota_tier(tok1) == "free"
    r = verify(tok1, f"mock-tx-{uids[0][:8]}")
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["tier"] == "premium" and d["environment"] == "mock"
    assert d["product_id"] == "freshrun.premium.monthly" and d["expires_at"]
    assert quota_tier(tok1) == "premium"
    rows = c.get(f"{_SB}/rest/v1/subscriptions", headers=_ADM,
                 params={"user_id": f"eq.{uid1}", "select": "status,expires_at,environment"}).json()
    assert len(rows) == 1 and rows[0]["status"] == "active" and rows[0]["environment"] == "mock"
    ok("200 premium ✓ 구독 행 active ✓ /me/quota tier 반영 ✓")

    step("2-2. 같은 거래 재전송 → 멱등 (갱신 거래는 연장)")
    r = verify(tok1, f"mock-tx-{uids[0][:8]}", days=60.0)
    assert r.status_code == 200, "같은 유저의 재검증은 멱등이어야 함"
    rows = c.get(f"{_SB}/rest/v1/subscriptions", headers=_ADM,
                 params={"user_id": f"eq.{uid1}", "select": "expires_at"}).json()
    exp = datetime.fromisoformat(rows[0]["expires_at"])
    assert exp > datetime.now(timezone.utc) + timedelta(days=45), "만료 연장 반영"
    ok("재전송 200 멱등 ✓ 만료 연장 ✓")

    step("2-3. 위조/불량 페이로드 → 400")
    r = api(c, MOCK, "POST", "/iap/verify", tok2, json={"jws": "x.y.z"})  # mock 모드에 jws만
    assert r.status_code == 400 and r.json()["detail"]["error"] == "invalid_transaction"
    r = api(c, MOCK, "POST", "/iap/verify", tok2, json={
        "mock": {"original_transaction_id": "t", "product_id": "p",
                 "expires_at": "어제쯤"}})
    assert r.status_code == 400, "ISO 아님 → 400"
    r = api(c, MOCK, "POST", "/iap/verify", tok2, json={
        "mock": {"original_transaction_id": "t", "product_id": "p",
                 "expires_at": "2026-01-01T00:00:00"}})
    assert r.status_code == 400, "타임존 없음 → 400"
    r = api(c, MOCK, "POST", "/iap/verify", tok2, json={
        "mock": {"original_transaction_id": "t", "product_id": "p",
                 "expires_at": iso_in(-1)}})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "transaction_expired"
    r = api(c, MOCK, "POST", "/iap/verify", tok2, json={
        "mock": {"original_transaction_id": "t", "product_id": "p",
                 "expires_at": iso_in(1), "extra": 1}})
    assert r.status_code == 422, "화이트리스트 밖 키 → 422"
    ok("jws-only 400 ✓ 비ISO 400 ✓ 타임존 400 ✓ 만료 거래 400 ✓ 잉여 키 422 ✓")

    step("2-4. 재사용 공격: 다른 유저가 같은 거래 → 409")
    r = verify(tok2, f"mock-tx-{uids[0][:8]}")
    assert r.status_code == 409, r.text[:200]
    assert r.json()["detail"]["error"] == "transaction_already_used"
    assert quota_tier(tok2) == "free", "공격자는 free 유지"
    ok("409 transaction_already_used ✓ tier 미전환 ✓")

    step("2-5. 만료 → lazy 강등 → 프리미엄 게이트 403")
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = c.patch(f"{_SB}/rest/v1/subscriptions", headers=_ADM,
                params={"user_id": f"eq.{uid1}"}, json={"expires_at": past})
    assert r.status_code in (200, 204)
    assert quota_tier(tok1) == "free", "만료 후 첫 게이트 통과 시 강등"
    rows = c.get(f"{_SB}/rest/v1/subscriptions", headers=_ADM,
                 params={"user_id": f"eq.{uid1}", "select": "status"}).json()
    assert rows[0]["status"] == "expired"
    r = api(c, MOCK, "GET", "/me/insights/monthly", tok1,
            params={"year": 2026, "month": 6})
    assert r.status_code == 403 and r.json()["detail"]["error"] == "premium_required"
    ok("tier free 강등 ✓ status expired ✓ 인사이트 403 ✓")

    step("2-6. 갱신 verify → premium 복귀")
    r = verify(tok1, f"mock-tx-renew-{uids[0][:8]}", days=30.0)
    assert r.status_code == 200
    assert quota_tier(tok1) == "premium"
    # PK=거래 id라 재구독은 새 행 — 이력 2행 (expired + active)
    rows = c.get(f"{_SB}/rest/v1/subscriptions", headers=_ADM,
                 params={"user_id": f"eq.{uid1}", "select": "status"}).json()
    assert sorted(x["status"] for x in rows) == ["active", "expired"], rows
    ok("재구독 → 새 active 행 + premium 복귀 ✓ (이력 보존)")

    step("2-7. admin premium 보호 (구독 행 없는 premium — test1 패턴)")
    r = c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM,
                params={"user_id": f"eq.{uid3}"}, json={"tier": "premium"})
    assert r.status_code in (200, 204)
    assert quota_tier(tok3) == "premium", "구독 행 없는 premium은 강등 금지"
    assert quota_tier(tok3) == "premium", "반복 호출에도 유지"
    ok("admin 부여 premium 유지 ✓ (lazy 훅이 안 건드림)")

    step("2-8. 웹훅 골격: 수신 → raw 저장 → 200")
    marker = f"h.{int(time.time())}payload.sig"  # JWS 형태 (3세그먼트)
    r = c.post(f"{MOCK}/iap/notifications", json={"signedPayload": marker})
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    rows = c.get(f"{_SB}/rest/v1/iap_notifications_raw", headers=_ADM,
                 params={"payload->>signedPayload": f"eq.{marker}",
                         "select": "processed"}).json()
    assert len(rows) == 1 and rows[0]["processed"] is False
    # JWS 형태 아님 → 저장 안 하지만 200 (Apple 재시도 방지)
    r = c.post(f"{MOCK}/iap/notifications", json={"signedPayload": "not-a-jws"})
    assert r.status_code == 200
    r = c.post(f"{MOCK}/iap/notifications", json={})
    assert r.status_code == 200
    ok("raw 저장 (processed=false) ✓ 비정상 페이로드도 200 ✓")


def run():
    ts = int(time.time())
    pw = "TestPass123!"
    emails = [f"iap-u{i}-{ts}@t.l" for i in range(1, 4)]
    uids: list[str] = []
    mock_proc = None

    with httpx.Client(timeout=30) as c:
        try:
            step("공용: 유저 3명 + mock 모드 서버(8002) 기동")
            toks = []
            for i, e in enumerate(emails, start=1):
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
                r = api(c, BASE, "PATCH", "/me/profile", toks[-1],
                        json={"nickname": f"결제u{i}-{ts % 100000}"})
                assert r.status_code == 200, r.text[:200]
            mock_proc = start_server(8002, {"IAP_MODE": "mock"})
            assert wait_up(8002), "mock 서버(8002) 기동 실패"
            ok("유저 3명 + 8002 (IAP_MODE=mock) 기동")

            phase1_guards(c, toks[0])
            phase2(c, uids, toks)

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            if mock_proc is not None:
                mock_proc.terminate()
                try:
                    mock_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    mock_proc.kill()
            sb_del_in(c, "subscriptions", "user_id", uids)
            c.delete(f"{_SB}/rest/v1/iap_notifications_raw",
                     headers={**_ADM, "Prefer": "return=minimal"},
                     params={"payload->>signedPayload": "like.h.*"})
            sb_del_in(c, "profiles", "user_id", uids)
            for uid in uids:
                sb_del_user(c, uid)
            ok("mock 서버 종료 · iap 데이터·profiles·auth users 삭제")


if __name__ == "__main__":
    run()
