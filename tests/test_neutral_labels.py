"""
Unit test: 중립 라벨 전환 (§3 축 B — 지명 hallucination 근절, 2026-07-22)

Gemini 툴 스키마에서 name·description·summary 제거 → 좌표만 받고 서버가 중립 라벨
("출발/지점 N/복귀·도착")·중립 제목("5.0km 순환 코스")을 채운다. 여기선 가짜 OpenAI
클라이언트로 generate_route를 구동해 창작 지명 0을 검증.

Run: python tests/test_neutral_labels.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import Coordinate
from app.services import openai_service


def ok(m):  print(f"  ✓ {m}")
def fail(m): print(f"  ✗ {m}"); sys.exit(1)


def _fake_response(args: dict):
    fn = SimpleNamespace(arguments=json.dumps(args))
    tc = SimpleNamespace(function=fn)
    msg = SimpleNamespace(tool_calls=[tc])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class _FakeCompletions:
    def __init__(self, args): self._args = args
    async def create(self, **kw): return _fake_response(self._args)


class _FakeClient:
    def __init__(self, args):
        self.chat = SimpleNamespace(completions=_FakeCompletions(args))


def _patch(args):
    """generate_route가 쓰는 모듈 _client를 가짜로 교체하고 원본 반환(복원용)."""
    orig = openai_service._client
    openai_service._client = _FakeClient(args)
    return orig


def run_tests():
    start = Coordinate(lat=37.5242, lng=126.6303)  # 청라 — hallucination 재현 지역

    print("[1. 툴 스키마에 name·description·summary 부재]")
    props = openai_service._route_tool()["function"]["parameters"]["properties"]
    assert "summary" not in props, "summary 필드 제거"
    wp_props = props["waypoints"]["items"]["properties"]
    assert "name" not in wp_props and "description" not in wp_props, "waypoint name·description 제거"
    assert set(wp_props) == {"coordinate", "is_pitstop"}, f"좌표+pitstop만, got {set(wp_props)}"
    ok("스키마: 좌표+is_pitstop만 (name·description·summary 제거)")

    print("\n[2. 좌표만 응답 → 서버가 중립 라벨·제목 주입 (loop)]")
    args = {"total_distance_km": 5.0, "waypoints": [
        {"coordinate": {"lat": 37.5242, "lng": 126.6303}, "is_pitstop": False},
        {"coordinate": {"lat": 37.5280, "lng": 126.6350}, "is_pitstop": True},
        {"coordinate": {"lat": 37.5260, "lng": 126.6390}, "is_pitstop": False},
        {"coordinate": {"lat": 37.5242, "lng": 126.6303}, "is_pitstop": False}]}
    orig = _patch(args)
    try:
        r = asyncio.run(openai_service.generate_route(
            target_distance_km=5.0, start=start, end=None, lang="ko"))
    finally:
        openai_service._client = orig
    names = [w.name for w in r.waypoints]
    assert names == ["출발", "지점 1", "지점 2", "복귀"], f"중립 라벨, got {names}"
    assert all(w.description is None for w in r.waypoints), "description 없음"
    assert r.summary == "5.0km 순환 코스", f"중립 제목, got {r.summary!r}"
    # 창작 지명 0 — 응답 어디에도 실제 지명 문자열이 없어야
    blob = json.dumps(r.model_dump(), ensure_ascii=False)
    for hallu in ("경기장", "공원", "천", "공촌", "연희", "아시아드"):
        assert hallu not in blob, f"창작 지명 '{hallu}' 누출: {blob[:120]}"
    ok(f"라벨 {names} · 제목 {r.summary!r} · 창작 지명 0")

    print("\n[3. one-way(end 지정) → 마지막 라벨 '도착']")
    args2 = {"total_distance_km": 5.0, "waypoints": [
        {"coordinate": {"lat": 37.5242, "lng": 126.6303}, "is_pitstop": False},
        {"coordinate": {"lat": 37.5280, "lng": 126.6390}, "is_pitstop": False},
        {"coordinate": {"lat": 37.5310, "lng": 126.6450}, "is_pitstop": False}]}
    orig = _patch(args2)
    try:
        r2 = asyncio.run(openai_service.generate_route(
            target_distance_km=5.0, start=start,
            end=Coordinate(lat=37.5310, lng=126.6450), lang="ko"))
    finally:
        openai_service._client = orig
    # 라벨 '도착'·제목 '편도'가 one-way 경로 입증(is_one_way 플래그는 route_service가
    # 설정 — generate_route 층 아님, distance/E2E 테스트가 커버).
    assert [w.name for w in r2.waypoints] == ["출발", "지점 1", "도착"], [w.name for w in r2.waypoints]
    assert r2.summary == "5.0km 편도 코스", r2.summary
    ok("one-way: 출발/지점 1/도착 · 제목 '5.0km 편도 코스'")

    print("\n[4. en lang → 영문 중립 라벨]")
    orig = _patch(args)
    try:
        r3 = asyncio.run(openai_service.generate_route(
            target_distance_km=5.0, start=start, end=None, lang="en"))
    finally:
        openai_service._client = orig
    assert [w.name for w in r3.waypoints] == ["Start", "Point 1", "Point 2", "Return"], [w.name for w in r3.waypoints]
    assert r3.summary == "5.0km loop course", r3.summary
    ok("en: Start/Point N/Return · '5.0km loop course'")

    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)


if __name__ == "__main__":
    run_tests()
