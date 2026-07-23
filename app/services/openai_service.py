"""OpenAI integration using Function Calling to produce structured routes.

The model is asked to design a running route given a target distance, a
start (and optional end) location, and a pitstop keyword. We force the model
to call the `build_running_route` tool, whose JSON Schema mirrors our
`RouteResponse` Pydantic model — so the model's output is structured and
directly validatable.
"""

from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from app.core.config import settings
from app.models.schemas import AiCourseSettings, CoachCue, Coordinate, RouteResponse

import os

from app.core.json_util import loads_lenient

logger = logging.getLogger(__name__)


def _loads_tool_args(raw: str) -> dict:
    """모델 tool_call arguments 파싱 (미이스케이프 제어문자 방어 — 공용 단일 소스).

    Gemini가 간헐적으로 U+0000~U+001F를 이스케이프 없이 문자열에 담는 케이스 방어.
    파싱 로직은 app.core.json_util.loads_lenient에 일원화(T-map 응답 파싱과 동일)."""
    return loads_lenient(raw, context="gemini tool_call")

# Resolve the base URL: prefer the value loaded from .env via Settings, but if
# it is empty or still the OpenAI default, fall back to the OPENAI_BASE_URL
# environment variable. This lets us route requests to the Gemini
# OpenAI-compatible relay instead of the official OpenAI endpoint.
_DEFAULT_OPENAI_URL = "https://api.openai.com/v1"
_base_url = settings.openai_base_url
if not _base_url or _base_url == _DEFAULT_OPENAI_URL:
    _base_url = os.getenv("OPENAI_BASE_URL", _base_url or _DEFAULT_OPENAI_URL)

_client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url=_base_url,  # routes to Gemini's OpenAI-compatible endpoint
    # v2.5 콜 타임아웃 8s — 미설정 시 SDK 기본 600s라 서버가 늘어진 콜을 무한
    # 대기했다. 평균 콜 ~3.2s이므로 8s는 정상 콜 여유 + 스파이크 방어. 타임아웃
    # 콜은 APITimeoutError → route_service의 gather return_exceptions로 그 롤만 실패.
    timeout=8.0,
    # Gemini 429/5xx 재시도는 **이 SDK 층에서만** 수행(2026-07-22 명시적 일원화).
    # route_service는 롤 스태거로 429 발생 자체를 줄이되 앱 레벨 재시도는 두지
    # 않는다(이중 재시도 금지). 기본값 2 유지 — 지수 백오프로 순간 스로틀 흡수.
    max_retries=2,
)

# AI 생성 텍스트의 출력 언어 — 유저 settings.lang(ko/en)을 따른다. lang name은
# 프롬프트·스키마 description에 주입돼 "반드시 {한국어/English}로" 지시가 된다.
_LANG_NAME = {"ko": "한국어(Korean)", "en": "영어(English)"}


def _lang_name(lang: str | None) -> str:
    return _LANG_NAME.get(lang or "ko", _LANG_NAME["ko"])


# ── 중립 라벨/제목 (2026-07-22, §3 축 B — 지명 hallucination 근절) ─────────────
# Gemini가 지명·서사를 못 만들게 스키마에서 뺐으므로, 표시 라벨은 서버가 좌표
# 순서만으로 중립 생성한다. pitstop 라벨은 route_service의 Kakao 실해석이 덮어씀.
def _neutral_label(idx: int, n: int, is_one_way: bool, lang: str | None) -> str:
    """순서 기반 중립 라벨 — 출발/지점 N/복귀(loop)·도착(one-way)."""
    ko = (lang or "ko") != "en"
    if idx == 0:
        return "출발" if ko else "Start"
    if idx == n - 1:
        if is_one_way:
            return "도착" if ko else "Finish"
        return "복귀" if ko else "Return"
    return f"지점 {idx}" if ko else f"Point {idx}"


