"""Feedback learning loop: turn past negative feedback into avoidance hints.

Since there is no login yet (user_id is NULL), we relate a new generation
request to past feedback by START LOCATION: we look at routes that started
near the requested start point, gather the negative feedback tags from runs
on those routes, and return the most frequent ones so the prompt can tell
the model what to avoid.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import NEGATIVE_TAGS, Coordinate

logger = logging.getLogger(__name__)

# String values of the negative tags (what's stored in runs.feedback_tags).
_NEGATIVE_VALUES = {tag.value for tag in NEGATIVE_TAGS}

# Approximate km per degree of latitude (good enough for a ~1km box filter).
_KM_PER_DEG_LAT = 111.0


def _top_negative_tags(
    runs: list[dict], min_count: int, top_n: int
) -> list[str]:
    """Tally negative feedback tags across runs; return the top ones.

    Keeps only tags in the negative vocabulary that appear at least
    `min_count` times, ordered by frequency, capped at `top_n`.
    """
    counter: Counter[str] = Counter()
    for run in runs:
        for tag in run.get("feedback_tags") or []:
            if tag in _NEGATIVE_VALUES:
                counter[tag] += 1
    return [tag for tag, count in counter.most_common() if count >= min_count][:top_n]


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two WGS84 points, in kilometers."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def collect_avoidance_hints(
    start: Coordinate,
    radius_km: float = 1.0,
    days: int = 90,
    min_count: int = 2,
    top_n: int = 3,
) -> list[str]:
    """Return negative tags to avoid for routes starting near `start`.

    Best-effort: any failure (DB down, bad data) logs a warning and returns
    an empty list, so route generation is never blocked.

    Steps:
      1. Find past routes whose start is within `radius_km` of `start`.
      2. Collect feedback tags from runs on those routes in the last `days`.
      3. Tally negative tags; keep those seen >= `min_count`, top `top_n`.
    """
    try:
        supabase = get_supabase_admin()

        # 1) Bounding-box prefilter (cheap, index-backed), then refine by
        #    true distance. Longitude degrees shrink with latitude.
        d_lat = radius_km / _KM_PER_DEG_LAT
        cos_lat = max(math.cos(math.radians(start.lat)), 1e-6)
        d_lng = radius_km / (_KM_PER_DEG_LAT * cos_lat)

        routes_res = await asyncio.to_thread(
            lambda: supabase.table("routes")
            .select("id, start_lat, start_lng")
            .gte("start_lat", start.lat - d_lat)
            .lte("start_lat", start.lat + d_lat)
            .gte("start_lng", start.lng - d_lng)
            .lte("start_lng", start.lng + d_lng)
            .execute()
        )

        route_ids = [
            row["id"]
            for row in routes_res.data
            if row.get("start_lat") is not None
            and row.get("start_lng") is not None
            and _haversine_km(
                start.lat, start.lng, row["start_lat"], row["start_lng"]
            )
            <= radius_km
        ]
        if not route_ids:
            return []

        # 2) Recent runs on those routes.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        runs_res = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .select("feedback_tags, ran_at")
            .in_("route_id", route_ids)
            .gte("ran_at", cutoff)
            .execute()
        )

        # 3) Tally negative tags only.
        adopted = _top_negative_tags(runs_res.data, min_count, top_n)

        if adopted:
            logger.info(
                "Avoidance hints near (%.5f, %.5f): %s (from %d nearby route(s)).",
                start.lat,
                start.lng,
                adopted,
                len(route_ids),
            )
        return adopted
    except Exception:  # noqa: BLE001 - learning loop is best-effort
        logger.warning(
            "Failed to collect avoidance hints; generating without them.",
            exc_info=True,
        )
        return []


async def collect_route_avoidance_hints(
    route_id: str,
    owner_id: str | None = None,
    days: int = 90,
    min_count: int = 1,
    top_n: int = 3,
) -> list[str]:
    """Return negative tags to avoid, learned from one specific route's runs.

    Used when the client explicitly points at a past route (e.g. "this course
    was bad, give me a better one"). Because the route is chosen deliberately,
    `min_count` defaults to 1 (a single bad run is a real signal).

    소유권(감사 M4): owner_id가 주어지면 그 유저 소유의 route일 때만 학습한다.
    남의 비공개 route id를 넣어 그 route의 피드백을 프롬프트로 프로브하는 것을
    차단 — 소유가 아니면 조용히 [] 반환 (존재 은닉).

    Best-effort: any failure logs a warning and returns an empty list.
    """
    try:
        supabase = get_supabase_admin()
        if owner_id is not None:
            own = await asyncio.to_thread(
                lambda: supabase.table("routes")
                .select("id")
                .eq("id", route_id)
                .eq("user_id", owner_id)
                .limit(1)
                .execute()
            )
            if not own.data:
                return []  # 남의 route — 학습 거부
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        runs_res = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .select("feedback_tags, ran_at")
            .eq("route_id", route_id)
            .gte("ran_at", cutoff)
            .execute()
        )

        adopted = _top_negative_tags(runs_res.data, min_count, top_n)
        if adopted:
            logger.info(
                "Avoidance hints from route %s: %s.", route_id, adopted
            )
        return adopted
    except Exception:  # noqa: BLE001 - learning loop is best-effort
        logger.warning(
            "Failed to collect avoidance hints for route %s; ignoring.",
            route_id,
            exc_info=True,
        )
        return []
