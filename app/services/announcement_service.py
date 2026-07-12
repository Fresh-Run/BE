"""Crew announcements + attendance RSVP.

Permissions reuse crew_service.ensure_member / ensure_manager (owner·admin
writes today; widen there when a manager role lands). Tallies and rosters
always reflect current members only — departing members' votes are removed
via remove_member_rsvps (called from leave/kick).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import (
    AnnouncementCreate,
    AnnouncementDetailResponse,
    AnnouncementResponse,
    AnnouncementUpdate,
    RsvpMember,
    RsvpTally,
)
from app.services import chat_service, crew_service, notification_service, profile_service

logger = logging.getLogger(__name__)

_CHECK_VIOLATION = "23514"


class AnnouncementNotFound(Exception):
    """No such announcement in this crew."""


class InvalidAnnouncement(Exception):
    """A DB CHECK rejected the fields (half coords, 마감>run_at, ...)."""


class RsvpClosed(Exception):
    """The vote deadline (coalesce(rsvp_closes_at, run_at)) has passed."""


class RsvpNotAvailable(Exception):
    """The announcement has no run_at, so there is nothing to RSVP to."""


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _rsvp_open(row: dict) -> bool:
    """True when the announcement has a run and its deadline hasn't passed."""
    if not row.get("run_at"):
        return False
    deadline = _parse_ts(row.get("rsvp_closes_at") or row["run_at"])
    return datetime.now(timezone.utc) < deadline


