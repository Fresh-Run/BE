"""Orchestration: combine the OpenAI route generation with Map API data.

This is the business-logic glue the API layer calls. It asks OpenAI for a
candidate route, optionally resolves the pitstop against the real Map API,
and enriches the response with actual pedestrian routing geometry.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict

from openai import APIError as OpenAIAPIError
from postgrest.exceptions import APIError
from pydantic import ValidationError

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import (
    AiCourseSettings,
    CommentResponse,
    Coordinate,
    PublicRouteResponse,
    RouteRequest,
    RouteResponse,
    StoredRoute,
)
from app.services import feedback_service, map_service, notification_service, openai_service, profile_service

logger = logging.getLogger(__name__)


class RouteNotFound(Exception):
    """Route does not exist, or is hidden from this user."""


class CommentNotFound(Exception):
    """Comment does not exist under the given route."""


class CommentAccessDenied(Exception):
    """Caller is neither the comment author nor the route owner."""


class RouteGenerationFailed(Exception):
    """Gemini never produced a usable route across all radius attempts."""


class OneWayEndTooFar(Exception):
    """일방(end) 요청의 직선거리가 target×0.8 초과 — 물리적으로 불가(422).

    도로 팽창(실측 ≥1.2×)상 직선거리 d의 코스는 최소 ~1.25d — target이 그보다
    짧으면 어떤 시스템도 못 만든다(v2.3 E2E 실증: d=5.0·target=5.0 → 전패 502).
    min_target_km: 이 도착지가 성립하는 최소 목표 거리(= d/0.8, 0.1 올림) 힌트.
    """

    def __init__(self, distance_km: float, min_target_km: float):
        self.distance_km = distance_km
        self.min_target_km = min_target_km
        super().__init__(f"one-way end too far: d={distance_km}, min={min_target_km}")


# 일방 실행가능성 상한 — |start−end| ≤ target×0.8 (여유 0.2는 도로 팽창분)
_ONE_WAY_MAX_DIST_FACTOR = 0.8


async def _course_context(user_id: str | None) -> tuple[AiCourseSettings, str]:
    """(ai_course 선호, lang) — 한 번의 get_settings로 둘 다 (쿼리 증가 0).

    Best-effort like the feedback loop: a settings hiccup must never block
    route generation. 실패 시 서버 기본값 + 'ko'.
    """
    if not user_id:
        return AiCourseSettings(), "ko"
    try:
        s = await profile_service.get_settings(user_id)
        return s.ai_course, s.lang
    except Exception:  # noqa: BLE001 - settings are a preference, not a gate
        logger.warning("Failed to load settings; using defaults.", exc_info=True)
        return AiCourseSettings(), "ko"


def _resolve_course_prefs(
    req: RouteRequest, saved: AiCourseSettings
) -> tuple[float, AiCourseSettings]:
    """Merge body values over saved settings (body > 설정 > 기본값), per field.

    Returns (effective target distance, effective prefs). The saved object
    already has server defaults merged in (get_settings), so only the body
    override step happens here. terrain='hill' + avoid_hills=true resolves
    to avoid_hills winning (terrain drops to 'mixed').
    """
    target_km = (
        req.target_distance_km
        if req.target_distance_km is not None
        else saved.default_distance_km
    )
    prefs = AiCourseSettings(
        terrain=req.terrain if req.terrain is not None else saved.terrain,
        default_distance_km=saved.default_distance_km,
        scenic=req.scenic if req.scenic is not None else saved.scenic,
        avoid_hills=req.avoid_hills if req.avoid_hills is not None else saved.avoid_hills,
        prefer_loop=req.prefer_loop if req.prefer_loop is not None else saved.prefer_loop,
        surface=req.surface if req.surface is not None else saved.surface,
    )
    if prefs.avoid_hills and prefs.terrain == "hill":
        prefs.terrain = "mixed"
    return target_km, prefs


# ── 동적 탐색 반경 ─────────────────────────────────────────────────────────────

# 거리 보장 v2.1 — 비대칭 밴드 (2026-07-20 최종 룰링, Ivan 절충안: 폭 0.6으로
# 명중률 확보): **target−0.1 ≤ actual ≤ target+0.5km**만 합격.
# TF 실기기 5km→3.0km 낙산 사례 계기 — 구 ±0.5 대칭이 "5km→4.5km"를 합격시키던
# 하한을 −0.1로 조임. 불합격은 후보 보관 후 반경 루프 재시도(cap 4 불변).
# 전패 시(v2.1 확정): **미달(<target−0.1) 후보 반환 금지** — 초과 후보 최선만
# target_missed=True로 서빙, 초과 0이면 RouteGenerationFailed(기존 502
# route_generation_failed 계약 재사용, 쿼터 미소모 — 프론트 "다시 설정" 유도).
_UNDER_TOLERANCE_KM = 0.1
_OVER_TOLERANCE_KM = 0.5
_MAX_RADIUS_KM = 8.0

# v2.2 (2026-07-20 긴급 재보정 — 실전 명중률 0 대응):
# ① 적응형 팽창비: attempt N의 실측 ratio(스냅/체인)를 N+1의 체인 목표에 피드백.
#    실측 13건 분포(중앙값 1.58, 범위 1.09~2.11)상 어떤 고정 상수도 폭 0.6 밴드를
#    1회에 못 맞춤 — 직전 관측이 같은 지역의 최선 추정치. 관측치는 클램프
#    [1.1, 2.2] (분포 밖 극단 관측이 다음 조준을 망치는 것 방지).
# ② 전패 초과 서빙 캡: 초과 최선이 target+1.0 넘으면 서빙 대신 실패(502) —
#    "6.3km는 5km 요청의 답이 아니다"(오너). 캡 값 1.0은 판단 플래그.
_RATIO_CLAMP = (1.1, 2.2)
_OVER_SERVE_CAP_KM = 1.0

# v2.3 스냅 전 사전 게이트 (부검 2026-07-20: 502 건의 후보 7.71/6.45km — 원인은
# aim 3.9에 chain 5.57 같은 Gemini 비순응): 체인이 aim×[0.75, 1.25] 밖이면
# T-map 없이 Gemini만 재추첨(attempt당 최대 2회). 소진 시 그 attempt는 miss.
# T-map 왕복(약 0.6s/leg×N)과 무효 후보 적재를 아낀다.
_PRE_GATE_BAND = (0.75, 1.25)
_PRE_GATE_REROLLS = 2
# 일방(end 좌표) 요청의 초기 팽창비 — corridor 경로는 루프보다 우회가 적어
# 스냅 팽창이 낮다(E2E 실측: 루프 1.6 vs 일방 체인≈직선). 적응형이 이후 보정.
_ONE_WAY_INFLATION = 1.25

# 예상 시간 = 러닝 기준 (2026-07-20 오너 확정): T-map 도보 시간(~13분/km)을
# 버리고 거리 × 기본 러닝 페이스 6'30"/km로 재계산. 개인 페이스 반영은 후속.
_RUN_PACE_MIN_PER_KM = 6.5


def _log_perf_failed(t0: float, perf: dict) -> None:
    """생성 실패(502) 경로의 계측 요약 — 성공 PERF와 동형(관측 공백 방지)."""
    logger.info(
        "[PERF] route generate FAILED: total=%.1fs | gemini=%.1fs(%d call) | "
        "tmap=%.1fs(%d leg) | attempts=%d | pre_rejects=%d",
        time.perf_counter() - t0, perf["gemini_s"], perf["gemini_calls"],
        perf["tmap_s"], perf["tmap_legs"], perf["attempts"], perf["pre_rejects"],
    )


def _within_band(actual_km: float, target_km: float) -> bool:
    """비대칭 합격 판정 — [target−0.1, target+0.5], 부동소수 여유 1e-9."""
    return (
        (target_km - _UNDER_TOLERANCE_KM - 1e-9)
        <= actual_km
        <= (target_km + _OVER_TOLERANCE_KM + 1e-9)
    )


def _waypoint_chain_km(route: RouteResponse) -> float:
    """웨이포인트 직선 체인 길이(km) — 팽창비 계측 로그용 (haversine 합)."""
    pts = [wp.coordinate for wp in route.waypoints]
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        p1, p2 = math.radians(a.lat), math.radians(b.lat)
        dp, dl = math.radians(b.lat - a.lat), math.radians(b.lng - a.lng)
        x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        total += 2 * 6371.0 * math.asin(math.sqrt(x))
    return total


def _dist_km(a: Coordinate, b: Coordinate) -> float:
    """두 좌표 간 haversine 거리(km) — end-aware 반경·중점 계산용."""
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = math.radians(b.lat - a.lat), math.radians(b.lng - a.lng)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


def _radius_schedule(target_km: float, start_end_km: float | None = None) -> list[float]:
    """목표 거리 비례 탐색 반경 시퀀스 (최대 4시도, 상한 8km, 중복 제거).

    루프 코스 L km는 기하학상 반경 ~L/4가 필요하므로 r0=clamp(target/4, 1, 8),
    이후 +1.0 → +2.5 → 8.0으로 점증 (기획의 +500m×16회 대신 비용·지연 통제형).

    v2.3 end-aware: end 좌표가 있는 일방 요청은 탐색 원이 start-end corridor를
    덮어야 한다 — 중점 중심 원 반경 max(r0, |start−end|/2 + 1.0). start 중심
    r0=target/4 원은 |start−end|≈target일 때 도착지에 못 닿는 기하 모순(현행
    미구현이던 것 신규 — Ivan 일방통행 파킹 사유).
    """
    r0 = min(_MAX_RADIUS_KM, max(1.0, round(target_km / 4, 1)))
    if start_end_km is not None:
        r0 = min(_MAX_RADIUS_KM, max(r0, round(start_end_km / 2 + 1.0, 1)))
    out: list[float] = []
    for r in (r0, r0 + 1.0, r0 + 2.5, _MAX_RADIUS_KM):
        r = min(round(r, 1), _MAX_RADIUS_KM)
        if r not in out:
            out.append(r)
    return out


def _filter_conflicting_avoid_tags(
    avoid_tags: list[str], prefs: AiCourseSettings
) -> list[str]:
    """Drop community hints that contradict the user's explicit preference.

    명시적 유저 선호 > 커뮤니티 힌트: terrain='hill'이면 '오르막많음' 회피를,
    surface='trail'이면 '노면나쁨'(→ well-paved 유도) 회피를 제외한다.
    """
    dropped = set()
    if prefs.terrain == "hill":
        dropped.add("오르막많음")
    if prefs.surface == "trail":
        dropped.add("노면나쁨")
    return [t for t in avoid_tags if t not in dropped]


async def create_running_route(
    req: RouteRequest, user_id: str | None = None
) -> RouteResponse:
    """Produce a running route for the given request.

    Steps:
      1. Ask OpenAI to design a route (structured via function calling).
      2. (Optional) Resolve the pitstop keyword to a real nearby place.
      3. (Optional) Fetch real pedestrian path geometry from the Map API.

    user_id (from a validated token) is stored on the saved route; None for
    anonymous requests.
    """
    # Step 0: learning loop — gather what nearby runners disliked, so the
    # model can avoid it. Best-effort: returns [] on any failure. The user's
    # saved ai_course settings load concurrently (also best-effort).
    avoid_tags, (saved_prefs, lang) = await asyncio.gather(
        feedback_service.collect_avoidance_hints(req.start),
        _course_context(user_id),
    )

    # If the client points at a specific past route, add its negative
    # feedback on top of the location-based hints (union, de-duplicated).
    if req.avoid_from_route_id:
        # owner_id 전달 — 본인 소유 route만 학습 (남의 비공개 route 프로브 차단, M4)
        for tag in await feedback_service.collect_route_avoidance_hints(
            req.avoid_from_route_id, owner_id=user_id
        ):
            if tag not in avoid_tags:
                avoid_tags.append(tag)

    # 우선순위: body 명시값 > 유저 설정 > 서버 기본값. 그리고 명시적 선호와
    # 모순되는 커뮤니티 회피 힌트는 제거 (선호가 이긴다).
    target_km, prefs = _resolve_course_prefs(req, saved_prefs)
    avoid_tags = _filter_conflicting_avoid_tags(avoid_tags, prefs)

    # Step 1~3을 동적 탐색 반경 루프로: 좁은 반경에서 시작해 실패(경로 연결
    # 불가 / 실측 미달)하면 반경을 넓혀 재시도. 출발지는 고정.
    best: RouteResponse | None = None
    best_meta: dict | None = None  # 채택 attempt 계측(리포트 B — 영속화)
    miss_candidates: list[tuple[float, RouteResponse, dict]] = []  # (실측 km, route, meta)
    nopath_candidate: tuple[RouteResponse, dict] | None = None  # (route, meta)
    pitstop_places: list | None = None  # Kakao 검색은 결정적 — 첫 성공 결과 재사용

    # 구간별 계측 (병목 관측용 — 항상 켜둔 경량 타이머)
    _t0 = time.perf_counter()
    _perf = {"gemini_s": 0.0, "gemini_calls": 0, "tmap_s": 0.0, "tmap_legs": 0,
             "attempts": 0, "pre_rejects": 0}

    # v2.3 end-aware: 일방(end 좌표) 요청은 탐색 원을 corridor 중점 기준으로,
    # 초기 팽창비도 낮게(직선형 경로 — E2E 부검에서 aim 3.2로 4/4 pre_miss 전멸).
    start_end_km = _dist_km(req.start, req.end) if req.end else None
    # 실행가능성 게이트(v2.3 마감): 직선거리 > target×0.8이면 시작 전에 422 —
    # Gemini/T-map 비용 0으로 반려(전패 502보다 정직·저렴).
    if (start_end_km is not None
            and start_end_km > target_km * _ONE_WAY_MAX_DIST_FACTOR + 1e-9):
        min_target = math.ceil(start_end_km / _ONE_WAY_MAX_DIST_FACTOR * 10) / 10
        raise OneWayEndTooFar(round(start_end_km, 1), min_target)
    radius_center = None
    if req.end is not None:
        radius_center = Coordinate(
            lat=(req.start.lat + req.end.lat) / 2,
            lng=(req.start.lng + req.end.lng) / 2,
        )

    # 적응형 팽창비 추정치 — 첫 attempt는 초기 상수, 이후 직전 실측으로 갱신
    est_ratio = (openai_service._SNAP_INFLATION if start_end_km is None
                 else _ONE_WAY_INFLATION)

    for i, radius_km in enumerate(_radius_schedule(target_km, start_end_km)):
        _perf["attempts"] += 1
        chain_aim_km = (target_km + openai_service._BAND_AIM_KM) / est_ratio
        if start_end_km is not None:
            # 체인 물리 하한: start→…→end 체인은 직선거리보다 짧을 수 없다
            chain_aim_km = max(chain_aim_km, start_end_km * 1.05)
        chain_aim_km = round(chain_aim_km, 1)

        # v2.3 사전 게이트: 체인이 aim×[0.75, 1.25] 밖이면 T-map 없이 Gemini만
        # 재추첨(최대 2회). 전 롤 소진 시 **aim 최근접 롤로 salvage** — 원지시는
        # "소진 시 miss"였으나 E2E 부검에서 pre_miss가 attempt를 통째로 태워
        # 후보 고갈→502 양산(잠실 3/4·일방 4/4 소실). T-map은 attempt당 1회로
        # 동일하게 상한되므로 salvage가 비용 증가 없이 후보만 보존(판단 플래그).
        route = None
        chain_km = 0.0
        attempt_rejects = 0
        salvage: tuple[float, RouteResponse] | None = None  # (chain_km, cand)
        try:
            for _roll in range(1 + _PRE_GATE_REROLLS):
                _g = time.perf_counter()
                cand = await openai_service.generate_route(
                    target_distance_km=target_km,
                    start=req.start,
                    end=req.end,
                    pitstop_keyword=req.pitstop_keyword,
                    notes=req.notes,
                    avoid_tags=avoid_tags,
                    prefs=prefs,
                    radius_km=radius_km,
                    lang=lang,
                    chain_target_km=chain_aim_km,
                    radius_center=radius_center,
                )
                _perf["gemini_s"] += time.perf_counter() - _g
                _perf["gemini_calls"] += 1
                c_km = _waypoint_chain_km(cand)
                if (chain_aim_km * _PRE_GATE_BAND[0]
                        <= c_km
                        <= chain_aim_km * _PRE_GATE_BAND[1]):
                    route, chain_km = cand, c_km
                    break
                attempt_rejects += 1
                if salvage is None or abs(c_km - chain_aim_km) < abs(salvage[0] - chain_aim_km):
                    salvage = (c_km, cand)
            if route is None and salvage is not None:
                chain_km, route = salvage
        except OpenAIAPIError:
            # ①-a API 장애: 반경과 무관 — 확장 재시도는 낭비. 이미 확보한
            # 후보가 있으면 그걸로 마무리, 없으면 그대로 실패.
            if miss_candidates or nopath_candidate is not None:
                logger.warning("Gemini API 장애 (radius=%skm) — 기존 후보로 마무리", radius_km)
                break
            raise
        except (ValueError, ValidationError):
            # ①-b/c/d tool call 없음·파싱·검증 실패: 비결정적 — 이 시도만
            # 무효 처리하고 다음 반경으로 (반경이 커져도 손해 없음).
            logger.warning(
                "Gemini 응답 파싱/검증 실패 (radius=%skm) — 다음 반경으로 재시도",
                radius_km, exc_info=True,
            )
            continue
        finally:
            _perf["pre_rejects"] += attempt_rejects

        if route is None:  # 롤 전부 예외 없이 실패한 극단 케이스만 (이론상 salvage가 항상 존재)
            continue

        # Step 2: snap the pitstop to a real place if a keyword was given.
        if req.pitstop_keyword:
            try:
                if pitstop_places is None:
                    pitstop_places = await map_service.search_places(
                        req.pitstop_keyword, near=req.start
                    )
                if pitstop_places:
                    nearest = pitstop_places[0]
                    for wp in route.waypoints:
                        if wp.is_pitstop:
                            wp.name = nearest.name
                            wp.coordinate = nearest.coordinate
                            wp.description = nearest.address
                            break
            except Exception:  # noqa: BLE001 - map enrichment is best-effort
                # If the Map API fails, keep the AI-suggested pitstop as-is.
                logger.warning(
                    "Pitstop place lookup failed for %r; keeping AI suggestion.",
                    req.pitstop_keyword,
                    exc_info=True,
                )

        route.search_radius_km = radius_km
        route.radius_expanded = i > 0

        # Step 3: 보행 경로 연결 + 실측 거리로 성공 판정 (비대칭 밴드).
        #   OK      — 연결됐고 target−0.1 ≤ 실측 ≤ target+0.5 → 즉시 채택
        #   MISS    — 연결됐지만 밴드 밖(미달·초과) → 후보 보관, 재시도
        #   NO_PATH — 연결 실패(또는 waypoint<2) → AI 추정 폴백 보관, 반경 확장
        # (반경 확장은 미달에 유효 — 초과 케이스도 스케줄 그대로 진행: 프롬프트가
        #  체인 목표를 고정하므로 반경이 커져도 오버슈트를 키우지 않고 재추첨 효과만)
        # status: OK / MISS / NO_PATH(T-map 장애 → AI추정 폴백) /
        #         UNTRAVERSABLE(강 위 등 보행 불가 leg → 후보 폐기, 리포트 A)
        status = "NO_PATH"
        actual_km = route.total_distance_km
        # chain_km은 사전 게이트에서 이미 계산됨 (Gemini 기하 의도 — 팽창비 재료)
        if len(route.waypoints) >= 2:
            try:
                via = [wp.coordinate for wp in route.waypoints[1:-1]] or None
                _m = time.perf_counter()
                pedestrian = await map_service.get_pedestrian_route(
                    origin=route.waypoints[0].coordinate,
                    destination=route.waypoints[-1].coordinate,
                    waypoints=via,
                )
                _perf["tmap_s"] += time.perf_counter() - _m
                _perf["tmap_legs"] += len(route.waypoints) - 1
                route.polyline = pedestrian.path
                # 표시용: 거리 소수 1자리 (소수점 노출 방지). 시간은 루프 뒤
                # 일괄 러닝 환산(_RUN_PACE_MIN_PER_KM) — T-map 도보 시간 미사용.
                raw_km = pedestrian.distance_m / 1000.0
                route.total_distance_km = round(raw_km, 1)
                # 게이트는 반올림 전 원값으로 (v2.1 — 0.1 표시 반올림이 ±50m
                # 경계를 뭉개던 것 제거: 5.55는 표시 5.5여도 밴드 밖으로 판정)
                actual_km = raw_km
                status = "OK" if _within_band(raw_km, target_km) else "MISS"
                # 적응형 피드백: 이 attempt의 실측 팽창비를 다음 조준에 반영
                if chain_km > 0:
                    est_ratio = min(max(raw_km / chain_km, _RATIO_CLAMP[0]),
                                    _RATIO_CLAMP[1])
            except map_service.LegNotRoutable:
                # traversability 게이트(리포트 A): 실보행 불가 leg가 있는 후보 —
                # 폐기(어떤 candidate에도 미보관 → 서빙 불가). 물 위 직선 코스를
                # 주느니 재추첨/다음 반경, 최종엔 정직한 502가 낫다. pre-snap
                # 게이트는 거리만 보므로 강 양안 웨이포인트를 못 거른다(스냅 후에만
                # 보행 가능성 판정 가능) — 이 게이트가 그 공백을 메운다.
                status = "UNTRAVERSABLE"
            except Exception:  # noqa: BLE001 - keep AI estimates if routing fails
                # T-map API 장애(HTTP/네트워크) — AI 추정 폴백(polyline 없음).
                # 좌표는 Gemini가 육지 기반이라 물 위 직선 문제와 무관.
                logger.warning(
                    "Pedestrian routing (%s) failed; falling back to AI distance "
                    "estimate. Polyline will be unavailable.",
                    map_service.settings.map_provider,
                    exc_info=True,
                )

        # 시도별 계측 1줄 — 팽창비 재보정 재료(_SNAP_INFLATION, 20건 축적 시
        # 중앙값 재산정). 좌표·유저 id 미기록(위치 프라이버시), 키 없음.
        snap_ratio = ((actual_km / chain_km)
                      if (chain_km > 0 and status != "NO_PATH") else 0.0)
        logger.info(
            "route_gen attempt=%d radius=%.1f chain_km=%.2f snapped_km=%.2f "
            "ratio=%.2f target=%.1f aim=%.1f pre_reject=%d verdict=%s",
            i + 1, radius_km, chain_km,
            actual_km if status != "NO_PATH" else 0.0,
            snap_ratio, target_km, chain_aim_km, attempt_rejects, status.lower(),
        )

        # 계측 영속화 재료(리포트 B): 이 attempt의 채택 시 저장할 메타.
        # 위치·유저 식별은 담지 않는다(코스 행 자체에 좌표 있음 — 중복 불요).
        attempt_meta = {
            "ratio": round(snap_ratio, 3),
            "attempt": i + 1,
            "pre_reject": attempt_rejects,
        }

        if status == "OK":
            best = route
            best_meta = {**attempt_meta, "verdict": "hit"}
            break
        if status == "MISS":
            miss_candidates.append((actual_km, route, attempt_meta))
        elif status == "NO_PATH":
            nopath_candidate = (route, attempt_meta)
        # UNTRAVERSABLE: 폐기 — 어떤 후보에도 안 담는다(서빙 금지)

    if best is None:
        # 루프 소진: |오차| 최소 후보 채택 + target_missed 플래그(반려 대신
        # 최선+정직한 표시 — 프론트가 "요청 거리와 달라요" 안내). 연결 후보가
        # 없으면 AI 추정 폴백(동일 기준으로 플래그). 유효 응답 0이면 실패.
        if miss_candidates:
            # v2.1: 미달(<target−0.1) 후보는 반환 금지. v2.2: 초과도
            # target+_OVER_SERVE_CAP_KM(1.0)까지만 서빙 — 그보다 큰 이탈은
            # "5km 요청의 답이 아니다"(오너). 서빙 가능 초과가 없으면 생성 실패
            # (502, 쿼터 미소모 — 프론트 "다시 설정" 유도).
            over = [
                (k, r, m) for k, r, m in miss_candidates
                if target_km < k <= target_km + _OVER_SERVE_CAP_KM + 1e-9
            ]
            if over:
                _k, best, _meta = min(over, key=lambda t: t[0] - target_km)
                best.target_missed = True
                best_meta = {**_meta, "verdict": "missed"}
            else:
                _log_perf_failed(_t0, _perf)  # 502도 계측(관측 공백 방지)
                raise RouteGenerationFailed()
        elif nopath_candidate is not None:
            best, _meta = nopath_candidate
            best.target_missed = not _within_band(
                best.total_distance_km, target_km
            )
            best_meta = {**_meta, "verdict": "nopath"}
        else:
            _log_perf_failed(_t0, _perf)
            raise RouteGenerationFailed()

    # 예상 시간 = 러닝 기준 일괄 환산 (오너 확정 2026-07-20) — T-map 도보 시간·
    # AI 추정 무관하게 최종 거리 × 6'30"/km. NO_PATH 폴백 경로 포함 단일 소스.
    best.estimated_duration_min = float(
        round(best.total_distance_km * _RUN_PACE_MIN_PER_KM)
    )
    # 일방통행 플래그(리포트 D) — 생성 응답에도 노출(_save_route의 DB 저장과 동일 기준)
    best.is_one_way = req.end is not None

    # 계측 요약 — 병목 분포 관측 (총합/Gemini/T-map/재시도)
    _total = time.perf_counter() - _t0
    logger.info(
        "[PERF] route generate: total=%.1fs | gemini=%.1fs(%d call) | "
        "tmap=%.1fs(%d leg) | attempts=%d | pre_rejects=%d | expanded=%s",
        _total, _perf["gemini_s"], _perf["gemini_calls"],
        _perf["tmap_s"], _perf["tmap_legs"], _perf["attempts"],
        _perf["pre_rejects"], best.radius_expanded,
    )

    # 계측 영속화(리포트 B): 채택 attempt 메타 + 전체 시도/재추첨 카운트를 코스
    # 행에 함께 저장 → 링버퍼 유실과 무관하게 ratio 분포·재보정 트리거를 조회 가능.
    # verdict: hit(밴드 내)·missed(초과 서빙)·nopath(AI 추정 폴백). 502는 행 없음
    # (실패 계측은 별도 테이블 없이 PERF FAILED 로그 유지 — 과설계 금지).
    gen_meta = {**(best_meta or {"verdict": "unknown"}),
                "attempts": _perf["attempts"],
                "pre_rejects": _perf["pre_rejects"],
                "one_way": req.end is not None}

    # Step 4: persist the generated route to Supabase (best-effort).
    await _save_route(req, best, user_id, target_distance_km=target_km, gen_meta=gen_meta)

    return best


async def _save_route(
    req: RouteRequest,
    route: RouteResponse,
    user_id: str | None = None,
    target_distance_km: float | None = None,
    gen_meta: dict | None = None,
) -> None:
    """Insert the generated route into the Supabase `routes` table.

    Best-effort: saving is a side feature, so any failure is logged and
    swallowed rather than breaking route generation. user_id is left NULL
    until authentication is wired up.

    supabase-py is synchronous, so the blocking call is run in a worker
    thread to avoid stalling the async event loop.
    """
    # Start coordinate (from the first waypoint) powers the location-based
    # learning loop; store it as top-level columns for fast proximity queries.
    start_coord = route.waypoints[0].coordinate if route.waypoints else None

    record = {
        # Owner (from a validated token; None when anonymous)
        "user_id": user_id,
        # Input values (RouteRequest; target은 설정 폴백이 반영된 최종값)
        "target_distance_km": (
            target_distance_km
            if target_distance_km is not None
            else req.target_distance_km
        ),
        "pitstop_keyword": req.pitstop_keyword,
        "notes": req.notes,
        # Start coordinate (for the learning loop)
        "start_lat": start_coord.lat if start_coord else None,
        "start_lng": start_coord.lng if start_coord else None,
        # Generated result (RouteResponse)
        "summary": route.summary,
        "total_distance_km": route.total_distance_km,
        "estimated_duration_min": route.estimated_duration_min,
        "waypoints": [wp.model_dump() for wp in route.waypoints],
        "polyline": (
            [c.model_dump() for c in route.polyline]
            if route.polyline is not None
            else None
        ),
        # 일방통행 여부 (리포트 D) — end 좌표 동봉 요청이면 일방. end 좌표 자체는
        # 저장 안 하므로 이 플래그가 유일한 사후 판별 수단.
        "is_one_way": req.end is not None,
        # 생성 계측 (리포트 B) — ratio·attempt·pre_reject·verdict. 위치·유저
        # 식별 없음(코스 행 자체에 좌표 있음). None이면 컬럼 default(null).
        "gen_meta": gen_meta,
    }

    try:
        supabase = get_supabase_admin()
        result = await asyncio.to_thread(
            lambda: supabase.table("routes").insert(record).execute()
        )
        saved_id = result.data[0]["id"] if result.data else "?"
        logger.info("Saved generated route to Supabase (id=%s).", saved_id)
    except Exception:  # noqa: BLE001 - persistence is best-effort
        logger.warning(
            "Failed to save generated route to Supabase; "
            "route generation still succeeded.",
            exc_info=True,
        )


async def list_routes(user_id: str, limit: int = 20) -> list[StoredRoute]:
    """Return the caller's saved routes, newest first.

    Scoped to `user_id` in app code (the service_role client bypasses RLS,
    so this filter is what enforces "my data only" until RLS is enabled).
    """
    limit = max(1, min(limit, 100))
    supabase = get_supabase_admin()
    result = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [StoredRoute(**row) for row in result.data]


async def get_route(route_id: str, user_id: str) -> StoredRoute | None:
    """Return one of the caller's saved routes by id, or None.

    Returns None if the route doesn't exist OR isn't owned by `user_id`,
    so a non-owner cannot fetch someone else's route.
    """
    supabase = get_supabase_admin()
    result = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("id", route_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return StoredRoute(**result.data[0])


_UNIQUE_VIOLATION = "23505"


async def _copy_counts(route_ids: list[str]) -> dict[str, int]:
    """Return {route_id: copy_count} for the given route ids (one IN query)."""
    if not route_ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("copied_from")
        .in_("copied_from", route_ids)
        .execute()
    )
    counts: dict[str, int] = defaultdict(int)
    for row in res.data:
        counts[row["copied_from"]] += 1
    return dict(counts)


async def _like_counts(route_ids: list[str]) -> dict[str, int]:
    """Return {route_id: like_count} for the given ids (one IN query)."""
    if not route_ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("route_likes")
        .select("route_id")
        .in_("route_id", route_ids)
        .execute()
    )
    counts: dict[str, int] = defaultdict(int)
    for row in res.data:
        counts[row["route_id"]] += 1
    return dict(counts)


async def _liked_by_me(route_ids: list[str], user_id: str) -> set[str]:
    """Return the set of route_ids that `user_id` has liked (one IN + eq query)."""
    if not route_ids:
        return set()
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("route_likes")
        .select("route_id")
        .in_("route_id", route_ids)
        .eq("user_id", user_id)
        .execute()
    )
    return {row["route_id"] for row in res.data}


async def _comment_counts(route_ids: list[str]) -> dict[str, int]:
    """Return {route_id: comment_count} for the given ids (one IN query)."""
    if not route_ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("route_comments")
        .select("route_id")
        .in_("route_id", route_ids)
        .execute()
    )
    counts: dict[str, int] = defaultdict(int)
    for row in res.data:
        counts[row["route_id"]] += 1
    return dict(counts)


async def like_route(route_id: str, user_id: str) -> None:
    """Add a like to a public route. Idempotent: double-liking is silently ignored.

    Raises RouteNotFound if the route doesn't exist or is not public (treats
    private routes the same as missing to avoid revealing their existence).
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("is_public, user_id")
        .eq("id", route_id)
        .limit(1)
        .execute()
    )
    if not res.data or not res.data[0]["is_public"]:
        raise RouteNotFound()

    route_owner = res.data[0].get("user_id")
    # 차단·비공개 게이트 — feed_allows(403)보다 선행(은닉 우선). 차단/비가시
    # 소유자의 코스는 존재 은닉(404), run kudos의 _can_see_run과 동일 정책.
    if route_owner and route_owner != user_id and not await profile_service.can_see_user(
        route_owner, user_id
    ):
        raise RouteNotFound()
    if route_owner and route_owner != user_id and not await profile_service.feed_allows(
        route_owner, "allow_likes"
    ):
        raise profile_service.FeedActionDisabled("likes")
    liked_new = True
    try:
        await asyncio.to_thread(
            lambda: supabase.table("route_likes")
            .insert({"route_id": route_id, "user_id": user_id})
            .execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:  # 23505 = already liked, that's fine
            raise
        liked_new = False

    if liked_new and route_owner:
        try:
            await notification_service.create_notification(
                recipient_id=route_owner,
                actor_id=user_id,
                type="route_liked",
                target_id=route_id,
                target_type="route",
            )
        except Exception:
            logger.warning("route_liked 알림 생성 실패", exc_info=True)


async def unlike_route(route_id: str, user_id: str) -> None:
    """Remove a like from a route. Idempotent: unliking a non-liked route is a no-op."""
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("route_likes")
        .delete()
        .eq("route_id", route_id)
        .eq("user_id", user_id)
        .execute()
    )


