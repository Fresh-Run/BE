"""
polyline_thumb eps 완화(25→15, 2026-09-11) — 피드 썸네일 곡선 각짐 개선.

순수 함수(무DB): eps 상수·≤36 상한(페이로드 불변)·곡선 보존·멱등·계약 shape 불변.
Run: python tests/test_polyline_thumb.py
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import track_service as ts  # noqa: E402

_n = 0


def ok(m):
    global _n
    _n += 1
    print(f"  ✓ {m}")


def _hav(a, b):
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = math.radians(b["lat"] - a["lat"]), math.radians(b["lng"] - a["lng"])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(x))


def _med_gap(poly):
    if len(poly) < 2:
        return 0.0
    g = sorted(_hav(poly[i], poly[i + 1]) for i in range(len(poly) - 1))
    return g[len(g) // 2]


def _curve(n=120, radius_m=250):
    """곡선 트랙 합성 — 반원 호(dense). 실 러닝 곡선 근사."""
    lat0, lng0 = 37.50, 127.03
    out = []
    for i in range(n):
        ang = math.pi * i / (n - 1)  # 0~180도 반원
        dlat = (radius_m * math.sin(ang)) / 111000.0
        dlng = (radius_m * (1 - math.cos(ang))) / (111000.0 * math.cos(math.radians(lat0)))
        out.append({"lat": lat0 + dlat, "lng": lng0 + dlng})
    return out


def main():
    print("[A. 상수·상한]")
    assert ts.THUMB_EPSILON_M == 15.0, ts.THUMB_EPSILON_M
    ok(f"THUMB_EPSILON_M = 15.0(25→15 완화)")

    curve = _curve(120)
    thumb = ts.make_polyline_thumb(curve)
    assert len(thumb) <= ts.THUMB_MAX_POINTS, len(thumb)
    ok(f"곡선 120점 → thumb {len(thumb)}점 (≤{ts.THUMB_MAX_POINTS} 상한·페이로드 불변)")

    print("\n[B. 곡선 보존 — eps15 vs eps25]")
    ts.THUMB_EPSILON_M = 25.0
    t25 = ts.make_polyline_thumb(curve)
    ts.THUMB_EPSILON_M = 15.0
    t15 = ts.make_polyline_thumb(curve)
    # eps15가 곡선 점 더 보존(점 수 ≥) + median 간격 ≤ (더 촘촘)
    assert len(t15) >= len(t25), (len(t15), len(t25))
    assert _med_gap(t15) <= _med_gap(t25) + 1, (_med_gap(t15), _med_gap(t25))
    ok(f"곡선 보존 — eps25 {len(t25)}점/{_med_gap(t25):.0f}m → eps15 {len(t15)}점/{_med_gap(t15):.0f}m(더 촘촘)")

    print("\n[C. 멱등(재계산 = 동일)]")
    assert ts.make_polyline_thumb(curve) == ts.make_polyline_thumb(curve)
    # thumb를 다시 thumb해도(백필 재실행 모사) 동일 — 이미 ≤36이면 무변
    re = ts.make_polyline_thumb(thumb)
    assert re == thumb, "thumb 재적용이 변경(멱등 위반)"
    ok("재계산·재적용 동일(백필 멱등)")

    print("\n[D. 계약 shape 불변]")
    assert all(set(p.keys()) == {"lat", "lng"} for p in thumb)
    assert all(isinstance(p["lat"], float) and isinstance(p["lng"], float) for p in thumb)
    ok("thumb 원소 {lat,lng} float — 클라 소비 필드 불변")

    print("\n[E. 짧은 트랙(상한 미만) 무변)]")
    short = _curve(20)   # 20점 < 36
    ts_short = ts.make_polyline_thumb(short)
    assert ts_short == [{"lat": round(p["lat"], 5), "lng": round(p["lng"], 5)} for p in short]
    ok("36점 미만 트랙 → 전량 유지(5자리 반올림만)")


if __name__ == "__main__":
    main()
    print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_n} assert)\n" + "=" * 50)
