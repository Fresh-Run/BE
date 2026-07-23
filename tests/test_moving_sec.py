"""
Unit test: split/run moving_sec (Ivan 배치 ①②, 2026-07-23)

이동시간 = 순간속도 ≥ MOVING_SPEED_MS(0.5) 구간의 dt 합(Strava식). elapsed(sec)는
정지 포함, moving_sec는 정지(신호등·휴식) 제외. run-level moving_s = Σ split.moving_sec.

Run: python tests/test_moving_sec.py
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import track_service as ts
from app.services.track_service import TrackPoint


def ok(m):  print(f"  ✓ {m}")
def fail(m): print(f"  ✗ {m}"); sys.exit(1)
def step(t): print(f"\n[{t}]")


def _straight(move_m: float, stop_s: float, interval_s: float = 4.0,
              speed: float = 3.0, start=(37.5445, 127.0374)) -> list[TrackPoint]:
    """직선 동쪽 주행 → 정지(제자리 stop_s초) → 다시 동쪽 주행. jitter 0(결정론).

    정지 구간은 위치 불변 → 순간속도 0 → moving서 제외, elapsed엔 포함."""
    lat, lng = start
    kx = 111320.0 * math.cos(math.radians(lat))
    t = 1_783_300_000_000
    step_m = speed * interval_s
    pts: list[TrackPoint] = []

    def emit():
        pts.append(TrackPoint(lat=lat, lng=lng, t_ms=t, acc=8.0))

    n = int(move_m / step_m)
    for _ in range(n):                     # phase A (동쪽 이동)
        emit(); lng += step_m / kx; t += int(interval_s * 1000)
    for _ in range(int(stop_s / interval_s)):  # 정지(제자리)
        emit(); t += int(interval_s * 1000)
    for _ in range(n):                     # phase B (동쪽 이동)
        emit(); lng += step_m / kx; t += int(interval_s * 1000)
    return pts


def run_tests():
    step("1. 등속 연속 주행(정지 0) → moving_s ≈ elapsed_s, 랩 moving_sec ≈ sec")
    # test_gps_track의 make_track 재사용(방향 랜덤워크 3km@5'30\")
    sys.path.insert(0, os.path.dirname(__file__))
    from test_gps_track_integration import make_track, to_points
    p = ts.process_track(to_points(make_track(3.0, 330)))
    assert p is not None
    # 전 구간 이동(속도 ~3m/s ≫ 0.5) → moving ≈ elapsed(±수초 GPS 지터)
    assert abs(p.moving_s - p.elapsed_s) <= 4, f"연속 주행 moving≈elapsed, got {p.moving_s} vs {p.elapsed_s}"
    for s in [s for s in p.splits if not s.partial]:
        assert s.moving_sec is not None and s.moving_sec <= s.sec, f"moving ≤ elapsed: {s}"
        assert s.sec - s.moving_sec <= 6, f"연속 주행은 랩 moving≈sec: {s}"
    # 랩합 차이(Σsec − Σmoving)는 trailing remainder가 상쇄돼 정지시간(여기선 0)에 수렴
    sec_tot = sum(s.sec for s in p.splits)
    mov_tot = sum(s.moving_sec for s in p.splits)
    assert sec_tot - mov_tot <= 6, f"연속 주행: 랩합서도 moving≈elapsed, 차 {sec_tot - mov_tot}"
    ok(f"moving_s {round(p.moving_s)} ≈ elapsed_s {round(p.elapsed_s)} · Σsec−Σmoving {sec_tot - mov_tot}")

    step("2. 신호등 정지(40s 제자리) → elapsed − moving ≈ 정지시간(3점 평활 경계분 제외)")
    # 3점 이동평균이 정지 경계 ~2구간(8s)을 부분이동으로 블렌딩 → 순수 제외 ≈ 40−8=32s
    p = ts.process_track(_straight(move_m=800, stop_s=40))
    assert p is not None, "합성 트랙이 유효해야"
    excluded = p.elapsed_s - p.moving_s
    assert p.moving_s < p.elapsed_s, "moving < elapsed(정지 존재)"
    assert 28 <= excluded <= 42, f"40s 정지 대부분이 moving서 제외돼야(경계 평활 감안), got {excluded:.0f}s"
    ok(f"elapsed {p.elapsed_s:.0f}s − moving {p.moving_s:.0f}s = {excluded:.0f}s(정지 40s−경계평활)")

    step("3. 랩합 Σsec − Σmoving == 총 제외분 (안분 정합, remainder 상쇄)")
    sec_tot = sum(s.sec for s in p.splits)
    mov_tot = sum(s.moving_sec for s in p.splits)
    # 랩합 차이는 총 제외분(elapsed−moving)과 일치해야(둘 다 정지시간, trailing 상쇄)
    assert abs((sec_tot - mov_tot) - excluded) <= 3, \
        f"랩합 차이 {sec_tot - mov_tot} == 총 제외 {excluded:.0f}"
    for s in p.splits:
        assert 0 <= s.moving_sec <= s.sec, f"0 ≤ moving ≤ elapsed 불변식: {s}"
    ok(f"Σsec {sec_tot} − Σmoving {mov_tot} = {sec_tot - mov_tot} == 총 제외 {excluded:.0f} · 랩별 0≤moving≤sec")

    step("4. 하위호환: moving_sec 기본 필드 존재 + RunSplit 직렬화")
    from app.models.schemas import RunSplit
    rs = RunSplit(km=1.0, sec=330, elev_gain_m=5)  # moving_sec 생략 → None
    assert rs.moving_sec is None, "구 데이터/생략 시 None(하위호환)"
    d = RunSplit(km=1.0, sec=330, elev_gain_m=5, moving_sec=310).model_dump()
    assert d["moving_sec"] == 310 and "moving_sec" in d
    ok("moving_sec 생략→None · 지정 시 직렬화 포함")

    print("\n" + "=" * 52 + "\n  ALL TESTS PASSED\n" + "=" * 52)


if __name__ == "__main__":
    run_tests()
