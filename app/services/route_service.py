"""Orchestration: combine the OpenAI route generation with Map API data.

This is the business-logic glue the API layer calls. It asks OpenAI for a
candidate route, optionally resolves the pitstop against the real Map API,
and enriches the response with actual pedestrian routing geometry.
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
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
from app.core.config import settings
from app.services import (
    anchor_service, feedback_service, map_service, notification_service,
    openai_service, profile_service,
)

logger = logging.getLogger(__name__)


class RouteNotFound(Exception):
    """Route does not exist, or is hidden from this user."""


class CommentNotFound(Exception):
    """Comment does not exist under the given route."""


class CommentAccessDenied(Exception):
    """Caller is neither the comment author nor the route owner."""


class RouteGenerationFailed(Exception):
    """Gemini never produced a usable route across all radius attempts."""


class RouteGenerationUnavailable(Exception):
    """일시적 인프라 한계로 코스를 만들 수 없음 — 현재는 T-map 쿼터 소진(429).

    RouteGenerationFailed(산포 전패, 우리가 시도했으나 밴드 후보 0)과 구분: 이건
    외부 의존(T-map 일일 콜 예산)이 바닥나 스냅 자체를 못 한 것. API 층이 502가
    아니라 503 route_generation_unavailable("잠시 후 다시")로 매핑 — nopath 폴백
    (폴리라인 없는 가짜 코스 200 서빙)을 대체하는 정직한 실패(2026-07-21 오너 승격)."""


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


class LoopTargetTooShort(Exception):
    """순환(원점 복귀) target이 물리적 최소 루프 거리 미만 — 사전 422(one-way 게이트 미러).

    도보 스냅 팽창(1.3~1.9×) + 최소 도로 세그먼트상 순환 코스의 물리적 최소가 ~2.5~3km라
    그보다 짧은 목표는 어떤 체인으로도 못 만들어 502를 낭비한다(small-ask 실측 2026-07-22:
    t=1.5 요청의 스냅 9개 전량 ≥2.7km). 생성 진입 전 차단(Gemini 0콜·쿼터 미소모).
    min_target_km: 순환 최소 목표 거리 힌트."""

    def __init__(self, requested_km: float, min_target_km: float):
        self.requested_km = requested_km
        self.min_target_km = min_target_km
        super().__init__(f"loop target too short: {requested_km} < {min_target_km}")


# 일방 실행가능성 상한 — |start−end| ≤ target×0.8 (여유 0.2는 도로 팽창분)
_ONE_WAY_MAX_DIST_FACTOR = 0.8
# 순환 물리 최소 하한(small-ask 2026-07-22) — 실측 근거 2.7이나 표본 2건이라 **보수적
# 2.0 시작**(오탐=가능한데 막음 최소화). gen_failures로 2.0~2.7 실패 관측되면 상향 여지.
_LOOP_MIN_TARGET_KM = 2.0


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
# v2.4 (2026-07-20 오너 결정 — 하한 완화): 하한 −0.1→−0.3, 밴드
# [target−0.3, target+0.5] 폭 0.8. 계측(v71 로그) 근거: 4.84 같은 아깝게 미달
# 후보가 하한 −0.1 밖으로 버려지고 다음 attempt의 초과(5.38)를 서빙하던 초과
# 편향(저장분 dev>0:dev<0 = 34:8)을 완화. 전패 처리(미달 반환 금지·초과 최선·
# 둘 다 없으면 502)는 새 하한 기준으로 불변.
_UNDER_TOLERANCE_KM = 0.3
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
# 초과 서빙 spur 상한(00:51 신사 star 회귀, 2026-07-24) — over-cap(missed) 후보가
# longest_retrace_m > 이 값이면 "긴 팔 코스"라 서빙서 제외(engine 불문). 제외로 0이면
# band_cap_zero → 재추첨/정직 502. 억지 star 서빙 근본 차단.
_OVER_SERVE_MAX_SPUR_M = 800.0
# v2.6 §2 재추첨 학습 완화 — compliance(3롤 median/aim)를 ±10%로 clamp.
# 무제한이면 산포 큰 지역(사용자 좌표 ratio 1.1~2.9)에서 est_ratio가 진동해
# aim이 3.2↔2.4로 널뛰며 미달·초과 반복(E2E 실측 역효과). ±10%로 방향만 반영.
_COMPLIANCE_CLAMP = (0.90, 1.10)

# v2.3 스냅 전 사전 게이트 (부검 2026-07-20: 502 건의 후보 7.71/6.45km — 원인은
# aim 3.9에 chain 5.57 같은 Gemini 비순응): 체인이 aim×[0.75, 1.25] 밖이면
# T-map 없이 Gemini만 재추첨(attempt당 최대 2회). 소진 시 그 attempt는 miss.
# T-map 왕복(약 0.6s/leg×N)과 무효 후보 적재를 아낀다.
_PRE_GATE_BAND = (0.75, 1.25)
_PRE_GATE_REROLLS = 2  # (v2.7 배치 풀에서 미사용 — attempt 재추첨 개념 폐기)

# v2.7 배치 풀 (§2 생성 전략, 오너 확정): attempt 루프 폐기 → 처음부터 N개
# 체인 병렬 생성 → pre-gate 통과분 전부 병렬 스냅 → 밴드 최근접 서빙. 스냅 표본을
# 4→다수로 늘려 Gemini 산포를 흡수(현행은 12콜 생성에 스냅 4개뿐이던 낭비 제거).
# 적응형 폐기(1패스라 attempt 간 피드백 없음 — est_ratio는 초기 조준에만).
_POOL_SIZE = 9              # 병렬 생성 후보 수(Gemini 9콜 고정)
_REDRAW_POOL_SIZE = 5       # 적응 재추첨 축소 풀(미노스 부검 2026-07-24) — band_cap_zero
                           # 언더슈트 지배 시 실측 ratio로 aim 상향해 1회만 재시도(+~5-8s)
# 롤 간 스태거(2026-07-22): 9콜 동시 발사가 Gemini relay 순간 RPM을 튀겨 429
# 스로틀→일부 롤 실패→후보 부족→502를 유발(E2E 성수 실측: /chat/completions 재시도
# 3회). roll j를 j×이 값만큼 늦게 발사해 피크를 평탄화(~9RPS→~4RPS). 총 추가 지연
# (N-1)×0.25≈2s로 20s 예산 무해. ⚠️ Gemini 콜 실패 재시도는 **SDK 층 단일**
# (openai_service _client.max_retries=2) — 앱은 추가 재시도 없음(이중 재시도 금지).
_POOL_STAGGER_S = 0.25
# T-map leg 상한 안전핀(§4.1) — 무료 쿼터(일 1000 leg) 방어. 통과분 스냅 leg
# 누적이 이 값 넘으면 나머지 후보 미스냅(예산 게이트 성격 백스톱). 오늘 815/1000
# 도달이 근거. gen_meta.tmap_legs로 실소모 관측.
_TMAP_LEG_CAP = 40
# v2.5 지연 통제 (오너 결정 — 콜 3배 폭증 대응):
# ① 시간 예산 — 총 경과 이 값 초과 시 신규 attempt 진입 금지, 그 시점 최선 판정
#    (진행 중 attempt는 완주 허용, 중간 절단 없음). 첫 attempt는 무조건 1회 보장.
# ② pre-gate 재추첨은 gather 병렬 발사(순차 합 대신 max 1콜 시간 — route_service).
# ③ Gemini 콜 타임아웃은 openai_service 클라이언트에 설정(8s).
_TIME_BUDGET_S = 20.0
# 일방(end 좌표) 요청의 초기 팽창비 — corridor 경로는 루프보다 우회가 적어
# 스냅 팽창이 낮다(E2E 실측: 루프 1.6 vs 일방 체인≈직선). 적응형이 이후 보정.
_ONE_WAY_INFLATION = 1.25

# 격자 est_ratio 테이블 (§1 본수술, §3 STEP 2, 2026-07-22) — 캠페인 40건 실측
# ratio 중앙값을 seed로 좌표별 초기 조준 보정. 기존 뚝섬 단일 1.8 override를 대체·
# 일반화. 도로망 팽창(수변 고팽창~격자 저팽창)이 좌표별로 달라 단일 default 1.6이
# 양극에서 틀림(목동 1.41 undershoot / 뚝섬 1.84 overshoot 실측). 각 (lat,lng,반경km,
# ratio) 반경 내 첫 매치 적용, 미등록 격자는 default(_SNAP_INFLATION 1.6).
# ⚠️ 하드코딩 시작 — 실측 좌표만 등록(발명 금지). gen_failures 축적으로 격자 늘면
# DB 테이블화. initial_ratio가 gen_meta·gen_failures에 저장돼 적용·효과 자동 관측.
_GRID_RATIOS = [
    # (lat, lng, radius_km, ratio) — 캠페인 실측 ratio(서빙+실패 통합 분포) 근거
    (37.5219, 127.0561, 2.0, 1.84),  # 뚝섬권 (기존 1.8 override 대체 — overshoot 상단)
    (37.5445, 127.0374, 2.0, 1.62),  # 성수권 (수변, 서빙 10/10 hit — 충분)
    (37.5285, 126.9328, 2.0, 1.58),  # 여의도권 (bimodal 산포 — 격자로 중심만)
    (37.5242, 126.6303, 2.0, 1.85),  # 청라권 (STEP3 실패분포로 overshoot 확인 → 상향)
    (37.5265, 126.8620, 2.0, 1.41),  # 목동권 (내륙 격자 저팽창 — undershoot 교정 확증)
    (37.4995, 127.0360, 2.0, 1.38),  # 강남권 (STEP3 502 가시화로 극심 undershoot 발견)
    (37.5200, 127.0200, 2.0, 1.45),  # 신사/논현권 (미노스 502 부검 — 성공 route 3건 실측
                                     # median 1.445, 강남역 격자서 >2km라 default 1.6 undershoot)
]


def _grid_ratio(start: Coordinate) -> float | None:
    """등록 격자 반경 내면 실측 est_ratio, 아니면 None(→ 전국 default)."""
    for lat, lng, rad, ratio in _GRID_RATIOS:
        if _dist_km(start, Coordinate(lat=lat, lng=lng)) <= rad:
            return ratio
    return None


def _initial_est_ratio(start: Coordinate, start_end_km: float | None) -> float:
    """초기 팽창비 조준 — 일방 corridor(1.25) > 등록 격자 실측 > 전국 기본(1.6).
    적응형 폐기(1패스 풀)라 이 값이 유일 조준. 격자 실측이 좌표별 팽창을 보정한다."""
    if start_end_km is not None:
        return _ONE_WAY_INFLATION
    grid = _grid_ratio(start)
    if grid is not None:
        return grid
    return openai_service._SNAP_INFLATION

# 예상 시간 = 러닝 기준 (2026-07-20 오너 확정): T-map 도보 시간(~13분/km)을
# 버리고 거리 × 기본 러닝 페이스 6'30"/km로 재계산. 개인 페이스 반영은 후속.
_RUN_PACE_MIN_PER_KM = 6.5


def _log_perf_failed(t0: float, perf: dict) -> None:
    """생성 실패(502/503) 경로의 계측 요약 — 성공 PERF와 동형(관측 공백 방지).

    v2.7 배치 풀 키(gemini_calls·tmap_legs)만 참조 — 구 attempts/pre_rejects는
    attempt 루프와 함께 폐기됐다(그 키 잔존 참조가 실패 경로에서 KeyError→502로
    삼켜지며 503 분기를 가리던 잠복 버그, 2026-07-21 수정)."""
    logger.info(
        "[PERF] route generate FAILED: total=%.1fs | gemini=%.1fs(%d call) | "
        "tmap=%.1fs(%d leg)",
        time.perf_counter() - t0, perf["gemini_s"], perf["gemini_calls"],
        perf["tmap_s"], perf["tmap_legs"],
    )


async def _record_gen_failure(
    req: RouteRequest, target_km: float, t0: float, snaps: list,
    meta: dict, initial_ratio: float, fail: str, pitstop: dict | None = None,
) -> None:
    """502 관측 영속(§3 STEP 1, 2026-07-22) — gen_failures. best-effort: 저장 실패가
    502 계약을 못 막는다. 실패 케이스 snap 분포 가시화(survivorship bias 제거)용.
    프라이버시: 유저 미저장, 시작점은 격자 수준(소수 2자리≈1.1km)만.
    pitstop: 채택 pitstop 관측(gen_meta와 대칭 — "pitstop이 실패에 관여했나" 진단용)."""
    try:
        record = {"meta": {
            **meta, "snaps": snaps,
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "initial_ratio": round(initial_ratio, 3),
            "one_way": req.end is not None, "target_km": target_km,
            "grid_lat": round(req.start.lat, 2), "grid_lng": round(req.start.lng, 2),
            "fail": fail, "pitstop": pitstop,
        }}
        supabase = get_supabase_admin()
        await asyncio.to_thread(
            lambda: supabase.table("gen_failures").insert(record).execute())
    except Exception:  # noqa: BLE001 — 관측 저장 실패가 502를 못 막음
        logger.warning("gen_failures 관측 저장 실패 — 무시", exc_info=True)


def _quota_dominant(snap_errs: dict, n_success: int) -> bool:
    """스냅 실패의 지배 원인이 T-map 429(쿼터)인가 — 503 정직화 분기 판정.

    **보수적**(오너 지시 "애매하면 기존 동작"): 쿼터 실패가 전체 스냅 시도의
    **엄격 과반**일 때만 True. 즉 quota > success + (legnotroutable + other).
    실 스냅이 하나라도 성공했거나 지오 문제(LegNotRoutable)가 섞여 과반 미달이면
    False → 기존 nopath 폴백/502 유지. 2026-07-21 E2E 전패(429 100%)는 True로
    잡히고, 뚝섬-1(성공 2 + 쿼터 1)은 False(성공했으니 쿼터 탓 아님)로 걸러진다."""
    quota = snap_errs.get("quota", 0)
    others = n_success + snap_errs.get("legnotroutable", 0) + snap_errs.get("other", 0)
    return quota > 0 and quota > others


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


# ── 품질 점수 (진단 E#2·#5, 2026-07-22) — 밴드 내 복수 후보 tiebreak + 관측 ──────
# 문제: 선택이 거리-단독이라 아파트 지그재그(5.0km)가 깔끔한 공원 루프(4.6km)를
# 이김. park_coverage(공원/수변 근접 웨이포인트 비율)·zigzag_score(급반전 수)를
# tiebreak로 추가 — 거리는 최종 순위로 강등.
def _zigzag_score(route: RouteResponse) -> int:
    """웨이포인트 체인의 급반전(백트랙) 수 — 지그재그/의미없는 우회 프록시(낮을수록
    매끈). 연속 3점의 턴이 >120°(방향 반전)면 1. 루프 자연 회전(≤120°)은 미집계."""
    pts = [wp.coordinate for wp in route.waypoints]
    if len(pts) < 3:
        return 0
    kx = math.cos(math.radians(pts[0].lat))  # 경도 스케일 보정(각도 정확도)
    cnt = 0
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        v1 = ((b.lng - a.lng) * kx, b.lat - a.lat)
        v2 = ((c.lng - b.lng) * kx, c.lat - b.lat)
        m1, m2 = math.hypot(*v1), math.hypot(*v2)
        if m1 == 0 or m2 == 0:
            continue
        if (v1[0] * v2[0] + v1[1] * v2[1]) / (m1 * m2) < -0.5:  # 턴 > 120°
            cnt += 1
    return cnt


def _park_coverage(route: RouteResponse, park_coords: list[Coordinate],
                   radius_m: float = 300.0) -> float:
    """중간 웨이포인트 중 공원/수변 300m 내 비율(0~1) — 러닝 적합도 프록시.
    park_coords 없으면(검색 실패) 0.0 — tiebreak는 zigzag로 자연 강등."""
    mids = route.waypoints[1:-1] or route.waypoints
    if not mids or not park_coords:
        return 0.0
    near = sum(1 for wp in mids
               if any(_dist_km(wp.coordinate, pc) * 1000 <= radius_m for pc in park_coords))
    return round(near / len(mids), 2)


# ── 폴리라인 수준 품질 (오너 Phase 1 C, 2026-07-23) — 스냅 기하의 되돌기·갭 검출 ──
# zigzag_score는 waypoint 6점만 봐 스냅 폴리라인의 되돌기를 못 잡는다(실사례 de78d97c:
# zigzag 0인데 스냅 경로가 idx27-28↔46-47 되밟기). 스냅 폴리라인(~200점)에서 직접 측정.
_RETRACE_NEAR_M = 20.0

def _polyline_max_gap_m(polyline: list) -> float:
    """인접 폴리라인 점 간 최대 갭(m) — T-map 성긴 정점/직선 점프 관측."""
    if not polyline or len(polyline) < 2:
        return 0.0
    return round(max(_dist_km(polyline[i - 1], polyline[i])
                     for i in range(1, len(polyline))) * 1000, 1)


def _polyline_retrace(polyline: list, near_m: float = _RETRACE_NEAR_M) -> int:
    """되돌기 수 — 나중 세그먼트가 앞 세그먼트를 (근사) 역방향으로 되밟는 구간 수.
    seg i(p[i]→p[i+1])와 seg j(j>i)에서 p[j]≈p[i+1] & p[j+1]≈p[i]이면 되돌기 1.
    O(n²)이나 n~200·후보 9라 무해. 낮을수록 깔끔한 루프."""
    n = len(polyline) if polyline else 0
    if n < 4:
        return 0
    near_km = near_m / 1000.0
    cnt = 0
    for i in range(n - 1):
        ai, bi = polyline[i], polyline[i + 1]
        for j in range(i + 2, n - 1):
            if (_dist_km(polyline[j], bi) <= near_km
                    and _dist_km(polyline[j + 1], ai) <= near_km):
                cnt += 1
                break  # 세그먼트당 1회만(중복 카운트 방지)
    return cnt


def _spur_metrics(polyline: list, near_m: float = _RETRACE_NEAR_M,
                  micro_m: float = 50.0, long_m: float = 100.0) -> dict:
    """체감 왕복 스퍼 지표(§8.16 교정, 앵커 에픽) — retrace 카운트가 마이크로 반전까지
    세 러너 체감과 어긋난 것을 교정. 이중주행 회랑(seg가 역방향으로 다시 밟힘)을 연속
    구간으로 묶어 길이 측정:
    - longest_retrace_m: 최장 이중주행 회랑 길이(러너가 가장 빡치는 "N km 왕복")
    - long_spur_count: 100m 초과 회랑 수 · micro_reversals: 50m 미만 잔반전 수
    앵커·v87 공통 기록 → 롤아웃 A/B의 자."""
    n = (len(polyline) - 1) if polyline else 0
    if n < 2:
        return {"longest_retrace_m": 0, "long_spur_count": 0, "micro_reversals": 0}
    near_km = near_m / 1000.0
    seg = [_dist_km(polyline[i], polyline[i + 1]) * 1000 for i in range(n)]
    marked = [False] * n
    for i in range(n):
        for j in range(n):
            if (j != i and _dist_km(polyline[j], polyline[i + 1]) <= near_km
                    and _dist_km(polyline[j + 1], polyline[i]) <= near_km):
                marked[i] = True
                break
    runs, k = [], 0
    while k < n:
        if marked[k]:
            length = 0.0
            while k < n and marked[k]:
                length += seg[k]
                k += 1
            runs.append(length)
        else:
            k += 1
    return {"longest_retrace_m": round(max(runs, default=0.0)),
            "long_spur_count": sum(1 for L in runs if L > long_m),
            "micro_reversals": sum(1 for L in runs if L < micro_m)}


def _serveable_over_cap(scored: list, target_km: float, engine_of: dict) -> list:
    """초과(missed) 서빙 자격 후보 (00:51 신사 star 회귀 수정, 2026-07-24):
    target < km ≤ target+cap AND (1) engine≠anchor(앵커는 밴드 내 park 경쟁만 — 원설계
    복원) AND (2) longest_retrace_m ≤ 800(engine 불문 긴 팔 차단). 하방 거리 보장은 v87
    롤 몫이라 앵커·star를 초과 서빙서 빼도 안전(빈 결과면 상위가 재추첨/502)."""
    return [(k, r) for k, r in scored
            if target_km < k <= target_km + _OVER_SERVE_CAP_KM + 1e-9
            and engine_of.get(id(r)) != "anchor"
            and _spur_metrics(r.polyline)["longest_retrace_m"] <= _OVER_SERVE_MAX_SPUR_M]


def _best_in_band(in_band: list, target_km: float, quals: dict):
    """밴드 내 후보 선택 — 1개면 그대로(현행), 복수면 tiebreak
    [park_coverage desc · zigzag_score asc · retrace asc · 거리 근접 asc].
    quals: id(route)→(park, zig, retrace). retrace는 스냅 폴리라인 되돌기(Phase 1 C)."""
    if len(in_band) == 1:
        return in_band[0]
    return min(in_band, key=lambda t: (
        -quals[id(t[1])][0], quals[id(t[1])][1], quals[id(t[1])][2],
        abs(t[0] - target_km)))


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


def _pool_radii(target_km: float, start_end_km: float | None, n: int) -> list[float]:
    """v2.7 배치 풀 N개의 반경 — 스케줄(좁은~넓은)을 순환 분산해 다양성 확보.
    예: 스케줄 [1.2,2.2,3.7,8.0], n=9 → [1.2,2.2,3.7,8.0,1.2,2.2,3.7,8.0,1.2]."""
    sched = _radius_schedule(target_km, start_end_km)
    return [sched[i % len(sched)] for i in range(n)]


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


async def _adaptive_redraw(req, target_km, measured_ratio, avoid_tags, prefs, lang,
                           radius_center, start_end_km):
    """band_cap_zero 언더슈트 지배 시 1회 적응 재추첨 — 실측 ratio로 chain aim 상향,
    축소 풀(5롤) 재생성·스냅. **in-band 우선, 없으면 over-cap missed(spur 게이트)도 서빙**
    (01:16 미노스: 재추첨 5.7이 missed로 나갔어야 할 것을 버려 502하던 것 수정).
    ⚠️ 재귀 없음(1회 한정) — 상한 5롤·leg 상한 재사용."""
    # measured_ratio 블렌드(01:16 부검): 소수 불운 롤에서 나온 실측이 노이즈(1.32→aim
    # 과대→오버슈트). 등록 격자면 grid ratio에 2:1 가중(신뢰), 미등록이면 실측 단독.
    grid = _grid_ratio(req.start)
    ratio = statistics.median([measured_ratio, grid, grid]) if grid is not None else measured_ratio
    aim = (target_km + openai_service._BAND_AIM_KM) / ratio
    if start_end_km is not None:
        aim = max(aim, start_end_km * 1.05)
    aim = round(aim, 1)
    radii = _pool_radii(target_km, start_end_km, _REDRAW_POOL_SIZE)

    async def _roll(j):
        if j:
            await asyncio.sleep(j * _POOL_STAGGER_S)
        return await openai_service.generate_route(
            target_distance_km=target_km, start=req.start, end=req.end,
            pitstop_keyword=req.pitstop_keyword, notes=req.notes,
            avoid_tags=avoid_tags, prefs=prefs, radius_km=radii[j], lang=lang,
            chain_target_km=aim, radius_center=radius_center)

    results = await asyncio.gather(*[_roll(j) for j in range(_REDRAW_POOL_SIZE)],
                                   return_exceptions=True)
    cands = [r for r in results if isinstance(r, RouteResponse)]
    meta = {"measured_ratio": round(measured_ratio, 3), "redraw_aim": aim,
            "redraw_gen": len(cands)}
    if not cands:
        return None, meta
    to_snap, leg = [], 0
    for r in sorted(cands, key=lambda r: abs(_waypoint_chain_km(r) - aim)):
        legs = len(r.waypoints) - 1
        if legs < 1 or leg + legs > _TMAP_LEG_CAP:
            continue
        to_snap.append(r)
        leg += legs

    async def _snap(r):
        via = [wp.coordinate for wp in r.waypoints[1:-1]] or None
        return await map_service.get_pedestrian_route(
            origin=r.waypoints[0].coordinate, destination=r.waypoints[-1].coordinate,
            waypoints=via)

    scored = []
    for r, out in zip(to_snap, await asyncio.gather(*[_snap(r) for r in to_snap],
                                                    return_exceptions=True)):
        if isinstance(out, BaseException):
            continue
        raw = out.distance_m / 1000.0
        r.polyline = out.path
        r.total_distance_km = round(raw, 1)
        scored.append((raw, r))
    meta["redraw_snaps"] = [round(k, 1) for k, _ in scored]
    meta["blended_ratio"] = round(ratio, 3)
    in_band = [(k, r) for k, r in scored if _within_band(k, target_km)]
    if in_band:
        _k, best = min(in_band, key=lambda t: abs(t[0] - target_km))
        meta.update({"redraw_hit": True, "redraw_verdict": "hit"})
        return best, meta
    # in-band 없으면 over-cap missed(v87·spur 게이트 ≤800) — 메인 흐름과 동일 서빙.
    # 재추첨은 전부 v87(generate_route)이라 engine 마킹 v87.
    over = _serveable_over_cap(scored, target_km, {id(r): "v87" for _, r in scored})
    if over:
        _k, best = min(over, key=lambda t: t[0] - target_km)
        best.target_missed = True
        meta.update({"redraw_hit": True, "redraw_verdict": "missed"})
        return best, meta
    meta["redraw_hit"] = False
    return None, meta


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

    # v2.7 배치 풀 (§2): attempt 루프 폐기 → N개 병렬 생성 → pre-gate 통과분
    # 전부 병렬 스냅 → 밴드 최근접 서빙. 스냅 표본을 4→다수로 늘려 Gemini 산포
    # 흡수. 게이트(밴드·캡·salvage·traversability·시간 예산)는 전부 불변, 선택 층만.
    pitstop_places: list | None = None
    best: RouteResponse | None = None
    best_meta: dict | None = None

    _t0 = time.perf_counter()
    _perf = {"gemini_s": 0.0, "gemini_calls": 0, "tmap_s": 0.0, "tmap_legs": 0}

    # end-aware(v2.3) + 실행가능성 게이트(v2.3 마감): 직선거리 > target×0.8이면 422
    start_end_km = _dist_km(req.start, req.end) if req.end else None
    # 순환 최소거리 게이트(small-ask 2026-07-22) — 루프(end 없음) target이 물리 최소 미만이면
    # 생성 진입 전 422(Gemini 0콜·쿼터 미소모, one-way 게이트 미러).
    if start_end_km is None and target_km < _LOOP_MIN_TARGET_KM - 1e-9:
        raise LoopTargetTooShort(round(target_km, 1), _LOOP_MIN_TARGET_KM)
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

    # 초기 조준(적응형 폐기 — 1패스 풀이라 attempt 간 피드백 없음)
    est_ratio = _initial_est_ratio(req.start, start_end_km)
    initial_ratio = est_ratio
    chain_aim_km = (target_km + openai_service._BAND_AIM_KM) / est_ratio
    if start_end_km is not None:
        chain_aim_km = max(chain_aim_km, start_end_km * 1.05)  # 체인 물리 하한
    chain_aim_km = round(chain_aim_km, 1)

    # 1) N개 병렬 생성 — 반경 스케줄 순환 분산(좁은~넓은 다양성). 롤 간 스태거로
    #    Gemini 순간 RPM 피크를 평탄화(429 스로틀 완화, 2026-07-22). 재시도는 SDK 층.
    # 혼합 풀(§9 부활): ANCHOR_POOL_N만큼 v87 롤을 앵커 롤로 대체(Gemini 0콜). v87 롤이
    # 거리 보장 하방, 앵커 롤이 park·spur로 tiebreak 경쟁. v87 최소 3 보장(하방 안전).
    anchor_n = max(0, min(settings.anchor_pool_n, _POOL_SIZE - 3))
    v87_n = _POOL_SIZE - anchor_n
    radii = _pool_radii(target_km, start_end_km, v87_n)

    async def _staggered_roll(j: int) -> RouteResponse:
        if j:
            await asyncio.sleep(j * _POOL_STAGGER_S)
        return await openai_service.generate_route(
            target_distance_km=target_km, start=req.start, end=req.end,
            pitstop_keyword=req.pitstop_keyword, notes=req.notes,
            avoid_tags=avoid_tags, prefs=prefs, radius_km=radii[j], lang=lang,
            chain_target_km=chain_aim_km, radius_center=radius_center,
        )

    rolls = [_staggered_roll(j) for j in range(v87_n)]
    _g = time.perf_counter()
    results = await asyncio.gather(*rolls, return_exceptions=True)
    _perf["gemini_s"] += time.perf_counter() - _g  # 병렬 → wall-clock
    _perf["gemini_calls"] = len(results)

    gen_cands = [(r, _waypoint_chain_km(r), radii[j])
                 for j, r in enumerate(results) if isinstance(r, RouteResponse)]
    engine_of: dict = {id(r): "v87" for r, _, _ in gen_cands}
    # 앵커 롤(규칙 기반, Gemini 0콜) — best-effort. 실패·앵커 부족 시 v87 단독(하방 보호).
    if anchor_n > 0:
        try:
            _anchors = await anchor_service.collect_anchors(
                req.start, target_km, probe_dead_end=False)
            for _ar in anchor_service.build_anchor_candidates(
                    req.start, _anchors, target_km, anchor_n,
                    needs_pitstop=bool(req.pitstop_keyword)):
                gen_cands.append((_ar, _waypoint_chain_km(_ar), 0.0))
                engine_of[id(_ar)] = "anchor"
        except Exception:  # noqa: BLE001 — 앵커 실패가 생성을 막지 않는다(v87로 서빙)
            logger.warning("앵커 롤 생성 실패 — v87 단독 진행", exc_info=True)
    if not gen_cands:
        excs = [r for r in results if isinstance(r, BaseException)]
        _log_perf_failed(_t0, _perf)
        if any(isinstance(e, OpenAIAPIError) for e in excs):
            raise next(e for e in excs if isinstance(e, OpenAIAPIError))
        await _record_gen_failure(req, target_km, _t0, [],
                                  {"pool_size": 0, "snapped_count": 0, "tmap_legs": 0,
                                   "snap_errors": {}}, initial_ratio, "no_gen_cands")
        raise RouteGenerationFailed()  # 전 롤 파싱/검증 실패

    # 2) pre-gate: 체인 aim×[0.75,1.25] 통과분. 통과 0이면 전체(salvage). aim
    #    최근접 순 정렬 — 좋은 후보 먼저 스냅(leg 상한 컷 시 유리).
    lo, hi = chain_aim_km * _PRE_GATE_BAND[0], chain_aim_km * _PRE_GATE_BAND[1]
    passed = [c for c in gen_cands if lo <= c[1] <= hi] or gen_cands
    passed.sort(key=lambda c: abs(c[1] - chain_aim_km))

    # 3) T-map leg 상한(40) 내에서 스냅 대상 선정 — 무료 쿼터 백스톱(§4.1)
    to_snap: list[tuple[RouteResponse, float, float]] = []  # (route, chain, radius)
    leg_budget = 0
    for r, ck, rad in passed:
        legs = len(r.waypoints) - 1
        if legs < 1:
            continue
        if leg_budget + legs > _TMAP_LEG_CAP:
            break
        to_snap.append((r, ck, rad))
        leg_budget += legs
    _perf["tmap_legs"] = leg_budget

    # pitstop 스냅 (키워드 있으면) — 첫 성공 결과를 스냅 대상 전부에 재사용.
    # pitstop_obs: 관측 대칭(2026-07-22) — 채택 name·category_code + 필터 축소 수치를
    # gen_meta(성공)·gen_failures(실패) 양쪽에 기록해 "pitstop이 실패에 관여했나"를
    # 데이터로 즉답. 키워드 없으면 None(키 미기록).
    pitstop_obs: dict | None = None
    if req.pitstop_keyword and to_snap:
        try:
            # 검색 반경·정렬을 target·의도 연동으로(2026-07-22 (b)): 위치 밴드 상한이
            # target×0.5라 반경이 그만큼 커야 자연 지점 후보를 덮는다. ⚠️ **핵심**: 랜드마크형은
            # sort='accuracy' — distance 정렬은 근접 상호가 실제 공원을 묻어 밴드 내 공원 0이지만
            # accuracy는 청라호수공원(986m) 등 실제 공원을 상위로(청라 실측). limit 15.
            _intent, _ = map_service._keyword_intent(req.pitstop_keyword)
            _radius_m = max(2000, round(target_km * map_service._POS_BAND_HI_FACTOR * 1000))
            _sort = "accuracy" if _intent == "landmark" else "distance"
            pitstop_places = await map_service.search_places(
                req.pitstop_keyword, near=req.start, radius_m=_radius_m, limit=15, sort=_sort)
            # 의도 존중(백로그 (b)): 상업 카테고리 제외·적합도·**위치밴드** 랭킹 통과
            # 후보 채택. 통과 0이면 무필터 최근접 폴백(가용성 우선 — 502 안 냄). 위치밴드
            # 우대로 시작 코앞(84m) pitstop이 루프 핀치→overshoot 유발하던 것 교정.
            ranked = map_service.rank_places_for_keyword(
                req.pitstop_keyword, pitstop_places, start=req.start, target_km=target_km)
            pick = None
            if ranked:
                pick = ranked[0]
            elif pitstop_places:
                pick = pitstop_places[0]
                logger.info("pitstop 적합후보 0 — 무필터 최근접 폴백: %r (kw=%r)",
                            pick.name, req.pitstop_keyword)
            in_band = bool(pick and map_service._in_position_band(req.start, pick, target_km))
            # 채택 pitstop의 Kakao accuracy 순위(대표성 tiebreak 효과 자동 검증, 오너 E).
            acc_rank = pitstop_places.index(pick) if pick in pitstop_places else None
            pitstop_obs = {
                "kw": req.pitstop_keyword,
                "name": pick.name if pick else None,
                "cat": pick.category_code if pick else None,
                "raw_n": len(pitstop_places), "ranked_n": len(ranked),
                "fallback": bool(pick and not ranked),  # 무필터 최근접 폴백 여부
                "in_band": in_band,  # 위치 밴드(루프 자연 지점) 내 채택 여부
                "acc_rank": acc_rank,  # Kakao accuracy 순위(대표성, 0=최상위)
            }
            if pick is not None:
                for r, _ck, _rad in to_snap:
                    for wp in r.waypoints:
                        if wp.is_pitstop:
                            wp.name, wp.coordinate, wp.description = (
                                pick.name, pick.coordinate, pick.address)
                            break
        except Exception:  # noqa: BLE001 — best-effort
            logger.warning("Pitstop lookup failed for %r; keeping AI suggestion.",
                           req.pitstop_keyword, exc_info=True)
            pitstop_obs = {"kw": req.pitstop_keyword, "error": True}

    # 4) 통과분 전부 병렬 스냅 (T-map). LegNotRoutable(강 위)→폐기, 장애→스킵.
    async def _snap(r: RouteResponse):
        via = [wp.coordinate for wp in r.waypoints[1:-1]] or None
        return await map_service.get_pedestrian_route(
            origin=r.waypoints[0].coordinate, destination=r.waypoints[-1].coordinate,
            waypoints=via)

    _m = time.perf_counter()
    snap_out = await asyncio.gather(*[_snap(r) for r, _, _ in to_snap], return_exceptions=True)
    _perf["tmap_s"] += time.perf_counter() - _m

    scored: list[tuple[float, RouteResponse]] = []  # (raw_km, route) — 스냅 성공
    nopath_fallback: RouteResponse | None = None    # T-map 장애 시 AI추정 폴백
    snaps: list[float | None] = []
    # 스냅 실패 분류(오늘 진단을 막았던 무기록 삼킴 수정) — 지배 원인 판정·계측용.
    snap_errs = {"quota": 0, "legnotroutable": 0, "other": 0}
    for (r, ck, rad), out in zip(to_snap, snap_out):
        _is_anchor = engine_of.get(id(r)) == "anchor"
        r.search_radius_km = 0.0 if _is_anchor else rad
        r.radius_expanded = False if _is_anchor else (rad != radii[0])
        if isinstance(out, BaseException):
            snaps.append(None)
            # ⚠️ 앵커 롤 스냅 실패는 snap_errs 불오염 — v87 적응 재추첨·503 지배 판정을
            # 보호(앵커는 보조 기여자, 실패 시 그냥 드롭. 하방 거리 보장은 v87 롤 몫).
            if not _is_anchor:
                if isinstance(out, map_service.TmapQuotaExceeded):
                    snap_errs["quota"] += 1
                elif isinstance(out, map_service.LegNotRoutable):
                    snap_errs["legnotroutable"] += 1
                else:
                    snap_errs["other"] += 1
                    logger.warning("스냅 실패(nopath 폴백 후보): %s: %s",
                                   type(out).__name__, out)
                    if nopath_fallback is None:
                        nopath_fallback = r
            continue
        raw_km = out.distance_m / 1000.0
        r.polyline = out.path
        r.total_distance_km = round(raw_km, 1)
        scored.append((raw_km, r))
        snaps.append(round(raw_km, 1))
    if snap_errs["quota"]:
        logger.warning("T-map 429 쿼터 소진 %d/%d leg-batch — 정직 503 분기 검토",
                       snap_errs["quota"], len(to_snap))

    # 품질 점수(E#2·#5): 시작 인근 공원 1콜(best-effort) → 후보별 park_coverage·
    # zigzag_score 계산. 실패 시 park_coords=[] → park 0, zigzag만으로 tiebreak.
    park_coords: list[Coordinate] = []
    try:
        _pp = await map_service.search_places(
            "공원", near=req.start, sort="accuracy",
            radius_m=max(2000, round(target_km * 500)), limit=15)
        park_coords = [p.coordinate for p in _pp]
    except Exception:  # noqa: BLE001 — 품질 점수는 부가, 생성 무영향
        logger.warning("park_coverage용 공원 검색 실패 — zigzag만으로 tiebreak", exc_info=True)
    # 품질: waypoint 레벨(park·zigzag) + 스냅 폴리라인 레벨(retrace·max_gap, Phase 1 C).
    # quals에는 tiebreak용 (park, zig, retrace)만; max_gap은 관측 전용(cand_quality).
    quals: dict = {}
    cand_quality = []
    for k, r in scored:
        park, zig = _park_coverage(r, park_coords), _zigzag_score(r)
        retrace, max_gap = _polyline_retrace(r.polyline), _polyline_max_gap_m(r.polyline)
        quals[id(r)] = (park, zig, retrace)
        cand_quality.append({"km": round(k, 1), "park": park, "zig": zig,
                             "retrace": retrace, "max_gap_m": max_gap,
                             "engine": engine_of.get(id(r), "v87")})  # 롤아웃 A/B 관측

    # 5) 선택: 밴드 최근접(복수면 품질 tiebreak) → 캡 내 초과 최선(missed) →
    #    [쿼터 지배면 503] → AI추정 폴백 → 502
    _meta = {"pool_size": len(gen_cands), "snapped_count": len(scored),
             "tmap_legs": leg_budget, "snap_errors": snap_errs,
             "anchor_n": anchor_n, "cand_quality": cand_quality}

    def _eng(route):  # 채택 engine (없으면 v87 — nopath 폴백 등)
        return engine_of.get(id(route), "v87")
    in_band = [(k, r) for k, r in scored if _within_band(k, target_km)]
    if in_band:
        _k, best = _best_in_band(in_band, target_km, quals)  # E#2: park>zigzag>거리
        best_meta = {**_meta, "verdict": "hit",
                     "ratio": round(_k / _waypoint_chain_km(best), 3),
                     "park_coverage": quals[id(best)][0], "zigzag_score": quals[id(best)][1],
                     "retrace": quals[id(best)][2], "max_gap_m": _polyline_max_gap_m(best.polyline)}
    else:
        over = _serveable_over_cap(scored, target_km, engine_of)
        if over:
            _k, best = min(over, key=lambda t: t[0] - target_km)
            best.target_missed = True
            best_meta = {**_meta, "verdict": "missed",
                         "ratio": round(_k / _waypoint_chain_km(best), 3),
                         "park_coverage": quals[id(best)][0], "zigzag_score": quals[id(best)][1],
                         "retrace": quals[id(best)][2], "max_gap_m": _polyline_max_gap_m(best.polyline)}
        elif _quota_dominant(snap_errs, len(scored)):
            # T-map 429가 스냅 시도의 과반 — 폴백은 폴리라인 없는 가짜 코스다.
            # nopath로 200 서빙하는 대신 정직하게 503(잠시 후 재시도). 보수적:
            # 지배(과반) 아닐 때만 기존 폴백 유지(2026-07-21 오너 승격).
            _log_perf_failed(_t0, _perf)
            logger.warning("스냅 실패 지배 원인=쿼터(429) — route_generation_unavailable 503 "
                           "(quota=%d success=%d other=%d)",
                           snap_errs["quota"], len(scored),
                           snap_errs["legnotroutable"] + snap_errs["other"])
            raise RouteGenerationUnavailable()
        elif nopath_fallback is not None:
            best = nopath_fallback  # AI추정(polyline 없음) — 진짜 no-path(지오 장애)
            best.target_missed = not _within_band(best.total_distance_km, target_km)
            best_meta = {**_meta, "verdict": "nopath", "ratio": 0.0,
                         "park_coverage": _park_coverage(best, park_coords),
                         "zigzag_score": _zigzag_score(best),
                         "retrace": _polyline_retrace(best.polyline),
                         "max_gap_m": _polyline_max_gap_m(best.polyline)}
        else:
            # 적응 재추첨(미노스 부검 2026-07-24) — band_cap_zero가 **전 후보 언더슈트
            # 지배 + snap_errors 0**이면 미등록 저팽창 격자의 조준 미스일 확률 높음.
            # 실측 ratio(snap/chain 중앙값)로 aim 상향해 1회 재추첨. 발동 좁게(초과
            # 후보 있으면 이미 missed 서빙, 쿼터/장애면 딴 분기). +~5-8s(어차피 502였음).
            # 재추첨 판정은 **v87 후보 기준**(앵커는 aim 무관·초과 star가 재추첨을 막지
            # 않게 — 00:51 회귀 교훈). v87이 전부 언더슈트면 aim 상향 재추첨 정당.
            rd_meta = None
            _v87 = [(k, r) for k, r in scored if engine_of.get(id(r)) == "v87"]
            all_under = bool(_v87) and all(k < target_km for k, _ in _v87)
            if all_under and not any(snap_errs.values()):
                chains = [k / _waypoint_chain_km(r) for k, r in _v87
                          if _waypoint_chain_km(r) > 0]
                if chains:
                    best, rd_meta = await _adaptive_redraw(
                        req, target_km, statistics.median(chains), avoid_tags, prefs,
                        lang, radius_center, start_end_km)
            if rd_meta and rd_meta.get("redraw_hit"):
                # 재추첨 서빙 — in-band면 hit_redraw, over-cap이면 missed_redraw(target_missed).
                _rv = rd_meta.get("redraw_verdict", "hit")
                best_meta = {**_meta,
                             "verdict": "hit_redraw" if _rv == "hit" else "missed_redraw",
                             "ratio": round(best.total_distance_km / _waypoint_chain_km(best), 3),
                             "park_coverage": _park_coverage(best, park_coords),
                             "zigzag_score": _zigzag_score(best),
                             "retrace": _polyline_retrace(best.polyline),
                             "max_gap_m": _polyline_max_gap_m(best.polyline),
                             "redraw": rd_meta}
                logger.info("적응 재추첨 %s — measured=%.3f blended=%.3f aim=%.1f km=%.1f",
                            _rv, rd_meta["measured_ratio"], rd_meta.get("blended_ratio", 0),
                            rd_meta["redraw_aim"], best.total_distance_km)
            else:
                _log_perf_failed(_t0, _perf)
                await _record_gen_failure(req, target_km, _t0, snaps,
                                          {**_meta, "redraw": rd_meta}, initial_ratio,
                                          "band_cap_zero", pitstop=pitstop_obs)
                raise RouteGenerationFailed()  # 재추첨도 실패 — 정직한 502

    # 아파트 관통 관측(백로그 #6, 2026-07-23) — 선택 route의 중간 waypoint 역지오코딩해
    # 아파트 신호 카운트. **관측 전용(필터 아님)**, best-effort. 실발생률 축적으로
    # 접근성 필터 착수 여부 재판정(트리거: apt_signal 비율·테스터 리포트).
    try:
        _apt_coords = [wp.coordinate for wp in best.waypoints[1:-1]] or \
            [wp.coordinate for wp in best.waypoints]
        _apt_hits, _apt_checked = await map_service.count_apartment_signal(_apt_coords)
        best_meta["apt_signal"] = _apt_hits
        best_meta["apt_checked"] = _apt_checked
    except Exception:  # noqa: BLE001 — 관측이라 실패해도 생성 무영향
        logger.warning("apt_signal 관측 실패 — 스킵", exc_info=True)

    # 체감 왕복 스퍼 지표(§8.16, 앵커 에픽 롤아웃 A/B의 자) — v87·앵커 공통 기록.
    best_meta.update(_spur_metrics(best.polyline))
    best_meta["engine"] = _eng(best)  # 채택 engine(v87/anchor) — 혼합 풀 A/B 관측

    logger.info(
        "route_gen POOL n=%d snapped=%d tmap_legs=%d aim=%.1f target=%.1f verdict=%s",
        _POOL_SIZE, len(scored), leg_budget, chain_aim_km, target_km,
        best_meta["verdict"],
    )

    # 예상 시간 = 러닝 기준 일괄 환산 (오너 확정 2026-07-20) — T-map 도보 시간·
    # AI 추정 무관하게 최종 거리 × 6'30"/km. NO_PATH 폴백 경로 포함 단일 소스.
    best.estimated_duration_min = float(
        round(best.total_distance_km * _RUN_PACE_MIN_PER_KM)
    )
    # 일방통행 플래그(리포트 D) — 생성 응답에도 노출(_save_route의 DB 저장과 동일 기준)
    best.is_one_way = req.end is not None
    # 중립 제목 최종 확정(§3 축 B, 2026-07-22) — 표시 거리(스냅 후 최종)와 일치하는
    # 중립 템플릿으로 override. generate_route가 넣은 추정거리 기반 제목을 최종값으로 갱신.
    best.summary = openai_service._neutral_summary(
        best.total_distance_km, best.is_one_way, lang)

    # 계측 요약 — 병목 분포 관측 (v2.7 배치 풀: pool·snapped·tmap_legs)
    _total = time.perf_counter() - _t0
    logger.info(
        "[PERF] route generate: total=%.1fs | gemini=%.1fs(%d call) | "
        "tmap=%.1fs(%d leg) | pool=%d snapped=%d | expanded=%s",
        _total, _perf["gemini_s"], _perf["gemini_calls"],
        _perf["tmap_s"], _perf["tmap_legs"], _POOL_SIZE,
        best_meta["snapped_count"], best.radius_expanded,
    )

    # 계측 영속화(리포트 B) — 링버퍼 유실 무관 조회. verdict: hit·missed·nopath.
    # v2.7: pool_size·snapped_count·tmap_legs(쿼터 관측) 추가, attempt/pre_reject 폐기.
    gen_meta = {**(best_meta or {"verdict": "unknown"}),
                "one_way": req.end is not None,
                "snaps": snaps,  # 스냅된 후보 전부(v2.4 → v2.7 풀 표본)
                "elapsed_s": round(_total, 1),  # 총 소요(v2.5)
                "initial_ratio": round(initial_ratio, 3),  # 초기 조준값(v2.6 §4)
                "pitstop": pitstop_obs}  # 채택 pitstop 관측(2026-07-22, gen_failures와 대칭)

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
