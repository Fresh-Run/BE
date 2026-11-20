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


def _retrace_runs(pts):
    """(retrace_m, total_m, runs[각 연속 왕복 run 길이]) — app·script 공유 코어.

    각 점 i가 비인접(±2 밖) 선분의 _NEAR_M 내면 '왕복 점'. 연속 왕복 선분을 run으로 묶음.
    """
    n = len(pts)
    if n < 4:
        return 0.0, 0.0, []
    seg_len = [_hav(pts[i], pts[i + 1]) for i in range(n - 1)]
    total_m = sum(seg_len)
    retraced = [False] * n
    for i in range(n):
        pi = pts[i]
        for j in range(n - 1):
            if abs(j - i) <= 2 or abs(j + 1 - i) <= 2:
                continue
            if _seg_pt_dist(pi, pts[j], pts[j + 1]) < _NEAR_M:
                retraced[i] = True
                break
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
