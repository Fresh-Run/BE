"""
Unit: 스크리닝 보조 지표 (scripts/screen_seed_candidates.py, 2026-08-18)

외부 콜 0·DB 무접촉(합성 궤적).
B-1 bbox 둘레비 — 단일 사각 루프 ≈1.0(통과) / 동일 루프 3랩 ≈3.0(>1.5 기각)
    — 제주 911a674f 갭(동방향 랩이 이중주행 지표를 통과) 재발 방지
B-2 역방향 이중주행 — 왕복 팔 궤적은 여전히 이중주행 지표가 잡음(기존 축 불변)
B-3 screen_track 판정 — 3랩 합성은 '자기중첩 의심' 기각, 단일 루프는 후보 통과

Run: python tests/test_screen_metrics.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.screen_seed_candidates import (  # noqa: E402
    bbox_ratio, double_run_ratio, screen_track)


def ok(m):
    print(f"  ✓ {m}")


def rect_loop(w_deg=0.005, h_deg=0.012, step=0.0002, lat0=37.30, lng0=127.10):
    """사각 루프 합성(약 0.55×1.33km — 둘레 ~3.6km, 밴드 내)."""
    pts = []
    x = 0.0
    while x < w_deg:
        pts.append((lat0, lng0 + x)); x += step
    y = 0.0
    while y < h_deg:
        pts.append((lat0 + y, lng0 + w_deg)); y += step
    x = w_deg
    while x > 0:
        pts.append((lat0 + h_deg, lng0 + x)); x -= step
    y = h_deg
    while y > 0:
        pts.append((lat0 + y, lng0)); y -= step
    pts.append(pts[0])
    return pts


def run_tests():
    loop = rect_loop()
    r1 = bbox_ratio(loop)
    laps3 = loop[:-1] * 3 + [loop[0]]
    r3 = bbox_ratio(laps3)
    assert 0.8 <= r1 <= 1.2, r1
    assert r3 > 2.5, r3
    ok(f"B-1 단일 {r1:.2f}(통과) vs 3랩 {r3:.2f}(>1.5 기각) — 동방향 랩 검출")

    # 왕복 팔: 루프 + 500m 팔 왕복
    arm = [(37.30, 127.10 - i * 0.0002) for i in range(1, 25)]
    outback = loop[:-1] + arm + arm[::-1] + [loop[0]]
    dr = double_run_ratio(outback)
    # 검출 자체 증명이 목적(정확 비율은 리샘플·근접 반경에 민감) — 0 초과 유의값
    assert dr > 0.08, dr
    ok(f"B-2 왕복 팔 이중주행 {dr*100:.0f}% — 역방향 축 기존 검출 불변")

    v3 = screen_track(laps3)
    assert "reject" in v3 and "자기중첩" in v3["reject"], v3
    v1 = screen_track(loop)
    assert "reject" not in v1 and v1["tier"] == "clean", v1
    ok(f"B-3 3랩 기각({v3['reject'][:20]}…) · 단일 루프 후보 통과({v1['km']}km)")

    print("\n전부 통과 — 외부 콜 0·DB 무접촉")


if __name__ == "__main__":
    run_tests()
