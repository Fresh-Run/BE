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
    _polyline_retrace, _polyline_max_gap_m, _spur_metrics, _serveable_over_cap,
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
    _k, best, _tb = _best_in_band(in_band, 5.0, quals)
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

    print("\n[9. _serveable_over_cap: 앵커 제외 + spur 게이트 (00:51 신사 star 회귀)]")
    def C3(la, lo): return Coordinate(lat=la, lng=lo)
    def rt_pl(pl): return RouteResponse(summary="x", total_distance_km=6.0, polyline=pl,
                                        waypoints=[_wp(37.5, 127.0), _wp(37.5, 127.0)])
    clean = [C3(37.50, 127.00 + i * 0.001) for i in range(10)]  # 직선 → longest 0
    star = [C3(37.50, 127.00 + i * 0.0012) for i in range(8)]   # 나가서
    star = star + star[::-1][1:]                                 # 같은 길로 복귀 = 긴 팔(>800m)
    v87_clean = rt_pl(clean)   # v87 초과·spur 양호
    v87_star = rt_pl(star)     # v87 초과·긴 팔
    anc_clean = rt_pl(clean)   # 앵커 초과·spur 양호(그래도 제외돼야)
    eng = {id(v87_clean): "v87", id(v87_star): "v87", id(anc_clean): "anchor"}
    assert _spur_metrics(star)["longest_retrace_m"] > 800, _spur_metrics(star)
    # km 6.0 = target 5.0 초과 캡 내(≤6.0)
    over = _serveable_over_cap([(6.0, v87_clean), (6.0, v87_star), (6.0, anc_clean)], 5.0, eng)
    ids = {id(t[1]) for t in over}
    assert id(v87_clean) in ids, "v87 정상 초과는 서빙 자격"
    assert id(v87_star) not in ids, "v87이라도 긴 팔(>800)은 제외"
    assert id(anc_clean) not in ids, "앵커는 spur 양호해도 초과 서빙 제외(밴드 내만)"
    ok(f"v87 정상 초과만 자격 · v87 star 제외 · 앵커 제외 (자격 {len(over)}/3)")
    # 전멸 시(앵커 star만) → 빈 결과 → 상위가 재추첨/502
    only_bad = _serveable_over_cap([(6.0, v87_star), (6.0, anc_clean)], 5.0, eng)
    assert only_bad == [], "긴팔 v87+앵커만 → 초과 서빙 0(→band_cap_zero 재추첨/502)"
    ok("긴팔·앵커만 존재 → 초과 서빙 후보 0")

    print("\n[10. crossing 4순위 tiebreak (2026-08-03 승인 ⓐ)]")
    E, F = route([(37.53, 126.63)] * 4), route([(37.53, 126.63)] * 4)
    # 상위 3기준 동률 + crossing 차이 → crossing 낮은 쪽. engaged는 "승자가
    # 실제로 바뀐 개입"만 True(구키 선두와 같으면 False — 개입률 관측 정의)
    q5 = {id(E): (0.5, 0, 0, 9), id(F): (0.5, 0, 0, 3)}
    k, best, tb = _best_in_band([(5.0, E), (5.0, F)], 5.0, q5)
    assert best is F and tb is True, "동률 시 crossing 낮은 쪽 + 개입 플래그"
    q5b = {id(E): (0.5, 0, 0, 3), id(F): (0.5, 0, 0, 9)}
    k, best, tb = _best_in_band([(5.0, E), (5.0, F)], 5.0, q5b)
    assert best is E and tb is False, "구키 선두와 동일 승자면 개입 아님"
    # 상위 기준 비동률 → crossing이 역방향이어도 기존 선택(무교란)·engaged False
    q6 = {id(E): (0.9, 0, 0, 99), id(F): (0.5, 0, 0, 1)}
    k, best, tb = _best_in_band([(5.0, E), (5.0, F)], 5.0, q6)
    assert best is E and tb is False, "park 우위가 crossing 열세를 이김(무교란)"
    # None은 최후순위
    q7 = {id(E): (0.5, 0, 0, None), id(F): (0.5, 0, 0, 20)}
    k, best, tb = _best_in_band([(5.0, E), (5.0, F)], 5.0, q7)
    assert best is F and tb is True, "crossing None은 실값(20)보다 후순위"
    # 구형 3-튜플 quals 방어(스퍼 테스트 등 — crossing 없음 취급)
    q8 = {id(E): (0.5, 0, 0), id(F): (0.5, 0, 2)}
    assert _best_in_band([(5.0, E), (5.0, F)], 5.0, q8)[1] is E
    ok("동률 개입 ✓ 비동률 무교란 ✓ None 최후순위 ✓ 3-튜플 방어 ✓")

    print("\n[11. 재추첨 L tiebreak (2026-08-03 승인 ⓑ)]")
    from app.services.route_service import _redraw_pick_in_band
    def C4(la, lo): return Coordinate(lat=la, lng=lo)
    arm = [C4(37.50, 126.60 + i * 0.001) for i in range(8)]
    star_r = route([(37.5, 126.6)] * 4); star_r.polyline = arm + arm[::-1][1:]   # L 큼
    clean_r = route([(37.5, 126.6)] * 4); clean_r.polyline = [C4(37.50, 126.60), C4(37.505, 126.605)]
    # 0.1 버킷 동률(4.98 vs 5.02 — 근접차 0.02/0.02) → L 낮은 쪽
    k, best, tb = _redraw_pick_in_band([(4.98, star_r), (5.02, clean_r)], 5.0)
    assert best is clean_r and tb is True, "동률 버킷 → L 낮은 쪽"
    # 비동률(5.0 vs 5.4) → 기존 최근접 그대로(무교란 — star여도)
    k, best, tb = _redraw_pick_in_band([(5.0, star_r), (5.4, clean_r)], 5.0)
    assert best is star_r and tb is False, "거리 우위 무교란"
    # 단일 후보 그대로
    assert _redraw_pick_in_band([(5.2, star_r)], 5.0)[1] is star_r
    ok("0.1 버킷 동률 시 L 개입 ✓ 비동률 무교란 ✓ 단일 그대로 ✓")

    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)


if __name__ == "__main__":
    run_tests()
