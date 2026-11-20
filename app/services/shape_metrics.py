"""코스 모양(shape) 지표 — 순수 함수(폴리라인 기하만, DB·외부 호출 0).

SQ1 관측(ROUTE_SHAPE_QUALITY_DESIGN) 단일 소스. app(서빙 성공/실패 기록)과
scripts/measure_hill_shape.py가 **같은 `_retrace_runs`를 공유**해 결과가 일치한다.

- retrace_ratio(polyline): 왕복 구간 길이 비율(0~1). <4점이면 None.
- branch_count(polyline): 막다른 가지(>50m 연속 왕복 run) 개수. <4점이면 None.

polyline 원소는 Coordinate(.lat/.lng)·dict({lat,lng})·tuple((lat,lng)) 모두 수용.
⚠️ 서빙 판정에 쓰지 않는다(관측 전용). self_cross는 밀집 polyline 과다카운트라 여기 없음.
"""
from __future__ import annotations

import math

_EARTH_M = 6371000.0
_NEAR_M = 20.0        # route_service._RETRACE_NEAR_M 와 동일 개념(왕복 근접 판정)
_BRANCH_MIN_M = 50.0  # 이 길이 초과 연속 왕복 run = 막다른 가지 1개


def _latlng(p):
    if hasattr(p, "lat"):          # Coordinate 모델
        return (p.lat, p.lng)
    if isinstance(p, dict):        # DB jsonb {lat,lng}
        return (p["lat"], p["lng"])
    return (p[0], p[1])            # tuple/list


def _norm(polyline):
    return [_latlng(p) for p in (polyline or [])]


def _hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * _EARTH_M * math.asin(math.sqrt(h))


def _seg_pt_dist(p, a, b):
    """점 p와 선분 a-b의 근사 최단거리(m) — p 기준 로컬 평면."""
    def to_m(q):
        return ((q[1] - p[1]) * 111320 * math.cos(math.radians(p[0])),
                (q[0] - p[0]) * 110540)
    ax, ay = to_m(a)
    bx, by = to_m(b)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(cx, cy)


