"""
S1 관측 — _candidate_obs 후보별 미서빙 사유 분류 (순수 함수·무DB, 항상 실행).
ROUTE_NEAREST_SERVE_DESIGN §6. 서빙 무영향·기록 전용 로직의 band/reject 분류 검증.
Run: python tests/test_candidate_obs.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import route_service as rs  # noqa: E402

_n = 0


def ok(m):
    global _n
    _n += 1
    print(f"  ✓ {m}")


def _obs(cases, target):
    """cases: [(km, engine, longest_retrace_m)] → _candidate_obs 결과."""
    scored, engine_of, spur_of = [], {}, {}
    for km, eng, rt in cases:
        r = object()                 # _candidate_obs는 id(r)만 씀(속성 미접근)
        scored.append((km, r))
        engine_of[id(r)] = eng
        spur_of[id(r)] = rt
    return rs._candidate_obs(scored, target, engine_of, spur_of)


def main():
    # target=5 → 밴드 [4.7, 5.5], 초과서빙창 (5.5, 6.0] retrace≤800
    print("[A. band/reject 분류 — target=5]")
    res = _obs([
        (5.0, "v87", 100),    # 밴드 내
        (4.4, "v87", 100),    # 언더(4.7 미만)
        (6.8, "v87", 100),    # 오버·창 밖(>6.0)
        (5.6, "v87", 900),    # 오버·창 내·retrace>800
        (5.6, "anchor", 100), # 오버·창 내·앵커
        (5.8, "v87", 100),    # 오버·창 내·합격(serveable 엣지)
    ], 5.0)
    by = {round(c["km"], 1): c for c in res}  # 주의: 5.6 두 건 → 뒤 것이 덮음(아래 개별 검증)

    assert by[5.0]["band"] == "in" and by[5.0]["reject"] == "in_band", by[5.0]
    ok("5.0 → in / in_band")
    assert by[4.4]["band"] == "under" and by[4.4]["reject"] == "out_of_band_under", by[4.4]
    ok("4.4 → under / out_of_band_under")
    assert by[6.8]["band"] == "over" and by[6.8]["reject"] == "out_of_band_over", by[6.8]
    ok("6.8 → over / out_of_band_over(창 밖)")
    assert by[5.8]["reject"] == "serveable_over", by[5.8]
    ok("5.8 → over / serveable_over(거리·retrace 합격)")

    # 5.6 두 건 개별(v87 retrace>800 / anchor)
    r56 = [c for c in res if round(c["km"], 1) == 5.6]
    rejects = {c["engine"]: c["reject"] for c in r56}
    assert rejects["v87"] == "retrace_over_cap", rejects
    assert rejects["anchor"] == "anchor_excluded", rejects
    ok("5.6 v87(retrace900)→retrace_over_cap · 5.6 anchor→anchor_excluded")

    print("\n[B. 필드 shape · engine·retrace 보존]")
    c = res[0]
    # SQ1(retrace_ratio·branch_count) + 회랑 1단계(friendly_ratio·retrace_friendly_m·
    # retrace_road_m·branch_count_strict) additive — 계약 확장 반영(총 11키).
    assert set(c) == {"km", "engine", "longest_retrace_m", "band", "reject",
                      "retrace_ratio", "branch_count", "friendly_ratio",
                      "retrace_friendly_m", "retrace_road_m", "branch_count_strict"}, set(c)
    assert c["km"] == 5.0 and c["engine"] == "v87" and c["longest_retrace_m"] == 100
    # mock r=object()엔 polyline 없음 → shape_obs·corridor_obs 예외 삼킴 → 지표 null(예외 안전)
    assert c["retrace_ratio"] is None and c["branch_count"] is None, c
    assert c["friendly_ratio"] is None and c["branch_count_strict"] is None, c
    ok("각 후보 11키(+friendly_ratio·retrace_friendly_m·retrace_road_m·branch_count_strict) · "
       "shape/corridor 예외 시 지표 null(안전)")

    print("\n[C. 빈 입력 · retrace None 내성]")
    assert rs._candidate_obs([], 5.0, {}, {}) == []
    ok("빈 scored → []")
    res2 = _obs([(5.7, "v87", None)], 5.0)  # retrace 미기록(None) — 창 내지만 컷 판정 불가
    assert res2[0]["reject"] == "serveable_over", res2  # None은 >800 아님 → 앵커/합격 분기
    ok("retrace=None → 예외 없이 분류(>800 미적용)")


if __name__ == "__main__":
    main()
    print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_n} assert)\n" + "=" * 50)
