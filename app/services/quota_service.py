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
from datetime import datetime, timedelta, timezone

from postgrest.exceptions import APIError

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import AiGenerationQuota, QuotaResponse
from app.services.run_service import _KST, _week_start_utc

logger = logging.getLogger(__name__)

AI_WEEKLY_LIMIT = 3  # free-tier AI course generations per KST week

# BM 결정(2026-07-06): 기획 원안 '크루 생성 프리미엄 전용'에서 '무료 1개
# 맛보기'로 확정 — 출시 초기 콘텐츠 부트스트랩용. 추후 조정 가능.
FREE_CREW_LIMIT = 1  # free 유저가 owner일 수 있는 크루 수


class QuotaExceeded(Exception):
    """Free-tier weekly AI generation quota is used up."""

    def __init__(self, used: int, reset_at: str):
        self.used = used
        self.limit = AI_WEEKLY_LIMIT
        self.reset_at = reset_at
        super().__init__("AI generation quota exceeded")


class PremiumRequired(Exception):
    """Feature is premium-only and the caller is on the free tier."""

    def __init__(self, feature: str):
        self.feature = feature
        super().__init__(f"Premium required for {feature}")


async def ensure_premium(user_id: str, feature: str) -> None:
    """Raise PremiumRequired unless the caller's tier is 'premium'."""
    if await get_tier(user_id) != "premium":
        raise PremiumRequired(feature)


class CrewLimitExceeded(Exception):
    """Free tier already owns FREE_CREW_LIMIT crews."""

    def __init__(self, limit: int):
        self.limit = limit
        super().__init__("Free-tier crew creation limit reached")


# 크루 생성 한도는 create_crew_limited RPC로 원자화(M8) — 옛 count-then-insert
# 게이트(ensure_crew_creation)는 제거. tier→limit 계산은 create_crew 핸들러가 하고
# CrewLimitExceeded는 crew_service.create_crew가 RPC 에러에서 매핑한다.


def _reset_at_kst() -> str:
    """Next Monday 00:00 KST (when the weekly quota refills), as KST ISO."""
    week_start = datetime.fromisoformat(_week_start_utc())
    return (week_start + timedelta(weeks=1)).astimezone(_KST).isoformat()


async def get_tier(user_id: str) -> str:
    """Return the user's tier ('free'/'premium'); no profile counts as free.

    premium이면 IAP 구독 만료를 lazy 확인 — 만료 시 이 자리에서 강등한다.
    모든 프리미엄 게이트(ensure_premium/크루 한도/쿼터)가 이 함수를 지나므로
    별도 잡 없이 강등이 전 기능에 즉시 일관 적용된다.
    """
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
    tier = res.data[0].get("tier") or "free"
    if tier == "premium":
        return await _lazy_iap_downgrade(user_id)
    return tier


async def _lazy_iap_downgrade(user_id: str) -> str:
    """IAP 구독 만료 lazy 강등. 반환은 최종 tier.

    - 구독 행 없음 = admin 수동 부여(test1 등) → premium 유지, 강등 없음.
    - active인데 expires_at 경과 → status='expired' + profiles.tier='free'.
    - expired/revoked인데 tier가 premium으로 남아 있으면(중간 크래시) 치유.
    - 확인 실패 시 premium 유지 (게이트가 DB 장애로 유료 유저를 막으면 안 됨).
    """
    try:
        supabase = get_supabase_admin()
        # PK가 거래 id라 유저당 여러 행 가능 (재구독 이력) — 가장 늦게
        # 만료되는 행이 현재 구독 상태를 대표한다.
        res = await asyncio.to_thread(
            lambda: supabase.table("subscriptions")
            .select("status, expires_at")
            .eq("user_id", user_id)
            .order("expires_at", desc=True)
            .limit(1)
            .execute()
        )
        if not res.data:
            return "premium"  # admin 부여 — 만료 개념 없음
        sub = res.data[0]
        expired = (
            sub["status"] == "active"
            and datetime.fromisoformat(sub["expires_at"]) <= datetime.now(timezone.utc)
        )
        if expired:
            # 대표 행이 만료면 나머지 active도 전부 그보다 먼저 만료된 것
            await asyncio.to_thread(
                lambda: supabase.table("subscriptions")
                .update({"status": "expired",
                         "updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("user_id", user_id)
                .eq("status", "active")
                .execute()
            )
        if expired or sub["status"] in ("expired", "revoked"):
            await asyncio.to_thread(
                lambda: supabase.table("profiles")
                .update({"tier": "free"})
                .eq("user_id", user_id)
                .execute()
            )
            logger.info("IAP 구독 만료 — tier 강등 (user=%s)", user_id)
            return "free"
        return "premium"
    except Exception:  # noqa: BLE001 - 확인 실패가 유료 유저를 막으면 안 됨
        logger.warning("IAP 만료 확인 실패 — premium 유지", exc_info=True)
        return "premium"


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


# AI 쿼터 검사는 reserve_ai_generation RPC로 원자화(M3) — 옛 check-then-record
# 게이트(check_ai_quota)·기록(record_ai_generation)은 reserve/release로 대체.


async def reserve_ai_generation(user_id: str, limit: int | None) -> str:
    """Gemini 호출 전에 쿼터 슬롯을 원자 예약 (M3). 예약 id 반환.

    reserve_ai_generation RPC가 user advisory lock으로 직렬화 후 주간 count를
    검사하고 route_generations에 삽입 → 동시 N건 중 한도 내 개수만 예약 성공,
    나머지는 QuotaExceeded. limit=None(premium)은 검사 없이 로그만 남김
    (get_quota의 used 표시 보존). 생성 실패 시 release_ai_generation으로 회수.
    """
    supabase = get_supabase_admin()
    try:
        res = await asyncio.to_thread(
            lambda: supabase.rpc(
                "reserve_ai_generation",
                {"_user_id": user_id, "_limit": limit, "_week_start": _week_start_utc()},
            ).execute()
        )
    except APIError as exc:
        if "quota_exceeded" in str(exc):
            # 예약 거부 시점의 used는 한도와 같음(그래서 막힌 것)
            raise QuotaExceeded(used=limit or 0, reset_at=_reset_at_kst()) from exc
        raise
    return res.data  # RPC returns the reservation uuid (scalar)


async def release_ai_generation(reservation_id: str) -> None:
    """예약 해제 (생성 실패 시) — 예약 행 삭제로 '실패는 무료' 시맨틱 보존.

    Best-effort: 삭제 실패해도 다음 주 리셋으로 회수되므로 치명적이지 않다.
    """
    if not reservation_id:
        return
    try:
        supabase = get_supabase_admin()
        await asyncio.to_thread(
            lambda: supabase.table("route_generations")
            .delete()
            .eq("id", reservation_id)
            .execute()
        )
    except Exception:  # noqa: BLE001
        logger.warning("AI 예약 해제 실패 (다음 주 리셋으로 회수)", exc_info=True)


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
