"""
🛑 SUPERSEDED 2026-08-25 — 대상 시드(대전 어린이정원)가 미실행·등재 안 됨. 대전
그래프 공장 부적합 확정(deferred_realrun — 배경지도 육안 미수용, 실주 시드 대기).
이 테스트는 파일 geometry 검증이라 여전히 통과하나 코스는 비라이브 — 이력 보존용.
배경: CLAUDE.md "그래프 공장 원칙" · seed_qa_verdicts.json.

Integration: 대전 그래프 공장 핀포인트 시드 — 기하·형상·게이트 검증 (2026-08-25)

db/2026-08-25_seed_daejeon_graphfactory.sql 산출물 검증(광교·일산 동형 — 프라이버시
절 대체: graph_factory 산출이라 원 GPS 소유자 부재, 진입점 공공 실 POI 근접 assert).
대전=핀포인트 등재(클린율25%·한밭수목원 코어 한정). DB 무접촉(파일 파싱만).

E-1 진입점 실 POI(한밭수목원 어린이정원 AT4) 100m 내 + 이름원칙
G-1 폐합 0·실측 4,511m ±50·distance_km 합치
G-2 motorway/trunk 0m (rs._road_hit_m 대전 커버 확인분)
G-3 자기교차 0(형상 게이트)·이중≤5%·둘레비≤1.5
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
                        "db", "2026-08-25_seed_daejeon_graphfactory.sql")
POI_NAME = "한밭수목원 어린이정원"
POI = (36.36919, 127.38722)   # Kakao AT4 실 POI


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

    print("[E 진입점 — 공공 실 POI 근접 + 이름원칙(프라이버시 절 대체)]")
    assert len(aps) == 1 and poly[0] == aps[0], (len(aps), poly[0], aps[0])
    d = dm(aps[0], POI)
    assert d <= 100, (POI_NAME, d)
    m_name = re.search(r"insert into[\s\S]*?\(\s*'([^']+)'", sql)
    assert m_name and "한밭수목원" in m_name.group(1), m_name
    ok(f"E-1 진입점 실 POI '{POI_NAME}' {d:.0f}m · 코스명 실명 '{m_name.group(1)}'(이름원칙)")

    print("[G 기하·형상·게이트]")
    assert poly[0] == poly[-1] and len(poly) == 82
    total = sum(dm(poly[i], poly[i + 1]) for i in range(len(poly) - 1))
    assert abs(total - 4511) <= 50, total
    m = re.search(r"'대전',\s*([\d.]+)", sql)
    assert m and abs(float(m.group(1)) - total / 1000) <= 0.05, (m and m.group(1), total)
    ok(f"G-1 폐합 0 · 실측 {total:.0f}m · distance_km {m.group(1)} 합치 · 82점")

    hard_run, hard_total = rs._road_hit_m(list(poly), "hard")
    _, trunk_total = rs._road_hit_m(list(poly), "obs")
    assert hard_run == 0.0 and hard_total == 0.0 and trunk_total == 0.0
    ok("G-2 motorway·trunk 물림 0m (대전 도로 데이터 커버 확인분)")

    sc = self_intersections(list(poly))
    dr = double_run_ratio(list(poly))
    br = bbox_ratio(list(poly))
    spur = rs._spur_metrics([Coordinate(lat=p[0], lng=p[1]) for p in poly])
    assert sc == 0, ("자기교차", sc)
    assert dr <= 0.05 and br <= 1.5, (dr, br)
    ok(f"G-3 자기교차 {sc}(단일 폐곡선) · 이중 {dr*100:.0f}% · 둘레비 {br:.2f} · 회랑 {spur['longest_retrace_m']}m")

    print("\n전부 통과 — DB 무접촉·부수효과 0")


if __name__ == "__main__":
    run_tests()
