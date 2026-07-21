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

_state: dict = {"seq": [], "i": 0, "gemini_calls": 0, "chain_targets": [],
                "gemini_seq": [], "g": 0, "radii": []}

# 기준 기하(d=0.0045)의 체인 길이 ≈ 1.537km — chain_target에 비례 스케일해
# "순응하는 Gemini"를 모사한다(v2.3 사전 게이트가 기본 시나리오를 안 막게).
_BASE_CHAIN_KM = 1.537


async def _mock_generate_route(**kw) -> RouteResponse:
    _state["gemini_calls"] += 1
    # 적응형 피드백 검증용 — route_service가 attempt별로 전달한 체인 목표 기록
    aim = kw.get("chain_target_km")
    _state["chain_targets"].append(aim)
    _state["radii"].append(kw.get("radius_km"))
    # gemini_seq: 호출별 체인 순응 배수(chain = aim × factor). 소진 시 1.0(순응).
    gseq = _state["gemini_seq"]
    factor = float(gseq[_state["g"]]) if _state["g"] < len(gseq) else 1.0
    _state["g"] += 1
    chain_km = (aim or _BASE_CHAIN_KM) * factor
    start: Coordinate = kw["start"]
    d = 0.0045 * (chain_km / _BASE_CHAIN_KM)
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
        raise RuntimeError("mock: no pedestrian path")  # T-map 장애 → NO_PATH 폴백
    if item.get("untraversable"):
        # 강 위 등 보행 불가 leg (리포트 A) → traversability 게이트가 폐기해야
        raise map_service.LegNotRoutable()
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
    _state["gemini_seq"] = data.get("gemini_seq", [])
    _state["i"] = 0
    _state["g"] = 0
    _state["gemini_calls"] = 0
    _state["chain_targets"] = []
    _state["radii"] = []
    return {"ok": True}


@app.get("/__mock/stats")
async def mock_stats():
    return {"gemini_calls": _state["gemini_calls"], "tmap_calls": _state["i"],
            "chain_targets": _state["chain_targets"], "radii": _state["radii"]}
