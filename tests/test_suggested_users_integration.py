"""
Integration: GET /users/suggested 서비스 계약 (Ivan v1, 2026-07-28)

제외 3종(본인/팔로우/차단 양방향) · 잠금 bio null · limit 클램프 · 빈 결과 ·
회귀(유저 검색). 임시 유저 5명 생성→종료 시 관계·프로필·유저 전량 삭제.

Run: python tests/test_suggested_users_integration.py
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
from app.services import profile_service  # noqa: E402

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
                   json={"email": f"sg-{tag}-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    uid = r.json()["id"]
    _created.append(uid)
    return uid


async def main():
    sb = get_supabase_admin()
    # A=viewer, B=팔로우 대상, C=A가 차단, D=잠금(private)+bio, E=A를 차단
    A, B, C, D, E = (make_user(t) for t in "abcde")
    for uid, nick in ((A, f"sgA{TS}"), (B, f"sgB{TS}"), (C, f"sgC{TS}"),
                      (E, f"sgE{TS}")):
        await profile_service.upsert_profile(uid, ProfileUpdate(nickname=nick))
    await profile_service.upsert_profile(
        D, ProfileUpdate(nickname=f"sgD{TS}", bio="잠금계정 소개", visibility="private"))
    sb.table("follows").insert({"follower_id": A, "following_id": B}).execute()
    sb.table("blocks").insert([{"blocker_id": A, "blocked_id": C},
                               {"blocker_id": E, "blocked_id": A}]).execute()

    print("[1. 제외 3종 — 본인·팔로우·차단 양방향]")
    rows = await profile_service.suggested_users(A, limit=50)
    ids = {r["user_id"] for r in rows}
    assert A not in ids, "본인 제외"
    assert B not in ids, "팔로우 중 제외"
    assert C not in ids and E not in ids, "차단 양방향 제외"
    assert D in ids, "잠금 계정은 포함돼야(검색 계약 상속)"
    ok(f"본인·팔로우(B)·차단(C·E) 제외, 잠금(D) 포함 — 결과 {len(rows)}명")

    print("\n[2. 잠금 계정 bio null + 계약 필드]")
    d_row = next(r for r in rows if r["user_id"] == D)
    assert d_row["bio"] is None and d_row["nickname"] == f"sgD{TS}", d_row
    assert d_row["is_following"] is False and "area" in d_row and "public_run_count" in d_row
    ok("잠금 bio=null·닉네임 유지 · is_following=false · area/public_run_count 키 존재")

    print("\n[3. limit 클램프]")
    one = await profile_service.suggested_users(A, limit=1)
    assert len(one) == 1, len(one)
    big = await profile_service.suggested_users(A, limit=999)  # 내부 50 캡 — 에러 없이
    assert len(big) <= 50
    zero = await profile_service.suggested_users(A, limit=0)   # 하한 1
    assert len(zero) == 1
    ok(f"limit 1→1건 · 999→{len(big)}건(≤50) · 0→1건(하한)")

    print("\n[4. 빈 결과 — 전 후보 차단 경로]")
    _orig = profile_service.blocked_ids_batch

    async def _block_all(viewer_id, ids_):
        return set(ids_)

    profile_service.blocked_ids_batch = _block_all
    try:
        empty = await profile_service.suggested_users(A, limit=20)
    finally:
        profile_service.blocked_ids_batch = _orig
    assert empty == [], empty
    ok("후보 전멸 시 빈 배열(에러 없음)")

    print("\n[5. 회귀 — 유저 검색 계약 불변]")
    sr = await profile_service.search_users(A, f"sgD{TS}"[:6], limit=20)
    hit = [r for r in sr if r["user_id"] == D]
    assert hit and hit[0]["bio"] is None, sr
    assert all(r["user_id"] not in (C, E) for r in sr), "검색도 차단 제외 유지"
    ok("검색: 잠금 D bio null 포함·차단 제외 — 기존 계약 불변")


def cleanup():
    sb = get_supabase_admin()
    for uid in _created:
        sb.table("follows").delete().or_(
            f"follower_id.eq.{uid},following_id.eq.{uid}").execute()
        sb.table("blocks").delete().or_(
            f"blocker_id.eq.{uid},blocked_id.eq.{uid}").execute()
        sb.table("profiles").delete().eq("user_id", uid).execute()
        httpx.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_adm(), timeout=30)
    left = sum(1 for uid in _created
               if sb.table("profiles").select("user_id").eq("user_id", uid).execute().data)
    assert left == 0, f"잔여 프로필 {left}"
    print(f"\n[cleanup] 임시 유저 {len(_created)}명·관계·프로필 삭제 완료(잔여 0)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
