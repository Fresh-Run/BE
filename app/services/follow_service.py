"""Follow service: user-to-user follows, follower/following lists, public profiles.

Counts are computed in real time via PostgREST's Content-Range count (rows are
not fetched), so follower counts stay correct without denormalized counters.
"""

from __future__ import annotations

import asyncio
import logging

from postgrest.exceptions import APIError

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import FollowUserItem, PublicProfileResponse
from app.services import notification_service, profile_service, run_service

logger = logging.getLogger(__name__)

_UNIQUE_VIOLATION = "23505"  # already following (idempotent double-tap)
_CHECK_VIOLATION = "23514"  # follows_no_self (DB backstop for self-follow)

_MAX_PAGE = 100


class UserNotFound(Exception):
    """The target user has no profile (treated the same as nonexistent)."""


class SelfFollowNotAllowed(Exception):
    """A user tried to follow themself."""


async def _ensure_user_exists(user_id: str) -> None:
    """Raise UserNotFound unless the user has a profile.

    The follows FK points at auth.users, but users without a profile are not
    followable — they can't be rendered in any list.
    """
    if await profile_service.get_profile(user_id) is None:
        raise UserNotFound()


async def follow_user(target_id: str, follower_id: str) -> None:
    """Follow another user. Idempotent: re-following is silently ignored.

    Fires a best-effort 'user_followed' notification only on a genuinely new
    follow (not on double-taps).
    """
    if target_id == follower_id:
        raise SelfFollowNotAllowed()
    await _ensure_user_exists(target_id)

    supabase = get_supabase_admin()
    followed_new = True
    try:
        await asyncio.to_thread(
            lambda: supabase.table("follows")
            .insert({"follower_id": follower_id, "following_id": target_id})
            .execute()
        )
    except APIError as exc:
        if exc.code == _UNIQUE_VIOLATION:  # already following, that's fine
            followed_new = False
        elif exc.code == _CHECK_VIOLATION:
            raise SelfFollowNotAllowed() from exc
        else:
            raise

    if followed_new:
        try:
            await notification_service.create_notification(
                recipient_id=target_id,
                actor_id=follower_id,
                type="user_followed",
                target_id=follower_id,
                target_type="user",
            )
        except Exception:  # noqa: BLE001
            logger.warning("user_followed 알림 생성 실패", exc_info=True)


async def unfollow_user(target_id: str, follower_id: str) -> None:
    """Unfollow a user. Idempotent: unfollowing a non-followed user is a no-op."""
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("follows")
        .delete()
        .eq("follower_id", follower_id)
        .eq("following_id", target_id)
        .execute()
    )


async def _follow_count(column: str, user_id: str) -> int:
    """Count follows rows where `column` = user_id.

    count="exact" reads the total from Content-Range, so limit(1) keeps the
    payload tiny while the count still covers all matching rows.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("follows")
        .select("follower_id", count="exact")
        .eq(column, user_id)
        .limit(1)
        .execute()
    )
    return res.count or 0


async def _follows(follower_id: str, following_id: str) -> bool:
    """Return True if follower_id follows following_id (one point query)."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("follows")
        .select("follower_id")
        .eq("follower_id", follower_id)
        .eq("following_id", following_id)
        .limit(1)
        .execute()
    )
    return bool(res.data)


async def _following_set(viewer_id: str, user_ids: list[str]) -> set[str]:
    """Return the subset of user_ids that viewer_id follows (one IN query)."""
    if not user_ids:
        return set()
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("follows")
        .select("following_id")
        .eq("follower_id", viewer_id)
        .in_("following_id", user_ids)
        .execute()
    )
    return {row["following_id"] for row in res.data}


async def _list_follow_users(
    target_id: str,
    viewer_id: str,
    *,
    key_col: str,
    other_col: str,
    limit: int,
    offset: int,
) -> list[FollowUserItem]:
    """Shared list query: rows where key_col = target_id, newest first.

    Each item carries is_following (viewer → listed user) so the frontend can
    render follow buttons inside the list without extra requests.
    """
    await _ensure_user_exists(target_id)
    limit = max(1, min(limit, _MAX_PAGE))
    offset = max(0, offset)

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("follows")
        .select(f"{other_col}, created_at")
        .eq(key_col, target_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data
    if not rows:
        return []

    ids = [row[other_col] for row in rows]
    briefs, following = await asyncio.gather(
        profile_service.get_profile_briefs(ids),
        _following_set(viewer_id, ids),
    )
    return [
        FollowUserItem(
            user_id=row[other_col],
            nickname=briefs.get(row[other_col], {}).get("nickname"),
            avatar_url=briefs.get(row[other_col], {}).get("avatar_url"),
            followed_at=row["created_at"],
            is_following=row[other_col] in following,
        )
        for row in rows
    ]


async def list_followers(
    target_id: str, viewer_id: str, limit: int = 20, offset: int = 0
) -> list[FollowUserItem]:
    """Users who follow target_id, newest first."""
    return await _list_follow_users(
        target_id,
        viewer_id,
        key_col="following_id",
        other_col="follower_id",
        limit=limit,
        offset=offset,
    )


async def list_following(
    target_id: str, viewer_id: str, limit: int = 20, offset: int = 0
) -> list[FollowUserItem]:
    """Users whom target_id follows, newest first."""
    return await _list_follow_users(
        target_id,
        viewer_id,
        key_col="follower_id",
        other_col="following_id",
        limit=limit,
        offset=offset,
    )


async def get_public_profile(target_id: str, viewer_id: str) -> PublicProfileResponse:
    """Another user's public profile with follow stats. Never exposes email.

    비공개 계정을 볼 권한 없으면 잠금 응답(locked=true) — 닉네임·아바타만,
    카운트·bio 미노출. 존재 은닉은 안 함(팔로우 요청하려면 프로필 필요 —
    차단은 v3에서 404 은닉으로 별도).
    """
    profile = await profile_service.get_profile(target_id)
    if profile is None:
        raise UserNotFound()

    if not await profile_service.can_see_user(target_id, viewer_id):
        is_following, is_followed_by = await asyncio.gather(
            _follows(viewer_id, target_id), _follows(target_id, viewer_id),
        )
        return PublicProfileResponse(
            user_id=profile.user_id, nickname=profile.nickname,
            avatar_url=profile.avatar_url, bio=None, tier=profile.tier,
            created_at=profile.created_at, follower_count=0, following_count=0,
            is_following=is_following, is_followed_by=is_followed_by,
            public_run_count=0, visibility=profile.visibility, locked=True,
        )

    (follower_count, following_count, is_following, is_followed_by,
     pub_run_count) = await asyncio.gather(
        _follow_count("following_id", target_id),
        _follow_count("follower_id", target_id),
        _follows(viewer_id, target_id),
        _follows(target_id, viewer_id),
        run_service.public_run_count(target_id),
    )
    return PublicProfileResponse(
        user_id=profile.user_id,
        nickname=profile.nickname,
        avatar_url=profile.avatar_url,
        bio=profile.bio,
        tier=profile.tier,
        created_at=profile.created_at,
        follower_count=follower_count,
        following_count=following_count,
        is_following=is_following,
        is_followed_by=is_followed_by,
        public_run_count=pub_run_count,
        visibility=profile.visibility,
        locked=False,
    )