async def _get_announcement(crew_id: str, announcement_id: str) -> dict:
    """Fetch one announcement scoped to the crew, or raise AnnouncementNotFound."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_announcements")
        .select("*")
        .eq("id", announcement_id)
        .eq("crew_id", crew_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise AnnouncementNotFound()
    return res.data[0]


async def _tallies(announcement_ids: list[str], crew_id: str) -> dict[str, RsvpTally]:
    """Batch {announcement_id: RsvpTally} (one IN query, counted in Python).

    현재 크루원의 표만 집계 — 탈퇴/강퇴자의 RSVP는 _cleanup_member_rsvps가
    best-effort라 잔존할 수 있으므로 crew_members 교집합으로 필터한다(L6).
    """
    if not announcement_ids:
        return {}
    supabase = get_supabase_admin()
    rsvps, members = await asyncio.gather(
        asyncio.to_thread(
            lambda: supabase.table("crew_announcement_rsvps")
            .select("announcement_id, status, user_id")
            .in_("announcement_id", announcement_ids)
            .execute()
        ),
        asyncio.to_thread(
            lambda: supabase.table("crew_members")
            .select("user_id")
            .eq("crew_id", crew_id)
            .execute()
        ),
    )
    member_ids = {m["user_id"] for m in members.data}
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rsvps.data:
        if row["user_id"] in member_ids:  # 탈퇴자 표 제외
            counts[row["announcement_id"]][row["status"]] += 1
    return {
        aid: RsvpTally(
            going=c["going"], not_going=c["not_going"], maybe=c["maybe"]
        )
        for aid, c in counts.items()
    }


async def _my_rsvps(announcement_ids: list[str], user_id: str) -> dict[str, str]:
    """Batch {announcement_id: my status} for the caller."""
    if not announcement_ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_announcement_rsvps")
        .select("announcement_id, status")
        .eq("user_id", user_id)
        .in_("announcement_id", announcement_ids)
        .execute()
    )
    return {row["announcement_id"]: row["status"] for row in res.data}


def _to_response(
    row: dict,
    tally: RsvpTally,
    my_rsvp: str | None,
    author_brief: dict | None,
) -> AnnouncementResponse:
    author_brief = author_brief or {}
    return AnnouncementResponse(
        **row,
        author_nickname=author_brief.get("nickname"),
        author_avatar_url=author_brief.get("avatar_url"),
        rsvp_open=_rsvp_open(row),
        rsvp=tally,
        my_rsvp=my_rsvp,
    )


async def _notify_members(crew_id: str, author_id: str, announcement_id: str) -> None:
    """Best-effort broadcast to all crew members (author auto-skipped)."""
    try:
        supabase = get_supabase_admin()
        res = await asyncio.to_thread(
            lambda: supabase.table("crew_members")
            .select("user_id")
            .eq("crew_id", crew_id)
            .execute()
        )
        await asyncio.gather(*[
            notification_service.create_notification(
                recipient_id=row["user_id"],
                actor_id=author_id,
                type="crew_announcement",
                target_id=announcement_id,
                target_type="announcement",
                payload={"crew_id": crew_id},  # 공지가 속한 크루 딥링크용
            )
            for row in res.data
        ])
    except Exception:  # noqa: BLE001
        logger.warning("crew_announcement 알림 브로드캐스트 실패", exc_info=True)


async def create_announcement(
    crew_id: str, caller_id: str, req: AnnouncementCreate
) -> AnnouncementResponse:
    """Create an announcement (owner only) and notify all members once."""
    await crew_service.ensure_manager(crew_id, caller_id)

    record = {
        "crew_id": crew_id,
        "author_id": caller_id,
        **req.model_dump(exclude_none=True),
    }
    supabase = get_supabase_admin()
    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("crew_announcements").insert(record).execute()
        )
    except APIError as exc:
        if exc.code == _CHECK_VIOLATION:
            raise InvalidAnnouncement() from exc
        raise
    row = res.data[0]

    await _notify_members(crew_id, caller_id, row["id"])

    # 크루 채팅에 시스템 메시지 유입 (v1.5 단일 훅) — best-effort(실패해도 공지 성공).
    # sender_id=작성자(운영진 표기), content="announcement" 렌더 키, payload에 딥링크.
    try:
        await chat_service.post_system(
            crew_id, caller_id, "announcement",
            {"announcement_id": row["id"], "title": row.get("title")},
        )
    except Exception:  # noqa: BLE001
        logger.warning("공지 시스템 메시지 삽입 실패 — 공지는 성공 (crew=%s)",
                       crew_id, exc_info=True)

    briefs = await profile_service.get_profile_briefs([caller_id])
    return _to_response(row, RsvpTally(), None, briefs.get(caller_id))


async def list_announcements(
    crew_id: str, caller_id: str, limit: int = 20, offset: int = 0
) -> list[AnnouncementResponse]:
    """Announcements newest-first with tallies + my_rsvp (members only)."""
    await crew_service.ensure_member(crew_id, caller_id)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_announcements")
        .select("*")
        .eq("crew_id", crew_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data
    if not rows:
        return []

    ann_ids = [r["id"] for r in rows]
    tallies, mine, nicknames = await asyncio.gather(
        _tallies(ann_ids, crew_id),
        _my_rsvps(ann_ids, caller_id),
        profile_service.get_profile_briefs([r.get("author_id") for r in rows]),
    )
    return [
        _to_response(
            row,
            tallies.get(row["id"], RsvpTally()),
            mine.get(row["id"]),
            nicknames.get(row.get("author_id")),
        )
        for row in rows
    ]


async def get_announcement(
    crew_id: str, caller_id: str, announcement_id: str
) -> AnnouncementDetailResponse:
    """Announcement detail with the attendee roster (members only)."""
    await crew_service.ensure_member(crew_id, caller_id)
    row = await _get_announcement(crew_id, announcement_id)

    supabase = get_supabase_admin()
    going_res, tallies, mine, nicknames = await asyncio.gather(
        asyncio.to_thread(
            lambda: supabase.table("crew_announcement_rsvps")
            .select("user_id")
            .eq("announcement_id", announcement_id)
            .eq("status", "going")
            .order("updated_at")
            .execute()
        ),
        _tallies([announcement_id], crew_id),
        _my_rsvps([announcement_id], caller_id),
        profile_service.get_profile_briefs([row.get("author_id")]),
    )
    going_ids = [r["user_id"] for r in going_res.data]
    going_nicknames = await profile_service.get_nicknames(going_ids)

    base = _to_response(
        row,
        tallies.get(announcement_id, RsvpTally()),
        mine.get(announcement_id),
        nicknames.get(row.get("author_id")),
    )
    return AnnouncementDetailResponse(
        **base.model_dump(),
        going_members=[
            RsvpMember(user_id=uid, nickname=going_nicknames.get(uid))
            for uid in going_ids
        ],
    )


async def update_announcement(
    crew_id: str, caller_id: str, announcement_id: str, req: AnnouncementUpdate
) -> AnnouncementResponse:
    """Partial update (owner only). Deliberately sends no notification."""
    await crew_service.ensure_manager(crew_id, caller_id)
    row = await _get_announcement(crew_id, announcement_id)

    data = req.model_dump(exclude_unset=True)
    if data:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        supabase = get_supabase_admin()
        try:
            res = await asyncio.to_thread(
                lambda: supabase.table("crew_announcements")
                .update(data)
                .eq("id", announcement_id)
                .execute()
            )
        except APIError as exc:
            if exc.code == _CHECK_VIOLATION:
                raise InvalidAnnouncement() from exc
            raise
        row = res.data[0]

    tallies, mine, nicknames = await asyncio.gather(
        _tallies([announcement_id], crew_id),
        _my_rsvps([announcement_id], caller_id),
        profile_service.get_profile_briefs([row.get("author_id")]),
    )
    return _to_response(
        row,
        tallies.get(announcement_id, RsvpTally()),
        mine.get(announcement_id),
        nicknames.get(row.get("author_id")),
    )


async def delete_announcement(
    crew_id: str, caller_id: str, announcement_id: str
) -> None:
    """Delete an announcement (owner only). RSVPs go via ON DELETE CASCADE."""
    await crew_service.ensure_manager(crew_id, caller_id)
    await _get_announcement(crew_id, announcement_id)  # 404 if missing

    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("crew_announcements")
        .delete()
        .eq("id", announcement_id)
        .execute()
    )
    # 이 공지를 가리키던 알림 정리 (M10 — 유령 알림·unread_count 방지)
    try:
        await notification_service.delete_for_target("announcement", announcement_id)
    except Exception:  # noqa: BLE001
        logger.warning("공지 삭제 후 알림 정리 실패 (ann=%s)", announcement_id, exc_info=True)


async def rsvp(
    crew_id: str, caller_id: str, announcement_id: str, status: str
) -> None:
    """Cast/overwrite the caller's vote (members only, one vote per member)."""
    await crew_service.ensure_member(crew_id, caller_id)
    row = await _get_announcement(crew_id, announcement_id)

    if not row.get("run_at"):
        raise RsvpNotAvailable()
    if not _rsvp_open(row):
        raise RsvpClosed()

    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("crew_announcement_rsvps")
        .upsert({
            "announcement_id": announcement_id,
            "user_id": caller_id,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .execute()
    )


async def remove_member_rsvps(crew_id: str, user_id: str) -> None:
    """Drop all of a user's votes in one crew (called on leave/kick)."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_announcements")
        .select("id")
        .eq("crew_id", crew_id)
        .execute()
    )
    ann_ids = [r["id"] for r in res.data]
    if not ann_ids:
        return
    await asyncio.to_thread(
        lambda: supabase.table("crew_announcement_rsvps")
        .delete()
        .eq("user_id", user_id)
        .in_("announcement_id", ann_ids)
        .execute()
    )
