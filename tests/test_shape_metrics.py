"""
SQ1 모양 지표 — app/services/shape_metrics 순수 함수(무DB, 항상 실행).
ROUTE_SHAPE_QUALITY_DESIGN. retrace_ratio·branch_count 기대값 일치 + 스크립트 단일소스 일치.
Run: python tests/test_shape_metrics.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import shape_metrics as sm  # noqa: E402

_n = 0


def ok(m):
    global _n
    _n += 1
    print(f"  ✓ {m}")


def _densify(corners, step=10.0):
    out = []
    for i in range(len(corners) - 1):
        a, b = corners[i], corners[i + 1]
        d = sm._hav(a, b)
        k = max(1, int(d / step))
        for j in range(k):
            t = j / k
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    out.append(corners[-1])
    return out


# 고정 합성 데이터(동형 — 성북동 사례의 왕복/가지 구조 모사)
CLEAN_LOOP = _densify([(37.500, 127.000), (37.500, 127.004),
                       (37.503, 127.004), (37.503, 127.000), (37.500, 127.000)])
OUT_AND_BACK = ([(37.500 + 0.0001 * k, 127.000) for k in range(31)] +
                [(37.500 + 0.0001 * k, 127.000) for k in range(29, -1, -1)])


def main():
    print("[A. 기대값 일치 — 고정 합성 데이터]")
    clean = sm.shape_obs(CLEAN_LOOP)
    assert clean["branch_count"] == 0, clean
    assert clean["retrace_ratio"] < 0.05, clean   # 깨끗한 루프 = 왕복 거의 0
    ok(f"깨끗한 루프 → retrace_ratio={clean['retrace_ratio']}(<0.05)·branch=0")

    oab = sm.shape_obs(OUT_AND_BACK)
    assert oab["retrace_ratio"] == 0.9667, oab     # golden(결정론)
    assert oab["branch_count"] == 2, oab
    ok(f"왕복 직선 → retrace_ratio={oab['retrace_ratio']}·branch={oab['branch_count']}(기대 일치)")

    print("\n[B. 스크립트 단일소스 일치 — measure_hill_shape와 동일 코어]")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import measure_hill_shape as script  # noqa: E402
    for name, pts in [("clean", CLEAN_LOOP), ("oab", OUT_AND_BACK)]:
        s = script.shape_metrics(pts)
        assert round(sm.retrace_ratio(pts) * 100, 1) == s["retrace_ratio_pct"], (name, s)
        assert sm.branch_count(pts) == s["n_branches_gt50m"], (name, s)
    ok("sm.retrace_ratio×100 == script.retrace_ratio_pct · sm.branch_count == script.n_branches")

    print("\n[C. 경계·입력형·일관성]")
    assert sm.shape_obs([(37.5, 127.0), (37.5, 127.001)]) == {"retrace_ratio": None, "branch_count": None}
    assert sm.retrace_ratio([]) is None and sm.branch_count([]) is None
    ok("<4점·빈 입력 → None")

    # shape_obs == 개별 함수(일관성)
    assert sm.shape_obs(OUT_AND_BACK)["retrace_ratio"] == sm.retrace_ratio(OUT_AND_BACK)
    assert sm.shape_obs(OUT_AND_BACK)["branch_count"] == sm.branch_count(OUT_AND_BACK)
    ok("shape_obs == retrace_ratio()/branch_count() 개별 결과")

    # Coordinate / dict / tuple 입력 등가
    class C:
        def __init__(s, lat, lng):
            s.lat, s.lng = lat, lng
    as_obj = [C(la, ln) for la, ln in OUT_AND_BACK]
    as_dict = [{"lat": la, "lng": ln} for la, ln in OUT_AND_BACK]
    assert sm.shape_obs(as_obj) == sm.shape_obs(as_dict) == sm.shape_obs(OUT_AND_BACK)
    ok("Coordinate·dict·tuple 입력 등가")

    print("\n[D. 회랑 1단계 — corridor_obs·branch_count_strict]")
    # friendly(21) road_segments → friendly_ratio=1, 왕복 전부 친화 / road(23) → 0, 전부 도로
    co_f = sm.corridor_obs(OUT_AND_BACK, [("21", "보행자도로", 680.0)])
    co_r = sm.corridor_obs(OUT_AND_BACK, [("23", "강변북로", 680.0)])
    assert co_f["friendly_ratio"] == 1.0 and co_f["retrace_road_m"] == 0 and co_f["retrace_friendly_m"] > 0, co_f
    assert co_r["friendly_ratio"] == 0.0 and co_r["retrace_friendly_m"] == 0 and co_r["retrace_road_m"] > 0, co_r
    ok(f"roadType21→friendly_ratio=1·왕복 친화 / roadType23→0·왕복 도로")
    # road_segments 없으면 friendly/split None, branch_count_strict만 계산
    co_none = sm.corridor_obs(OUT_AND_BACK, None)
    assert co_none["friendly_ratio"] is None and co_none["retrace_friendly_m"] is None
    assert co_none["branch_count_strict"] is not None
    ok("road_segments 없음 → friendly/split None·branch_count_strict만 계산")
    # branch_count_strict(>150m)가 branch_count(>50m)보다 노이즈 보정(작거나 같음)
    assert sm.branch_count_strict(OUT_AND_BACK) <= sm.branch_count(OUT_AND_BACK)
    assert sm.branch_count_strict([(37.5, 127.0), (37.5, 127.001)]) is None  # <4점
    ok(f"branch_count_strict(>150m) ≤ branch_count(>50m) · <4점 None")


if __name__ == "__main__":
    main()
    print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_n} assert)\n" + "=" * 50)
