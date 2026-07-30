"""
Integration: runs.app_version (additive, 2026-07-31)

1. 미전송 → insert 성공(기존 클라 무영향 — 키 생략이라 컬럼 미적용 DB에서도 무해)
2. 전송 → 행에 그대로 저장 (컬럼 필요 — 미적용이면 명시적 대기 종료)
3. 65자 초과 → 422(ValidationError, max_length=64)
4. 컬럼 적용 후 미전송 행은 null

Run: python tests/test_app_version_integration.py
⚠️ 2번 이후는 오너가 db/2026-07-31_runs_app_version.sql 실행 후에만 통과 —
미적용이면 "[검증 불가]"를 찍고 exit 1(조용한 통과 금지).
임시 유저·run은 종료 시 전부 삭제(잔여 0 assert).
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
import pydantic  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.models.schemas import RunRequest  # noqa: E402
from app.services import run_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None
VER = "1.4.2 (118) e2e-test"


def ok(m):
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _column_exists() -> bool:
    k = settings.supabase_service_role_key
    spec = httpx.get(f"{_SB}/rest/v1/", headers={"apikey": k, "Authorization": f"Bearer {k}"},
                     timeout=30).json()
    return "app_version" in spec["definitions"]["runs"]["properties"]


async def main():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"appver-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]
    sb = get_supabase_admin()

    print("[1. 미전송 — insert 성공(키 생략, 컬럼 유무 무관)]")
    res = await run_service.create_run(
        RunRequest(distance_km=1.0, duration_sec=600), user_id=_uid)
    rid_null = res.id
    ok(f"run 저장 성공 id={rid_null[:8]} (app_version 미전송)")

    print("\n[3. 65자 초과 → 검증 거부]")
    try:
        RunRequest(distance_km=1.0, duration_sec=600, app_version="x" * 65)
        raise AssertionError("65자 app_version이 통과하면 안 됨")
    except pydantic.ValidationError:
        ok("max_length=64 초과 거부(422 경로)")

    if not _column_exists():
        print("\n[검증 불가] runs.app_version 컬럼 미적용 — 오너가 "
              "db/2026-07-31_runs_app_version.sql 실행 후 재실행 필요:\n"
              "  python tests/test_app_version_integration.py")
        sys.exit(1)

    print("\n[2. 전송 — 행에 그대로 저장]")
    res2 = await run_service.create_run(
        RunRequest(distance_km=1.2, duration_sec=700, app_version=VER), user_id=_uid)
    row = sb.table("runs").select("app_version").eq("id", res2.id).execute().data[0]
    assert row["app_version"] == VER, row
    ok(f"app_version '{VER}' 저장 확인")

    print("\n[4. 미전송 행은 null]")
    row0 = sb.table("runs").select("app_version").eq("id", rid_null).execute().data[0]
    assert row0["app_version"] is None, row0
    ok("미전송 run의 app_version = null")


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    rows = sb.table("runs").select("id").eq("user_id", _uid).execute().data
    if rows:
        sb.table("runs").delete().in_("id", [x["id"] for x in rows]).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    left = len(sb.table("runs").select("id").eq("user_id", _uid).execute().data)
    assert left == 0
    print(f"\n[cleanup] runs {len(rows)}건·임시 유저 삭제·잔여 0")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
