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
from app.models.schemas import Coordinate, RouteResponse

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


def _build_prompt(
    target_distance_km: float,
    start: Coordinate,
    end: Coordinate | None,
    pitstop_keyword: str | None,
    notes: str | None,
) -> str:
    end_text = (
        f"end at ({end.lat}, {end.lng})"
        if end
        else "return to the starting point (a loop route)"
    )
    pitstop_text = (
        f"Include at least one pitstop matching the keyword '{pitstop_keyword}'."
        if pitstop_keyword
        else "No specific pitstop is required."
    )
    notes_text = f"\nRunner preferences: {notes}" if notes else ""
    return (
        f"Design a running route in South Korea of about {target_distance_km} km. "
        f"Start at ({start.lat}, {start.lng}) and {end_text}. "
        f"{pitstop_text} "
        "Provide ordered waypoints with realistic WGS84 coordinates near the start, "
        "mark any pitstop with is_pitstop=true, and call build_running_route with the result."
        f"{notes_text}"
    )


async def generate_route(
    target_distance_km: float,
    start: Coordinate,
    end: Coordinate | None = None,
    pitstop_keyword: str | None = None,
    notes: str | None = None,
) -> RouteResponse:
    """Generate a structured running route via OpenAI Function Calling.

    Args:
        target_distance_km: Desired total distance.
        start: Starting coordinate.
        end: Optional end coordinate; if None, a loop back to start is assumed.
        pitstop_keyword: Optional waypoint keyword, e.g. '편의점'.
        notes: Optional free-form preferences.

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
            target_distance_km, start, end, pitstop_keyword, notes
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
