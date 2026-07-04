"""Crew (community) persistence and membership logic.

Data access uses the service_role client (bypasses RLS); visibility rules
(public vs private, membership) are enforced here in app code. supabase-py is
synchronous, so blocking calls run in worker threads.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import (
    ChallengeCreate,
    ChallengeResponse,
    CrewCreate,
    CrewMemberResponse,
    CrewRankingEntry,
    CrewResponse,
    CrewUpdate,
)
from app.services import notification_service, profile_service

_KST = timezone(timedelta(hours=9))

logger = logging.getLogger(__name__)


# --- Errors (mapped to HTTP status codes by the API layer) -------------------


class CrewError(Exception):
    """Base class for crew operation errors."""


class ChallengeAlreadyActive(CrewError):
    """A non-ended challenge already exists for this crew."""


class CrewNotFound(CrewError):
    """Crew does not exist (or is hidden from this user)."""


class CrewAccessDenied(CrewError):
    """Crew exists but the action isn't allowed (e.g. joining a private crew)."""


class CrewFull(CrewError):
    """Crew has reached max_members."""


class AlreadyMember(CrewError):
    """User is already a member of the crew."""


class NotAMember(CrewError):
    """User is not a member of the crew."""


class OwnerCannotKickSelf(CrewError):
    """The owner cannot kick themselves (use leave/transfer/delete instead)."""


class OwnerCannotLeave(CrewError):
    """The owner cannot leave their own crew (must delete/transfer instead)."""


class NotOwner(CrewError):
    """Caller is not the owner of the crew (owner-only action)."""


class TargetNotMember(CrewError):
    """Transfer target is not a member of the crew."""


class AlreadyOwner(CrewError):
    """Transfer target is already the owner (no-op)."""


# --- Helpers -----------------------------------------------------------------


def _to_response(
    crew: dict, member_count: int, owner_nickname: str | None = None
) -> CrewResponse:
    """Build a CrewResponse from a crew row dict + computed member count."""
    return CrewResponse(
        **crew, member_count=member_count, owner_nickname=owner_nickname
    )


async def _build_responses(
    crews: list[dict], counts: dict[str, int]
) -> list[CrewResponse]:
    """Attach member counts + owner nicknames (batched) to crew rows."""
    nicknames = await profile_service.get_nicknames([c["owner_id"] for c in crews])
    return [
        _to_response(c, counts.get(c["id"], 0), nicknames.get(c["owner_id"]))
        for c in crews
    ]


async def _one_response(crew: dict, member_count: int) -> CrewResponse:
    """Build a single CrewResponse, resolving the owner's nickname."""
    nicknames = await profile_service.get_nicknames([crew["owner_id"]])
    return _to_response(crew, member_count, nicknames.get(crew["owner_id"]))


async def _member_counts(crew_ids: list[str]) -> dict[str, int]:
    """Return {crew_id: member_count} for the given crews (counted, not stored)."""
    if not crew_ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .select("crew_id")
        .in_("crew_id", crew_ids)
        .execute()
    )
    counts: dict[str, int] = {}
    for row in res.data:
        counts[row["crew_id"]] = counts.get(row["crew_id"], 0) + 1
    return counts


