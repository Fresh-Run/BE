"""±500m 보장 테스트용 패치 앱 (uvicorn tests.mock_route_app:app --port 8001).

openai_service.generate_route·map_service.get_pedestrian_route를 스크립트된
시퀀스로 대체 — Gemini·T-map 실호출 0. 시나리오는 POST /__mock/scenario로 주입:
  {"seq": [{"snap_km": 4.2}, {"no_path": true}, ...]}
각 T-map 호출이 seq를 순서대로 소비. Gemini mock은 호출 수만 센다(비용 검증용).
test_push_notification의 mock Expo(8001) 선례를 따른 패턴.
"""
from __future__ import annotations

from fastapi import Request

from app.main import app
from app.models.schemas import Coordinate, PedestrianRoute, RouteResponse, Waypoint
from app.services import map_service, openai_service

_state: dict = {"seq": [], "i": 0, "gemini_calls": 0, "chain_targets": []}


async def _mock_generate_route(**kw) -> RouteResponse:
    _state["gemini_calls"] += 1
    # 적응형 피드백 검증용 — route_service가 attempt별로 전달한 체인 목표 기록
    _state["chain_targets"].append(kw.get("chain_target_km"))
    start: Coordinate = kw["start"]
    # 고정 4-waypoint 루프 (직선 체인 ~2.8km 상당 — chain_km 로그 계산용 기하)
    d = 0.0045  # ~0.5km/변
    wps = [
        Waypoint(name="시작", coordinate=start),
        Waypoint(name="wp1", coordinate=Coordinate(lat=start.lat + d, lng=start.lng)),
        Waypoint(name="wp2", coordinate=Coordinate(lat=start.lat + d, lng=start.lng + d)),
        Waypoint(name="복귀", coordinate=start),
    ]
    return RouteResponse(
        summary="mock course", total_distance_km=kw["target_distance_km"],
        estimated_duration_min=30.0, waypoints=wps, polyline=None,
    )


async def _mock_pedestrian(origin, destination, waypoints=None) -> PedestrianRoute:
    seq = _state["seq"]
    item = seq[min(_state["i"], len(seq) - 1)] if seq else {"snap_km": 4.0}
    _state["i"] += 1
    if item.get("no_path"):
        raise RuntimeError("mock: no pedestrian path")
    km = float(item["snap_km"])
    return PedestrianRoute(
        provider="tmap", distance_m=km * 1000.0, duration_s=km * 360.0,
        path=[origin, destination],
    )


# 모듈 속성 패치 — route_service는 호출 시점에 모듈 속성을 조회하므로 이걸로 충분
openai_service.generate_route = _mock_generate_route
map_service.get_pedestrian_route = _mock_pedestrian


@app.post("/__mock/scenario")
async def set_scenario(req: Request):
    data = await req.json()
    _state["seq"] = data["seq"]
    _state["i"] = 0
    _state["gemini_calls"] = 0
    _state["chain_targets"] = []
    return {"ok": True}


@app.get("/__mock/stats")
async def mock_stats():
    return {"gemini_calls": _state["gemini_calls"], "tmap_calls": _state["i"],
            "chain_targets": _state["chain_targets"]}
