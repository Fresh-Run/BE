"""
Integration: 일산 그래프 공장 3호 지역 시드(2행) — 기하·형상·게이트 검증 (2026-08-25)

db/2026-08-25_seed_ilsan_graphfactory.sql 산출물 검증(청라·광교 1호 동형 —
프라이버시 절 대체: graph_factory 산출이라 원 GPS 소유자 부재. 진입점 공공 실 POI
근접 assert). **형상 축 신규**: self_intersections==0(단일 폐곡선). DB 무접촉.

행별:
  [장거리] 일산호수공원 주제광장 순환 8.62km — 진입점 주제광장, 회랑 30m
  [단거리] 일산호수공원 노래하는분수대 순환 3.97km — 진입점 노래하는분수대,
           회랑 183m(spur 오너 육안 통과 — 회랑<100 미적용, 형상 self_cross 0이 게이트)
공통: 폐합 0·거리 합치·motorway/trunk 0·자기교차 0·이중≤5%·둘레비≤1.5·이름원칙.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import Coordinate  # noqa: E402
from app.services import route_service as rs  # noqa: E402
from scripts.screen_seed_candidates import (  # noqa: E402
    bbox_ratio, double_run_ratio, self_intersections,
)

SQL_PATH = os.path.join(os.path.dirname(__file__), "..",
                        "db", "2026-08-25_seed_ilsan_graphfactory.sql")

# APPLY 순서: [0]장거리 [1]단거리. (name, POI명, POI좌표, distance_km, 실측m, pts)
ROWS = [
    ("일산호수공원 주제광장 순환", "일산호수공원 주제광장", (37.65507, 126.76754), 8.62, 8620, 157),
    ("일산호수공원 노래하는분수대 순환", "일산호수공원 노래하는분수대", (37.66395, 126.75769), 3.97, 3974, 78),
]


def ok(m):
    print(f"  ✓ {m}")


def dm(a, b):
    return rs._dist_km(Coordinate(lat=a[0], lng=a[1]),
                       Coordinate(lat=b[0], lng=b[1])) * 1000


def run_tests():
    sql = open(SQL_PATH).read()
    blobs = re.findall(r"'(\[\[.*?\]\])'::jsonb", sql, re.S)
    assert len(blobs) == 4, len(blobs)   # 2행 × (polyline + access_points)
    for idx, (name, poi_name, poi, dist_km, exp_m, exp_pts) in enumerate(ROWS):
        poly = [tuple(p) for p in json.loads(blobs[idx * 2])]
        aps = [tuple(p) for p in json.loads(blobs[idx * 2 + 1])]
        print(f"[{name}]")

        # E 진입점 — 공공 실 POI 근접 + 이름원칙(프라이버시 절 대체)
        assert len(aps) == 1 and poly[0] == aps[0] and len(poly) == exp_pts, \
            (len(aps), len(poly), exp_pts)
        d = dm(aps[0], poi)
        assert d <= 100, (poi_name, d)
        assert name in sql and "일산호수공원" in name, name   # 코스명 실 POI 실명
        ok(f"E 진입점 실 POI '{poi_name}' {d:.0f}m · 코스명 실명(이름원칙) · {exp_pts}점")

        # G-1 폐합·거리
        assert poly[0] == poly[-1]
        total = sum(dm(poly[i], poly[i + 1]) for i in range(len(poly) - 1))
        assert abs(total - exp_m) <= 50, (total, exp_m)
        assert abs(float(dist_km) - total / 1000) <= 0.05, (dist_km, total)
        ok(f"G-1 폐합 0 · 실측 {total:.0f}m · distance_km {dist_km} 합치")

        # G-2 도로 게이트
        hard_run, hard_total = rs._road_hit_m(list(poly), "hard")
        _, trunk_total = rs._road_hit_m(list(poly), "obs")
        assert hard_run == 0.0 and hard_total == 0.0 and trunk_total == 0.0
        ok("G-2 motorway·trunk 물림 0m")

        # G-3 형상: 자기교차 0(신규 게이트) + 이중≤5% + 둘레비≤1.5
        sc = self_intersections(list(poly))
        dr = double_run_ratio(list(poly))
        br = bbox_ratio(list(poly))
        spur = rs._spur_metrics([Coordinate(lat=p[0], lng=p[1]) for p in poly])
        assert sc == 0, ("자기교차", sc)
        assert dr <= 0.05 and br <= 1.5, (dr, br)
        ok(f"G-3 자기교차 {sc}(단일 폐곡선) · 이중 {dr*100:.0f}% · 둘레비 {br:.2f} · 회랑 {spur['longest_retrace_m']}m")

    print("\n전부 통과 — DB 무접촉·부수효과 0 (2행)")


if __name__ == "__main__":
    run_tests()
