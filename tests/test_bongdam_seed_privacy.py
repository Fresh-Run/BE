"""
Integration: 봉담 상리 캐노니컬 시드 초안 — 프라이버시·기하 검증 (2026-08-18)

db/2026-08-18_seed_bongdam_sangri_draft.sql 산출물 검증(팽성 전례 동형). DB는
run_tracks 읽기 전용 조회만(원 좌표 하드코딩 방지 — 런타임 대조). 부수효과 0.

P-1 원 시작·종료 정확 좌표 polyline 부재(양끝 40m 트림 소거)
P-2 polyline[0]=공공 진입점(하늘하늘어린이공원측) — 원 시작 ≥300m
P-3 access_points 3점 전부 원 시작·종료 ≥300m
G-1 루프 폐합(첫=끝)·실측 2,968m ±50m·distance_km 합치(±0.05)
G-2 §8.20 — motorway 하드 물림 0m
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.models.schemas import Coordinate  # noqa: E402
from app.services import route_service as rs  # noqa: E402

SQL_PATH = os.path.join(os.path.dirname(__file__), "..",
                        "db", "2026-08-18_seed_bongdam_sangri_draft.sql")
RUN_PREFIX = "2d420f54"
ENTRY = (37.221523, 126.946373)


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

    sb = get_supabase_admin()
    rid = next(t["run_id"] for t in
               sb.table("run_tracks").select("run_id").limit(1000).execute().data
               if t["run_id"].startswith(RUN_PREFIX))
    pts = sb.table("run_tracks").select("points").eq("run_id", rid).execute().data[0]["points"]
    orig_s = (pts[0]["lat"], pts[0]["lng"])
    orig_e = (pts[-1]["lat"], pts[-1]["lng"])

    print("[P 프라이버시]")
    flat = {(round(p[0], 6), round(p[1], 6)) for p in poly}
    assert (round(orig_s[0], 6), round(orig_s[1], 6)) not in flat
    assert (round(orig_e[0], 6), round(orig_e[1], 6)) not in flat
    ok("P-1 원 시작·종료 정확 좌표 부재")
    assert poly[0] == ENTRY and dm(poly[0], orig_s) >= 300
    ok(f"P-2 진입점 공공 지점 · 원시작 {dm(poly[0], orig_s):.0f}m")
    assert len(aps) == 3
    for ap in aps:
        assert dm(ap, orig_s) >= 300 and dm(ap, orig_e) >= 300, ap
    ok("P-3 진입점 3점 전부 300m+ 이격")

    print("[G 기하]")
    assert poly[0] == poly[-1]
    total = sum(dm(poly[i], poly[i + 1]) for i in range(len(poly) - 1))
    assert abs(total - 2968) <= 50, total
    m = re.search(r"'봉담',\s*([\d.]+)", sql)
    assert m and abs(float(m.group(1)) - total / 1000) <= 0.05
    ok(f"G-1 폐합 0 · 실측 {total:.0f}m · distance_km {m.group(1)} 합치")
    hard_run, hard_total = rs._road_hit_m(list(poly), "hard")
    assert hard_run == 0.0 and hard_total == 0.0
    ok("G-2 motorway 하드 물림 0m")
    print("\n전부 통과 — DB 읽기 전용·부수효과 0")


if __name__ == "__main__":
    run_tests()