def _neutral_summary(km: float, is_one_way: bool, lang: str | None) -> str:
    """거리·구성 중심 중립 제목 — 지명 창작 여지 0. 표시명은 프론트 역지오코딩."""
    ko = (lang or "ko") != "en"
    if ko:
        return f"{km}km {'편도' if is_one_way else '순환'} 코스"
    return f"{km}km {'one-way' if is_one_way else 'loop'} course"


def _route_tool(lang: str | None = None) -> dict:
    """중립 라벨 전환(2026-07-22, §3 축 B): 웨이포인트 name·description·summary를
    스키마에서 제거 — Gemini가 지명·서사를 **창작하지 못하게 원천 차단**(청라 라벨
    hallucination 근절). 좌표+순서+is_pitstop만 받고, 표시 라벨·제목은 서버가 중립
    템플릿으로 채운다(pitstop 이름만 Kakao 실해석). 기하 필드(거리)는 불변."""
    return {
        "type": "function",
        "function": {
            "name": "build_running_route",
            "description": (
                "Return a structured running route for a runner in South Korea as "
                "ordered waypoint COORDINATES only (no names or descriptions — the "
                "server assigns display labels). Mark any pitstop with is_pitstop=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "total_distance_km": {
                        "type": "number",
                        "description": "Estimated total distance of the route in km.",
                    },
                    "estimated_duration_min": {
                        "type": "number",
                        "description": "Estimated jogging duration in minutes.",
                    },
                    "waypoints": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "coordinate": {
                                    "type": "object",
                                    "properties": {
                                        "lat": {"type": "number"},
                                        "lng": {"type": "number"},
                                    },
                                    "required": ["lat", "lng"],
                                },
                                "is_pitstop": {"type": "boolean"},
                            },
                            "required": ["coordinate", "is_pitstop"],
                        },
                    },
                },
                "required": ["total_distance_km", "waypoints"],
            },
        },
    }


# Maps a negative feedback tag (stored value) to a concrete avoidance
# instruction injected into the prompt. Tags without an entry are ignored.
AVOIDANCE_INSTRUCTIONS = {
    "오르막많음": "prefer flat terrain and avoid steep hills",
    "신호등많음": "minimize road crossings and traffic lights; prefer parks and riversides",
    "노면나쁨": "prefer well-paved running paths",
    "사람많음": "prefer quieter, less crowded paths",
    "너무김": "keep strictly within the target distance",
    "너무짧음": "ensure the route reaches the full target distance",
}


def _prefs_text(prefs: AiCourseSettings | None) -> str:
    """유저의 AI 코스 선호(설정+body 머지 결과)를 프롬프트 문단으로 변환.

    terrain='hill'과 avoid_hills=true가 함께 오면 avoid_hills가 이긴다
    (hill 선호 문구는 생략) — 설정 화면에서 둘 다 켤 수 있으므로 거부하지 않음.
    """
    if prefs is None:
        return ""
    phrases: list[str] = []
    if prefs.terrain == "flat":
        phrases.append("prefer flat terrain")
    elif prefs.terrain == "hill" and not prefs.avoid_hills:
        phrases.append("include some uphill sections for training")
    if prefs.avoid_hills:
        phrases.append("avoid steep hills")
    if prefs.scenic:
        phrases.append("prefer scenic paths — riversides, parks, waterfront")
    if prefs.surface == "paved":
        phrases.append("prefer well-paved surfaces")
    elif prefs.surface == "trail":
        phrases.append("prefer unpaved trails and dirt paths")
    if not phrases:
        return ""
    return "\nRunner's saved preferences: " + "; ".join(phrases) + "."