async def bookmark_route(route_id: str, user_id: str) -> None:
    """Bookmark a public route. Idempotent: re-bookmarking is silently ignored.

    Same visibility rule as likes (404 for missing/private routes). Bookmarks
    are a private action, so unlike likes no notification is sent.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("is_public")
        .eq("id", route_id)
        .limit(1)
        .execute()
    )
    if not res.data or not res.data[0]["is_public"]:
        raise RouteNotFound()

    try:
        await asyncio.to_thread(
            lambda: supabase.table("route_bookmarks")
            .insert({"route_id": route_id, "user_id": user_id})
            .execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:  # 23505 = already bookmarked, fine
            raise


async def unbookmark_route(route_id: str, user_id: str) -> None:
    """Remove a bookmark. Idempotent: removing a non-bookmark is a no-op."""
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("route_bookmarks")
        .delete()
        .eq("route_id", route_id)
        .eq("user_id", user_id)
        .execute()
    )


async def delete_route(route_id: str, user_id: str) -> None:
    """본인 코스 하드 삭제 (run-delete의 단순 동생). 복구 없음.

    소유 확인(타인/없음/기삭제 전부 404 은닉 — 존재 숨김 표준) → 행 삭제.
    캐스케이드는 전부 DB FK로 처리(실증 2026-07-21):
      - route_bookmarks·route_likes·route_comments·coach_scripts: on delete
        **cascade** → 자동 소멸(유일한 커밋 지점, 앱 재계산 코드 없음)
      - runs.route_id·routes.copied_from: on delete **set null** → run 기록·
        복사본 코스는 잔존(연결만 끊김 — 러닝 기록/파생 코스는 독립 자산)
    피드 route_summary는 runs.route_id JOIN routes.summary 라이브 계산이라
    route_id가 null 되면 자동으로 null(코스 피드는 routes 직접 조회라 그냥 빠짐).
    채팅 공유는 run_share(run 대상)만 있고 route 공유 기능은 없음 — 무관.

    best-effort 정리: route 대상 알림(route_liked·route_commented) — target_id가
    route_id인 polymorphic 알림이라 FK 없음, 방치 시 stale 404 탭(run-delete 선례).
    코스엔 Storage 자산 없음(코스 이미지는 크루 전용) — 사진 정리 불필요.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("id")
        .eq("id", route_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise RouteNotFound()  # 타인/없음/기삭제 — 동일 404(은닉)

    deleted = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .delete()
        .eq("id", route_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not deleted.data:
        raise RouteNotFound()  # 동시 삭제 레이스 — 패자 반환행 0 → 404 (L8 패턴)

    # best-effort 정리 — route 대상 알림 (실패는 로그만, CLAUDE.md)
    try:
        await asyncio.to_thread(
            lambda: supabase.table("notifications")
            .delete()
            .eq("target_type", "route")
            .eq("target_id", route_id)
            .execute()
        )
    except Exception:  # noqa: BLE001
        logger.warning("route %s 알림 정리 실패 — stale 알림 잔존(탭 404)",
                       route_id, exc_info=True)


async def list_bookmarked_routes(
    user_id: str, limit: int = 20, offset: int = 0
) -> list[PublicRouteResponse]:
    """The caller's bookmarked routes, most recently bookmarked first.

    Routes that went private after being bookmarked are hidden (same
    don't-reveal rule as elsewhere), so a page can come back shorter than
    `limit` even when more bookmarks exist.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("route_bookmarks")
        .select("route_id")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    route_ids = [row["route_id"] for row in res.data]
    if not route_ids:
        return []

    routes_res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .in_("id", route_ids)
        .eq("is_public", True)
        .execute()
    )
    if not routes_res.data:
        return []

    # Preserve bookmark order (the IN query returns rows unordered).
    by_id = {r["id"]: r for r in routes_res.data}
    rows = [by_id[rid] for rid in route_ids if rid in by_id]
    return await _to_public_responses(rows, user_id)


async def _to_public_responses(
    rows: list[dict], user_id: str
) -> list[PublicRouteResponse]:
    """Enrich raw route rows with counts/is_liked/nicknames (batch, no N+1)."""
    route_ids = [r["id"] for r in rows]
    copy_counts, like_counts, liked_set, comment_counts, nicknames = await asyncio.gather(
        _copy_counts(route_ids),
        _like_counts(route_ids),
        _liked_by_me(route_ids, user_id),
        _comment_counts(route_ids),
        profile_service.get_profile_briefs([r.get("user_id") for r in rows]),
    )
    return [
        PublicRouteResponse(
            **row,
            owner_id=row.get("user_id"),
            is_mine=(row.get("user_id") == user_id),
            owner_nickname=nicknames.get(row.get("user_id"), {}).get("nickname"),
            owner_avatar_url=nicknames.get(row.get("user_id"), {}).get("avatar_url"),
            copy_count=copy_counts.get(row["id"], 0),
            like_count=like_counts.get(row["id"], 0),
            is_liked=row["id"] in liked_set,
            comment_count=comment_counts.get(row["id"], 0),
        )
        for row in rows
    ]


async def list_following_feed(
    user_id: str, limit: int = 20, offset: int = 0
) -> list[PublicRouteResponse]:
    """Public routes by users the caller follows, newest first (limit+offset).

    Returns [] when the caller follows no one. The IN-list approach is fine
    at MVP scale; switch to a join/RPC if following counts grow very large.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("follows")
        .select("following_id")
        .eq("follower_id", user_id)
        .execute()
    )
    following_ids = [row["following_id"] for row in res.data]
    if not following_ids:
        return []

    result = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("is_public", True)
        .in_("user_id", following_ids)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    if not result.data:
        return []
    return await _to_public_responses(result.data, user_id)


async def list_public_routes(
    user_id: str, limit: int = 20, sort: str = "newest"
) -> list[PublicRouteResponse]:
    """Return public routes for the discovery feed.

    sort='newest'  — DB-level ORDER BY created_at DESC + LIMIT (fast).
    sort='popular' — fetch all public routes, batch-count copies, sort in
                     Python by copy_count DESC, then apply limit. Suitable
                     while the public route count is small; switch to an RPC
                     aggregate when scale demands it.
    """
    limit = max(1, min(limit, 100))
    supabase = get_supabase_admin()

    if sort == "newest":
        result = await asyncio.to_thread(
            lambda: supabase.table("routes")
            .select("*")
            .eq("is_public", True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = result.data
    else:  # popular — need all rows to rank, then limit
        result = await asyncio.to_thread(
            lambda: supabase.table("routes")
            .select("*")
            .eq("is_public", True)
            .execute()
        )
        rows = result.data

    if not rows:
        return []
    # 결정 B(둘러보기로 확장): 차단·비공개 계정 owner의 코스는 둘러보기 피드에서도
    # 제외(검색과 동형). 'popular' 정렬/limit 및 enrichment보다 앞 — owner 없는
    # 코스(user_id None)는 유지. (newest는 DB limit 후 필터라 소폭 under-fill 가능.)
    visible = await profile_service.visible_owners(user_id, [r.get("user_id") for r in rows])
    rows = [r for r in rows if r.get("user_id") in visible or r.get("user_id") is None]
    if not rows:
        return []

    route_ids = [r["id"] for r in rows]
    copy_counts, like_counts, liked_set, comment_counts, nicknames = await asyncio.gather(
        _copy_counts(route_ids),
        _like_counts(route_ids),
        _liked_by_me(route_ids, user_id),
        _comment_counts(route_ids),
        profile_service.get_profile_briefs([r.get("user_id") for r in rows]),
    )

    if sort == "popular":
        rows = sorted(rows, key=lambda r: copy_counts.get(r["id"], 0), reverse=True)[:limit]

    return [
        PublicRouteResponse(
            **row,
            owner_id=row.get("user_id"),
            is_mine=(row.get("user_id") == user_id),
            owner_nickname=nicknames.get(row.get("user_id"), {}).get("nickname"),
            owner_avatar_url=nicknames.get(row.get("user_id"), {}).get("avatar_url"),
            copy_count=copy_counts.get(row["id"], 0),
            like_count=like_counts.get(row["id"], 0),
            is_liked=row["id"] in liked_set,
            comment_count=comment_counts.get(row["id"], 0),
        )
        for row in rows
    ]


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two (lat, lng) points in kilometres."""
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lng2 - lng1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def search_nearby_routes(
    lat: float,
    lng: float,
    radius_km: float,
    sort_by: str,
    user_id: str,
    limit: int = 20,
) -> list[PublicRouteResponse]:
    """Return public routes whose start point lies within radius_km of (lat, lng).

    Step 1 — SQL bounding box (fast, uses indexes on start_lat / start_lng).
    Step 2 — Python Haversine to drop box-corner false positives.
    Step 3 — sort and limit in Python (copy_count for 'popular', created_at for 'newest').
    """
    limit = max(1, min(limit, 100))
    radius_km = max(0.1, min(radius_km, 50.0))  # 상한 없으면 전 공개코스 풀스캔
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.0 * math.cos(math.radians(lat)))

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("is_public", True)
        .gte("start_lat", lat - lat_delta)
        .lte("start_lat", lat + lat_delta)
        .gte("start_lng", lng - lng_delta)
        .lte("start_lng", lng + lng_delta)
        .order("created_at", desc=True)
        .execute()
    )

    # Step 2: precise circle filter (removes box-corner false positives)
    rows = [
        r for r in res.data
        if r.get("start_lat") is not None
        and r.get("start_lng") is not None
        and _haversine_km(lat, lng, r["start_lat"], r["start_lng"]) <= radius_km
    ]
    if not rows:
        return []
    # 결정 B: 비공개 계정 owner의 코스는 검색(근처)에서 제외
    visible = await profile_service.visible_owners(user_id, [r.get("user_id") for r in rows])
    rows = [r for r in rows if r.get("user_id") in visible or r.get("user_id") is None]
    if not rows:
        return []

    route_ids = [r["id"] for r in rows]
    copy_counts, like_counts, liked_set, comment_counts, nicknames = await asyncio.gather(
        _copy_counts(route_ids),
        _like_counts(route_ids),
        _liked_by_me(route_ids, user_id),
        _comment_counts(route_ids),
        profile_service.get_profile_briefs([r.get("user_id") for r in rows]),
    )

    if sort_by == "popular":
        rows = sorted(rows, key=lambda r: copy_counts.get(r["id"], 0), reverse=True)

    rows = rows[:limit]

    return [
        PublicRouteResponse(
            **row,
            owner_id=row.get("user_id"),
            is_mine=(row.get("user_id") == user_id),
            owner_nickname=nicknames.get(row.get("user_id"), {}).get("nickname"),
            owner_avatar_url=nicknames.get(row.get("user_id"), {}).get("avatar_url"),
            copy_count=copy_counts.get(row["id"], 0),
            like_count=like_counts.get(row["id"], 0),
            is_liked=row["id"] in liked_set,
            comment_count=comment_counts.get(row["id"], 0),
        )
        for row in rows
    ]


def _sanitize(q: str) -> str:
    """Remove chars that break PostgREST filter syntax or inject extra wildcards."""
    return q.strip().replace(",", "").replace("*", "")


async def search_public_routes(
    q: str, user_id: str, limit: int = 20
) -> list[PublicRouteResponse]:
    """Search public routes by summary (case-insensitive partial match).

    Returns [] when q is blank after sanitization.
    Enriches results with copy_count, like_count, is_liked, comment_count, owner_nickname
    using the same batch pattern as list_public_routes.
    """
    safe = _sanitize(q)
    if not safe:
        return []

    limit = max(1, min(limit, 100))
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("is_public", True)
        .ilike("summary", f"%{safe}%")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = res.data
    if not rows:
        return []
    # 결정 B: owner가 비공개 계정이면 코스가 public이어도 검색에서 제외
    visible = await profile_service.visible_owners(user_id, [r.get("user_id") for r in rows])
    rows = [r for r in rows if r.get("user_id") in visible or r.get("user_id") is None]
    if not rows:
        return []

    route_ids = [r["id"] for r in rows]
    copy_counts, like_counts, liked_set, comment_counts, nicknames = await asyncio.gather(
        _copy_counts(route_ids),
        _like_counts(route_ids),
        _liked_by_me(route_ids, user_id),
        _comment_counts(route_ids),
        profile_service.get_profile_briefs([r.get("user_id") for r in rows]),
    )

    return [
        PublicRouteResponse(
            **row,
            owner_id=row.get("user_id"),
            is_mine=(row.get("user_id") == user_id),
            owner_nickname=nicknames.get(row.get("user_id"), {}).get("nickname"),
            owner_avatar_url=nicknames.get(row.get("user_id"), {}).get("avatar_url"),
            copy_count=copy_counts.get(row["id"], 0),
            like_count=like_counts.get(row["id"], 0),
            is_liked=row["id"] in liked_set,
            comment_count=comment_counts.get(row["id"], 0),
        )
        for row in rows
    ]


async def set_route_public(
    route_id: str, user_id: str, is_public: bool
) -> StoredRoute | None:
    """Publish/unpublish one of the caller's routes. None if not found/not theirs."""
    supabase = get_supabase_admin()
    result = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .update({"is_public": is_public})
        .eq("id", route_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        return None
    return StoredRoute(**result.data[0])


async def copy_route(route_id: str, user_id: str) -> StoredRoute:
    """Copy a route ('이 코스 달리기') into the caller's account.

    The source must be public OR owned by the caller. The copy is created
    private, owned by the caller, with copied_from pointing at the source.
    The source is left unchanged. Raises RouteNotFound otherwise.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("id", route_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise RouteNotFound()
    src = res.data[0]
    # Can't copy someone else's private route (don't reveal it exists).
    if not src["is_public"] and src.get("user_id") != user_id:
        raise RouteNotFound()

    record = {
        "user_id": user_id,
        "is_public": False,  # copies start private
        "copied_from": route_id,
        # Copy the route content (but not the source owner's private notes)
        "target_distance_km": src.get("target_distance_km"),
        "pitstop_keyword": src.get("pitstop_keyword"),
        "start_lat": src.get("start_lat"),
        "start_lng": src.get("start_lng"),
        "summary": src["summary"],
        "total_distance_km": src["total_distance_km"],
        "estimated_duration_min": src.get("estimated_duration_min"),
        "waypoints": src.get("waypoints") or [],
        "polyline": src.get("polyline"),
    }
    out = await asyncio.to_thread(
        lambda: supabase.table("routes").insert(record).execute()
    )
    logger.info("User %s copied route %s -> %s.", user_id, route_id, out.data[0]["id"])
    return StoredRoute(**out.data[0])


async def create_comment(route_id: str, user_id: str, content: str) -> CommentResponse:
    """Add a comment to a public route.

    Raises RouteNotFound if the route doesn't exist or is not public.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("is_public, user_id")
        .eq("id", route_id)
        .limit(1)
        .execute()
    )
    if not res.data or not res.data[0]["is_public"]:
        raise RouteNotFound()

    route_owner = res.data[0].get("user_id")
    # 차단·비공개 게이트 — feed_allows(403)보다 선행(은닉 우선, like_route와 동형).
    if route_owner and route_owner != user_id and not await profile_service.can_see_user(
        route_owner, user_id
    ):
        raise RouteNotFound()
    if route_owner and route_owner != user_id and not await profile_service.feed_allows(
        route_owner, "allow_comments"
    ):
        raise profile_service.FeedActionDisabled("comments")

    out = await asyncio.to_thread(
        lambda: supabase.table("route_comments")
        .insert({"route_id": route_id, "user_id": user_id, "content": content})
        .execute()
    )
    row = out.data[0]
    nicknames = await profile_service.get_profile_briefs([user_id])

    if route_owner:
        try:
            await notification_service.create_notification(
                recipient_id=route_owner,
                actor_id=user_id,
                type="route_commented",
                target_id=route_id,
                target_type="route",
            )
        except Exception:
            logger.warning("route_commented 알림 생성 실패", exc_info=True)

    brief = nicknames.get(user_id) or {}
    return CommentResponse(**row, nickname=brief.get("nickname"),
                           avatar_url=brief.get("avatar_url"))


async def list_comments(route_id: str, viewer_id: str, limit: int = 50) -> list[CommentResponse]:
    """Return comments on a public route, oldest first (차단 발신자 제외 — v3.6).

    Raises RouteNotFound if the route doesn't exist or is not public. owner
    잠금 게이트는 미적용 유지(공개 코스 = 공개 콘텐츠, 감사 3차 L 수용). 차단
    필터만: viewer와 차단 관계인 작성자 댓글은 목록에서 제외.
    """
    limit = max(1, min(limit, 100))
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("is_public")
        .eq("id", route_id)
        .limit(1)
        .execute()
    )
    if not res.data or not res.data[0]["is_public"]:
        raise RouteNotFound()

    comments_res = await asyncio.to_thread(
        lambda: supabase.table("route_comments")
        .select("*")
        .eq("route_id", route_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    rows = comments_res.data
    if not rows:
        return []

    commenter_ids = [r["user_id"] for r in rows]
    briefs, blocked = await asyncio.gather(
        profile_service.get_profile_briefs(commenter_ids),
        profile_service.blocked_ids_batch(viewer_id, commenter_ids),
    )
    return [CommentResponse(**row,
                            nickname=briefs.get(row["user_id"], {}).get("nickname"),
                            avatar_url=briefs.get(row["user_id"], {}).get("avatar_url"))
            for row in rows if row["user_id"] not in blocked]


async def delete_comment(route_id: str, comment_id: str, caller_id: str) -> None:
    """Delete a comment. Caller must be the comment author or the route owner.

    Raises CommentNotFound if the comment doesn't exist under this route.
    Raises CommentAccessDenied if the caller has neither permission.
    """
    supabase = get_supabase_admin()
    comment_res = await asyncio.to_thread(
        lambda: supabase.table("route_comments")
        .select("user_id")
        .eq("id", comment_id)
        .eq("route_id", route_id)
        .limit(1)
        .execute()
    )
    if not comment_res.data:
        raise CommentNotFound()

    if comment_res.data[0]["user_id"] != caller_id:
        route_res = await asyncio.to_thread(
            lambda: supabase.table("routes")
            .select("user_id")
            .eq("id", route_id)
            .limit(1)
            .execute()
        )
        if not route_res.data or route_res.data[0]["user_id"] != caller_id:
            raise CommentAccessDenied()

    await asyncio.to_thread(
        lambda: supabase.table("route_comments")
        .delete()
        .eq("id", comment_id)
        .execute()
    )
