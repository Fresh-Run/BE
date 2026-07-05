"""User profile persistence + nickname lookups.

Profiles are 1:1 with auth.users (profiles.user_id = auth user id). Data access
uses the service_role client; user_id always comes from the validated token.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import (
    ProfileResponse,
    ProfileUpdate,
    SettingsPatch,
    UserSettings,
)

logger = logging.getLogger(__name__)

# Postgres unique-violation error code (raised when a nickname is taken).
_UNIQUE_VIOLATION = "23505"


class NicknameTaken(Exception):
    """The requested nickname is already used by another profile."""


class ProfileNotFound(Exception):
    """Settings write requires an existing profile row."""


async def get_profile(user_id: str) -> ProfileResponse | None:
    """Return the user's profile, or None if they haven't created one."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("profiles")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    return ProfileResponse(**res.data[0])


async def upsert_profile(user_id: str, req: ProfileUpdate) -> ProfileResponse:
    """Create or update the caller's profile (insert if missing, else update).

    Only the fields provided are written, so a nickname-only update won't wipe
    an existing avatar_url/bio. Raises NicknameTaken on a duplicate nickname.
    """
    record: dict = {
        "user_id": user_id,
        "nickname": req.nickname,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if req.avatar_url is not None:
        record["avatar_url"] = req.avatar_url
    if req.bio is not None:
        record["bio"] = req.bio

    supabase = get_supabase_admin()
    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("profiles").upsert(record).execute()
        )
    except APIError as exc:
        if exc.code == _UNIQUE_VIOLATION:
            raise NicknameTaken() from exc
        raise

    logger.info("Upserted profile for user %s.", user_id)
    return ProfileResponse(**res.data[0])


def _sanitize_settings(stored: dict) -> dict:
    """Drop keys no longer in the whitelist (two levels) so a shrunken
    whitelist can't break GET for users with stale stored keys."""
    clean: dict = {}
    for key, value in stored.items():
        if key not in UserSettings.model_fields:
            continue
        field = UserSettings.model_fields[key]
        if isinstance(value, dict) and hasattr(field.annotation, "model_fields"):
            clean[key] = {k: v for k, v in value.items()
                          if k in field.annotation.model_fields}
        else:
            clean[key] = value
    return clean


async def _stored_settings(user_id: str) -> dict | None:
    """Raw settings dict, or None when the user has no profile row."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("profiles")
        .select("settings")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    return res.data[0].get("settings") or {}


async def get_settings(user_id: str) -> UserSettings:
    """The caller's settings, defaults merged in (완전한 객체).

    Users without a profile row simply get the defaults — reads are safe.
    """
    stored = await _stored_settings(user_id)
    return UserSettings.model_validate(_sanitize_settings(stored or {}))


async def patch_settings(user_id: str, patch: SettingsPatch) -> UserSettings:
    """Deep-merge the provided keys into stored settings (idempotent).

    Storage stays sparse (only what the user changed), so server-side
    default changes apply to everyone who hasn't overridden them.
    Raises ProfileNotFound when the user has no profile row yet.
    """
    stored = await _stored_settings(user_id)
    if stored is None:
        raise ProfileNotFound()

    changes = patch.model_dump(exclude_unset=True, exclude_none=True)
    merged = dict(stored)
    for key, value in changes.items():
        if isinstance(value, dict):
            merged[key] = {**merged.get(key, {}), **value}
        else:
            merged[key] = value

    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("profiles")
        .update({"settings": merged})
        .eq("user_id", user_id)
        .execute()
    )
    return UserSettings.model_validate(_sanitize_settings(merged))


async def get_profile_briefs(user_ids: list[str | None]) -> dict[str, dict]:
    """Batch-resolve {user_id: {nickname, avatar_url}} (deduped, NULLs dropped).

    Generalization of get_nicknames for responses that also need the avatar
    (e.g. follower/following lists) — still one IN query for the whole set.
    """
    ids = list({uid for uid in user_ids if uid})
    if not ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("profiles")
        .select("user_id, nickname, avatar_url")
        .in_("user_id", ids)
        .execute()
    )
    return {row["user_id"]: row for row in res.data}


async def get_nicknames(user_ids: list[str | None]) -> dict[str, str]:
    """Batch-resolve {user_id: nickname} for the given ids (deduped, NULLs dropped).

    Used to attach owner/member nicknames to feed and crew responses without
    per-row joins (one query for the whole result set).
    """
    ids = list({uid for uid in user_ids if uid})
    if not ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("profiles")
        .select("user_id, nickname")
        .in_("user_id", ids)
        .execute()
    )
    return {row["user_id"]: row["nickname"] for row in res.data}
