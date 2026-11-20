"""코스 오르막(고도) + 모양(shape) 지표 실측 — 읽기 전용(DB select + 무료 고도 API).

HILL_AVOID_DESIGN / ROUTE_SHAPE_QUALITY_DESIGN 근거 수집용 1회성 측정 도구.
DB의 기존 서빙 코스 polyline을 읽어(쓰기 0):
  (고도) 샘플 간격별 누적 상승(m)·km당 상승·최대 구간 경사(%) — Open-Meteo Elevation API
         (무료·비상용 전용, Copernicus DEM GLO-90 90m, 100좌표/콜). 연구용 소량 호출만.
  (모양) 왕복 비율·최장 왕복(m)·막다른 가지 수·자기교차 수·km당 급회전.

실행:
  python scripts/measure_hill_shape.py                 # 기본 3코스(한남동/여의도/성북동) 전체
  python scripts/measure_hill_shape.py --no-elevation  # 모양 지표만(고도 API 미호출)
  python scripts/measure_hill_shape.py --ids <uuid> ... # 임의 route_id

주의: 단일 DB=프로덕션. 이 스크립트는 select만(쓰기·수정 0). 고도 API는 무료 비상용 티어.
"""
from __future__ import annotations

import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.core.supabase_client import get_supabase_admin  # noqa: E402

# 실측 사례(2026-11-20) 기본 코스
DEFAULT_IDS = {
    "한남동(남산자락·오르막 제보 2026-11-20, 5.0→5.6km)": "0b1c2cf6-24ee-4271-b813-7a6bd5ce1f8a",
    "여의도공원(평지 대조)": "81896ec0-cd65-4f1c-a0c6-5da14774a361",
    "성북동(모양 제보 2026-11-20, 5.0→4.8km)": "27acb82e-8196-4252-aac8-ee1d026cb1d3",
}
_ELEV_URL = "https://api.open-meteo.com/v1/elevation"
_EARTH_M = 6371000.0


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * _EARTH_M * math.asin(math.sqrt(h))


def _pts(polyline):
    """polyline(jsonb) → [(lat,lng)]. {lat,lng} 또는 [lat,lng] 모두 수용."""
    out = []
    for p in polyline or []:
        if isinstance(p, dict):
            out.append((p["lat"], p["lng"]))
        else:
            out.append((p[0], p[1]))
    return out


def _resample(pts, step_m):
    """경로를 step_m 등간격으로 재샘플 → [(lat,lng)]."""
    if len(pts) < 2:
        return pts
    out = [pts[0]]
    carry = 0.0
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        seg = hav(a, b)
        if seg == 0:
            continue
        d = carry
        while d + step_m <= seg:
            d += step_m
            t = d / seg
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        carry = (d + step_m) - seg if False else (seg - d)
    out.append(pts[-1])
    return out


def _fetch_elev(samples):
    """Open-Meteo 고도 — 100개씩 배치. 실패 시 None(폴백 시뮬: 고도 조회 실패 경로)."""
    elevs = []
    with httpx.Client(timeout=20) as c:
        for i in range(0, len(samples), 100):
            chunk = samples[i:i + 100]
            lat = ",".join(f"{p[0]:.5f}" for p in chunk)
            lng = ",".join(f"{p[1]:.5f}" for p in chunk)
            r = c.get(_ELEV_URL, params={"latitude": lat, "longitude": lng})
            r.raise_for_status()
            elevs.extend(r.json()["elevation"])
            time.sleep(0.3)  # 공손한 호출 간격
    return elevs


def elevation_metrics(pts, step_m):
    samples = _resample(pts, step_m)
    elev = _fetch_elev(samples)
    cum_up = 0.0
    max_grade = 0.0
    for i in range(1, len(samples)):
        de = elev[i] - elev[i - 1]
        if de > 0:
            cum_up += de
        horiz = hav(samples[i - 1], samples[i])
        if horiz > 1:
            max_grade = max(max_grade, abs(de) / horiz * 100)
    total_km = sum(hav(samples[i - 1], samples[i]) for i in range(1, len(samples))) / 1000
    return {"step_m": step_m, "n_samples": len(samples), "total_km": round(total_km, 2),
            "cum_ascent_m": round(cum_up), "ascent_per_km": round(cum_up / total_km) if total_km else 0,
            "max_grade_pct": round(max_grade, 1)}


# ── 모양(shape) 지표 — 고도 무관, polyline 기하만 ──────────────────────────
_NEAR_M = 20.0  # route_service._RETRACE_NEAR_M 와 동일 개념


def _seg_pt_dist(p, a, b):
    """점 p와 선분 a-b의 근사 최단거리(m) — 로컬 평면 근사."""
    # 위경도 → 로컬 m (p 기준)
    def to_m(q):
        return ((q[1] - p[1]) * 111320 * math.cos(math.radians(p[0])),
                (q[0] - p[0]) * 110540)
    ax, ay = to_m(a)
    bx, by = to_m(b)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(ax, ay)
    t = max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(cx, cy)