async def _my_crew_ids(user_id: str) -> list[str]:
    """Return the ids of crews the user belongs to."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .select("crew_id")
        .eq("user_id", user_id)
        .execute()
    )
    return [row["crew_id"] for row in res.data]


async def _is_member(crew_id: str, user_id: str) -> bool:
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .select("user_id")
        .eq("crew_id", crew_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return bool(res.data)


# --- Operations --------------------------------------------------------------


async def create_crew(req: CrewCreate, owner_id: str) -> CrewResponse:
    """Create a crew and add the owner to crew_members (role='owner')."""
    supabase = get_supabase_admin()
    record = {
        "owner_id": owner_id,
        "name": req.name,
        "description": req.description,
        "area": req.area,
        "radius_km": req.radius_km,
        "sport": req.sport,
        "level": req.level.value,
        "max_members": req.max_members,
        "is_public": req.is_public,
        "active_days": req.active_days,
        "active_time": req.active_time,
        "color": req.color,
    }
    res = await asyncio.to_thread(
        lambda: supabase.table("crews").insert(record).execute()
    )
    crew = res.data[0]

    # Owner is automatically a member.
    await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .insert({"crew_id": crew["id"], "user_id": owner_id, "role": "owner"})
        .execute()
    )
    logger.info("Created crew (id=%s, owner=%s).", crew["id"], owner_id)
    return await _one_response(crew, member_count=1)


async def list_my_crews(user_id: str) -> list[CrewResponse]:
    """Return crews the user belongs to, newest first."""
    crew_ids = await _my_crew_ids(user_id)
    if not crew_ids:
        return []
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crews")
        .select("*")
        .in_("id", crew_ids)
        .order("created_at", desc=True)
        .execute()
    )
    counts = await _member_counts(crew_ids)
    return await _build_responses(res.data, counts)


def _sanitize(q: str) -> str:
    """Remove chars that break PostgREST OR filter syntax or inject extra wildcards."""
    return q.strip().replace(",", "").replace("*", "")


async def search_crews(q: str, limit: int = 20) -> list[CrewResponse]:
    """Search public crews by name, area, or description (case-insensitive partial match).

    Returns [] when q is blank after sanitization.
    """
    safe = _sanitize(q)
    if not safe:
        return []

    supabase = get_supabase_admin()
    pattern = f"*{safe}*"
    res = await asyncio.to_thread(
        lambda: supabase.table("crews")
        .select("*")
        .eq("is_public", True)
        .or_(f"name.ilike.{pattern},area.ilike.{pattern},description.ilike.{pattern}")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    if not res.data:
        return []
    counts = await _member_counts([c["id"] for c in res.data])
    return await _build_responses(res.data, counts)


async def list_browse_crews(user_id: str) -> list[CrewResponse]:
    """Return public crews plus private crews the user is a member of."""
    supabase = get_supabase_admin()
    pub = await asyncio.to_thread(
        lambda: supabase.table("crews").select("*").eq("is_public", True).execute()
    )
    crews_by_id: dict[str, dict] = {c["id"]: c for c in pub.data}

    # Include private crews the user is in (not covered by the public query).
    my_ids = await _my_crew_ids(user_id)
    missing = [cid for cid in my_ids if cid not in crews_by_id]
    if missing:
        mine = await asyncio.to_thread(
            lambda: supabase.table("crews").select("*").in_("id", missing).execute()
        )
        for c in mine.data:
            crews_by_id[c["id"]] = c

    crews = sorted(
        crews_by_id.values(), key=lambda c: c["created_at"], reverse=True
    )
    counts = await _member_counts([c["id"] for c in crews])
    return await _build_responses(crews, counts)


async def get_crew(crew_id: str, user_id: str) -> CrewResponse | None:
    """Return a crew if public or the user is a member; otherwise None (404)."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crews").select("*").eq("id", crew_id).limit(1).execute()
    )
    if not res.data:
        return None
    crew = res.data[0]
    if not crew["is_public"] and not await _is_member(crew_id, user_id):
        return None  # don't reveal private crews to non-members
    counts = await _member_counts([crew_id])
    return await _one_response(crew, counts.get(crew_id, 0))


async def join_crew(crew_id: str, user_id: str) -> CrewResponse:
    """Add the user as a member. Public crews only; respects max_members."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crews").select("*").eq("id", crew_id).limit(1).execute()
    )
    if not res.data:
        raise CrewNotFound()
    crew = res.data[0]
    if not crew["is_public"]:
        raise CrewAccessDenied()  # no invite flow yet
    if await _is_member(crew_id, user_id):
        raise AlreadyMember()

    counts = await _member_counts([crew_id])
    current = counts.get(crew_id, 0)
    if crew["max_members"] is not None and current >= crew["max_members"]:
        raise CrewFull()

    await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .insert({"crew_id": crew_id, "user_id": user_id, "role": "member"})
        .execute()
    )
    logger.info("User %s joined crew %s.", user_id, crew_id)

    try:
        await notification_service.create_notification(
            recipient_id=crew["owner_id"],
            actor_id=user_id,
            type="crew_joined",
            target_id=crew_id,
            target_type="crew",
        )
    except Exception:
        logger.warning("crew_joined 알림 생성 실패", exc_info=True)

    return await _one_response(crew, current + 1)


async def leave_crew(crew_id: str, user_id: str) -> None:
    """Remove the user from a crew. The owner cannot leave."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crews")
        .select("owner_id")
        .eq("id", crew_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise CrewNotFound()
    if res.data[0]["owner_id"] == user_id:
        raise OwnerCannotLeave()
    if not await _is_member(crew_id, user_id):
        raise NotAMember()

    await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .delete()
        .eq("crew_id", crew_id)
        .eq("user_id", user_id)
        .execute()
    )
    logger.info("User %s left crew %s.", user_id, crew_id)


