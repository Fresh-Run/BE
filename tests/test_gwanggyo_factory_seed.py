"""
Integration: 광교 그래프 공장 2호 지역 시드 — 기하·게이트 검증 (2026-08-25)

db/2026-08-25_seed_gwanggyo_graphfactory1_draft.sql 산출물 검증(청라 1호 동형 —
프라이버시 절 대체: graph_factory 산출이라 원 GPS 소유자·자택 개념 부재. 대신
진입점이 공공 실 POI(광교호수공원 원천습지) 근접임을 assert). DB 무접촉(파일 파싱만).

E-1 진입점 1점 — 공공 실 POI(광교호수공원 원천습지) 100m 내 + 이름원칙(코스명이 실 POI)
G-1 루프 폐합(첫=끝)·실측 3,656m ±50m·distance_km 합치(±0.05)
G-2 §8.20 — motorway 하드 물림 0m·trunk 0m (rs._road_hit_m 광교 커버 확인분)
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
                        "db", "2026-08-25_seed_gwanggyo_graphfactory1_draft.sql")
# 광교호수공원 원천습지 (Kakao 실 POI, 상업 상호차용 배제 필터 통과분)
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

    print("[E 진입점 — 공공 실 POI 근접 + 이름원칙(프라이버시 절 대체 — 원 소유자 부재)]")
    assert len(aps) == 1 and poly[0] == aps[0], (len(aps), poly[0], aps[0])
    d = dm(aps[0], POI)
    assert d <= 100, (POI_NAME, d)
    # 이름원칙: 코스명이 실 POI 실명(발명 아님) — 진입점 근접이 실명 근거
    m_name = re.search(r"insert into[\s\S]*?\(\s*'([^']+)'", sql)
    assert m_name and "광교호수공원" in m_name.group(1), m_name
    ok(f"E-1 진입점 실 POI '{POI_NAME}' {d:.0f}m 내 · 코스명 실명 '{m_name.group(1)}'(이름원칙)")

    print("[G 기하·게이트]")
    assert poly[0] == poly[-1]
    total = sum(dm(poly[i], poly[i + 1]) for i in range(len(poly) - 1))
    assert abs(total - 3656) <= 50, total
    m = re.search(r"'광교',\s*([\d.]+)", sql)
    assert m and abs(float(m.group(1)) - total / 1000) <= 0.05, (m and m.group(1), total)
    ok(f"G-1 폐합 0 · 실측 {total:.0f}m · distance_km {m.group(1)} 합치")

    hard_run, hard_total = rs._road_hit_m(list(poly), "hard")
    _, trunk_total = rs._road_hit_m(list(poly), "obs")
    assert hard_run == 0.0 and hard_total == 0.0 and trunk_total == 0.0, (hard_run, trunk_total)
    ok("G-2 motorway·trunk 물림 0m (광교 도로 데이터 커버 확인분)")

    dr = double_run_ratio(list(poly))
    br = bbox_ratio(list(poly))
    spur = rs._spur_metrics([Coordinate(lat=p[0], lng=p[1]) for p in poly])
    assert dr <= 0.05 and br <= 1.5 and spur["longest_retrace_m"] < 100, (dr, br, spur)
    ok(f"G-3 이중 {dr*100:.0f}% · 둘레비 {br:.2f} · 회랑 {spur['longest_retrace_m']}m")

    print("\n전부 통과 — DB 무접촉·부수효과 0")


if __name__ == "__main__":
    run_tests()
