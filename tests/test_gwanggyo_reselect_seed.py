"""
Integration: 광교 재등재 시드 — 원천호수 순환 3.27km (2026-08-25)

db/2026-08-25_seed_gwanggyo_reselect.sql 검증. 롤백된 원천습지(self_cross2·
street-grid)를 대체 — 같은 진입점, target 3.27km로 원천호수 수변 실순환.
광교/일산 동형(프라이버시 절 대체: 진입점 공공 실 POI 근접). DB 무접촉.

E-1 진입점 실 POI(광교호수공원 원천습지) 100m 내 + 이름원칙
G-1 폐합 0·실측 3,272m ±50·distance_km 합치
G-2 motorway/trunk 0m
G-3 자기교차 **≤1**(오너 배경지도 육안 통과 — 하단 62m 경미 spur, 십자 관통 아님.
    일산 self_cross0 표준의 배경지도 완화 사례) · 이중≤5% · 둘레비≤1.5
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
                        "db", "2026-08-25_seed_gwanggyo_reselect.sql")
POI_NAME = "광교호수공원 원천습지"
POI = (37.28546, 127.06267)


def ok(m):
    print(f"  ✓ {m}")


def dm(a, b):
    return rs._dist_km(Coordinate(lat=a[0], lng=a[1]),
                       Coordinate(lat=b[0], lng=b[1])) * 1000


def run_tests():
    sql = open(SQL_PATH).read()
    blobs = re.findall(r"'(\[\[.*?\]\])'::jsonb", sql, re.S)
    assert len(blobs) == 2, len(blobs)
    poly = [tuple(p) for p in json.loads(blobs[0])]
    aps = [tuple(p) for p in json.loads(blobs[1])]

    print("[E 진입점 — 공공 실 POI 근접 + 이름원칙]")
    assert len(aps) == 1 and poly[0] == aps[0] and len(poly) == 47, (len(aps), len(poly))
    d = dm(aps[0], POI)
    assert d <= 100, (POI_NAME, d)
    m_name = re.search(r"insert into[\s\S]*?\(\s*'([^']+)'", sql)
    assert m_name and "광교" in m_name.group(1) and "원천호수" in m_name.group(1), m_name
    ok(f"E-1 진입점 실 POI '{POI_NAME}' {d:.0f}m · 코스명 실명 '{m_name.group(1)}'(수변 실명·이름원칙)")

    print("[G 기하·형상·게이트]")
    assert poly[0] == poly[-1]
    total = sum(dm(poly[i], poly[i + 1]) for i in range(len(poly) - 1))
    assert abs(total - 3272) <= 50, total
    m = re.search(r"'광교',\s*([\d.]+)", sql)
    assert m and abs(float(m.group(1)) - total / 1000) <= 0.05, (m and m.group(1), total)
    ok(f"G-1 폐합 0 · 실측 {total:.0f}m · distance_km {m.group(1)} 합치")

    hard_run, hard_total = rs._road_hit_m(list(poly), "hard")
    _, trunk_total = rs._road_hit_m(list(poly), "obs")
    assert hard_run == 0.0 and hard_total == 0.0 and trunk_total == 0.0
    ok("G-2 motorway·trunk 물림 0m")

    sc = self_intersections(list(poly))
    dr = double_run_ratio(list(poly))
    br = bbox_ratio(list(poly))
    spur = rs._spur_metrics([Coordinate(lat=p[0], lng=p[1]) for p in poly])
    # self_cross ≤1 허용: 하단 62m 경미 spur(십자 관통 아님), 배경지도 원천호수 수변
    # 실추종 오너 육안 통과(2026-08-25). 일산 self_cross0 표준의 완화 근거.
    assert sc <= 1, ("자기교차 초과", sc)
    assert dr <= 0.05 and br <= 1.5, (dr, br)
    ok(f"G-3 자기교차 {sc}(≤1 허용·배경지도 수변추종 통과) · 이중 {dr*100:.0f}% · 둘레비 {br:.2f} · 회랑 {spur['longest_retrace_m']}m")

    print("\n전부 통과 — DB 무접촉·부수효과 0")


if __name__ == "__main__":
    run_tests()