# 도보 스냅 팽창 보정 (docs/ROUTE_DISTANCE_GUARANTEE_DESIGN.md §3).
# 실측 3건(2026-07-14, 4km 목표): 팽창비 1.13(뚝섬)/1.50(여의도)/1.74(서울숲),
# 중앙값 1.50 → 1.45 채택(저팽창 격자 도로망에서 미달을 덜 만들도록 소폭 하향 —
# 오버슈트는 ±0.5km 게이트+재시도가 잡음). ⚠️ 표본 3건 한계: route_gen 계측
# 로그가 20건 이상 쌓이면 ratio 중앙값을 재산정해 이 상수를 갱신할 것.
# 스냅 팽창비 초기값 — 2026-07-20 긴급 재보정: 1.45 → 1.6 (실측 13건 중앙값
# 1.58·평균 1.61, 전 실패가 초과 방향 = 상수 과소). 표본이 서울 target 5km에
# 편중된 점은 판단 플래그 — attempt 2부터는 route_service가 직전 실측 ratio를
# 피드백하므로(적응형) 이 상수는 첫 시도 조준에만 쓰인다.
_SNAP_INFLATION = 1.6
# 비대칭 밴드 [target−0.1, target+0.5] 중심 조준 오프셋 — 체인 목표를
# (target+0.2) 기준으로 계산해 미달 확률을 구조적으로 낮춘다(v2.1 룰링과 세트).
_BAND_AIM_KM = 0.2
# 체인 상한 배수 — 프롬프트 "MUST NOT exceed aim×1.15" + 사전 게이트 [0.75,1.25].
# (v2.6 양방향 하한 _CHAIN_FLOOR_FACTOR는 미달 유발로 롤백 — 2026-07-21 오너 결정.)
_CHAIN_CAP_FACTOR = 1.15


