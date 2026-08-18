"""
Integration: 청라 그래프 공장 1호 시드 초안 — 기하·게이트 검증 (2026-08-19)

db/2026-08-19_seed_cheongna_graphfactory1_draft.sql 산출물 검증(봉담 동형 —
단, **프라이버시 절 축소 근거**: graph_factory 산출이라 원 GPS 소유자·자택
개념이 없다(그래프 노드 좌표) — 원 좌표 대조 절 해당 없음. 대신 진입점이
공공 POI 근접임을 assert). DB 무접촉(파일 파싱만).

E-1 진입점 3점 — 공공 POI(백조자리공원·변전공원·청람초) 각 100m 내
G-1 루프 폐합(첫=끝)·실측 4,640m ±50m·distance_km 합치(±0.05)
G-2 §8.20 — motorway 하드 물림 0m·trunk 0m
G-3 §8.19 보조 — 이중주행 ≤5%·bbox 둘레비 ≤1.5·왕복 회랑 <100m
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import Coordinate  # noqa: E402
from app.services import route_service as rs  # noqa: E402
from scripts.screen_seed_candidates import bbox_ratio, double_run_ratio  # noqa: E402

SQL_PATH = os.path.join(os.path.dirname(__file__), "..",
                        "db", "2026-08-19_seed_cheongna_graphfactory1_draft.sql")
POIS = {"백조자리공원": (37.5365717, 126.6426587),
        "변전공원": (37.5408837, 126.6476340),
        "인천청람초등학교": (37.5390642, 126.6445765)}


def ok(m):
    print(f"  ✓ {m}")


def dm(a, b):
    return rs._dist_km(Coordinate(lat=a[0], lng=a[1]),
                       Coordinate(lat=b[0], lng=b[1])) * 1000


def run_tests():
    sql = open(SQL_PATH).read()
    blobs = re.findall(r"'(\[\[.*?\]\])'::jsonb", sql, re.S)
    assert len(blobs) == 2
    poly = [tuple(p) for p in json.loads(blobs[0])]
    aps = [tuple(p) for p in json.loads(blobs[1])]

    print("[E 진입점 — 공공 POI 근접(프라이버시 절 대체 — 원 소유자 부재)]")
    assert len(aps) == 3 and poly[0] == aps[0]
    for ap, (name, pc) in zip(aps, POIS.items()):
        d = dm(ap, pc)
        assert d <= 100, (name, d)
    ok("E-1 진입점 3점 전부 실 POI 100m 내(백조자리·변전공원·청람초)")

    print("[G 기하·게이트]")
    assert poly[0] == poly[-1]
    total = sum(dm(poly[i], poly[i + 1]) for i in range(len(poly) - 1))
    assert abs(total - 4640) <= 50, total
    m = re.search(r"'청라',\s*([\d.]+)", sql)
    assert m and abs(float(m.group(1)) - total / 1000) <= 0.05
    ok(f"G-1 폐합 0 · 실측 {total:.0f}m · distance_km {m.group(1)} 합치")

    hard_run, hard_total = rs._road_hit_m(list(poly), "hard")
    _, trunk_total = rs._road_hit_m(list(poly), "obs")
    assert hard_run == 0.0 and hard_total == 0.0 and trunk_total == 0.0
    ok("G-2 motorway·trunk 물림 0m")

    dr = double_run_ratio(list(poly))
    br = bbox_ratio(list(poly))
    spur = rs._spur_metrics([Coordinate(lat=p[0], lng=p[1]) for p in poly])
    assert dr <= 0.05 and br <= 1.5 and spur["longest_retrace_m"] < 100, (dr, br, spur)
    ok(f"G-3 이중 {dr*100:.0f}% · 둘레비 {br:.2f} · 회랑 {spur['longest_retrace_m']}m")

    print("\n전부 통과 — DB 무접촉·부수효과 0")


if __name__ == "__main__":
    run_tests()
