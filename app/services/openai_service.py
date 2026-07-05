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
from app.models.schemas import AiCourseSettings, Coordinate, RouteResponse

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
