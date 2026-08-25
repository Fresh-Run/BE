"""
Unit: 자기교차 형상 지표 self_intersections (§8.19 보조, 2026-08-25 일산 top1 실증)

폴리라인이 단일 폐곡선(0)인지 자기교차(≥1)인지 판정. 두 성분: 선분 정상 교차
(실 GPS X자) + 공유 노드 재방문(그래프 순환로 X자 — 선분교차가 못 잡는 케이스).
전례: 일산 top1(10.87km)이 선분교차 0인데 육안 십자 → 노드 재방문으로 검출.

Run: python tests/test_self_intersection_metric.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.screen_seed_candidates import self_intersections  # noqa: E402

_n = 0


def ok(m):
    global _n
    _n += 1
    print(f"  ✓ {m}")


def run_tests():
    print("[합성 케이스]")
    # 단순 사각 폐곡선 → 0
    square = [(37.0, 127.0), (37.0, 127.01), (37.01, 127.01), (37.01, 127.0), (37.0, 127.0)]
    assert self_intersections(square) == 0, self_intersections(square)
    ok("단순 사각 폐곡선 → 0")

    # 나비넥타이(bowtie) — 중앙 선분 정상 교차 → ≥1
    bowtie = [(37.0, 127.0), (37.01, 127.01), (37.01, 127.0), (37.0, 127.01), (37.0, 127.0)]
    assert self_intersections(bowtie) >= 1, self_intersections(bowtie)
    ok(f"나비넥타이(선분 X자) → {self_intersections(bowtie)}")

    # 노드 재방문(그래프 순환로 십자) — (37.0,127.01)이 idx1·idx3 비연속 재방문 → ≥1
    revisit = [(37.0, 127.0), (37.0, 127.01), (37.01, 127.01), (37.0, 127.01),
               (37.01, 127.0), (37.0, 127.0)]
    assert self_intersections(revisit) >= 1, self_intersections(revisit)
    ok(f"노드 재방문(그래프 X자) → {self_intersections(revisit)}")

    # 연속 중복 정점(0길이 세그)은 재방문으로 세지 않음
    dup = [(37.0, 127.0), (37.0, 127.0), (37.0, 127.01), (37.01, 127.01),
           (37.01, 127.0), (37.0, 127.0)]
    assert self_intersections(dup) == 0, self_intersections(dup)
    ok("연속 중복 정점(0길이) → 0(오탐 없음)")

    print("[실데이터 — 일산 배치(관측 정합)]")
    path = os.path.join(os.path.dirname(__file__), "..", "scripts",
                        "course_factory", "out", "ilsan_candidates.json")
    if os.path.exists(path):
        d = json.load(open(path))
        old = sorted(d, key=lambda r: (r["tier"] != "clean", r["dbl_pct"],
                                       r["longest_retrace_m"]))
        top1 = self_intersections(old[0]["pts"])   # 육안 십자관통 후보
        top3 = self_intersections(old[2]["pts"])   # 육안 단순 폐곡선
        assert top1 >= 1 and top3 == 0, (top1, top3)
        ok(f"기존정렬 top1 자기교차 {top1}(십자관통 검출) · top3 {top3}(단순 폐곡선)")
    else:
        ok("ilsan_candidates.json 부재 — 실데이터 검증 스킵(합성 케이스로 커버)")


if __name__ == "__main__":
    run_tests()
    print("\n" + "=" * 50 + f"\n  ALL TESTS PASSED ({_n} assert)\n" + "=" * 50)