async def transfer_ownership(
    crew_id: str, caller_id: str, new_owner_id: str, leave_after: bool = False
) -> CrewResponse:
    """Hand crew ownership to another member.

    Only the current owner may call. The target must already be a member.
    The old owner becomes a regular 'member' (and leaves too if leave_after).

    Atomicity: this performs several updates app-side (no transaction). Crew
    ownership transfers are rare, so the small race window is acceptable; an
    RPC could make it atomic later.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crews").select("*").eq("id", crew_id).limit(1).execute()
    )
    if not res.data:
        raise CrewNotFound()
    crew = res.data[0]

    if crew["owner_id"] != caller_id:
        raise NotOwner()
    if new_owner_id == caller_id:
        raise AlreadyOwner()
    if not await _is_member(crew_id, new_owner_id):
        raise TargetNotMember()

    # 1) Point the crew at the new owner.
    await asyncio.to_thread(
        lambda: supabase.table("crews")
        .update({"owner_id": new_owner_id})
        .eq("id", crew_id)
        .execute()
    )
    # 2) Promote the new owner's membership role.
    await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .update({"role": "owner"})
        .eq("crew_id", crew_id)
        .eq("user_id", new_owner_id)
        .execute()
    )
    # 3) Demote the old owner to a regular member.
    await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .update({"role": "member"})
        .eq("crew_id", crew_id)
        .eq("user_id", caller_id)
        .execute()
    )
    logger.info(
        "Crew %s ownership: %s -> %s.", crew_id, caller_id, new_owner_id
    )

    if leave_after:
        await asyncio.to_thread(
            lambda: supabase.table("crew_members")
            .delete()
            .eq("crew_id", crew_id)
            .eq("user_id", caller_id)
            .execute()
        )
        logger.info("Old owner %s left crew %s after transfer.", caller_id, crew_id)

    crew["owner_id"] = new_owner_id
    counts = await _member_counts([crew_id])
    return await _one_response(crew, counts.get(crew_id, 0))


async def list_members(crew_id: str, caller_id: str) -> list[CrewMemberResponse]:
    """Return the member roster for a crew.

    Visibility mirrors get_crew: public crews are open to any authenticated
    user; private crews are visible to members only. Raises CrewNotFound when
    the crew doesn't exist OR when a non-member tries to read a private crew
    (same 404, so the crew's existence isn't revealed).
    """
    supabase = get_supabase_admin()

    # 1. Confirm the crew exists and get is_public in one query.
    crew_res = await asyncio.to_thread(
        lambda: supabase.table("crews")
        .select("is_public")
        .eq("id", crew_id)
        .limit(1)
        .execute()
    )
    if not crew_res.data:
        raise CrewNotFound()

    is_public = crew_res.data[0]["is_public"]

    # 2. Fetch all members (we need the list anyway; reuse it for the
    #    visibility check instead of making a separate _is_member call).
    members_res = await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .select("user_id, role, joined_at")
        .eq("crew_id", crew_id)
        .execute()
    )
    members = members_res.data

    # 3. Visibility gate: private crew → caller must be in the member list.
    if not is_public:
        member_ids = {m["user_id"] for m in members}
        if caller_id not in member_ids:
            raise CrewNotFound()  # don't reveal the crew exists

    # 4. Sort: owner first, then by joined_at ASC (oldest members first).
    members.sort(key=lambda r: (0 if r["role"] == "owner" else 1, r["joined_at"]))

    # 5. Batch nickname lookup — one IN query, no N+1.
    nicknames = await profile_service.get_nicknames([m["user_id"] for m in members])

    return [
        CrewMemberResponse(
            user_id=m["user_id"],
            nickname=nicknames.get(m["user_id"]),
            role=m["role"],
            joined_at=m["joined_at"],
        )
        for m in members
    ]


def _week_start_utc() -> str:
    """ISO-8601 UTC string for this week's Monday 00:00 KST.

    KST = UTC+9. Monday 00:00 KST == Sunday 15:00 UTC of the prior week.
    We anchor on the local KST date so the boundary feels right to Korean users.
    """
    now_kst = datetime.now(_KST)
    monday_kst = (now_kst - timedelta(days=now_kst.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday_kst.astimezone(timezone.utc).isoformat()


async def get_weekly_ranking(crew_id: str, caller_id: str) -> list[CrewRankingEntry]:
    """Return members ranked by total distance run since this week's Monday 00:00 KST.

    Visibility mirrors list_members: public crews are open to any authenticated
    user; private crews return 404 for non-members. Members with no runs this
    week are excluded. Tied members share the same rank (1, 1, 3 …).
    """
    supabase = get_supabase_admin()

    # 1. Confirm crew exists and get is_public.
    crew_res = await asyncio.to_thread(
        lambda: supabase.table("crews")
        .select("is_public")
        .eq("id", crew_id)
        .limit(1)
        .execute()
    )
    if not crew_res.data:
        raise CrewNotFound()
    is_public = crew_res.data[0]["is_public"]

    # 2. Fetch member user_ids (reuse for visibility check + runs filter).
    members_res = await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .select("user_id")
        .eq("crew_id", crew_id)
        .execute()
    )
    member_ids = [r["user_id"] for r in members_res.data]

    # 3. Visibility gate: private crew → caller must be a member.
    if not is_public and caller_id not in member_ids:
        raise CrewNotFound()  # don't reveal the crew exists

    if not member_ids:
        return []

    # 4. Fetch this week's runs for all members in one IN query.
    week_start = _week_start_utc()
    runs_res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("user_id, distance_km")
        .in_("user_id", member_ids)
        .gte("ran_at", week_start)
        .execute()
    )

    # 5. Aggregate distance per member (only members with ≥1 run appear).
    totals: dict[str, float] = defaultdict(float)
    for row in runs_res.data:
        totals[row["user_id"]] += row["distance_km"]

    if not totals:
        return []

    # 6. Sort descending, assign ranks (tied members share the same rank).
    sorted_entries = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    ranked: list[tuple[int, str, float]] = []  # (rank, user_id, distance_km)
    current_rank = 1
    for i, (uid, dist) in enumerate(sorted_entries):
        if i > 0 and dist < sorted_entries[i - 1][1]:
            current_rank = i + 1
        ranked.append((current_rank, uid, dist))

    # 7. Batch nickname lookup.
    nicknames = await profile_service.get_nicknames([uid for _, uid, _ in ranked])

    return [
        CrewRankingEntry(
            rank=rank,
            user_id=uid,
            nickname=nicknames.get(uid),
            distance_km=round(dist, 2),
        )
        for rank, uid, dist in ranked
    ]


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string (with or without Z) into an aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


async def create_challenge(
    crew_id: str, caller_id: str, req: ChallengeCreate
) -> ChallengeResponse:
    """Create a crew challenge (owner only). Raises ChallengeAlreadyActive if one exists."""
    supabase = get_supabase_admin()

    # 1. Confirm crew exists and caller is owner.
    crew_res = await asyncio.to_thread(
        lambda: supabase.table("crews").select("owner_id").eq("id", crew_id).limit(1).execute()
    )
    if not crew_res.data:
        raise CrewNotFound()
    if crew_res.data[0]["owner_id"] != caller_id:
        raise NotOwner()

    # 2. Guard: reject if any non-ended challenge already exists.
    now_utc = datetime.now(timezone.utc).isoformat()
    active_res = await asyncio.to_thread(
        lambda: supabase.table("crew_challenges")
        .select("id")
        .eq("crew_id", crew_id)
        .gt("ends_at", now_utc)
        .limit(1)
        .execute()
    )
    if active_res.data:
        raise ChallengeAlreadyActive()

    # 3. Insert the challenge.
    record = {
        "crew_id": crew_id,
        "created_by": caller_id,
        "title": req.title,
        "goal_km": req.goal_km,
        "starts_at": req.starts_at,
        "ends_at": req.ends_at,
    }
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_challenges").insert(record).execute()
    )
    ch = res.data[0]
    logger.info("Created challenge (id=%s, crew=%s).", ch["id"], crew_id)

    now = datetime.now(timezone.utc)
    return ChallengeResponse(
        **ch,
        achieved_km=0.0,
        progress_pct=0.0,
        is_completed=False,
        is_active=_parse_ts(ch["starts_at"]) <= now <= _parse_ts(ch["ends_at"]),
    )


async def get_current_challenge(
    crew_id: str, caller_id: str
) -> ChallengeResponse | None:
    """Return the crew's active/upcoming challenge with real-time progress, or None.

    Visibility mirrors list_members: public crews are open to any authenticated
    user; private crews return 404 for non-members (raises CrewNotFound).
    """
    supabase = get_supabase_admin()

    # 1. Confirm crew exists and get is_public.
    crew_res = await asyncio.to_thread(
        lambda: supabase.table("crews").select("is_public").eq("id", crew_id).limit(1).execute()
    )
    if not crew_res.data:
        raise CrewNotFound()
    is_public = crew_res.data[0]["is_public"]

    # 2. Visibility gate (reuse member list we'll also need for progress calc).
    members_res = await asyncio.to_thread(
        lambda: supabase.table("crew_members").select("user_id").eq("crew_id", crew_id).execute()
    )
    member_ids = [r["user_id"] for r in members_res.data]
    if not is_public and caller_id not in member_ids:
        raise CrewNotFound()

    # 3. Fetch the current (non-ended) challenge.
    now_utc = datetime.now(timezone.utc).isoformat()
    ch_res = await asyncio.to_thread(
        lambda: supabase.table("crew_challenges")
        .select("*")
        .eq("crew_id", crew_id)
        .gt("ends_at", now_utc)
        .order("ends_at", desc=True)
        .limit(1)
        .execute()
    )
    if not ch_res.data:
        return None
    ch = ch_res.data[0]

    # 4. Calculate progress: runs within challenge period for all members.
    if member_ids:
        runs_res = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .select("distance_km")
            .in_("user_id", member_ids)
            .gte("ran_at", ch["starts_at"])
            .lte("ran_at", ch["ends_at"])
            .execute()
        )
        achieved_km = round(sum(r["distance_km"] for r in runs_res.data), 2)
    else:
        achieved_km = 0.0

    goal_km: float = ch["goal_km"]
    progress_pct = round(min(achieved_km / goal_km * 100, 100.0), 1)
    now = datetime.now(timezone.utc)

    return ChallengeResponse(
        **ch,
        achieved_km=achieved_km,
        progress_pct=progress_pct,
        is_completed=achieved_km >= goal_km,
        is_active=_parse_ts(ch["starts_at"]) <= now <= _parse_ts(ch["ends_at"]),
    )


async def update_crew(crew_id: str, caller_id: str, req: CrewUpdate) -> CrewResponse:
    """Partially update a crew (owner only). Only non-None fields are written.

    Protected fields (owner_id, id, created_at) are never touched regardless of
    what the client sends — they are simply not present in CrewUpdate.
    """
    supabase = get_supabase_admin()

    res = await asyncio.to_thread(
        lambda: supabase.table("crews").select("*").eq("id", crew_id).limit(1).execute()
    )
    if not res.data:
        raise CrewNotFound()
    crew = res.data[0]
    if crew["owner_id"] != caller_id:
        raise NotOwner()

    # mode='json' serialises enums (e.g. CrewLevel) to their string values.
    data = req.model_dump(mode="json", exclude_none=True)
    if not data:
        # Nothing to change — return current state.
        counts = await _member_counts([crew_id])
        return await _one_response(crew, counts.get(crew_id, 0))

    updated = await asyncio.to_thread(
        lambda: supabase.table("crews").update(data).eq("id", crew_id).execute()
    )
    counts = await _member_counts([crew_id])
    logger.info("Crew %s updated by owner %s: %s", crew_id, caller_id, list(data.keys()))
    return await _one_response(updated.data[0], counts.get(crew_id, 0))


async def kick_member(crew_id: str, caller_id: str, target_id: str) -> None:
    """Remove a member from a crew (owner only).

    Raises:
        CrewNotFound      — crew does not exist.
        NotOwner          — caller is not the owner.
        OwnerCannotKickSelf — owner tried to kick themselves.
        NotAMember        — target is not currently a member.
    """
    supabase = get_supabase_admin()

    res = await asyncio.to_thread(
        lambda: supabase.table("crews").select("owner_id").eq("id", crew_id).limit(1).execute()
    )
    if not res.data:
        raise CrewNotFound()
    if res.data[0]["owner_id"] != caller_id:
        raise NotOwner()
    if target_id == caller_id:
        raise OwnerCannotKickSelf()
    if not await _is_member(crew_id, target_id):
        raise NotAMember()

    await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .delete()
        .eq("crew_id", crew_id)
        .eq("user_id", target_id)
        .execute()
    )
    logger.info("User %s kicked from crew %s by owner %s.", target_id, crew_id, caller_id)


async def delete_crew(crew_id: str, caller_id: str) -> None:
    """Delete a crew (owner only). Memberships are removed via ON DELETE CASCADE."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crews")
        .select("owner_id")
        .eq("id", crew_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise CrewNotFound()
    if res.data[0]["owner_id"] != caller_id:
        raise NotOwner()

    await asyncio.to_thread(
        lambda: supabase.table("crews").delete().eq("id", crew_id).execute()
    )
    logger.info("Crew %s deleted by owner %s.", crew_id, caller_id)
