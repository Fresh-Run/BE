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


class NicknameRequired(Exception):
    """최초 프로필 생성 시 nickname 필수 (부분 PATCH는 생략 허용, 생성은 아님)."""


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

    부분 PATCH 시맨틱: nickname 생략=유지. 단 프로필 최초 생성(행 없음)은
    nickname 필수 — 없으면 NicknameRequired(422). 존재 여부로 insert/update를
    갈라 upsert의 NOT NULL INSERT 실패를 피한다.
    """
    supabase = get_supabase_admin()
    existing = await asyncio.to_thread(
        lambda: supabase.table("profiles").select("user_id")
        .eq("user_id", user_id).limit(1).execute()
    )
    is_new = not existing.data
    if is_new and req.nickname is None:
        raise NicknameRequired()

    record: dict = {
        "user_id": user_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if req.nickname is not None:   # 생략=유지 (부분 PATCH)
        record["nickname"] = req.nickname
    # 명시 null(avatar_url 키를 보냈는데 값이 null) = 삭제 — 미전송과 구분은
    # model_fields_set으로 (PATCH 명시 null 시맨틱 선례, 다른 필드 확대는 수요 시)
    avatar_delete = "avatar_url" in req.model_fields_set and req.avatar_url is None
    if req.avatar_url is not None:
        record["avatar_url"] = req.avatar_url
    elif avatar_delete:
        record["avatar_url"] = None
    if req.bio is not None:
        record["bio"] = req.bio
    # 신체 정보 4종 — 본인 전용(ProfileResponse에만 노출), 보낸 것만 갱신
    for body_field in ("birth_year", "weight_kg", "height_cm", "gender"):
        value = getattr(req, body_field)
        if value is not None:
            record[body_field] = value
    if req.visibility is not None:   # 계정 공개범위 (v1)
        record["visibility"] = req.visibility
    if req.follow_approval is not None:   # 팔로우 승인제 (v2)
        record["follow_approval"] = req.follow_approval

    try:
        if is_new:   # 최초 생성 — nickname 보장됨(위 분기), insert
            res = await asyncio.to_thread(
                lambda: supabase.table("profiles").insert(record).execute()
            )
        else:        # 갱신 — 보낸 필드만 update(생략된 nickname 보존)
            res = await asyncio.to_thread(
                lambda: supabase.table("profiles").update(record)
                .eq("user_id", user_id).execute()
            )
    except APIError as exc:
        if exc.code == _UNIQUE_VIOLATION:
            raise NicknameTaken() from exc
        raise

    if avatar_delete:  # Storage 파일도 정리 — best-effort (run 사진 교체와 동일 패턴)
        try:
            await asyncio.to_thread(
                lambda: supabase.storage.from_(_AVATAR_BUCKET).remove([user_id])
            )
        except Exception:  # noqa: BLE001
            logger.warning("아바타 삭제 중 Storage 정리 실패 — 진행 (user=%s)",
                           user_id, exc_info=True)

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

    # 러닝 사진도 Storage에 FK가 없어 명시 삭제 (best-effort — 아바타와 동일 축).
    # 감사 L-1: 업로드 후 PATCH 전 이탈한 고아 파일은 runs.photos에 없으므로,
    # run별 slot×ext 전조합(9경로)을 무조건 remove — 리스팅 없이 고아까지 커버
    # (없는 경로 remove는 무해).
    try:
        rows = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .select("id, photos")
            .eq("user_id", user_id)
            .execute()
        )
        paths: set[str] = set()
        for r in rows.data:
            paths.update(r.get("photos") or [])
            for slot in (1, 2, 3):
                for ext in ("jpg", "png", "webp"):
                    paths.add(f"{r['id']}/{slot}.{ext}")
        if paths:
            await asyncio.to_thread(
                lambda: supabase.storage.from_("run-photos").remove(sorted(paths))
            )
    except Exception:  # noqa: BLE001
        logger.warning("탈퇴 중 러닝 사진 삭제 실패 — 진행 (user=%s)", user_id,
                       exc_info=True)

    await asyncio.to_thread(lambda: supabase.auth.admin.delete_user(user_id))
    logger.info("계정 삭제 완료 (user=%s)", user_id)


# ── 계정 가시성 게이트 (docs/PRIVATE_PROFILE_DESIGN.md v1) ────────────────────
# profile visibility 축. run visibility와 AND 합성(_can_see_run이 선행 호출).
# 결정 A: followers/private 계정도 팔로우·크루 공존 시 노출(크루 가입=노출 동의).
# 차단(v3)·승인제(v2)는 이후 사이클에서 이 게이트에 합성.


async def _follows_or_crewmate(viewer_id: str, owner_id: str) -> bool:
    """viewer가 owner를 팔로우 중이거나 같은 크루 소속인가 (_can_see_run과 동일 관계)."""
    supabase = get_supabase_admin()
    follow = await asyncio.to_thread(
        lambda: supabase.table("follows")
        .select("follower_id")
        .eq("follower_id", viewer_id).eq("following_id", owner_id)
        .limit(1).execute()
    )
    if follow.data:
        return True
    my = await asyncio.to_thread(
        lambda: supabase.table("crew_members").select("crew_id")
        .eq("user_id", viewer_id).execute()
    )
    crew_ids = [r["crew_id"] for r in my.data]
    if not crew_ids:
        return False
    shared = await asyncio.to_thread(
        lambda: supabase.table("crew_members").select("crew_id")
        .eq("user_id", owner_id).in_("crew_id", crew_ids).limit(1).execute()
    )
    return bool(shared.data)


async def is_blocked_either(a_id: str, b_id: str) -> bool:
    """a·b 사이에 어느 방향이든 차단이 있는가 (양방향 노출 차단, v3)."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("blocks").select("blocker_id")
        .or_(f"and(blocker_id.eq.{a_id},blocked_id.eq.{b_id}),"
             f"and(blocker_id.eq.{b_id},blocked_id.eq.{a_id})")
        .limit(1).execute()
    )
    return bool(res.data)


