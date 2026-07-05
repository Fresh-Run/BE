"""
결정론 테스트: 코스 생성 거리 상한 32.2 (프론트 단위별 UI 상한 수용 안전망)
서버·외부 API 불필요 — pydantic 검증(=422 경로)과 반경 스케줄만 확인.
Run: python tests/test_distance_limit.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pydantic import ValidationError

from app.models.schemas import AiCourseSettings, AiCourseSettingsPatch, RouteRequest
from app.services.route_service import _radius_schedule


def ok(m):
    print(f"  ✓ {m}")


def must_fail(fn, label):
    try:
        fn()
    except ValidationError:
        return
    print(f"  ✗ {label}: 422(ValidationError)여야 함")
    sys.exit(1)


START = {"start": {"lat": 37.5445, "lng": 127.0374}}

print("\n[1. RouteRequest.target_distance_km 상한 32.2]")
assert RouteRequest(**START, target_distance_km=32.2).target_distance_km == 32.2
assert RouteRequest(**START, target_distance_km=32.19).target_distance_km == 32.19  # 20mi
assert RouteRequest(**START, target_distance_km=30).target_distance_km == 30       # km 모드 상한 (회귀)
must_fail(lambda: RouteRequest(**START, target_distance_km=32.3), "32.3")
must_fail(lambda: RouteRequest(**START, target_distance_km=100), "100 (구 상한)")
ok("32.2·32.19(20mi)·30 통과 ✓ 32.3·100 거부 ✓")

print("\n[2. settings.ai_course.default_distance_km 상한 32.2 (마일 모드 설정 슬라이더)]")
assert AiCourseSettings(default_distance_km=32.2).default_distance_km == 32.2
assert AiCourseSettingsPatch(default_distance_km=32.19).default_distance_km == 32.19
must_fail(lambda: AiCourseSettings(default_distance_km=32.3), "settings 32.3")
must_fail(lambda: AiCourseSettingsPatch(default_distance_km=33), "patch 33")
ok("설정 상한 동일 적용 ✓")

print("\n[3. 동적 탐색 반경 — 32.2에서 정상 (8km cap)]")
assert _radius_schedule(32.2) == [8.0], _radius_schedule(32.2)   # r0=8.05→cap 8.0, 1시도
assert _radius_schedule(30) == [7.5, 8.0], _radius_schedule(30)  # r0=7.5 → 2시도
ok("32.2 → [8.0] ✓ 30 → [7.5, 8.0] ✓ (cap 동작)")

print("\n" + "=" * 50)
print("  ALL TESTS PASSED")
print("=" * 50)
