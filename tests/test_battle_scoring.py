"""
배틀 스코어 엔진 — 순수 함수(무DB, 항상 실행). docs/BATTLE_DESIGN_v0_KO.md §3.

커버: per-run 공식·완주하한·flagged/unverified 0점·pace 계단·early_bird 경계(ran_at KST
07:00)·milestone 결정론(첫 5k/10k 1회)·streak 배율(cap 1.5)·participant 누적·시각 헬퍼.
Run: python tests/test_battle_scoring.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import battle_service as bs  # noqa: E402

_KST = timezone(timedelta(hours=9))
_n = 0


def ok(m):
    global _n
    _n += 1
    print(f"  ✓ {m}")


def _kst(h, m=0, day="2026-09-07"):
    """KST 시각 → UTC ISO(ran_at 저장 형태)."""
    return datetime.fromisoformat(f"{day}T{h:02d}:{m:02d}:00+09:00").astimezone(timezone.utc).isoformat()


def _run(dist, pace=400, ran_h=12, verified=True, flagged=False, rid="r"):
    return {"id": rid, "distance_km": dist, "avg_pace_sec_per_km": pace,
            "verification": "verified" if verified else "unverified",
            "is_flagged": flagged, "ran_at": _kst(ran_h)}


def main():
    print("[A. per-run 공식 + 게이트]")
    # 5km·pace 5:30(330<360→+10)·낮(early 0)·5k첫(+30) = 50+20+10+0+30 = 110... wait pace 400=6:40 → <420 →+5
    s, bd, c = bs.score_run(_run(5.0, pace=400, ran_h=12), is_5k_first=True)
    assert c and s == 50 + 20 + 5 + 0 + 30, (s, bd)   # base50 comp20 pace5 early0 mile30
    ok(f"5km 낮 pace6:40 5k첫 = {s}(base50+comp20+pace5+mile30)")

    # <1.5km → 0점·counted false
    s, bd, c = bs.score_run(_run(1.2), is_5k_first=False)
    assert s == 0 and not c
    ok("1.2km(<1.5 하한) → 0점·counted=false")

    # flagged → 0
    s, _, c = bs.score_run(_run(5.0, flagged=True))
    assert s == 0 and not c
    ok("is_flagged → 0점(anti-cheat)")

    # unverified → 0
    s, _, c = bs.score_run(_run(5.0, verified=False))
    assert s == 0 and not c
    ok("unverified → 0점(§2.4 verified-only)")

    print("\n[B. early_bird 경계(ran_at KST 07:00)]")
    s1, b1, _ = bs.score_run(_run(2.0, ran_h=6), is_5k_first=False)     # 06:00 → early
    s2, b2, _ = bs.score_run({**_run(2.0), "ran_at": _kst(7, 0)})       # 07:00 → 미포함
    assert b1["early_bird"] == 10 and b2["early_bird"] == 0
    ok(f"06:00 early +10 / 07:00 미포함 +0(경계 06:59 포함)")

    print("\n[C. pace 계단]")
    for pace, exp in [(280, 15), (330, 10), (400, 5), (500, 0)]:
        _, bd, _ = bs.score_run(_run(2.0, pace=pace))
        assert bd["pace"] == exp, (pace, bd["pace"])
    ok("pace <5:00→15 <6:00→10 <7:00→5 그외 0(플레이스홀더)")

    print("\n[D. streak 배율(cap 1.5)]")
    assert bs.streak_multiplier(0) == 1.0 and bs.streak_multiplier(5) == 1.25
    assert bs.streak_multiplier(10) == 1.5 and bs.streak_multiplier(20) == 1.5
    ok("streak 0→1.0 5→1.25 10→1.5 20→1.5(cap)")

    print("\n[E. milestone 결정론(첫 5k/10k 배틀당 1회)]")
    runs = [_run(6.0, ran_h=8, rid="a"), _run(3.0, ran_h=9, rid="b"),
            _run(11.0, ran_h=10, rid="c"), _run(7.0, ran_h=11, rid="d")]
    total, per = bs.score_participant(runs, streak_days=0)
    m = {p["run_id"]: p["breakdown"].get("milestone", 0) for p in per if p["counted"]}
    # 첫 ≥5km = a(6.0)→+30. 첫 ≥10km = c(11.0)→+50. d(7.0)는 5k 이미 소진→0
    assert m["a"] == 30 and m["c"] == 50 and m["d"] == 0 and m["b"] == 0, m
    ok(f"첫5k=a(+30)·첫10k=c(+50)·이후 재달성 0(중복 지급 없음)")

    print("\n[F. participant 누적 × streak]")
    # streak 4 → mult 1.2. 위 runs 합 × 1.2
    total0, per0 = bs.score_participant(runs, streak_days=0)
    total4, _ = bs.score_participant(runs, streak_days=4)
    assert abs(total4 - round(total0 * 1.2, 2)) < 0.01, (total0, total4)
    ok(f"참가자 점수 {total0} × streak_mult(4)=1.2 → {total4}")

    print("\n[G. _current_streak(ran_at KST 버킷)]")
    today = datetime.now(_KST).date()
    isos = [datetime.combine(today - timedelta(days=d), datetime.min.time().replace(hour=8), _KST)
            .astimezone(timezone.utc).isoformat() for d in (0, 1, 2, 4)]  # 오늘·어제·그제 연속, 4일전 끊김
    assert bs._current_streak(isos) == 3, bs._current_streak(isos)
    # 오늘·어제 미실행(3일전부터) → 현재 streak 0(끊김)
    old = [datetime.combine(today - timedelta(days=d), datetime.min.time().replace(hour=8), _KST)
           .astimezone(timezone.utc).isoformat() for d in (3, 4, 5)]
    assert bs._current_streak(old) == 0, bs._current_streak(old)
    ok("연속 3일→3 / 오늘·어제 공백→0(현재 진행만)")

    print("\n[H. ends_at KST 자정 정렬]")
    started = datetime.fromisoformat("2026-09-07T05:30:00+00:00")  # KST 14:30
    ends = bs._ends_at(started, 7)
    ends_kst = ends.astimezone(_KST)
    assert ends_kst.hour == 0 and ends_kst.minute == 0, ends_kst
    assert (ends_kst.date() - started.astimezone(_KST).date()).days == 7
    ok(f"수락 KST14:30 + 7일 → ends KST {ends_kst}(자정 정렬)")


if __name__ == "__main__":
    main()
    print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_n} assert)\n" + "=" * 50)
