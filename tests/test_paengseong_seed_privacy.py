"""
Integration: 팽성 송화리 캐노니컬 시드 초안 — 프라이버시·기하 검증 (2026-08-04)

시드 SQL(db/2026-08-04_seed_paengseong_songhwa_draft.sql) 산출물 검증. DB는
run_tracks **읽기 전용 조회만**(원 시작·종료 좌표 대조용 — 좌표를 레포에 하드코딩
하지 않기 위해 런타임 조회). 부수효과 0.

P-1 원 시작·종료 정확 좌표가 polyline에 부재(양끝 40m 보간 트림 소거)
P-2 polyline[0]=서단 공공 진입점 — 원 시작점과 ≥500m 이격
P-3 access_points 3점 전부 원 시작·종료와 ≥300m 이격 (자택 추정 지점 비노출)
P-4 진입점이 카드 대표점 후보(polyline[0]·access_points[0]) 어디서도 원 시작점 아님
G-1 루프 닫힘(첫=끝)·실측 길이 4,037m ±50m·distance_km 필드 합치(±0.05)
G-2 §8.20 게이트 — motorway 하드 물림 0m
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
                        "db", "2026-08-04_seed_paengseong_songhwa_draft.sql")
RUN_ID = "2c88acfc-5c95-4fbc-b6fe-6d8fa375c987"
ENTRY = (36.964317, 127.053579)   # 서단 도서관측(SQL 헤더와 동일)


def ok(m):
    print(f"  ✓ {m}")


def dm(a, b):
    return rs._dist_km(Coordinate(lat=a[0], lng=a[1]),
                       Coordinate(lat=b[0], lng=b[1])) * 1000


def run_tests():
    sql = open(SQL_PATH).read()
    blobs = re.findall(r"'(\[\[.*?\]\])'::jsonb", sql, re.S)
    assert len(blobs) == 2, "SQL에서 polyline/access_points 추출 실패"
    poly = [tuple(p) for p in json.loads(blobs[0])]
    aps = [tuple(p) for p in json.loads(blobs[1])]

    sb = get_supabase_admin()
    tr = sb.table("run_tracks").select("points").eq("run_id", RUN_ID).execute().data
    assert tr, "원 트랙 조회 실패(읽기 전용)"
    pts = tr[0]["points"]
    orig_s = (pts[0]["lat"], pts[0]["lng"])
    orig_e = (pts[-1]["lat"], pts[-1]["lng"])

    print("[P 프라이버시]")
    flat = {(round(p[0], 6), round(p[1], 6)) for p in poly}
    assert (round(orig_s[0], 6), round(orig_s[1], 6)) not in flat, "원 시작 좌표 잔존"
    assert (round(orig_e[0], 6), round(orig_e[1], 6)) not in flat, "원 종료 좌표 잔존"
    ok("P-1 원 시작·종료 정확 좌표 polyline 부재")

    assert poly[0] == ENTRY, poly[0]
    assert dm(poly[0], orig_s) >= 500, dm(poly[0], orig_s)
    ok(f"P-2 polyline[0]=서단 진입점 · 원시작 {dm(poly[0], orig_s):.0f}m 이격")

    assert len(aps) == 3
    for ap in aps:
        assert dm(ap, orig_s) >= 300, (ap, dm(ap, orig_s))
        assert dm(ap, orig_e) >= 300, (ap, dm(ap, orig_e))
    ok("P-3 진입점 3점 전부 원 시작·종료 300m+ 이격")

    assert aps[0] == ENTRY and aps[0] != (round(orig_s[0], 6), round(orig_s[1], 6))
    ok("P-4 대표점 후보(polyline[0]·access_points[0]) 원 시작점 아님")

    print("[G 기하]")
    assert poly[0] == poly[-1], "루프 미폐합"
    total = sum(dm(poly[i], poly[i + 1]) for i in range(len(poly) - 1))
    assert abs(total - 4037) <= 50, total
    m = re.search(r"'팽성',\s*([\d.]+)", sql)
    assert m and abs(float(m.group(1)) - total / 1000) <= 0.05, (m, total)
    ok(f"G-1 폐합 0 · 실측 {total:.0f}m · distance_km {m.group(1)} 합치")

    hard_run, hard_total = rs._road_hit_m(list(poly), "hard")
    assert hard_run == 0.0 and hard_total == 0.0, (hard_run, hard_total)
    ok("G-2 motorway 하드 물림 0m")

    print("\n전부 통과 — 프라이버시 4·기하 2 (DB 읽기 전용·부수효과 0)")


if __name__ == "__main__":
    run_tests()
