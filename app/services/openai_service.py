"""OpenAI integration using Function Calling to produce structured routes.

The model is asked to design a running route given a target distance, a
start (and optional end) location, and a pitstop keyword. We force the model
to call the `build_running_route` tool, whose JSON Schema mirrors our
`RouteResponse` Pydantic model — so the model's output is structured and
directly validatable.
"""

from __future__ import annotations

import json

from openai import AsyncOpenAI

from app.core.config import settings
from app.models.schemas import AiCourseSettings, CoachCue, Coordinate, RouteResponse

import os

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
)

# JSON Schema for the tool the model is forced to call. Mirrors RouteResponse.
ROUTE_TOOL = {
    "type": "function",
    "function": {
        "name": "build_running_route",
        "description": (
            "Return a structured running route for a runner in South Korea, "
            "including ordered waypoints and an optional pitstop."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Short human-readable description of the route.",
                },
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
                            "name": {"type": "string"},
                            "coordinate": {
                                "type": "object",
                                "properties": {
                                    "lat": {"type": "number"},
                                    "lng": {"type": "number"},
                                },
                                "required": ["lat", "lng"],
                            },
                            "is_pitstop": {"type": "boolean"},
                            "description": {"type": "string"},
                        },
                        "required": ["name", "coordinate", "is_pitstop"],
                    },
                },
            },
            "required": ["summary", "total_distance_km", "waypoints"],
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


def _build_prompt(
    target_distance_km: float,
    start: Coordinate,
    end: Coordinate | None,
    pitstop_keyword: str | None,
    notes: str | None,
    avoid_tags: list[str] | None = None,
    prefs: AiCourseSettings | None = None,
    radius_km: float | None = None,
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
    if radius_km is not None:
        area_text = (
            f"Keep every waypoint within {radius_km} km (straight-line) of the "
            "start point, and design the route so its total length closely "
            "matches the target distance (avoid overshooting). Provide ordered "
            "waypoints with realistic WGS84 coordinates, "
        )
    else:
        area_text = (
            "Provide ordered waypoints with realistic WGS84 coordinates near the start, "
        )

    return (
        f"Design a running route in South Korea of about {target_distance_km} km. "
        f"Start at ({start.lat}, {start.lng}) and {end_text}. "
        f"{pitstop_text} "
        f"{area_text}"
        "mark any pitstop with is_pitstop=true, and call build_running_route with the result."
        f"{_prefs_text(prefs)}"
        f"{notes_text}"
        f"{avoid_text}"
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

    Returns:
        A validated RouteResponse parsed from the model's tool call.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a local running coach in South Korea. You design safe, "
                "runnable routes (riversides, parks, sidewalks) and always respond "
                "by calling the build_running_route function."
            ),
        },
        {"role": "user", "content": _build_prompt(
            target_distance_km, start, end, pitstop_keyword, notes, avoid_tags,
            prefs, radius_km,
        )},
    ]

    response = await _client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        tools=[ROUTE_TOOL],
        tool_choice={"type": "function", "function": {"name": "build_running_route"}},
    )

    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        raise ValueError("Model did not return a tool call for build_running_route.")

    arguments = json.loads(tool_calls[0].function.arguments)
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

_COACH_SYSTEM = (
    "당신은 친근한 한국어 러닝 코치입니다. 러닝 중 TTS로 낭독될 짧은 멘트를 작성합니다. "
    "규칙: ① 의학적 조언 금지 — 심박수 목표, 건강 상태 진단, 부상·질병 관련 지시를 절대 "
    "하지 않습니다. 안전 관련은 '몸이 힘들면 천천히 걸어도 좋아요' 수준까지만. "
    "② 문장은 TTS 낭독용 — 한 멘트 1~2문장, 이모지·특수기호·영어 약어 금지, 숫자와 단위는 "
    "한글 낭독형으로 씁니다 (예: 5킬로미터, 5분 30초). "
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
) -> list[CoachCue]:
    """Generate the audio-coach cue list via function calling.

    Returns raw validated cues; ordering/range cleanup is the caller's job
    (coach_service._sanitize_cues).
    """
    messages = [
        {"role": "system", "content": _COACH_SYSTEM},
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

    arguments = json.loads(tool_calls[0].function.arguments)
    return [CoachCue.model_validate(c) for c in arguments.get("cues", [])]
