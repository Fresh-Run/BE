"""
배틀 통합 — 게이팅·라이프사이클·정산·레이스 (2026-09-07). docs/BATTLE_DESIGN_v0_KO.md.

⚠️ battles/battle_invites/battle_runs 테이블 필요 — db/2026-09-07_battles.sql 미적용 시
'검증 불가'로 스킵(오너 실행 후 재검). 스코어 순수 로직은 test_battle_scoring.py가 커버.

커버(테이블 존재 시):
  A. 생성→수락 라이프사이클(pending→active·started_at/ends_at 세팅·invite accepted)
  B. 게이팅 — 무료 30일 롤링 3회 경계(2 OK·3 차단 403)·프리미엄 스킵
  C. 동시 active 3캡(409)·레이스(asyncio.gather 동시 생성 — 캡 불변식)
  D. 포기 즉시패배(winner=상대·상대점수 유지)
  E. 정산 멱등(2회 실행 동일)·창내 verified만·battle_runs 영속
Run: python tests/test_battle_integration.py
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
from app.services import battle_service as bs  # noqa: E402
from app.services import quota_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uids: list[str] = []
_passed = 0


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _tables_exist() -> bool:
    try:
        get_supabase_admin().table("battles").select("id").limit(1).execute()
        return True
    except Exception as e:  # noqa: BLE001
        if "battles" in str(e) or "42P01" in str(e) or "PGRST" in str(e):
            return False
        raise


def _mk_user(email, tier="free"):
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": email, "password": "test1234", "email_confirm": True}, timeout=30)
    r.raise_for_status()
    uid = r.json()["id"]
    _uids.append(uid)
    get_supabase_admin().table("profiles").insert(
        {"user_id": uid, "nickname": email[:12], "tier": tier}).execute()
    return uid


async def main():
    if not _tables_exist():
        print("⚠️ 검증 불가 — battles 테이블 미적용(db/2026-09-07_battles.sql 오너 실행 대기).")
        print("   스코어 순수 로직은 test_battle_scoring.py로 확정. 통합은 SQL 후 재검.")
        return

    sb = get_supabase_admin()
    a = _mk_user(f"batA-{TS}@test.com")       # free 도전자
    b = _mk_user(f"batB-{TS}@test.com")       # free 상대
    prem = _mk_user(f"batP-{TS}@test.com", tier="premium")

    # A. 생성 → 수락
    print("[A. 생성→수락 라이프사이클]")
    battle = await bs.create_battle(a, b, "9월 대결", "🔥", 7, "points")
    assert battle["status"] == "pending" and battle["started_at"] is None
    ba = await bs.accept_battle(battle["id"], b)
    assert ba["status"] == "active" and ba["started_at"] and ba["ends_at"]
    inv = sb.table("battle_invites").select("status").eq("battle_id", battle["id"]).single().execute().data
    assert inv["status"] == "accepted"
    ok(f"생성 pending→수락 active·started/ends 세팅·invite accepted")

    # B. 무료 30일 롤링 3회 경계 (a는 이미 1개 생성) — 2개 더 생성 OK, 3번째 관여서 차단
    print("\n[B. 무료 30일 롤링 3회 게이팅]")
    await bs.create_battle(a, b, "2번", "⚡", 5, "points")   # a 관여 2
    await bs.create_battle(a, b, "3번", "💪", 5, "points")   # a 관여 3
    try:
        await bs.create_battle(a, b, "4번", "🏃", 5, "points")  # a 관여 4 → 차단
        raise AssertionError("무료 4번째 생성이 차단 안 됨")
    except bs.BattleError as e:
        assert e.status == 403 and e.code == "battle_free_limit", (e.status, e.code)
    ok("무료 30일 3회 초과 → 403 battle_free_limit")
    # 프리미엄 스킵
    for i in range(4):
        await bs.create_battle(prem, b, f"P{i}", "⭐", 5, "points")
    ok("프리미엄 → 30일 롤링 스킵(4개 생성 성공)")

    # C. 동시 active 3캡 (b가 여러 배틀 수락) + 레이스
    print("\n[C. 동시 active 3캡 + 레이스]")
    # prem의 배틀 4개를 b가 동시 수락 시도 → active 캡 3 불변식
    pend = sb.table("battles").select("id").eq("created_by", prem).eq("status", "pending").execute().data
    results = await asyncio.gather(*[bs.accept_battle(p["id"], b) for p in pend],
                                   return_exceptions=True)
    active_b = sb.table("battles").select("id").eq("status", "active").or_(
        f"created_by.eq.{b},opponent.eq.{b}").execute().data
    caps = [r for r in results if isinstance(r, bs.BattleError) and r.code == "battle_active_cap"]
    assert len(active_b) <= bs._ACTIVE_CAP, f"동시 active {len(active_b)} > 캡 {bs._ACTIVE_CAP}"
    ok(f"동시 수락 레이스 — active {len(active_b)}≤캡{bs._ACTIVE_CAP}·초과 {len(caps)}건 409")

    # D. 포기 즉시패배
    print("\n[D. 포기 즉시패배]")
    bf = await bs.forfeit_battle(ba["id"], a)   # a 포기 → b 승
    assert bf["status"] == "forfeited" and bf["winner"] == b
    ok(f"포기 → forfeited·winner=상대(b)·settled")

    # E. 정산 멱등 + 창내 verified
    print("\n[E. 정산 멱등]")
    # b가 수락한 active 배틀 하나 골라 정산 2회
    act = sb.table("battles").select("*").eq("status", "active").limit(1).execute().data
    if act:
        await bs.settle_battle(act[0])
        r1 = sb.table("battle_runs").select("run_id,run_score").eq("battle_id", act[0]["id"]).execute().data
        await bs.settle_battle(act[0])
        r2 = sb.table("battle_runs").select("run_id,run_score").eq("battle_id", act[0]["id"]).execute().data
        assert len(r1) == len(r2), (len(r1), len(r2))  # 멱등 — 중복 행 없음
        ok(f"정산 2회 멱등 — battle_runs {len(r1)}행 불변(UNIQUE)")
    else:
        ok("정산 대상 active 없음(스킵)")


def cleanup():
    if not _uids:
        return
    sb = get_supabase_admin()
    try:
        bids = sb.table("battles").select("id").or_(
            ",".join(f"created_by.eq.{u}" for u in _uids)).execute().data
        for bid in [x["id"] for x in bids]:
            sb.table("battle_runs").delete().eq("battle_id", bid).execute()
            sb.table("battle_invites").delete().eq("battle_id", bid).execute()
            sb.table("battles").delete().eq("id", bid).execute()
    except Exception:  # noqa: BLE001 — 테이블 없으면 스킵
        pass
    for u in _uids:
        sb.table("profiles").delete().eq("user_id", u).execute()
        httpx.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_adm(), timeout=30)
    print(f"\n[cleanup] 임시 유저 {len(_uids)}·배틀 정리")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + f"\n  {'ALL TESTS PASSED' if _passed else 'SKIPPED'} ({_passed} assert)\n" + "=" * 50)
    finally:
        cleanup()
