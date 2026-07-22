"""
Unit test: pitstop 의도 존중 재랭킹 (백로그 (b), 2026-07-22)

랜드마크형 키워드("공원")는 상업 카테고리 제외+적합도 랭킹 → 실제 공원 선택,
"…공원점" 상호 음식점 배제. 상업형("카페")은 그 카테고리만. 미분류는 현행.
mock은 실사용 청라 부검 top10 재현(치킨집 vs 공원).

Run: python tests/test_pitstop_intent.py
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import Place, Coordinate
from app.services.map_service import rank_places_for_keyword, _keyword_intent


def ok(m):  print(f"  ✓ {m}")
def fail(m): print(f"  ✗ {m}"); sys.exit(1)


def P(name, code):
    return Place(name=name, coordinate=Coordinate(lat=37.52, lng=126.63),
                 category=None, category_code=code, address="인천 서구")


# 실사용 청라 "공원" 검색 top10 재현(거리순) + 실제 공원·편의점 추가
TOP = [
    P("모래성공원", None),                        # 실제 소품 park (빈 코드)
    P("와플대학 청라호수공원캠퍼스", "FD6"),          # 음식점(상호 차용)
    P("나이스가이 프리미엄 청라호수공원점", None),       # 상호 차용(빈 코드)
    P("바른치킨 청라호수로봇점", "FD6"),
    P("블루클럽 청라호수공원점", None),               # 미용실(빈 코드, 상호 차용)
    P("자담치킨 청라호수공원점", "FD6"),
    P("롯데리아 인천청라호수공원점", "FD6"),
    P("요거트아이스크림의정석 청라호수공원점", "CE7"),    # 카페
    P("GS25 청라호수공원점", "CS2"),                # 편의점
]


def run_tests():
    print("[1. 키워드 의도 분류]")
    assert _keyword_intent("공원") == ("landmark", "공원")
    assert _keyword_intent("청라호수공원") == ("landmark", "공원")
    assert _keyword_intent("카페") == ("commercial", "CE7")
    assert _keyword_intent("편의점") == ("commercial", "CS2")
    assert _keyword_intent("분수대광장") == ("unknown", None)
    ok("공원/호수=landmark · 카페/편의점=commercial · 미분류=unknown")

    print("\n[2. '공원' 랜드마크 → 상업 제외 + 적합도 → 실제 공원 채택]")
    ranked = rank_places_for_keyword("공원", TOP)
    assert ranked, "통과 후보 있어야"
    assert ranked[0].name == "모래성공원", f"실제 공원이 [0], got {ranked[0].name}"
    # 음식점·카페·편의점 전부 배제됐나
    names = [p.name for p in ranked]
    assert not any("치킨" in n or "와플" in n or "롯데리아" in n or "요거트" in n or "GS25" in n for n in names), \
        f"상업시설 배제 실패: {names}"
    ok(f"[0]=모래성공원(실제 park) · 상업시설 전 배제 · 통과 {len(ranked)}건")

    print("\n[3. 적합도: 실제 명칭 > 상호 차용]")
    # 실제 명칭 '청라호수공원'(빈코드) 추가 → 상호차용보다 우선
    withreal = [P("청라호수공원", None)] + TOP
    r = rank_places_for_keyword("공원", withreal)
    assert r[0].name in ("청라호수공원", "모래성공원"), f"실제 공원명 우선, got {r[0].name}"
    # 상호차용(…공원점)은 실제명칭보다 뒤
    idx_real = min(i for i, p in enumerate(r) if p.name.endswith("공원"))
    idx_branch = next((i for i, p in enumerate(r) if "공원점" in p.name), 999)
    assert idx_real < idx_branch, f"실제명칭({idx_real})이 상호차용({idx_branch})보다 앞"
    ok("실제 명칭(…공원)이 상호 차용(…공원점)보다 우선")

    print("\n[4. '카페' 상업형 → CE7만]")
    r = rank_places_for_keyword("카페", TOP)
    assert len(r) == 1 and r[0].category_code == "CE7", f"카페만, got {[(p.name,p.category_code) for p in r]}"
    assert r[0].name == "요거트아이스크림의정석 청라호수공원점"
    ok("카페 → CE7 카페만 선택(요거트아이스크림)")

    print("\n[5. '편의점' → CS2만]")
    r = rank_places_for_keyword("편의점", TOP)
    assert len(r) == 1 and r[0].category_code == "CS2" and r[0].name.startswith("GS25")
    ok("편의점 → CS2만(GS25)")

    print("\n[6. 미분류 키워드 → 현행(원본 무필터)]")
    r = rank_places_for_keyword("분수대", TOP)
    assert r == TOP, "미분류는 원본 그대로"
    ok("미분류 → 원본 순서·개수 보존(현행 동작)")

    print("\n[7. 랜드마크인데 통과 후보 0 → [] (상위 폴백 신호)]")
    only_food = [p for p in TOP if p.category_code in ("FD6", "CE7", "CS2")]
    r = rank_places_for_keyword("공원", only_food)
    assert r == [], f"전부 상업이면 [], got {[p.name for p in r]}"
    ok("공원인데 후보 전부 상업 → [] (route_service가 무필터 최근접 폴백)")

    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)


if __name__ == "__main__":
    run_tests()
