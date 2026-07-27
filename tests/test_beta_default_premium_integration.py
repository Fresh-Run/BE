"""
Integration: 베타 신규 가입 기본 premium (BETA_DEFAULT_PREMIUM, 2026-07-27)

플래그 ON: 프로필 최초 생성 시 tier=premium / OFF: 컬럼 default(free) /
기존 유저 재PATCH는 tier 불변. 임시 유저 2명 생성→종료 시 전량 삭제.

Run: python tests/test_beta_default_premium_integration.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.models.schemas import ProfileUpdate  # noqa: E402
from app.services import profile_service, quota_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_created: list[str] = []


def ok(m):
    print(f"  ✓ {m}")


def _adm():
    key = settings.supabase_service_role_key
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def make_user(tag: str) -> str:
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"bdp-{tag}-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    uid = r.json()["id"]
    _created.append(uid)
    return uid


def tier_of(uid: str) -> str | None:
    rows = get_supabase_admin().table("profiles").select("tier") \
        .eq("user_id", uid).execute().data
    return rows[0]["tier"] if rows else None


async def main():
    print("[1. 플래그 ON — 최초 생성 시 premium]")
    u1 = make_user("on")
    settings.beta_default_premium = True
    try:
        await profile_service.upsert_profile(u1, ProfileUpdate(nickname=f"베타온{TS}"))
    finally:
        settings.beta_default_premium = False
    assert tier_of(u1) == "premium", tier_of(u1)
    assert await quota_service.get_tier(u1) == "premium", "get_tier 경유도 premium(구독 행 없음 유지)"
    ok("최초 생성 premium + get_tier premium(lazy 강등 무발동 — test1 전례 경로)")

    print("\n[2. 플래그 OFF — 최초 생성 시 free(컬럼 default)]")
    u2 = make_user("off")
    assert settings.beta_default_premium is False
    await profile_service.upsert_profile(u2, ProfileUpdate(nickname=f"베타오프{TS}"))
    assert tier_of(u2) == "free", tier_of(u2)
    ok("플래그 OFF 신규는 free — 출시기 원복 구조 확인")

    print("\n[3. 기존 유저 무영향 — 재PATCH가 tier를 안 만짐]")
    settings.beta_default_premium = True
    try:
        await profile_service.upsert_profile(u2, ProfileUpdate(bio="갱신 테스트"))
    finally:
        settings.beta_default_premium = False
    assert tier_of(u2) == "free", "갱신 분기에서 tier 변경 금지"
    ok("기존 행(free) 재PATCH 후에도 free 유지 — 승급은 최초 생성 시점만")


def cleanup():
    sb = get_supabase_admin()
    for uid in _created:
        sb.table("profiles").delete().eq("user_id", uid).execute()
        httpx.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_adm(), timeout=30)
    left = sum(1 for uid in _created
               if sb.table("profiles").select("user_id").eq("user_id", uid).execute().data)
    assert left == 0, f"정리 후 잔여 프로필 {left}"
    print(f"\n[cleanup] 임시 유저 {len(_created)}명·프로필 삭제 완료(잔여 0)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
