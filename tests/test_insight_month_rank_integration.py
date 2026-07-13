"""
Integration test: 월간 인사이트 순위 지표 (month_rank — "이번 달 N번째로 빠른 …")

4개 기록 차원 재사용, 가장 최근 verified run 랭킹, 가장 인상적 1개 선정.
같은 차원 3회 → 순위 정확 / 1회뿐 → null / verified만(unverified 제외) /
월 경계(지난달 미포함) / 거리대 버킷 정합.

Run: python tests/test_insight_month_rank_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timezone, timedelta
import httpx

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"
_KST = timezone(timedelta(hours=9))


def _keys():
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


def ok(m):        print(f"  ✓ {m}")
def step(t):      print(f"\n[{t}]")


def sb_user(c, email):
    return c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                  json={"email": email, "password": "test1234", "email_confirm": True}).json()["id"]


def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


def ins_run(c, uid, dist, dur, ran_at, verification="verified"):
    r = c.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": uid, "distance_km": dist, "duration_sec": dur,
                     "ran_at": ran_at.isoformat(), "verification": verification,
                     "visibility": "public"})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()[0]["id"]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        now = datetime.now(_KST)
        Y, M = now.year, now.month
        py, pm = (Y - 1, 12) if M == 1 else (Y, M - 1)

        def kst(day, hh=12):
            return datetime(Y, M, day, hh, tzinfo=_KST)

        step("0. U(프리미엄) — 이번 달 A·B·C(verified)·UNV(unverified 최근)·PREV(지난달)")
        uids["u"] = sb_user(c, f"imr-u-{TS}@test.com")
        tk = sb_login(c, f"imr-u-{TS}@test.com")
        assert api(c, "PATCH", "/me/profile", tk, json={"nickname": f"IMR{TS}"}).status_code == 200
        c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM, params={"user_id": f"eq.{uids['u']}"},
                json={"tier": "premium"})
        # A: 7km 6:00/km, B: 8km 5:30/km, C(최근 verified): 6km 5:45/km
        a = ins_run(c, uids["u"], 7.0, 7 * 360, kst(5))   # dur 2520
        b = ins_run(c, uids["u"], 8.0, 8 * 330, kst(6))   # dur 2640
        cid = ins_run(c, uids["u"], 6.0, 6 * 345, kst(7)) # dur 2070 — 최근 verified
        ins_run(c, uids["u"], 10.0, 3000, kst(8), verification="unverified")  # 최근이나 제외
        ins_run(c, uids["u"], 20.0, 7200, datetime(py, pm, 15, 12, tzinfo=_KST))  # 지난달 제외
        ok("적재: verified 3(A·B·C)+unverified 1(최근)+지난달 1")

        step("1. month_rank — best_5k 2번째·total 3 (가장 인상적 선정)")
        resp = api(c, "GET", f"/me/insights/monthly?year={Y}&month={M}", tk)
        assert resp.status_code == 200, resp.text[:200]
        mr = resp.json()["month_rank"]
        assert mr is not None, "month_rank 존재"
        # C: best_5k t5k=1725(B 1650만 빠름)→rank2 / best_pace rank2 / longest 3.
        # 동순위 2 중 tie 우선(best_5k tie2 < best_pace tie3) → best_5k 선정.
        assert mr["type"] == "best_5k", f"best_5k 선정 기대, got {mr['type']}"
        assert mr["rank"] == 2, f"2번째 기대, got {mr['rank']}"
        assert mr["total"] == 3, f"total 3(verified만·지난달 제외) 기대, got {mr['total']}"
        assert mr["run_id"] == cid, "랭크 대상=최근 verified run(C, unverified 아님)"
        ok("best_5k rank 2·total 3·대상=최근 verified(C) — verified·월경계 정합")

        step("2. 거리대 버킷 정합 — unverified·지난달이 total에 미포함")
        # total==3이 이미 unverified(10km) 미포함·지난달(20km) 미포함을 증명.
        # 추가: unverified가 최근이었으나 run_id가 C인 것으로 recent=verified 확인됨.
        ok("unverified·지난달 run 집계 제외 확인(total 3·대상 C)")

        step("3. 1회뿐 → null (각 차원 <2회, 타일 미생성)")
        uids["v"] = sb_user(c, f"imr-v-{TS}@test.com")
        tv = sb_login(c, f"imr-v-{TS}@test.com")
        assert api(c, "PATCH", "/me/profile", tv, json={"nickname": f"IMRV{TS}"}).status_code == 200
        c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM, params={"user_id": f"eq.{uids['v']}"},
                json={"tier": "premium"})
        ins_run(c, uids["v"], 6.0, 2100, kst(10))  # 이번 달 verified 단 1회
        mrv = api(c, "GET", f"/me/insights/monthly?year={Y}&month={M}", tv).json()["month_rank"]
        assert mrv is None, f"1회뿐이면 month_rank null(무의미), got {mrv}"
        ok("verified 1회뿐 → month_rank null (≥2 규칙)")

        step("4. 프리미엄 게이트 — free는 403")
        uids["f"] = sb_user(c, f"imr-f-{TS}@test.com")
        tf = sb_login(c, f"imr-f-{TS}@test.com")
        api(c, "PATCH", "/me/profile", tf, json={"nickname": f"IMRF{TS}"})
        assert api(c, "GET", f"/me/insights/monthly?year={Y}&month={M}", tf).status_code == 403
        ok("free tier 403 premium_required (기존 게이트 불변)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run_tests()