def _segs_cross(p1, p2, p3, p4):
    """선분 p1p2 와 p3p4 교차 여부(2D 로컬 근사)."""
    def o(a, b, c):
        return (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
    d1, d2 = o(p3, p4, p1), o(p3, p4, p2)
    d3, d4 = o(p1, p2, p3), o(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def shape_metrics(pts):
    n = len(pts)
    seg_len = [hav(pts[i], pts[i + 1]) for i in range(n - 1)]
    total_m = sum(seg_len)
    # 왕복: 각 점이 비인접 선분의 _NEAR_M 내인지 → 왕복 점. 인접(±2) 제외.
    retraced = [False] * n
    for i in range(n):
        for j in range(n - 1):
            if abs(j - i) <= 2 or abs(j + 1 - i) <= 2:
                continue
            if _seg_pt_dist(pts[i], pts[j], pts[j + 1]) < _NEAR_M:
                retraced[i] = True
                break
    retrace_m = sum(seg_len[i] for i in range(n - 1) if retraced[i] and retraced[i + 1])
    # 왕복 run(연속) → 최장·가지 수(>50m run)
    runs, cur = [], 0.0
    for i in range(n - 1):
        if retraced[i] and retraced[i + 1]:
            cur += seg_len[i]
        elif cur > 0:
            runs.append(cur); cur = 0.0
    if cur > 0:
        runs.append(cur)
    # 자기교차(비인접 선분쌍)
    cross = 0
    for i in range(n - 1):
        for j in range(i + 2, n - 1):
            if i == 0 and j == n - 2:  # 폐곡선 시작/끝 인접
                continue
            if _segs_cross(pts[i], pts[i + 1], pts[j], pts[j + 1]):
                cross += 1
    # 급회전/km (꼭짓점 회전각 > 100°)
    sharp = 0
    for i in range(1, n - 1):
        v1 = (pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        v2 = (pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        m1, m2 = math.hypot(*v1), math.hypot(*v2)
        if m1 == 0 or m2 == 0:
            continue
        cosang = max(-1, min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / (m1 * m2)))
        turn = math.degrees(math.acos(cosang))
        if turn > 100:
            sharp += 1
    km = total_m / 1000
    return {"total_km": round(km, 2), "n_points": n,
            "retrace_ratio_pct": round(retrace_m / total_m * 100, 1) if total_m else 0,
            "retrace_m": round(retrace_m), "longest_retrace_m": round(max(runs, default=0)),
            "n_branches_gt50m": sum(1 for r in runs if r > 50),
            "self_cross": cross, "sharp_turns_per_km": round(sharp / km, 1) if km else 0}


def distribution(n):
    """최근 서빙 순환 코스 n개의 shape 지표 분포(읽기 전용) — 성북동 위치 확인용."""
    sb = get_supabase_admin()
    rows = sb.table("routes").select("id,polyline,total_distance_km,target_distance_km") \
        .eq("is_one_way", False).order("created_at", desc=True).limit(n).execute().data
    import statistics as st
    keys = ["retrace_ratio_pct", "longest_retrace_m", "n_branches_gt50m", "sharp_turns_per_km"]
    acc = {k: [] for k in keys}
    for r in rows:
        pts = _pts(r["polyline"])
        if len(pts) < 4:
            continue
        sm = shape_metrics(pts)
        for k in keys:
            acc[k].append(sm[k])
    print(f"=== shape 분포 (최근 순환 {len(acc[keys[0]])}개) ===")
    def pct(v, q):
        s = sorted(v)
        return s[min(len(s) - 1, int(q * len(s)))]
    for k in keys:
        v = acc[k]
        print(f"  {k:20} median={st.median(v):.1f} p75={pct(v,0.75):.1f} "
              f"p90={pct(v,0.90):.1f} max={max(v):.1f}")
    return acc


def main():
    argv = sys.argv[1:]
    no_elev = "--no-elevation" in argv
    if "--dist" in argv:
        distribution(int(argv[argv.index("--dist") + 1]))
        return
    ids = None
    if "--ids" in argv:
        ids = {f"route[{i}]": v for i, v in enumerate(argv[argv.index("--ids") + 1:])}
    targets = ids or DEFAULT_IDS

    sb = get_supabase_admin()
    for label, rid in targets.items():
        rows = sb.table("routes").select("id,polyline,total_distance_km,target_distance_km,summary") \
            .eq("id", rid).limit(1).execute().data
        if not rows:
            print(f"\n### {label}: route {rid} 없음"); continue
        row = rows[0]
        pts = _pts(row["polyline"])
        print(f"\n### {label}")
        print(f"  route={row['id'][:8]} target={row.get('target_distance_km')} "
              f"total={row['total_distance_km']} '{(row.get('summary') or '')[:24]}' points={len(pts)}")
        sm = shape_metrics(pts)
        print(f"  [SHAPE] retrace={sm['retrace_ratio_pct']}%({sm['retrace_m']}m) "
              f"longest_retrace={sm['longest_retrace_m']}m branches>50m={sm['n_branches_gt50m']} "
              f"self_cross={sm['self_cross']} sharp_turns/km={sm['sharp_turns_per_km']}")
        if not no_elev:
            for step in (100, 50, 30):
                em = elevation_metrics(pts, step)
                print(f"  [ELEV step={step}m] samples={em['n_samples']} "
                      f"cum_ascent={em['cum_ascent_m']}m ({em['ascent_per_km']}m/km) "
                      f"max_grade={em['max_grade_pct']}%")


if __name__ == "__main__":
    main()