def _build_prompt(
    target_distance_km: float,
    start: Coordinate,
    end: Coordinate | None,
    pitstop_keyword: str | None,
    notes: str | None,
    avoid_tags: list[str] | None = None,
    prefs: AiCourseSettings | None = None,
    radius_km: float | None = None,
    chain_target_km: float | None = None,
    radius_center: Coordinate | None = None,
) -> str:
    if end:
        end_text = f"end at ({end.lat}, {end.lng})"
    elif prefs is not None and not prefs.prefer_loop:
        end_text = (
            "returning to the starting point is optional — "
            "a loop or an out-and-back route is fine"
        )
    else:
        end_text = "return to the starting point (a loop route)"
    pitstop_text = (
        f"Include at least one pitstop matching the keyword '{pitstop_keyword}'."
        if pitstop_keyword
        else "No specific pitstop is required."
    )
    notes_text = f"\nRunner preferences: {notes}" if notes else ""

    # Conditional avoidance paragraph from past negative feedback nearby.
    avoid_text = ""
    if avoid_tags:
        phrases = [
            AVOIDANCE_INSTRUCTIONS[tag]
            for tag in avoid_tags
            if tag in AVOIDANCE_INSTRUCTIONS
        ]
        if phrases:
            avoid_text = (
                "\nRunners near this start point previously disliked routes for "
                "these reasons. Actively avoid them this time: "
                + "; ".join(phrases)
                + "."
            )

    # 탐색 반경: 수치가 오면 "near the start"를 명시적 반경 제약으로 교체.
    # (구 문구의 "avoid overshooting"은 과소 기하를 유도해 삭제 — ±0.5km 보장 설계)
    if radius_km is not None and radius_center is not None:
        # end-aware(v2.3): 일방 요청은 start-end corridor 중점 기준 원 —
        # start 중심 원은 |start−end|≈target일 때 도착지에 못 닿는 기하 모순.
        area_line = (
            f"Keep every waypoint within {radius_km} km (straight-line) of "
            f"({radius_center.lat}, {radius_center.lng}) — the midpoint of the "
            "start-to-end corridor."
        )
    elif radius_km is not None:
        area_line = (
            f"Keep every waypoint within {radius_km} km (straight-line) of the "
            "start point."
        )
    else:
        area_line = "Keep every waypoint near the start point."

    # 거리 보장 v2.2: 도보 스냅 팽창을 프롬프트가 선보정 — 모델에게 어림이 아닌
    # 계산 가능한 직선 체인 목표를 준다. 조준점은 밴드 중심(target+0.2).
    # chain_target_km이 오면 그 값 사용(적응형 — route_service가 직전 attempt의
    # 실측 팽창비로 재계산해 전달), 없으면 초기 상수(_SNAP_INFLATION)로 계산.
    # 체인 상한 제약 — 상한만("MUST NOT exceed aim×1.15"). v2.6 양방향
    # [aim×0.90, aim×1.15] "aim for the middle"은 E2E에서 미달 편향을 유발해
    # 롤백(2026-07-21 오너 결정): 모델이 하한을 안 지키면서 "middle" 지시가
    # 오히려 짧은 체인을 유도 → 여의도 snaps 3.38/3.60 미달. 상한만 유지.
    chain_target = chain_target_km if chain_target_km is not None else round(
        (target_distance_km + _BAND_AIM_KM) / _SNAP_INFLATION, 1
    )
    chain_cap = round(chain_target * _CHAIN_CAP_FACTOR, 1)

    # v87 프롬프트 재구성(진단 G) — hard/strong/soft/forbidden 섹션화. 진단 근본:
    # 거리-단독 압력("shorter is not acceptable")이 무명 지점·지그재그 패딩을 유도.
    # 절충(오너): 상한 cap은 유지(오버슈트 방지·v2.6 미달 롤백 교훈), 대신 하한
    # 압력을 "지그재그로 채우지 마라"로 교체. 미달 재발 시 프롬프트만 롤백(E#2 유지).
    hard = (
        "HARD CONSTRAINTS — a route violating any of these is invalid:\n"
        f"1. Final on-road length: about {target_distance_km} km. The route is "
        f"snapped to real pedestrian roads, typically 1.3-1.7x longer than the "
        f"straight lines between waypoints, so place waypoints such that the SUM "
        f"OF STRAIGHT-LINE distances between consecutive waypoints (including the "
        f"return to start for loops) is about {chain_target} km. This chain MUST "
        f"NOT exceed {chain_cap} km — a longer route is invalid.\n"
        f"2. {area_line}\n"
        f"3. Start at ({start.lat}, {start.lng}) and {end_text}."
    )
    strong = (
        "\n\nSTRONG PREFERENCES:\n"
        "- Prefer well-known, established running areas close to the start — "
        "riversides, parks, waterfront promenades, and main sidewalks. Choose "
        "recognizable spots a local runner would name.\n"
        f"- {pitstop_text}"
    )
    forbidden = (
        "\n\nFORBIDDEN:\n"
        "- Do NOT pad the route with zigzags, backtracks, or meaningless detours "
        "just to reach the target distance. A slightly shorter, clean route is "
        "better than a padded one that hits the number exactly.\n"
        "- Do NOT invent obscure or unnamed spots, and do NOT route through the "
        "inside of apartment complexes, parking lots, or private/enclosed areas.\n"
        "- Do NOT place waypoints in military bases, restricted or reservation-only "
        "zones (기지·반환부지·예약제 구역) — prefer public, freely-runnable parks and paths.\n"
        "- Do NOT invent place names, descriptions, or a title — return ordered "
        "waypoints as realistic WGS84 coordinates only."
    )
    # 소프트(선호·메모·회피)는 있을 때만 SOFT 섹션으로. 없으면 생략(잡음 최소).
    soft_bits = "".join(
        s for s in (_prefs_text(prefs), notes_text, avoid_text) if s
    )
    soft = f"\n\nSOFT PREFERENCES (honor when they don't conflict with the above):{soft_bits}" if soft_bits else ""

    return (
        f"{hard}{strong}{forbidden}{soft}\n\n"
        "Mark any pitstop with is_pitstop=true and call build_running_route with the result."
    )


