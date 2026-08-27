"""
runs.avg_cadence_spm additive (이반 케이던스 선행, 2026-08-27)

RunRequest(extra=forbid)에 avg_cadence_spm: Optional[int] 추가 — 없던 필드라 클라가
보내면 422였던 것 해소. avg_pace_sec_per_km 동형(int·nullable·gt=0). 미전송 시 insert
키 생략(app_version 전례) → 컬럼 미적용 DB에서도 무cadence 저장 무해.

커버:
  A. 스키마(무DB) — RunRequest 필드 수용(422 해소)·gt=0·기본 None·RunResponse 보유
  B. DB additive — 무cadence 저장 정상(기존 무영향)·응답 null·조회 무영향
  C. DB 영속 — cadence 저장→조회 왕복(⚠️ 컬럼 존재 시만; 미적용이면 검증 불가 표기)
임시 유저·생성분 즉삭. Run: python tests/test_run_cadence.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.models.schemas import RunRequest, RunResponse  # noqa: E402
from app.services import run_service  # noqa: E402

TS = int(time.time())
_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_uid: str | None = None
_passed = 0


def ok(m):
    global _passed
    _passed += 1
    print(f"  ✓ {m}")


def _adm():
    k = settings.supabase_service_role_key
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def _column_exists() -> bool:
    """runs.avg_cadence_spm 컬럼 존재 여부(PostgREST 프로브) — 마이그레이션 실행 확인."""
    try:
        get_supabase_admin().table("runs").select("avg_cadence_spm").limit(1).execute()
        return True
    except Exception as e:  # noqa: BLE001 — column does not exist → APIError
        if "avg_cadence_spm" in str(e) or "42703" in str(e) or "PGRST" in str(e):
            return False
        raise


# ── A. 스키마 (무DB) — 422 해소 + 하위호환 ──────────────────────────────
def schema_tests():
    print("[A. 스키마 — RunRequest 수용(422 해소)·검증·RunResponse]")

    # A-1: avg_cadence_spm 수용(extra=forbid인데 필드 있으니 통과) — 이게 422 해소
    r = RunRequest(distance_km=5.0, duration_sec=1800, avg_cadence_spm=176)
    assert r.avg_cadence_spm == 176
    ok("A-1 RunRequest가 avg_cadence_spm 수용(extra=forbid·422 해소)")

    # A-2: 미전송 → 기본 None(additive·하위호환)
    r2 = RunRequest(distance_km=5.0, duration_sec=1800)
    assert r2.avg_cadence_spm is None
    ok("A-2 미전송 시 기본 None(기존 클라 무영향)")

    # A-3: gt=0 검증(avg_pace 동형) — 0/음수 거부
    for bad in (0, -5):
        try:
            RunRequest(distance_km=5.0, duration_sec=1800, avg_cadence_spm=bad)
            raise AssertionError(f"avg_cadence_spm={bad} 통과됨(gt=0 위반)")
        except ValidationError:
            pass
    ok("A-3 gt=0 검증(0·음수 422)")

    # A-4: RunResponse가 필드 보유(기본 None)
    assert "avg_cadence_spm" in RunResponse.model_fields
    ok("A-4 RunResponse 필드 보유(조회 계약)")


# ── B/C. DB additive + 영속 ─────────────────────────────────────────────
async def db_tests():
    global _uid
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_adm(),
                   json={"email": f"cad-{TS}@test.com", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    _uid = r.json()["id"]

    # B. 무cadence 저장 정상(기존 무영향)·응답 null
    print("\n[B. DB additive — 무cadence 저장(기존 무영향)]")
    run_b = await run_service.create_run(
        RunRequest(distance_km=5.0, duration_sec=1800), user_id=_uid)
    assert run_b.avg_cadence_spm is None, run_b.avg_cadence_spm
    got = await run_service.get_run(run_b.id, _uid)
    assert got is not None and got.avg_cadence_spm is None
    ok("무cadence: 저장 성공·응답 null·조회 null(additive·회귀 없음)")

    # C. cadence 영속(컬럼 존재 시만)
    print("\n[C. DB 영속 — cadence 저장→조회 왕복]")
    if not _column_exists():
        print("  ⚠️ 검증 불가 — runs.avg_cadence_spm 컬럼 미적용(오너 SQL 대기). "
              "스키마·additive는 A·B로 확정, 영속은 마이그레이션 후 재검.")
        return
    run_c = await run_service.create_run(
        RunRequest(distance_km=6.0, duration_sec=2100, avg_cadence_spm=182), user_id=_uid)
    assert run_c.avg_cadence_spm == 182, run_c.avg_cadence_spm
    # DB 부수효과: 실제 행에 영속
    sb = get_supabase_admin()
    row = sb.table("runs").select("avg_cadence_spm").eq("id", run_c.id).single().execute().data
    assert row["avg_cadence_spm"] == 182, row
    # 조회 왕복
    got_c = await run_service.get_run(run_c.id, _uid)
    assert got_c.avg_cadence_spm == 182
    ok("cadence=182 저장→DB 영속→조회 왕복 일치(부수효과 assert)")


def cleanup():
    if not _uid:
        return
    sb = get_supabase_admin()
    rows = sb.table("runs").select("id").eq("user_id", _uid).execute().data
    if rows:
        sb.table("runs").delete().in_("id", [x["id"] for x in rows]).execute()
    httpx.delete(f"{_SB}/auth/v1/admin/users/{_uid}", headers=_adm(), timeout=30)
    assert len(sb.table("runs").select("id").eq("user_id", _uid).execute().data) == 0
    print(f"\n[cleanup] runs {len(rows)}행·임시 유저 삭제(잔여 0)")


async def main():
    schema_tests()
    await db_tests()


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_passed} assert)\n" + "=" * 50)
    finally:
        cleanup()
