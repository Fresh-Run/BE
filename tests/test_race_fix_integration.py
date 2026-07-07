"""
Integration test: 레이스 묶음 RPC (H3 정원 · M8 크루한도 · M3 AI쿼터)
실동시(asyncio.gather) + 불변식 검증 — 수정본은 항상 성립(비-flaky).
- H3: 마지막 1슬롯에 K명 동시 가입 → 정확히 1명 admit, 정원 초과 0, 나머지 409
- M8: free 동시 2건 create → free 소유 1개, 성공 1·403 1
- M3: used=limit-1에서 동시 3건 예약 → 주간 count==limit, 성공 1·나머지 QuotaExceeded
      (Gemini 무관 — reserve_ai_generation을 in-process로 직접, 비용 0)
Run: python tests/test_race_fix_integration.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys():
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


def ok(m): print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")


async def mkuser(c, e, premium=False):
    r = await c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                     json={"email": e, "password": "TestPass123!", "email_confirm": True})
    uid = r.json()["id"]
    r = await c.post(f"{_SB}/auth/v1/token?grant_type=password",
                     headers={"apikey": _ANON, "Content-Type": "application/json"},
                     json={"email": e, "password": "TestPass123!"})
    tok = r.json()["access_token"]
    await c.patch(f"{BASE}/me/profile", headers={"Authorization": f"Bearer {tok}"},
                  json={"nickname": f"race-{uid[:5]}"})
    if premium:
        await c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM,
                      params={"user_id": f"eq.{uid}"}, json={"tier": "premium"})
    return uid, tok


def H(tok): return {"Authorization": f"Bearer {tok}"}


async def del_in(c, table, col, vals):
    if vals:
        await c.delete(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "return=minimal"},
                       params={col: f"in.({','.join(vals)})"})


async def main():
    ts = int(time.time())
    uids, crew_ids = [], []
    async with httpx.AsyncClient(timeout=60) as c:
        try:
            # ── H3: 정원 마지막 슬롯 동시 경쟁 ────────────────────────────
            step("H3. 정원 3, 2명 채운 뒤 5명 동시 가입 → 1명만, 초과 0")
            owner_id, owner = await mkuser(c, f"rh-owner-{ts}@t.l"); uids.append(owner_id)
            r = await c.post(f"{BASE}/crews", headers=H(owner),
                             json={"name": f"정원크루-{ts%100000}", "max_members": 3,
                                   "is_public": True, "join_policy": "open"})
            crew_id = r.json()["id"]; crew_ids.append(crew_id)
            # 1명 더 채워 2/3 (owner + filler)
            fu, ft = await mkuser(c, f"rh-fill-{ts}@t.l"); uids.append(fu)
            assert (await c.post(f"{BASE}/crews/{crew_id}/join", headers=H(ft))).status_code == 200
            # 5명 동시 가입 (마지막 1슬롯)
            joiners = []
            for i in range(5):
                u, t = await mkuser(c, f"rh-j{i}-{ts}@t.l"); uids.append(u); joiners.append(t)
            results = await asyncio.gather(
                *[c.post(f"{BASE}/crews/{crew_id}/join", headers=H(t)) for t in joiners],
                return_exceptions=True,
            )
            codes = [r.status_code for r in results]
            n200 = sum(x == 200 for x in codes)
            n409 = sum(x == 409 for x in codes)
            # 최종 멤버 수 (불변식: 절대 3 초과 안 함)
            members = await c.get(f"{_SB}/rest/v1/crew_members", headers=_ADM,
                                  params={"crew_id": f"eq.{crew_id}", "select": "user_id"})
            mc = len(members.json())
            assert mc == 3, f"정원 3 초과! member_count={mc}"
            assert n200 == 1, f"정확히 1명 admit 기대, got {n200} (codes={codes})"
            assert n409 == 4, f"나머지 4명 409 기대, got {n409} (codes={codes})"
            ok(f"member_count=3(초과 0) ✓ admit 1(200) ✓ CrewFull 4(409) ✓ (동시 5, codes={codes})")

            # ── M8: free 동시 크루 생성 ──────────────────────────────────
            step("M8. free 유저 동시 2건 create → 1개만 (성공 1·403 1)")
            f8u, f8t = await mkuser(c, f"rm8-{ts}@t.l"); uids.append(f8u)  # free (기본)
            res8 = await asyncio.gather(
                *[c.post(f"{BASE}/crews", headers=H(f8t),
                         json={"name": f"동시크루{i}-{ts%100000}", "is_public": True})
                  for i in range(2)],
                return_exceptions=True,
            )
            codes8 = [r.status_code for r in res8]
            for r in res8:
                if r.status_code in (200, 201):
                    crew_ids.append(r.json()["id"])
            owned = await c.get(f"{_SB}/rest/v1/crews", headers=_ADM,
                                params={"owner_id": f"eq.{f8u}", "select": "id"})
            oc = len(owned.json())
            assert oc == 1, f"free 소유 1개 기대(레이스로 2개면 버그), got {oc}"
            assert sum(x in (200, 201) for x in codes8) == 1, f"성공 1 기대 codes={codes8}"
            assert sum(x == 403 for x in codes8) == 1, f"403 1 기대 codes={codes8}"
            ok(f"free 소유 크루=1(2개 아님) ✓ 성공 1·403 1 ✓ (codes={codes8})")

            # ── M3: AI 쿼터 예약 동시 (in-process, Gemini 비용 0) ────────
            step("M3. used=2(한도 3)에서 동시 3건 예약 → count==3, 성공 1·나머지 QuotaExceeded")
            from app.services import quota_service as qs
            m3u, _ = await mkuser(c, f"rm3-{ts}@t.l"); uids.append(m3u)
            # 이번 주 route_generations 2건 선삽입 (used=2)
            for _ in range(2):
                await c.post(f"{_SB}/rest/v1/route_generations",
                             headers={**_ADM, "Prefer": "return=minimal"},
                             json={"user_id": m3u})
            # 동시 3건 예약 (limit=3) — reserve는 Gemini 전 단계라 mock 불필요
            reserved = await asyncio.gather(
                *[qs.reserve_ai_generation(m3u, qs.AI_WEEKLY_LIMIT) for _ in range(3)],
                return_exceptions=True,
            )
            n_ok = sum(not isinstance(r, Exception) for r in reserved)
            n_quota = sum(isinstance(r, qs.QuotaExceeded) for r in reserved)
            cnt = await c.get(f"{_SB}/rest/v1/route_generations", headers=_ADM,
                              params={"user_id": f"eq.{m3u}", "select": "id"})
            total = len(cnt.json())
            assert total == 3, f"주간 count 3 기대(초과면 버그), got {total}"
            assert n_ok == 1, f"예약 성공 1 기대, got {n_ok}"
            assert n_quota == 2, f"QuotaExceeded 2 기대, got {n_quota}"
            ok(f"주간 count=3(초과 0) ✓ 예약 성공 1·QuotaExceeded 2 ✓")

            print("\n" + "=" * 50); print("  ALL TESTS PASSED"); print("=" * 50)
        finally:
            step("Cleanup")
            await del_in(c, "crews", "id", crew_ids)
            await del_in(c, "route_generations", "user_id", uids)
            await del_in(c, "crew_members", "user_id", uids)
            await del_in(c, "profiles", "user_id", uids)
            for u in uids:
                await c.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM)
            ok("crews·route_generations·members·profiles·auth 삭제")


if __name__ == "__main__":
    asyncio.run(main())
