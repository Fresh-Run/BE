"""
Unit: 명백 언더슈트 선차단 (_undershoot_pregate, 예산 2단계 2026-08-05)

외부 콜 0·DB 무접촉. θ=0.50(7월 재생 — 오폐기 0·성공→실패 전환 0의 최공격값).
U-1 발동 — 예측(체인×est_ratio) < 0.50×target 후보만 폐기
U-2 비발동 경계 — 예측 == 0.50×target(등호)·초과는 유지
U-3 보수 가드 — 잔존 <3이면 최장 체인부터 복원(재추첨 재료 보존), 정렬 유지
U-4 전부 정상이면 무폐기·원본 그대로(무영향 회귀)
U-5 부수효과 — 입력 리스트 원본 비파괴

Run: python tests/test_undershoot_pregate.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import route_service as rs  # noqa: E402


def ok(m):
    print(f"  ✓ {m}")


def cand(chain):
    return (f"r{chain}", chain, 2.0)   # (route 대역, chain_km, radius)


def run_tests():
    target, est, aim = 5.0, 1.6, 3.25   # 예측 = chain×1.6, 임계 = 2.5 → chain 1.5625
    thin = cand(1.0)     # 예측 1.6 < 2.5 — 폐기 대상
    edge = cand(2.5 / est)              # 예측 == 2.5 — 등호는 유지
    good1, good2, good3 = cand(3.0), cand(3.2), cand(3.4)

    print("[U 선차단 경계]")
    passed = [good1, good2, good3, thin]
    kept, dropped = rs._undershoot_pregate(passed, est, target, aim)
    assert dropped == 1 and thin not in kept and len(kept) == 3
    ok("U-1 예측<0.50×target 후보만 폐기(콜 0)")

    kept, dropped = rs._undershoot_pregate([good1, good2, good3, edge], est, target, aim)
    assert dropped == 0 and edge in kept
    ok("U-2 등호(예측==0.50×target)·초과는 유지 — 비발동 경계")

    thin2, thin3 = cand(0.8), cand(1.2)
    kept, dropped = rs._undershoot_pregate([good1, thin, thin2, thin3], est, target, aim)
    # 정상 1개뿐 → 잔존 3까지 최장 체인(thin3=1.2, thin=1.0) 복원, thin2(0.8)만 폐기
    assert dropped == 1 and thin2 not in kept and len(kept) == 3
    assert thin in kept and thin3 in kept
    assert kept == sorted(kept, key=lambda c: abs(c[1] - aim)), "aim 최근접 정렬 유지"
    ok("U-3 잔존<3 보수 가드 — 최장 체인 복원·정렬 유지(재추첨 재료 보존)")

    orig = [good1, good2, good3]
    kept, dropped = rs._undershoot_pregate(orig, est, target, aim)
    assert dropped == 0 and kept == orig
    ok("U-4 전부 정상 → 무폐기·원본 순서 그대로(성공 케이스 무영향)")

    src = [good1, thin]
    before = list(src)
    rs._undershoot_pregate(src, est, target, aim)
    assert src == before, "입력 원본 비파괴"
    ok("U-5 입력 리스트 부수효과 0")

    print("\n전부 통과 — 외부 콜 0·DB 무접촉")


if __name__ == "__main__":
    run_tests()