def _retraced_flags(pts):
    """각 점이 비인접(±2 밖) 선분의 _NEAR_M 내인가(=왕복 점). 공간 격자 가속 — O(n) 기대.

    ⚠️ 결과는 브루트포스 O(n²)와 **완전 동일**(격자는 후보 선분 프루닝만, 최종 거리 판정은
    동일한 _seg_pt_dist<_NEAR_M). 격자 셀=_NEAR_M, 선분을 'bbox±_NEAR_M'이 닿는 셀에 버킷팅 →
    점의 **자기 셀**만 조회해도 _NEAR_M 내 선분을 전부 포함(정확 판정은 _seg_pt_dist가 프루닝).
    """
    n = len(pts)
    ref = pts[0]
    cos_ref = math.cos(math.radians(ref[0]))

    def xy(q):  # 공통 로컬 평면(ref 기준) — 격자 버킷팅 전용(거리 판정은 _seg_pt_dist)
        return ((q[1] - ref[1]) * 111320 * cos_ref, (q[0] - ref[0]) * 110540)

    cell = _NEAR_M
    P = [xy(p) for p in pts]
    grid: dict = {}
    for j in range(n - 1):
        (ax, ay), (bx, by) = P[j], P[j + 1]
        cx0 = int((min(ax, bx) - cell) // cell); cx1 = int((max(ax, bx) + cell) // cell)
        cy0 = int((min(ay, by) - cell) // cell); cy1 = int((max(ay, by) + cell) // cell)
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                grid.setdefault((cx, cy), []).append(j)

    flags = [False] * n
    for i in range(n):
        px, py = P[i]
        for j in grid.get((int(px // cell), int(py // cell)), ()):
            if abs(j - i) <= 2 or abs(j + 1 - i) <= 2:
                continue
            if _seg_pt_dist(pts[i], pts[j], pts[j + 1]) < _NEAR_M:
                flags[i] = True
                break
    return flags


def _retrace_runs(pts):
    """(retrace_m, total_m, runs[각 연속 왕복 run 길이]) — app·script 공유 코어.

    각 점 i가 비인접(±2 밖) 선분의 _NEAR_M 내면 '왕복 점'. 연속 왕복 선분을 run으로 묶음.
    점-선분 근접 판정은 _retraced_flags(격자 가속, 브루트포스와 동일 결과)에 위임.
    """
    n = len(pts)
    if n < 4:
        return 0.0, 0.0, []
    seg_len = [_hav(pts[i], pts[i + 1]) for i in range(n - 1)]
    total_m = sum(seg_len)
    retraced = _retraced_flags(pts)
    retrace_m = sum(seg_len[i] for i in range(n - 1) if retraced[i] and retraced[i + 1])
    runs, cur = [], 0.0
    for i in range(n - 1):
        if retraced[i] and retraced[i + 1]:
            cur += seg_len[i]
        elif cur > 0:
            runs.append(cur)
            cur = 0.0
    if cur > 0:
        runs.append(cur)
    return retrace_m, total_m, runs


def retrace_ratio(polyline):
    """왕복 구간 길이 비율(0~1, 소수 4자리). <4점·길이 0이면 None."""
    retrace_m, total_m, _ = _retrace_runs(_norm(polyline))
    if total_m <= 0:
        return None
    return round(retrace_m / total_m, 4)


def branch_count(polyline):
    """막다른 가지(>50m 연속 왕복 run) 개수. <4점이면 None."""
    pts = _norm(polyline)
    if len(pts) < 4:
        return None
    _, _, runs = _retrace_runs(pts)
    return sum(1 for r in runs if r > _BRANCH_MIN_M)


# 러닝 친화 roadType(SQ 회랑 1단계, RUNNING_CORRIDOR_DESIGN) — T-map 보행자 roadType.
# 21=보행자도로1(차도 분리 보도 — 가장 러닝 친화)만 friendly로 분류. 22·23·24(미분리/대로변/
# 불쾌)·0·None은 non-friendly. ⚠️ roadType 의미는 2차 출처(블로그)라 강변북로=23 같은 반례
# 존재 — 보수적으로 21만 채택. **name 기반 회랑 멤버십(4단계 회랑 데이터)로 정밀화 예정**.
_FRIENDLY_ROADTYPES = frozenset({"21"})
_BRANCH_STRICT_M = 150.0   # 막다른 가지 보정: 이 길이 초과 run만 가지로(50m는 왕복 노이즈 과다)


def branch_count_strict(polyline):
    """막다른 가지(>150m 연속 왕복 run) 개수 — branch_count(>50m)의 노이즈 보정판. <4점 None."""
    pts = _norm(polyline)
    if len(pts) < 4:
        return None
    _, _, runs = _retrace_runs(pts)
    return sum(1 for r in runs if r > _BRANCH_STRICT_M)


def _seg_roadtypes(pts, road_segments):
    """polyline 선분(n-1개)별 roadType(str) — road_segments 누적거리로 정렬 매칭(근사)."""
    seg_len = [_hav(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    rs = [(str(rt), float(d or 0)) for rt, _name, d in road_segments if (d or 0) > 0]
    out, ri, consumed = [], 0, 0.0
    for sl in seg_len:
        if ri < len(rs):
            out.append(rs[ri][0])
            consumed += sl
            if consumed >= rs[ri][1]:
                ri += 1
                consumed = 0.0
        else:
            out.append(None)
    return out


def corridor_obs(polyline, road_segments) -> dict:
    """회랑 1단계 관측(RUNNING_CORRIDOR_DESIGN) — friendly_ratio·왕복 친화/도로 분할·보정 가지수.

    반환 {friendly_ratio(0~1|None), retrace_friendly_m, retrace_road_m, branch_count_strict}.
    road_segments 없으면(canonical 등) friendly/split은 None, branch_count_strict만 계산.
    순수 함수 — 호출측(서빙 성공/실패 기록)이 예외를 삼킨다.
    """
    pts = _norm(polyline)
    res = {"friendly_ratio": None, "retrace_friendly_m": None,
           "retrace_road_m": None, "branch_count_strict": None}
    if len(pts) >= 4:
        _, _, runs = _retrace_runs(pts)
        res["branch_count_strict"] = sum(1 for r in runs if r > _BRANCH_STRICT_M)
    if not road_segments:
        return res
    total = sum(float(d or 0) for _, _, d in road_segments)
    if total > 0:
        fr = sum(float(d or 0) for rt, _, d in road_segments
                 if str(rt) in _FRIENDLY_ROADTYPES)
        res["friendly_ratio"] = round(fr / total, 4)
    if len(pts) >= 4:
        flags = _retraced_flags(pts)
        segrt = _seg_roadtypes(pts, road_segments)
        seg_len = [_hav(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        f = r = 0.0
        for i in range(len(pts) - 1):
            if flags[i] and flags[i + 1]:
                if str(segrt[i]) in _FRIENDLY_ROADTYPES:
                    f += seg_len[i]
                else:
                    r += seg_len[i]
        res["retrace_friendly_m"] = round(f)
        res["retrace_road_m"] = round(r)
    return res


def shape_obs(polyline) -> dict:
    """retrace_ratio + branch_count를 **_retrace_runs 1회로** 계산(개별 호출보다 2배 빠름).

    SQL1 기록용. 반환 {'retrace_ratio': 0~1|None, 'branch_count': int|None}.
    호출측(서빙 성공/실패 기록)이 예외를 삼키므로 여기선 degenerate만 None 처리.
    """
    pts = _norm(polyline)
    if len(pts) < 4:
        return {"retrace_ratio": None, "branch_count": None}
    retrace_m, total_m, runs = _retrace_runs(pts)
    return {
        "retrace_ratio": round(retrace_m / total_m, 4) if total_m > 0 else None,
        "branch_count": sum(1 for r in runs if r > _BRANCH_MIN_M),
    }