async def can_see_user(owner_id: str, viewer_id: str) -> bool:
    """viewer가 owner의 계정(프로필·러닝)에 접근 가능한가.

    차단 최우선(양방향 → False, 존재 은닉) → public 누구나 →
    followers·private는 팔로우 or 크루 공존. 본인은 항상.
    """
    if owner_id == viewer_id:
        return True
    if await is_blocked_either(owner_id, viewer_id):   # v3: 차단이 크루 공존보다 위
        return False
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("profiles").select("visibility")
        .eq("user_id", owner_id).limit(1).execute()
    )
    vis = (res.data[0]["visibility"] if res.data else "public")
    if vis == "public":
        return True
    return await _follows_or_crewmate(viewer_id, owner_id)


async def visible_owners(viewer_id: str, owner_ids: list[str]) -> set[str]:
    """{viewer가 볼 수 있는 owner_id} — 배치(목록·검색용, N+1 방지).

    차단(양방향)은 먼저 제외 → public 즉시 통과 → followers/private는 팔로잉·크루원.
    """
    ids = list({o for o in owner_ids if o})
    if not ids:
        return set()
    supabase = get_supabase_admin()
    # 차단 양방향 제외 (v3): viewer가 차단했거나 viewer를 차단한 owner
    blk = await asyncio.to_thread(
        lambda: supabase.table("blocks").select("blocker_id, blocked_id")
        .or_(f"and(blocker_id.eq.{viewer_id},blocked_id.in.({','.join(ids)})),"
             f"and(blocked_id.eq.{viewer_id},blocker_id.in.({','.join(ids)}))")
        .execute()
    )
    blocked_ids = {r["blocked_id"] for r in blk.data} | {r["blocker_id"] for r in blk.data}
    ids = [o for o in ids if o not in blocked_ids or o == viewer_id]
    if not ids:
        return set()
    profs = await asyncio.to_thread(
        lambda: supabase.table("profiles").select("user_id, visibility")
        .in_("user_id", ids).execute()
    )
    vis_map = {r["user_id"]: r["visibility"] for r in profs.data}
    visible = {viewer_id} & set(ids)
    restricted = []
    for oid in ids:
        if vis_map.get(oid, "public") == "public":
            visible.add(oid)
        elif oid != viewer_id:
            restricted.append(oid)
    if not restricted:
        return visible
    # 팔로잉 교집합
    fol = await asyncio.to_thread(
        lambda: supabase.table("follows").select("following_id")
        .eq("follower_id", viewer_id).in_("following_id", restricted).execute()
    )
    visible |= {r["following_id"] for r in fol.data}
    remaining = [o for o in restricted if o not in visible]
    if remaining:
        my = await asyncio.to_thread(
            lambda: supabase.table("crew_members").select("crew_id")
            .eq("user_id", viewer_id).execute()
        )
        crew_ids = [r["crew_id"] for r in my.data]
        if crew_ids:
            mates = await asyncio.to_thread(
                lambda: supabase.table("crew_members").select("user_id")
                .in_("crew_id", crew_ids).in_("user_id", remaining).execute()
            )
            visible |= {r["user_id"] for r in mates.data}
    return visible


# ── 피드 설정 게이트 (docs/PRIVATE_PROFILE_DESIGN.md v1.5) ────────────────────


class FeedActionDisabled(Exception):
    """owner가 좋아요/댓글을 설정으로 껐다 — 403 구조화 (존재 은닉 아님:
    콘텐츠는 이미 가시성 게이트를 통과해 보이는 상태라 '받지 않음'을 알려도
    은닉 위반 아님). feature: 'likes' | 'comments'."""

    def __init__(self, feature: str):
        super().__init__(f"{feature} disabled by owner")
        self.feature = feature


async def feed_allows(owner_id: str, key: str) -> bool:
    """owner의 피드 설정 허용 여부 (key: allow_likes | allow_comments).

    프로필 없는 유저(설정 미저장)는 기본 True — get_settings가 기본값 머지.
    """
    settings_obj = await get_settings(owner_id)
    return getattr(settings_obj.feed, key)
