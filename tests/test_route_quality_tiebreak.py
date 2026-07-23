"""
Unit test: 품질 tiebreak (진단 E#2·#5, 2026-07-22)

밴드 내 복수 후보 선택을 [park_coverage desc · zigzag_score asc · 거리 asc]로.
공원 근접 후보가 지그재그 후보를 이기는지 + park/zigzag 헬퍼 정확성.

Run: python tests/test_route_quality_tiebreak.py
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import RouteResponse, Waypoint, Coordinate
from app.services.route_service import (
    _park_coverage, _zigzag_score, _best_in_band,
    _polyline_retrace, _polyline_max_gap_m, _spur_metrics,
)


def ok(m):  print(f"  ✓ {m}")
def fail(m): print(f"  ✗ {m}"); sys.exit(1)


def _wp(la, lo):
    return Waypoint(name="x", coordinate=Coordinate(lat=la, lng=lo), is_pitstop=False)


def route(coords):
    return RouteResponse(summary="x", total_distance_km=5.0,
                         waypoints=[_wp(la, lo) for la, lo in coords])


PARK = Coordinate(lat=37.5350, lng=126.6360)


def run_tests():
    print("[1. _park_coverage: 공원 300m 내 중간 웨이포인트 비율]")
    # 중간 2점 다 공원 근처(0m·~25m) → 1.0
    near = route([(37.530, 126.630), (37.5350, 126.6360), (37.5352, 126.6362), (37.530, 126.630)])
    assert _park_coverage(near, [PARK]) == 1.0, _park_coverage(near, [PARK])
    # 중간 2점 다 공원서 멂(2km+) → 0.0
    far = route([(37.530, 126.630), (37.520, 126.610), (37.515, 126.615), (37.530, 126.630)])
    assert _park_coverage(far, [PARK]) == 0.0, _park_coverage(far, [PARK])
    # park_coords 없으면 0.0(검색 실패 시)
    assert _park_coverage(near, []) == 0.0
    ok("공원 근접 1.0 · 원거리 0.0 · park_coords 없음 0.0")

    print("\n[2. _zigzag_score: 급반전(백트랙) 수]")
    # 매끈한 루프(사각형 근사) → 급반전 없음
    smooth = route([(37.530, 126.630), (37.535, 126.636), (37.532, 126.641),
                    (37.528, 126.635), (37.530, 126.630)])
    # 지그재그(위→시작근처아래→위→시작) → 급반전 다수
    zig = route([(37.530, 126.630), (37.540, 126.630), (37.531, 126.630),
                 (37.539, 126.631), (37.530, 126.630)])
    zs_smooth, zs_zig = _zigzag_score(smooth), _zigzag_score(zig)
    assert zs_zig > zs_smooth, f"지그재그({zs_zig})가 매끈({zs_smooth})보다 커야"
    ok(f"매끈 {zs_smooth} < 지그재그 {zs_zig} (급반전 카운트)")

    print("\n[3. _best_in_band: 공원 후보 > 지그재그 후보 (동밴드)]")
    A = near   # park 1.0, zig 0
    B = zig    # park 0.0(공원 무관 좌표), zig 높음
    # quals는 3-tuple (park, zig, retrace) — retrace는 여기선 0
    quals = {id(A): (_park_coverage(A, [PARK]), _zigzag_score(A), 0),
             id(B): (_park_coverage(B, [PARK]), _zigzag_score(B), 0)}
    in_band = [(5.0, A), (5.0, B)]
    _k, best = _best_in_band(in_band, 5.0, quals)
    assert best is A, "공원 커버리지 높은 후보 채택(지그재그 아님)"
    ok(f"동밴드 공원 후보(park {quals[id(A)][0]}) > 지그재그 후보(park {quals[id(B)][0]}) 채택")

    print("\n[4. tiebreak 계층: park 동률 → zigzag → retrace → 거리]")
    C, D = route([(37.53, 126.63)] * 4), route([(37.53, 126.63)] * 4)
    q2 = {id(C): (0.5, 0, 0), id(D): (0.5, 3, 0)}  # park 동률, zigzag 다름
    assert _best_in_band([(5.0, C), (5.0, D)], 5.0, q2)[1] is C, "park 동률 → zigzag 적은 것"
    q3 = {id(C): (0.5, 1, 0), id(D): (0.5, 1, 0)}  # park·zig·retrace 동률, 거리 다름
    assert _best_in_band([(4.9, C), (5.3, D)], 5.0, q3)[1] is C, "park·zig 동률 → 거리 근접"
    ok("park 동률→zigzag 적은 것 · park·zig 동률→거리 근접")

    print("\n[5. Phase 1 C — retrace tiebreak: park·zigzag 동률 → 되돌기 적은 후보]")
    # 이번 부검(de78d97c)의 핵심: zigzag 0 동률인데 스냅 되돌기가 다른 케이스
    q4 = {id(C): (0.5, 0, 0), id(D): (0.5, 0, 5)}  # park·zig 동률, retrace 다름
    assert _best_in_band([(5.0, C), (5.0, D)], 5.0, q4)[1] is C, "park·zig 동률 → retrace 적은 것"
    ok("park·zig 동률에서 되돌기(retrace 0) 후보가 되밟기(retrace 5) 이김 — zigzag가 못 잡던 갭")

    print("\n[6. _polyline_retrace / _polyline_max_gap_m 정확성]")
    def C_(la, lo): return Coordinate(lat=la, lng=lo)
    # 깨끗한 직선(되돌기 0)
    clean = [C_(37.50, 126.60 + i * 0.001) for i in range(10)]
    assert _polyline_retrace(clean) == 0, f"직선 되돌기 0, got {_polyline_retrace(clean)}"
    # 되돌기: 동쪽 갔다가 같은 점들로 되돌아옴
    out = [C_(37.50, 126.60 + i * 0.001) for i in range(6)]
    back = out[::-1]
    retr = _polyline_retrace(out + back[1:])
    assert retr > 0, f"왕복 궤적 retrace>0, got {retr}"
    # 최대 갭: 점 사이 큰 점프
    gap_pl = [C_(37.50, 126.60), C_(37.50, 126.601), C_(37.52, 126.63)]  # 마지막 큰 점프
    mg = _polyline_max_gap_m(gap_pl)
    assert mg > 2000, f"큰 점프 max_gap>2km, got {mg}"
    assert _polyline_max_gap_m([]) == 0.0 and _polyline_max_gap_m([C_(37.5, 126.6)]) == 0.0
    ok(f"직선 retrace 0 · 왕복 retrace {retr} · max_gap {mg}m · 빈/단일 0.0")

    print("\n[7. 밴드 내 1개 → 현행대로(tiebreak 미적용)]")
    assert _best_in_band([(5.2, A)], 5.0, quals)[1] is A
    ok("단일 후보는 그대로 반환")

    print("\n[8. _spur_metrics: 이중주행 회랑 길이(체감, §8.16)]")
    def C2(la, lo): return Coordinate(lat=la, lng=lo)
    # 동쪽 ~440m 나갔다 같은 점들로 복귀 = 왕복 회랑 ~440m
    out = [C2(37.50, 126.60 + i * 0.001) for i in range(5)]  # 각 ~88m, 4구간 ~350m
    spur = out + out[::-1][1:]
    sm = _spur_metrics(spur)
    assert sm["longest_retrace_m"] >= 250, f"왕복 회랑 길이 포착, got {sm}"
    assert sm["long_spur_count"] >= 1, sm
    # 깨끗한 사각 루프(되밟기 없음) → longest ~0
    loop = [C2(37.50, 126.60), C2(37.505, 126.60), C2(37.505, 126.605),
            C2(37.50, 126.605), C2(37.50, 126.60)]
    sl = _spur_metrics(loop)
    assert sl["longest_retrace_m"] == 0, f"깨끗한 루프 회랑 0, got {sl}"
    ok(f"왕복 회랑 {sm['longest_retrace_m']}m 포착 · 깨끗한 루프 0 · 빈/단일 안전")
    assert _spur_metrics([]) == {"longest_retrace_m": 0, "long_spur_count": 0, "micro_reversals": 0}

    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)


if __name__ == "__main__":
    run_tests()
