"""
Unit: 트랙 좌표 정합성 국제화 (2026-07-30 — 한국 bbox 폐지, 호바트 실피해)

호바트·도쿄 실좌표 보존 + 쓰레기 3종(세계 밖·null island·대륙 점프) 드롭 +
한국 트랙 무영향. process_track 전체 파이프라인(거리·verified·splits) 경유.

Run: python tests/test_track_filter_global.py  (외부 콜 0)
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import track_service as ts  # noqa: E402


def ok(m):
    print(f"  ✓ {m}")


def mk_track(lat0, lng0, n=120, step_deg=0.00006, dt_ms=5000, acc=5.0):
    """~7m/5s(러닝 페이스) 직선 트랙 — 좌표계만 바꿔 재사용."""
    return [ts.TrackPoint(lat=lat0 + step_deg * i, lng=lng0, t_ms=1785400000000 + dt_ms * i,
                          acc=acc, alt=10.0) for i in range(n)]


def run():
    print("[1. 호바트·도쿄 — 트랙 보존·거리·verified·splits]")
    for name, la, lo in (("호바트", -42.88, 147.33), ("도쿄", 35.6852, 139.7528)):
        pts = mk_track(la, lo, n=160)
        out = ts.process_track(pts)
        assert out is not None, name
        assert out.point_count_kept == 160, (name, out.point_count_kept)
        assert 0.9 <= out.server_distance_km <= 1.2, (name, out.server_distance_km)
        assert out.splits and out.splits[0].km >= 1.0
        ok(f"{name}: kept 160/160 · server {out.server_distance_km:.2f}km · splits {len(out.splits)}")

    print("\n[2. 쓰레기 3종 드롭]")
    base = mk_track(-42.88, 147.33, n=60)
    junk_world = ts.TrackPoint(lat=95.0, lng=200.0, t_ms=base[-1].t_ms + 5000, acc=5.0)
    junk_null = ts.TrackPoint(lat=0.001, lng=0.001, t_ms=base[-1].t_ms + 10000, acc=5.0)
    junk_jump = ts.TrackPoint(lat=37.55, lng=127.0, t_ms=base[-1].t_ms + 15000, acc=5.0)  # 서울(대륙 점프)
    filt = ts._basic_filter(base + [junk_world, junk_null, junk_jump])
    assert len(filt) == 60, len(filt)
    assert all(abs(p.lat + 42.88) < 0.1 for p in filt)
    ok("세계 범위 밖·null island·대륙 점프(호바트→서울) 3종 전부 드롭, 실주행 60점 보존")

    print("\n[3. 한국 회귀 — 정상/노이즈(acc)/순간이동/저속(파이프라인 불변)]")
    kr = mk_track(37.55, 127.0, n=120)
    out_kr = ts.process_track(kr)
    assert out_kr.point_count_kept == 120
    noisy = kr[:60] + [ts.TrackPoint(lat=37.551, lng=127.0, t_ms=kr[59].t_ms + 1000, acc=99.0)] + kr[60:]
    f2 = ts._basic_filter(noisy)
    assert len(f2) == 120, "acc 컷 유지"
    teleport = list(kr)
    teleport.insert(60, ts.TrackPoint(lat=37.58, lng=127.0, t_ms=kr[59].t_ms + 2500, acc=5.0))  # ~3.3km/2.5s
    out_tp = ts.process_track(teleport)
    assert out_tp.point_count_kept <= 121 and out_tp.server_distance_km < 1.5, \
        (out_tp.point_count_kept, out_tp.server_distance_km)  # 속도 필터가 순간이동 무력화
    ok(f"한국 정상 kept 120 · acc99 드롭 · 순간이동 무력화(server {out_tp.server_distance_km:.2f}km)")

    print("\n[4. 앵커 창 경계 — 100km 내 실주행 통과]")
    far = mk_track(37.55, 127.0, n=30)
    edge = ts.TrackPoint(lat=37.55 + 0.85, lng=127.0, t_ms=far[-1].t_ms + 5000, acc=5.0)  # ~94km
    over = ts.TrackPoint(lat=37.55 + 0.95, lng=127.0, t_ms=far[-1].t_ms + 10000, acc=5.0)  # ~106km
    f4 = ts._basic_filter(far + [edge, over])
    assert len(f4) == 31, len(f4)   # 94km 통과·106km 드롭
    ok("94km 통과 · 106km 드롭 — 임계 100km 정상")


if __name__ == "__main__":
    run()
    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
