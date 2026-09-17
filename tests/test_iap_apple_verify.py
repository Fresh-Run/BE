"""
IAP Track B — apple 모드 검증 + 웹훅 (2026-08-27, 실 크리덴셜 불요)

SignedDataVerifier 서명 검증(크립토)은 라이브러리 몫이라 실 Sandbox 검증은 Track A 후
별도. 이 테스트는 **디코드 이후 로직**을 검증 — verifier decode를 fake로 주입해:
  A. 구성 가드 — root CA 번들·sandbox verifier 생성·prod app_apple_id 필수·mock 부팅거부
  B. 검증 매핑 → premium — 유효 JWS→subscriptions active+profiles premium·환경 분기
  C. 웹훅 4타입 — DID_RENEW 연장·EXPIRED lazy 강등·REFUND/REVOKE 즉시 강등
  D. 재처리 멱등 — processed=false 재처리→processed=true, 재실행 무해
임시 유저·구독·알림 전량 정리. Run: python tests/test_iap_apple_verify.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.models.schemas import IapVerifyRequest  # noqa: E402
from app.services import iap_apple, iap_service, quota_service  # noqa: E402
# 리팩터(2026-09-17): 애플 검증/디코드 내부 helper는 iap_apple로 이동. 공개 API
# (verify_purchase·store_notification·reprocess_unprocessed·예외)는 iap_service가
# re-export하므로 그대로 호출 — 아래 monkeypatch만 iap_apple로 경로 이동(동작 assert 불변).

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None
_otids: list[str] = []
_raw_ids: list[str] = []
_passed = 0


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _ms(days: float) -> int:
    return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp() * 1000)


# ── fake 디코드 결과(verifier decode 대체) ──────────────────────────────
class FakeTx:
    def __init__(self, otid, expires_ms, pid="premium.monthly", txid=None, env="Sandbox"):
        self.originalTransactionId = otid
        self.productId = pid
        self.expiresDate = expires_ms
        self.transactionId = txid or otid
        self.rawEnvironment = env
        self.environment = None


class _FakeData:
    def __init__(self, tx_jws):
        self.signedTransactionInfo = tx_jws


class FakeNotif:
    def __init__(self, ntype, tx_jws="t.x.j"):
        self.rawNotificationType = ntype
        self.notificationType = None
        self.data = _FakeData(tx_jws)


def _patch_tx(tx: FakeTx):
    iap_apple._verify_signed_transaction = lambda jws: tx


def _patch_notif(notif: FakeNotif, tx: FakeTx):
    iap_apple._verify_notification = lambda sp: notif
    iap_apple._verify_signed_transaction = lambda jws: tx


def _restore():
    import importlib
    importlib.reload(iap_apple)  # 패치된 helper 원본 복원(이제 iap_apple 소유)


def _sub(otid):
    return get_supabase_admin().table("subscriptions").select("*").eq(
        "original_transaction_id", otid).single().execute().data


def _tier_db():
    return get_supabase_admin().table("profiles").select("tier").eq(
        "user_id", _uid).single().execute().data["tier"]


def _reset_subs():
    sb = get_supabase_admin()
    sb.table("subscriptions").delete().eq("user_id", _uid).execute()
    sb.table("profiles").update({"tier": "free"}).eq("user_id", _uid).execute()


# ── A. 구성 가드 (무DB) ─────────────────────────────────────────────────
def guard_tests():
    print("[A. 구성 가드]")
    assert len(iap_apple._apple_root_cas()) >= 1
    ok(f"Apple Root CA 번들 로드({len(iap_apple._apple_root_cas())}개)")

    v = iap_apple._verifier("sandbox")   # bundle_id만으로 생성(app_apple_id 불요)
    assert v is not None
    ok("sandbox verifier 생성(app_apple_id 없이 — 출시 전 Sandbox 가능)")

    # prod는 app_apple_id 필수 — 미설정(Track A 전)이면 IapNotConfigured
    assert settings.appstore_app_apple_id is None
    try:
        iap_apple._verifier("production")
        raise AssertionError("prod verifier가 app_apple_id 없이 생성됨")
    except iap_service.IapNotConfigured:   # facade re-export = iap_common.IapNotConfigured 동일 객체
        ok("production verifier → IapNotConfigured(app_apple_id 필수·503 safe)")

    # 안전장치 ③: production+mock 요청 거부
    orig = (settings.iap_mode, settings.environment)
    try:
        settings.iap_mode, settings.environment = "mock", "production"
        assert iap_apple._mock_allowed() is False
    finally:
        settings.iap_mode, settings.environment = orig
    ok("production+mock 조합 거부(_mock_allowed=False, 부팅거부 ①과 이중)")


# ── B. 검증 → premium ───────────────────────────────────────────────────
async def verify_tests():
    print("\n[B. 검증 매핑 → premium]")
    assert settings.iap_mode == "apple", "테스트는 apple 모드 전제"
    otid = f"sandbox-{TS}-A"
    _otids.append(otid)
    _patch_tx(FakeTx(otid, _ms(30), env="Sandbox"))
    resp = await iap_service.verify_purchase(_uid, IapVerifyRequest(jws="a.b.c"))
    assert resp.tier == "premium" and resp.environment == "sandbox", (resp.tier, resp.environment)
    sub = _sub(otid)
    assert sub["status"] == "active" and sub["environment"] == "sandbox"
    assert _tier_db() == "premium"
    ok(f"유효 JWS→premium·subscriptions active·profiles premium·env=sandbox")

    # 환경 분기 — Production 거래
    otid2 = f"prod-{TS}-A"
    _otids.append(otid2)
    _patch_tx(FakeTx(otid2, _ms(30), env="Production"))
    resp2 = await iap_service.verify_purchase(_uid, IapVerifyRequest(jws="a.b.c"))
    assert resp2.environment == "production", resp2.environment
    ok("환경 분기 — Production 거래→environment=production")
    _reset_subs()


# ── C. 웹훅 4타입 ───────────────────────────────────────────────────────
async def _seed_active(otid, days=30):
    _otids.append(otid)
    _patch_tx(FakeTx(otid, _ms(days), env="Sandbox"))
    await iap_service.verify_purchase(_uid, IapVerifyRequest(jws="a.b.c"))


async def webhook_tests():
    print("\n[C. 웹훅 4타입]")

    # DID_RENEW → 만료 연장·active 유지
    _reset_subs()
    otid = f"renew-{TS}"
    await _seed_active(otid, days=10)
    old_exp = _sub(otid)["expires_at"]
    _patch_notif(FakeNotif("DID_RENEW"), FakeTx(otid, _ms(40), env="Sandbox"))
    await iap_service.store_notification("h.p.s")
    sub = _sub(otid)
    assert sub["status"] == "active" and sub["expires_at"] > old_exp, sub
    ok(f"DID_RENEW → 만료 연장({old_exp[:10]}→{sub['expires_at'][:10]})·active")

    # EXPIRED → status=expired + lazy 강등
    _reset_subs()
    otid = f"exp-{TS}"
    await _seed_active(otid)
    _patch_notif(FakeNotif("EXPIRED"), FakeTx(otid, _ms(-1), env="Sandbox"))
    await iap_service.store_notification("h.p.s")
    assert _sub(otid)["status"] == "expired"
    assert _tier_db() == "premium"  # 아직 DB는 premium(즉시 강등 아님)
    assert await quota_service.get_tier(_uid) == "free"  # lazy 훅이 강등
    ok("EXPIRED → status=expired·lazy 훅(get_tier)에서 free 강등")

    # REFUND → status=revoked + 즉시 강등
    _reset_subs()
    otid = f"refund-{TS}"
    await _seed_active(otid)
    _patch_notif(FakeNotif("REFUND"), FakeTx(otid, _ms(30), env="Sandbox"))
    await iap_service.store_notification("h.p.s")
    assert _sub(otid)["status"] == "revoked"
    assert _tier_db() == "free"  # 즉시 강등(lazy 대기 없이)
    ok("REFUND → status=revoked·즉시 tier=free(DB 직접)")

    # REVOKE → status=revoked + 즉시 강등
    _reset_subs()
    otid = f"revoke-{TS}"
    await _seed_active(otid)
    _patch_notif(FakeNotif("REVOKE"), FakeTx(otid, _ms(30), env="Sandbox"))
    await iap_service.store_notification("h.p.s")
    assert _sub(otid)["status"] == "revoked" and _tier_db() == "free"
    ok("REVOKE → status=revoked·즉시 tier=free")


# ── D. 재처리 멱등 ──────────────────────────────────────────────────────
async def reprocess_tests():
    print("\n[D. 재처리 멱등]")
    _reset_subs()
    otid = f"reproc-{TS}"
    await _seed_active(otid, days=10)
    sb = get_supabase_admin()
    # processed=false raw 직접 적재(웹훅 수신했으나 검증 미구성으로 미처리됐던 상황 모사)
    ins = sb.table("iap_notifications_raw").insert(
        {"payload": {"signedPayload": "h.p.s"}, "processed": False}).execute()
    rid = ins.data[0]["id"]
    _raw_ids.append(rid)

    _patch_notif(FakeNotif("DID_RENEW"), FakeTx(otid, _ms(45), env="Sandbox"))
    done1 = await iap_service.reprocess_unprocessed()
    assert done1 >= 1
    row = sb.table("iap_notifications_raw").select("processed,notification_type").eq(
        "id", rid).single().execute().data
    assert row["processed"] is True and row["notification_type"] == "DID_RENEW"
    exp_after = _sub(otid)["expires_at"]
    ok(f"재처리 1회 — processed=true·type=DID_RENEW·구독 반영({done1}건)")

    # 재실행 — 미처리 0(멱등)·상태 불변
    done2 = await iap_service.reprocess_unprocessed()
    assert done2 == 0, f"재실행이 재처리함(멱등 위반): {done2}"
    assert _sub(otid)["expires_at"] == exp_after
    ok("재실행 — 미처리 0(멱등)·구독 상태 불변")


async def main():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"iapv-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    get_supabase_admin().table("profiles").insert(
        {"user_id": _uid, "nickname": f"iapv{TS}", "tier": "free"}).execute()

    guard_tests()
    try:
        await verify_tests()
        await webhook_tests()
        await reprocess_tests()
    finally:
        _restore()


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    if _raw_ids:
        sb.table("iap_notifications_raw").delete().in_("id", _raw_ids).execute()
    sb.table("subscriptions").delete().eq("user_id", _uid).execute()
    sb.table("profiles").delete().eq("user_id", _uid).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    left = sb.table("subscriptions").select("original_transaction_id").eq("user_id", _uid).execute().data
    assert not left, f"구독 잔여 {len(left)}"
    print(f"\n[cleanup] 구독·profiles·raw {len(_raw_ids)}·임시 유저 삭제(잔여 0)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_passed} assert)\n" + "=" * 50)
    finally:
        cleanup()