async def generate_route(
    target_distance_km: float,
    start: Coordinate,
    end: Coordinate | None = None,
    pitstop_keyword: str | None = None,
    notes: str | None = None,
    avoid_tags: list[str] | None = None,
    prefs: AiCourseSettings | None = None,
    radius_km: float | None = None,
    lang: str = "ko",
    chain_target_km: float | None = None,
    radius_center: Coordinate | None = None,
) -> RouteResponse:
    """Generate a structured running route via OpenAI Function Calling.

    Args:
        target_distance_km: Desired total distance.
        start: Starting coordinate.
        end: Optional end coordinate; if None, a loop back to start is assumed.
        pitstop_keyword: Optional waypoint keyword, e.g. '편의점'.
        notes: Optional free-form preferences.
        avoid_tags: Negative feedback tags to steer away from.
        prefs: Effective AI-course preferences (body > user settings > defaults),
            resolved by route_service. None keeps the legacy prompt shape.
        radius_km: Search radius around the start (straight-line). None keeps
            the legacy "near the start" wording.
        lang: 출력 언어 (유저 settings.lang, ko/en). summary·waypoint 텍스트가
            이 언어로 나온다.

    Returns:
        A validated RouteResponse parsed from the model's tool call.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a local running coach in South Korea. You design safe, "
                "runnable routes (riversides, parks, sidewalks) and always respond "
                "by calling the build_running_route function. "
                "Return ordered waypoint COORDINATES only — do NOT invent place "
                "names, descriptions, or a title. The server assigns neutral display "
                "labels and resolves any pitstop name from the map provider. Focus "
                "entirely on realistic coordinates and the required geometry."
            ),
        },
        {"role": "user", "content": _build_prompt(
            target_distance_km, start, end, pitstop_keyword, notes, avoid_tags,
            prefs, radius_km, chain_target_km, radius_center,
        )},
    ]

    # reasoning_effort="none" — Gemini 2.5 flash의 thinking(추론) 비활성.
    # 코스 생성은 명확한 프롬프트를 따르는 구조화 출력이라 깊은 추론이 불필요.
    # 실측: thinking 켜짐 ~18~34s → 꺼짐 ~1.5s (품질 저하 없이 tool_call 정상).
    response = await _client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        tools=[_route_tool(lang)],
        tool_choice={"type": "function", "function": {"name": "build_running_route"}},
        reasoning_effort="none",
    )

    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        raise ValueError("Model did not return a tool call for build_running_route.")

    arguments = _loads_tool_args(tool_calls[0].function.arguments)
    # 중립 라벨 주입(§3 축 B): Gemini는 이제 좌표만 주므로 서버가 name·summary를
    # 채운다. RouteResponse.name/summary는 required라 validate 전에 주입 필수.
    # 표시 라벨·제목은 서버 중립 템플릿, pitstop 이름은 route_service의 Kakao가 덮어씀.
    is_one_way = end is not None
    wps = arguments.get("waypoints") or []
    for i, w in enumerate(wps):
        w["name"] = _neutral_label(i, len(wps), is_one_way, lang)
        w.pop("description", None)  # 서사 필드 방어 제거(스키마에서 뺐으나 만약 오면)
    arguments["summary"] = _neutral_summary(
        arguments.get("total_distance_km") or target_distance_km, is_one_way, lang)
    # Validate/coerce the model output against our Pydantic schema.
    return RouteResponse.model_validate(arguments)


# ── AI 오디오 코치 ─────────────────────────────────────────────────────────────

# JSON Schema for the coach-script tool. Mirrors list[CoachCue].
COACH_TOOL = {
    "type": "function",
    "function": {
        "name": "build_coach_script",
        "description": (
            "Return a Korean audio-coach script for a running course as an "
            "ordered list of TTS cues."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "trigger": {
                                "type": "string",
                                "enum": ["start", "distance_km", "waypoint", "finish"],
                            },
                            "at": {
                                "type": "number",
                                "description": (
                                    "distance_km: cumulative km. waypoint: index into "
                                    "the course's waypoint list. Omit for start/finish."
                                ),
                            },
                            "text": {"type": "string"},
                        },
                        "required": ["trigger", "text"],
                    },
                },
            },
            "required": ["cues"],
        },
    },
}

def _coach_system(lang: str | None) -> str:
    ln = _lang_name(lang)
    return (
        f"당신은 친근한 러닝 코치입니다. 러닝 중 TTS로 낭독될 짧은 멘트를 작성합니다. "
        f"모든 멘트(text)는 반드시 {ln}로 씁니다. "
        "규칙: ① 의학적 조언 금지 — 심박수 목표, 건강 상태 진단, 부상·질병 관련 지시를 절대 "
        "하지 않습니다. 안전 관련은 '몸이 힘들면 천천히 걸어도 좋아요' 수준까지만. "
        "② 문장은 TTS 낭독용 — 한 멘트 1~2문장, 이모지·특수기호 금지, 숫자와 단위는 "
        "낭독형으로 씁니다 (한국어 예: 5킬로미터, 5분 30초 / 영어 예: five kilometers). "
        "③ 과장 없이 담백하게 격려합니다. "
        "④ 반드시 build_coach_script 함수를 호출해 응답합니다."
    )


def _build_coach_prompt(
    distance_km: float,
    summary: str,
    waypoints: list[dict],
    run_count: int | None,
    avg_pace_sec_per_km: int | None,
    cue_interval_km: float,
) -> str:
    wp_lines = []
    for i, wp in enumerate(waypoints):
        desc = f" — {wp['description']}" if wp.get("description") else ""
        wp_lines.append(f"  {i}. {wp.get('name', '')}{desc}")
    wp_text = "\n".join(wp_lines) if wp_lines else "  (경유지 정보 없음)"

    if run_count and avg_pace_sec_per_km:
        runner = (
            f"지금까지 {run_count}회 러닝, 평소 페이스 "
            f"{avg_pace_sec_per_km // 60}분 {avg_pace_sec_per_km % 60}초/km"
        )
    else:
        runner = "첫 러닝 준비 중 (초보 러너 톤으로)"

    return (
        f"{distance_km}킬로미터 코스 \"{summary}\"의 오디오 코치 스크립트를 만들어 주세요.\n"
        f"경유지 (waypoint 인덱스 기준):\n{wp_text}\n"
        f"러너: {runner}.\n"
        f"약 {cue_interval_km}km 간격으로 distance_km 멘트를, 특색 있는 경유지에는 "
        "waypoint 멘트(그 장소의 명소·지형 이야기 1문장 포함)를, start와 finish 멘트를 "
        "각 1개 만들어 주세요. 총 12개 이하."
    )


async def generate_coach_script(
    distance_km: float,
    summary: str,
    waypoints: list[dict],
    run_count: int | None = None,
    avg_pace_sec_per_km: int | None = None,
    cue_interval_km: float = 1.0,
    lang: str = "ko",
) -> list[CoachCue]:
    """Generate the audio-coach cue list via function calling.

    lang: 멘트 출력 언어 (생성자 settings.lang). 코치 스크립트는 route당 캐시라
    "생성 시점 생성자 언어로 박제"된다.

    Returns raw validated cues; ordering/range cleanup is the caller's job
    (coach_service._sanitize_cues).
    """
    messages = [
        {"role": "system", "content": _coach_system(lang)},
        {"role": "user", "content": _build_coach_prompt(
            distance_km, summary, waypoints, run_count, avg_pace_sec_per_km,
            cue_interval_km,
        )},
    ]

    response = await _client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        tools=[COACH_TOOL],
        tool_choice={"type": "function", "function": {"name": "build_coach_script"}},
    )

    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        raise ValueError("Model did not return a tool call for build_coach_script.")

    arguments = _loads_tool_args(tool_calls[0].function.arguments)
    return [CoachCue.model_validate(c) for c in arguments.get("cues", [])]


# ── AI 월간 인사이트 ───────────────────────────────────────────────────────────

INSIGHT_TOOL = {
    "type": "function",
    "function": {
        "name": "build_monthly_insight",
        "description": (
            "Return a Korean monthly running insight: a coaching summary "
            "paragraph plus a 3-slot plan for next month."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "coaching": {
                    "type": "string",
                    "description": "코칭 요약 문단 (한국어 3~5문장).",
                },
                "plan": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "slot": {
                                "type": "string",
                                "enum": ["goal", "focus", "challenge"],
                            },
                            "title": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["slot", "title", "body"],
                    },
                },
            },
            "required": ["coaching", "plan"],
        },
    },
}

def _insight_system(lang: str | None) -> str:
    ln = _lang_name(lang)
    return (
        f"당신은 러닝 데이터를 분석해 월간 리포트를 쓰는 코치입니다. "
        f"coaching과 plan의 모든 텍스트는 반드시 {ln}로 씁니다. "
        "규칙: ① 의학적 조언 금지 — 심박수, 건강 상태 진단, 부상·질병 관련 지시를 "
        "절대 하지 않습니다. ② 제공된 수치만 인용합니다 — 입력에 없는 데이터"
        "(심박, 고도, 칼로리 등)를 지어내지 않습니다. ③ coaching은 3~5문장, 담백하게 "
        "격려하되 과장하지 않습니다. ④ plan은 goal(다음 달 목표)·focus(집중 포인트)·"
        "challenge(다음 도전) 세 슬롯을 각 1개씩, 이번 달 데이터에 근거해 제안합니다. "
        "⑤ 반드시 build_monthly_insight 함수를 호출해 응답합니다."
    )


def _pace_str(sec: int | None) -> str:
    if not sec:
        return "기록 없음"
    return f"{sec // 60}분 {sec % 60}초/km"


def _build_insight_prompt(
    year: int,
    month: int,
    total_distance_km: float,
    run_count: int,
    avg_pace_sec_per_km: int | None,
    delta_distance_km: float | None,
    weeks: list[dict],
    records: list[dict],
    pattern: dict,
) -> str:
    week_lines = "\n".join(
        f"  {w['index']}주차: {w['distance_km']}km ({w['run_count']}회, "
        f"평균 {_pace_str(w.get('avg_pace_sec_per_km'))})"
        for w in weeks if w["run_count"] > 0
    ) or "  (주차별 데이터 없음)"

    rec_names = {"best_pace": "최고 페이스", "best_5k": "최고 5K 환산",
                 "longest_distance": "최장 거리", "longest_duration": "최장 시간"}
    rec_lines = "\n".join(
        f"  {rec_names[r['type']]}: {r['value']}"
        + (" (이번 달 자기 기록 경신!)" if r["all_time_best"] else "")
        for r in records
    ) or "  (기록 없음)"

    tod_names = {"dawn": "새벽", "morning": "아침", "day": "낮",
                 "evening": "저녁", "night": "밤"}
    tod = pattern.get("time_of_day")
    delta_text = (
        f"전월 대비 {'+' if delta_distance_km >= 0 else ''}{delta_distance_km}km"
        if delta_distance_km is not None else "전월 데이터 없음"
    )
    next_month = 1 if month == 12 else month + 1

    return (
        f"{year}년 {month}월 러닝 데이터입니다. 이 수치만 근거로 월간 리포트를 만들어 주세요.\n"
        f"- 총 {total_distance_km}km, {run_count}회 러닝, "
        f"평균 페이스 {_pace_str(avg_pace_sec_per_km)}, {delta_text}\n"
        f"- 주차별 추이:\n{week_lines}\n"
        f"- 이번 달 최고 기록:\n{rec_lines}\n"
        f"- 패턴: 주로 {tod_names.get(tod, '다양한')} 시간대"
        f"({pattern.get('time_of_day_pct') or 0}%), "
        f"최장 연속 {pattern.get('longest_streak_days', 0)}일 러닝\n"
        f"plan의 goal 제목은 \"{next_month}월 목표\"로 해 주세요."
    )


async def generate_monthly_insight(lang: str = "ko", **kwargs) -> dict:
    """Generate the monthly insight via function calling.

    lang: 출력 언어 (본인 settings.lang). Returns {"coaching": str, "plan":
    [{slot,title,body}, ...]} — slot 검증·정렬은 insight_service의 몫.
    """
    messages = [
        {"role": "system", "content": _insight_system(lang)},
        {"role": "user", "content": _build_insight_prompt(**kwargs)},
    ]

    response = await _client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        tools=[INSIGHT_TOOL],
        tool_choice={"type": "function", "function": {"name": "build_monthly_insight"}},
    )

    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        raise ValueError("Model did not return a tool call for build_monthly_insight.")

    return _loads_tool_args(tool_calls[0].function.arguments)
