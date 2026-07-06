"""
Integration test: AI 월간 인사이트 (GET /me/insights/monthly, 프리미엄)
1) 결정론 — 주차 분할(KST 경계)·월 PR+all_time_best·패턴 버킷·streak·
   프롬프트 조립·403/422·캐시 3케이스·run 0 달 (Gemini 호출 0)
2) 실호출 1회 — 지난달 fixture runs → 구조·한국어 → 재호출 캐시 → 쿼터 미차감
Run: python tests/test_monthly_insight_integration.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, patch

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
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


def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


def mk_run(c, user_id, ran_at, d, dur, pace=None):
    r = c.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=minimal"},
               json={"user_id": user_id, "ran_at": ran_at, "distance_km": d,
                     "duration_sec": dur, "avg_pace_sec_per_km": pace})
    assert r.status_code in (200, 201), r.text[:200]


# ═══ Phase 1: 결정론 ═════════════════════════════════════════════════════════

def phase1_pure():
    from app.services import insight_service as ins
    from app.services.openai_service import _build_insight_prompt, _insight_system

    def row(i, ran_at, d=5.0, dur=1500, pace=300):
        return {"id": f"r{i}", "ran_at": ran_at, "distance_km": d,
                "duration_sec": dur, "avg_pace_sec_per_km": pace}

    step("1-1. 주차 분할 — KST 경계 (2026-07: 1일=수요일 → 5주)")
    rows = [
        row(1, "2026-07-05T14:59:00+00:00"),        # UTC 14:59 = KST 7/5(일) 23:59 → 1주차
        row(2, "2026-07-05T15:01:00+00:00"),        # UTC 15:01 = KST 7/6(월) 00:01 → 2주차
        row(3, "2026-07-31T10:00:00+09:00", 3.0, 1200, 400),
    ]
    w = ins._split_weeks(rows, 2026, 7)
    assert len(w) == 5, f"7월(수 시작, 31일)은 5주여야 함, got {len(w)}"
    assert w[0].run_count == 1 and w[1].run_count == 1, "UTC/KST 자정 경계 분리"
    assert w[4].run_count == 1 and w[4].distance_km == 3.0
    assert w[2].run_count == 0, "빈 주도 포함 (차트용)"
    ok("KST 자정 경계 ✓ 5주 그리드 ✓ 빈 주 포함 ✓")

    step("1-2. 월 PR + all_time_best 두 케이스")
    prev = [row(10, "2026-05-10T09:00:00+09:00", 8.0, 2800, 350)]   # 5월: 8km
    june = [row(11, "2026-06-10T09:00:00+09:00", 10.0, 3600, 360),  # 6월: 10km ← 경신
            row(12, "2026-06-20T09:00:00+09:00", 5.0, 1400, 280)]   # 페이스 280 ← 경신
    recs = ins._month_records(june, prev + june, 2026, 6)
    by = {r.type: r for r in recs}
    assert by["longest_distance"].value == 10.0 and by["longest_distance"].all_time_best
    assert by["best_pace"].value == 280 and by["best_pace"].all_time_best
    # 케이스2: 7월엔 6월보다 못한 기록 → 월 PR은 있지만 all_time_best=False
    july = [row(13, "2026-07-03T09:00:00+09:00", 6.0, 2100, 350)]
    recs = ins._month_records(july, prev + june + july, 2026, 7)
    by = {r.type: r for r in recs}
    assert by["longest_distance"].value == 6.0 and not by["longest_distance"].all_time_best
    assert not by["best_pace"].all_time_best
    ok("그 달 경신 → up ✓ 못 미친 달 → 월 PR만 (up 없음) ✓")

    step("1-3. 패턴 — 시간대 버킷 + streak 월 내 한정")
    rows = [row(20, "2026-06-01T07:30:00+09:00"),   # 아침, 월
            row(21, "2026-06-02T07:00:00+09:00"),   # 아침, 화 (연속 2)
            row(22, "2026-06-03T22:00:00+09:00"),   # 밤, 수 (연속 3)
            row(23, "2026-06-15T05:00:00+09:00")]   # 새벽, 월
    p = ins._compute_pattern(rows)
    assert p.weekday_counts == [2, 1, 1, 0, 0, 0, 0]
    assert p.time_of_day == "morning" and p.time_of_day_pct == 50
    assert p.longest_streak_days == 3
    assert ins._compute_pattern([]).time_of_day is None
    ok("요일 분포 ✓ 최빈 아침 50% ✓ streak 3 ✓ 빈 달 None ✓")

    step("1-4. 프롬프트 조립 — 가드 + 수치 포함 + 부재 데이터 미언급")
    _sys = _insight_system("ko")
    assert "의학적 조언 금지" in _sys and "지어내지 않습니다" in _sys and "한국어" in _sys
    prompt = _build_insight_prompt(
        year=2026, month=6, total_distance_km=42.8, run_count=12,
        avg_pace_sec_per_km=318, delta_distance_km=4.6,
        weeks=[{"index": 1, "distance_km": 8.2, "run_count": 2, "avg_pace_sec_per_km": 326}],
        records=[{"type": "best_pace", "value": 286, "all_time_best": True}],
        pattern={"time_of_day": "morning", "time_of_day_pct": 58, "longest_streak_days": 5})
    assert "42.8km" in prompt and "5분 18초/km" in prompt and "+4.6km" in prompt
    assert "자기 기록 경신" in prompt and "7월 목표" in prompt
    assert "심박" not in prompt and "고도" not in prompt and "칼로리" not in prompt
    ok("금지 가드 ✓ 수치 직렬화 ✓ 부재 데이터 미포함 ✓ 다음 달 제목 지정 ✓")

    step("1-5. plan 후처리")
    plan = ins._sanitize_plan([
        {"slot": "challenge", "title": "도전", "body": "b"},
        {"slot": "goal", "title": "목표", "body": "b"},
        {"slot": "goal", "title": "중복", "body": "b"},
        {"slot": "focus", "title": "집중", "body": "b"},
    ])
    assert [p_.slot for p_ in plan] == ["goal", "focus", "challenge"]
    assert plan[0].title == "목표", "슬롯당 첫 항목 유지"
    try:
        ins._sanitize_plan([{"slot": "diet", "title": "x", "body": "y"}])
        fail("허용 외 slot은 실패해야 함")
    except Exception:
        pass
    ok("정렬·중복 제거 ✓ slot enum ✓")


def phase1_cache_mock(uid_prem, prev2_y, prev2_m, cur_y, cur_m, c):
    """전전달(prev2)·이번 달을 사용 — phase2 실호출(지난달 캐시 선점)과 격리."""
    from app.services import insight_service as ins

    step("1-6. 캐시 3케이스 (mock): 재사용 / 이번 달 run 추가 → 재생성 / 지난달 유지")
    fake = {"coaching": "테스트 코칭 문단입니다. 꾸준했어요. 다음 달도 화이팅.",
            "plan": [{"slot": "goal", "title": "목표", "body": "b"},
                     {"slot": "focus", "title": "집중", "body": "b"},
                     {"slot": "challenge", "title": "도전", "body": "b"}]}
    gen = AsyncMock(return_value=fake)
    mk_run(c, uid_prem, f"{cur_y}-{cur_m:02d}-01T08:00:00+09:00", 3.0, 1000, 333)
    with patch.object(ins.openai_service, "generate_monthly_insight", gen):
        # 지난(전전)달: 2회 조회 → 생성 1회 + from_cache
        r1 = asyncio.run(ins.get_monthly_insight(uid_prem, prev2_y, prev2_m))
        r2 = asyncio.run(ins.get_monthly_insight(uid_prem, prev2_y, prev2_m))
        assert gen.call_count == 1 and r1.ai.from_cache is False and r2.ai.from_cache is True
        # 이번 달: 생성(2회째) → run 추가 → run_count 불일치 → 재생성(3회째)
        r3 = asyncio.run(ins.get_monthly_insight(uid_prem, cur_y, cur_m))
        assert gen.call_count == 2 and r3.ai.from_cache is False
        mk_run(c, uid_prem, f"{cur_y}-{cur_m:02d}-02T09:00:00+09:00", 2.0, 700, 350)
        r4 = asyncio.run(ins.get_monthly_insight(uid_prem, cur_y, cur_m))
        assert gen.call_count == 3 and r4.ai.from_cache is False, "run 추가 시 재생성"
        assert r4.stats.run_count == r3.stats.run_count + 1, "수치는 항상 최신"
        # 지난 달들은 이번 달 run 추가와 무관하게 캐시 유지
        r5 = asyncio.run(ins.get_monthly_insight(uid_prem, prev2_y, prev2_m))
        assert gen.call_count == 3 and r5.ai.from_cache is True
    ok("같은 달 캐시 ✓ 이번 달 run_count 무효화 ✓ 지난달 영구 ✓ 수치 fresh ✓")

    step("1-7. run 0회 달 → ai=null + Gemini 미호출")
    gen0 = AsyncMock()
    with patch.object(ins.openai_service, "generate_monthly_insight", gen0):
        r = asyncio.run(ins.get_monthly_insight(uid_prem, 2020, 1))
    assert r.ai is None and gen0.call_count == 0
    assert r.stats.run_count == 0 and r.records == []
    ok("빈 달 ai=null ✓ 호출 0 ✓")


def phase1_gates(c, tok_free, tok_prem):
    step("1-8. free 403 구조화 + 파라미터 422")
    r = api(c, "GET", "/me/insights/monthly", tok_free, params={"year": 2026, "month": 6})
    assert r.status_code == 403, r.text[:200]
    d = r.json()["detail"]
    assert d["error"] == "premium_required" and d["feature"] == "monthly_insight"
    for bad in ({"year": 2026, "month": 13}, {"year": 2026, "month": 0},
                {"year": 1999, "month": 6}, {"year": 2026}):
        assert api(c, "GET", "/me/insights/monthly", tok_prem,
                   params=bad).status_code == 422, bad
    ok("403 premium_required ✓ month/year 검증 422 ✓")


# ═══ Phase 2: 실호출 1회 ═════════════════════════════════════════════════════

def phase2(c, tok_prem, prev_y, prev_m):
    import re

    step("2-1. Gemini 실호출: 지난달 리포트 → 구조·한국어")
    r = api(c, "GET", "/me/insights/monthly", tok_prem,
            params={"year": prev_y, "month": prev_m}, timeout=90)
    assert r.status_code == 200, r.text[:400]
    d = r.json()
    assert d["stats"]["run_count"] == 5 and d["stats"]["total_distance_km"] > 0
    assert len(d["weeks"]) >= 4 and sum(w["run_count"] for w in d["weeks"]) == 5
    assert {x["type"] for x in d["records"]} >= {"best_pace", "longest_distance"}
    assert sum(d["pattern"]["weekday_counts"]) == 5
    ai = d["ai"]
    assert ai and ai["from_cache"] is False
    assert re.search(r"[가-힣]", ai["coaching"]) and len(ai["coaching"]) >= 30
    slots = [p["slot"] for p in ai["plan"]]
    assert slots == [s for s in ("goal", "focus", "challenge") if s in slots] and "goal" in slots
    ok(f"수치 블록 ✓ coaching {len(ai['coaching'])}자 ✓ plan {slots} — "
       f"{ai['coaching'][:60]}…")

    step("2-2. 재호출 → 캐시 (비용 0) + 쿼터 미차감")
    r = api(c, "GET", "/me/insights/monthly", tok_prem,
            params={"year": prev_y, "month": prev_m})
    assert r.status_code == 200 and r.json()["ai"]["from_cache"] is True
    r = api(c, "GET", "/me/quota", tok_prem)
    assert r.json()["ai_generation"]["used"] == 0
    ok("from_cache ✓ 쿼터 used=0 ✓ (인사이트는 쿼터 별개)")


def run():
    from datetime import datetime, timedelta, timezone
    ts = int(time.time())
    pw = "TestPass123!"
    uids: list[str] = []

    # 지난달/이번 달 (KST)
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    cur_y, cur_m = now.year, now.month
    prev = (now.replace(day=1) - timedelta(days=1))
    prev_y, prev_m = prev.year, prev.month
    prev2 = (prev.replace(day=1) - timedelta(days=1))
    prev2_y, prev2_m = prev2.year, prev2.month

    with httpx.Client(timeout=30) as c:
        try:
            phase1_pure()

            step("공용: premium/free 유저 + 지난달 fixture runs 5개")
            toks = []
            for i in (1, 2):
                e = f"mi-u{i}-{ts}@t.l"
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
                r = api(c, "PATCH", "/me/profile", toks[-1],
                        json={"nickname": f"인사u{i}-{ts % 100000}"})
                assert r.status_code == 200, r.text[:200]
            uid_prem, uid_free = uids
            tok_prem, tok_free = toks
            r = c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM,
                        params={"user_id": f"eq.{uid_prem}"}, json={"tier": "premium"})
            assert r.status_code in (200, 204)
            for day, d_km, dur in ((3, 5.0, 1500), (5, 3.0, 990), (12, 8.0, 2560),
                                   (13, 4.0, 1240), (24, 5.0, 1450)):
                mk_run(c, uid_prem, f"{prev_y}-{prev_m:02d}-{day:02d}T07:30:00+09:00",
                       d_km, dur)
            # 전전달 1개 — mock 캐시 테스트용 (실호출 달과 격리)
            mk_run(c, uid_prem, f"{prev2_y}-{prev2_m:02d}-10T07:30:00+09:00", 4.0, 1300)
            ok(f"{prev_y}-{prev_m:02d} runs 5개 + {prev2_y}-{prev2_m:02d} 1개 삽입 (Gemini 비용 0)")

            phase1_gates(c, tok_free, tok_prem)
            phase2(c, tok_prem, prev_y, prev_m)          # 실호출 1회
            phase1_cache_mock(uid_prem, prev2_y, prev2_m, cur_y, cur_m, c)

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            sb_del_in(c, "monthly_insights", "user_id", uids)
            sb_del_in(c, "runs", "user_id", uids)
            sb_del_in(c, "profiles", "user_id", uids)
            for uid in uids:
                sb_del_user(c, uid)
            ok("monthly_insights·runs·profiles·auth users 삭제")


if __name__ == "__main__":
    run()
