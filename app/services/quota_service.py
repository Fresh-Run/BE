"""Tier + quota service: server-side enforcement of free-tier limits.

The effective tier is read from profiles.tier (default 'free'). The only
write path today is the Supabase dashboard (admin); an IAP webhook will
update the same column later, so all reads here stay unchanged.

AI generation quota counts rows in route_generations — an immutable log —
rather than the routes table, so deleting routes can't refill the quota.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import AiGenerationQuota, QuotaResponse
from app.services.run_service import _KST, _week_start_utc

logger = logging.getLogger(__name__)

AI_WEEKLY_LIMIT = 3  # free-tier AI course generations per KST week


class QuotaExceeded(Exception):
    """Free-tier weekly AI generation quota is used up."""

    def __init__(self, used: int, reset_at: str):
        self.used = used
        self.limit = AI_WEEKLY_LIMIT
        self.reset_at = reset_at
        super().__init__("AI generation quota exceeded")


def _reset_at_kst() -> str:
    """Next Monday 00:00 KST (when the weekly quota refills), as KST ISO."""
    week_start = datetime.fromisoformat(_week_start_utc())
    return (week_start + timedelta(weeks=1)).astimezone(_KST).isoformat()


async def get_tier(user_id: str) -> str:
    """Return the user's tier ('free'/'premium'); no profile counts as free."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("profiles")
        .select("tier")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return "free"
    return res.data[0].get("tier") or "free"


async def _generations_this_week(user_id: str) -> int:
    """Count the caller's AI generations since Monday 00:00 KST.

    count="exact" reads the total from Content-Range; limit(1) keeps the
    payload tiny.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("route_generations")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .gte("created_at", _week_start_utc())
        .limit(1)
        .execute()
    )
    return res.count or 0


async def check_ai_quota(user_id: str) -> None:
    """Raise QuotaExceeded if a free user has no generations left this week.

    Called BEFORE the OpenAI/map pipeline so a blocked request costs nothing.
    Premium users are never blocked.
    """
    tier, used = await asyncio.gather(
        get_tier(user_id), _generations_this_week(user_id)
    )
    if tier == "premium":
        return
    if used >= AI_WEEKLY_LIMIT:
        raise QuotaExceeded(used=used, reset_at=_reset_at_kst())


async def record_ai_generation(user_id: str) -> None:
    """Log one successful AI generation (consumes quota).

    Best-effort: the route was already generated (and paid for), so a
    logging failure must not break the response — it just undercounts.
    """
    try:
        supabase = get_supabase_admin()
        await asyncio.to_thread(
            lambda: supabase.table("route_generations")
            .insert({"user_id": user_id})
            .execute()
        )
    except Exception:  # noqa: BLE001
        logger.warning("AI 생성 쿼터 기록 실패", exc_info=True)


async def get_quota(user_id: str) -> QuotaResponse:
    """Current tier + AI generation quota (for the '이번 주 2/3회' UI)."""
    tier, used = await asyncio.gather(
        get_tier(user_id), _generations_this_week(user_id)
    )
    if tier == "premium":
        ai = AiGenerationQuota(
            used=used, limit=None, remaining=None, reset_at=None, unlimited=True
        )
    else:
        ai = AiGenerationQuota(
            used=used,
            limit=AI_WEEKLY_LIMIT,
            remaining=max(0, AI_WEEKLY_LIMIT - used),
            reset_at=_reset_at_kst(),
            unlimited=False,
        )
    return QuotaResponse(tier=tier, ai_generation=ai)
