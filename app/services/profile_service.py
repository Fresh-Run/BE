"""User profile persistence + nickname lookups.

Profiles are 1:1 with auth.users (profiles.user_id = auth user id). Data access
uses the service_role client; user_id always comes from the validated token.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.core.config import settings
from app.core.supabase_client import get_supabase_admin
from app.models.schemas import (
    AvatarUploadUrlResponse,
    ProfileResponse,
    ProfileUpdate,
    SettingsPatch,
    UserSettings,
)

logger = logging.getLogger(__name__)

# Postgres unique-violation error code (raised when a nickname is taken).
_UNIQUE_VIOLATION = "23505"

# 데모 계정 — 시드 규칙상 삭제 금지 (scripts/seed_demo_data.py와 동일 목록).
_DEMO_EMAILS = frozenset(
    {"test1@freshrun.com", "test2@freshrun.com"}
    | {f"demo{i}@freshrun.com" for i in range(1, 6)}
)


class NicknameTaken(Exception):
    """The requested nickname is already used by another profile."""


class ProfileNotFound(Exception):
    """Settings write requires an existing profile row."""


class DemoAccountError(Exception):
    """데모 계정은 탈퇴할 수 없다 (시드 보호)."""


class CrewOwnerError(Exception):
    """다른 멤버가 있는 크루의 소유자는 위임/삭제 후에만 탈퇴할 수 있다."""

    def __init__(self, crew_ids: list[str]):
        super().__init__("owner of crews that still have members")
        self.crew_ids = crew_ids


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
    # 신체 정보 4종 — 본인 전용(ProfileResponse에만 노출), 보낸 것만 갱신
    for body_field in ("birth_year", "weight_kg", "height_cm", "gender"):
        value = getattr(req, body_field)
        if value is not None:
            record[body_field] = value

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


_AVATAR_BUCKET = "avatars"
_AVATAR_MAX_BYTES = 5 * 1024 * 1024
_AVATAR_TYPES = ["image/jpeg", "image/png", "image/webp"]


async def create_avatar_upload_url(user_id: str) -> AvatarUploadUrlResponse:
    """아바타 업로드용 signed URL 발급 — 3단계 흐름의 1단계.

    경로는 유저당 고정({user_id}) — 재업로드가 항상 덮어써서 옛 파일이 남지
    않는다. signed upload는 기존 객체에 409를 내므로 발급 전에 지운다.
    크기(5MB)·타입(jpeg/png/webp) 제한은 avatars 버킷 설정이 업로드 시점에
    강제한다 (public 버킷 — 읽기는 공개, 쓰기는 이 signed URL로만).
    """
    supabase = get_supabase_admin()

    def _issue() -> dict:
        storage = supabase.storage.from_(_AVATAR_BUCKET)
        try:
            storage.remove([user_id])  # 고정 경로 덮어쓰기 — 없어도 무해
        except Exception:  # noqa: BLE001
            pass
        return storage.create_signed_upload_url(user_id)

    res = await asyncio.to_thread(_issue)
    upload_url = res.get("signed_url") or res.get("signedUrl") or res.get("signedURL")
    if not upload_url:
        raise RuntimeError("Storage did not return a signed upload URL.")
    public_url = (
        f"{settings.supabase_url}/storage/v1/object/public/{_AVATAR_BUCKET}/{user_id}"
    )
    logger.info("아바타 업로드 URL 발급 (user=%s)", user_id)
    return AvatarUploadUrlResponse(
        upload_url=upload_url,
        public_url=public_url,
        max_bytes=_AVATAR_MAX_BYTES,
        allowed_types=_AVATAR_TYPES,
    )


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


async def delete_account(user_id: str, email: str | None) -> None:
    """회원 탈퇴 — auth.users 삭제가 커밋 지점, public 데이터는 FK cascade로
    원자적 소멸 (전 테이블 실증: docs/ACCOUNT_DELETION_DESIGN.md §1·§5).

    다른 멤버가 있는 소유 크루가 있으면 CrewOwnerError(위임/삭제 유도),
    본인뿐인 소유 크루는 자동 삭제. 아바타는 FK가 없어 명시 삭제(best-effort).
    """
    from app.services import crew_service  # 순환 import 방지 (crew→profile 역방향)

    if email and email.lower() in _DEMO_EMAILS:
        raise DemoAccountError()

    supabase = get_supabase_admin()

    owned = await asyncio.to_thread(
        lambda: supabase.table("crews").select("id").eq("owner_id", user_id).execute()
    )
    blocking: list[str] = []
    solo: list[str] = []
    for row in owned.data or []:
        crew_id = row["id"]
        members = await asyncio.to_thread(
            lambda cid=crew_id: supabase.table("crew_members")
            .select("user_id")
            .eq("crew_id", cid)
            .neq("user_id", user_id)
            .limit(1)
            .execute()
        )
        (blocking if members.data else solo).append(crew_id)
    if blocking:
        raise CrewOwnerError(blocking)

    for crew_id in solo:
        await crew_service.delete_crew(crew_id, caller_id=user_id)

    try:
        await asyncio.to_thread(
            lambda: supabase.storage.from_(_AVATAR_BUCKET).remove([user_id])
        )
    except Exception:  # noqa: BLE001
        logger.warning("탈퇴 중 아바타 삭제 실패 — 진행 (user=%s)", user_id, exc_info=True)

    await asyncio.to_thread(lambda: supabase.auth.admin.delete_user(user_id))
    logger.info("계정 삭제 완료 (user=%s)", user_id)
