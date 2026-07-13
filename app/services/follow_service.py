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


class FollowRequestPending(Exception):
    """승인제 계정에 이미 pending 요청이 있음 (멱등 — 409로 매핑)."""


class FollowRequestNotFound(Exception):
    """승인/거절할 pending 요청이 없음 (없거나 이미 처리됨)."""


async def _ensure_user_exists(user_id: str) -> None:
    """Raise UserNotFound unless the user has a profile.

    The follows FK points at auth.users, but users without a profile are not
    followable — they can't be rendered in any list.
    """
    if await profile_service.get_profile(user_id) is None:
        raise UserNotFound()


async def follow_user(target_id: str, follower_id: str) -> str:
    """Follow another user (승인제면 요청). Idempotent.

    반환: "followed"(즉시 팔로우/멱등) | "requested"(승인 대기 pending 생성).
    Fires a best-effort 'user_followed' notification only on a genuinely new follow.
    """
    if target_id == follower_id:
        raise SelfFollowNotAllowed()
    await _ensure_user_exists(target_id)
    # 차단 게이트 — 양방향 차단이면 존재 은닉(404). 승인제/비승인제 분기보다
    # 앞이라 pending 요청·follows 행·알림 어느 것도 생성되지 않는다(차단 우회 봉쇄).
    if await profile_service.is_blocked_either(target_id, follower_id):
        raise UserNotFound()

    supabase = get_supabase_admin()
    # 승인제 계정이면 즉시 팔로우 대신 pending 요청. 기존 팔로워는 이 경로를
    # 안 탄다 — 이미 follows에 있으면 approval 무관하게 관계 유지(소급 무영향).
    if await _needs_approval(target_id, follower_id):
        return await _create_follow_request(target_id, follower_id)  # "requested"

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
    return "followed"


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


async def remove_follower(follower_id: str, remover_id: str) -> None:
    """Remove `follower_id` from remover_id's followers (Instagram 'remove follower').

    unfollow_user와 **정반대 방향**의 엣지를 지운다: 여기서 지우는 행은
    (follower_id=follower_id, following_id=remover_id) — 상대가 나를 팔로우하는
    관계다(unfollow는 follower=me). 무알림(unfollow·block 관성). 차단(block)과
    구분 — 관계만 끊고 재팔로우는 막지 않는다.

    게이트 순서는 follow_user와 동형: self(400) → 존재(404) → 차단(404 은닉).
    멱등 — 이미 내 팔로워가 아니면 no-op(부수효과 0).
    """
    if follower_id == remover_id:
        raise SelfFollowNotAllowed()
    await _ensure_user_exists(follower_id)
    # 차단 게이트 — 양방향 차단이면 존재 은닉(404). follow_user와 동일하게 삭제보다
    # 앞이라 차단 관계에선 어떤 행도 건드리지 않는다(존재 은닉 우선).
    if await profile_service.is_blocked_either(follower_id, remover_id):
        raise UserNotFound()

    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("follows")
        .delete()
        .eq("follower_id", follower_id)      # 상대(제거 대상)가
        .eq("following_id", remover_id)      # 나를 팔로우하던 엣지
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

    명단 잠금(2026-07-13): 잠금 프로필은 **카운트는 진실이되 명단은 잠금**
    (인스타 비대칭 — 숫자 열고 리스트/콘텐츠 잠금). viewer가 target을 볼 수
    없으면 빈 목록(공개 프로필 러닝 탭 list_user_runs와 동일 선례).
    """
    await _ensure_user_exists(target_id)
    if target_id != viewer_id and not await profile_service.can_see_user(target_id, viewer_id):
        return []                                   # 잠금 → 명단 미노출(카운트는 프로필 응답에서 진실값)
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
    카운트·bio 미노출. 존재 은닉은 안 함(팔로우 요청하려면 프로필 필요).
    단 차단(v3)은 잠금과 달리 **404로 존재 은닉** — 양방향.
    """
    # 차단(양방향)은 존재 자체를 숨긴다 — 잠금(locked)보다 강함
    if target_id != viewer_id and await profile_service.is_blocked_either(
        target_id, viewer_id
    ):
        raise UserNotFound()

    profile = await profile_service.get_profile(target_id)
    if profile is None:
        raise UserNotFound()

    if not await profile_service.can_see_user(target_id, viewer_id):
        # 잠금이어도 **카운트는 진실값**(인스타 컨벤션 — 0은 프라이버시가 아니라
        # 오보). bio·러닝 목록·통계·피드는 잠금 유지, 리스트 엔드포인트도 잠금.
        # "숫자는 열되 명단은 잠금"이 이 계약의 요점.
        (follower_count, following_count, is_following, is_followed_by,
         pub_run_count) = await asyncio.gather(
            _follow_count("following_id", target_id),
            _follow_count("follower_id", target_id),
            _follows(viewer_id, target_id),
            _follows(target_id, viewer_id),
            run_service.public_run_count(target_id),
        )
        return PublicProfileResponse(
            user_id=profile.user_id, nickname=profile.nickname,
            avatar_url=profile.avatar_url, bio=None, tier=profile.tier,
            created_at=profile.created_at,
            follower_count=follower_count, following_count=following_count,
            is_following=is_following, is_followed_by=is_followed_by,
            public_run_count=pub_run_count, visibility=profile.visibility, locked=True,
        )

    (follower_count, following_count, is_following, is_followed_by,
     pub_run_count, flags) = await asyncio.gather(
        _follow_count("following_id", target_id),
        _follow_count("follower_id", target_id),
        _follows(viewer_id, target_id),
        _follows(target_id, viewer_id),
        run_service.public_run_count(target_id),
        profile_service.feed_flags_batch([target_id]),
    )
    f = flags.get(target_id, {})
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
        allow_likes=f.get("allow_likes", True),
        allow_comments=f.get("allow_comments", True),
    )


# ── 팔로우 승인제 (docs/PRIVATE_PROFILE_DESIGN.md v2) ─────────────────────────


async def _needs_approval(target_id: str, follower_id: str) -> bool:
    """target이 승인제이고 follower가 아직 팔로워가 아닐 때만 True.

    기존 팔로워는 approval 무관하게 관계 유지 — 소급 무영향(요청 경로 안 탐).
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("profiles").select("follow_approval")
        .eq("user_id", target_id).limit(1).execute()
    )
    if not (res.data and res.data[0].get("follow_approval")):
        return False
    return not await _follows(follower_id, target_id)


async def _create_follow_request(target_id: str, follower_id: str) -> str:
    """pending 요청 생성 (멱등). PK 충돌(23505)=이미 pending → 409 신호.

    거절됐던 행이면 status를 pending으로 되살린다(재신청 허용). 반환 "requested".
    """
    supabase = get_supabase_admin()
    try:
        await asyncio.to_thread(
            lambda: supabase.table("follow_requests")
            .insert({"requester_id": follower_id, "target_id": target_id})
            .execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:  # PK (requester,target) 이미 존재
            raise
        # 기존 행: rejected면 pending 부활, pending이면 이미 요청됨(멱등 409)
        upd = await asyncio.to_thread(
            lambda: supabase.table("follow_requests")
            .update({"status": "pending", "created_at": _now_iso(), "decided_at": None})
            .eq("requester_id", follower_id).eq("target_id", target_id)
            .eq("status", "rejected").execute()
        )
        if not upd.data:
            raise FollowRequestPending()  # 이미 pending — 멱등이나 명시 409
    try:
        await notification_service.create_notification(
            recipient_id=target_id, actor_id=follower_id,
            type="follow_requested", target_id=follower_id, target_type="user",
        )
    except Exception:  # noqa: BLE001
        logger.warning("follow_requested 알림 생성 실패", exc_info=True)
    return "requested"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def cancel_follow_request(target_id: str, requester_id: str) -> None:
    """내 pending 요청 취소 (멱등 — 없으면 no-op)."""
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("follow_requests").delete()
        .eq("requester_id", requester_id).eq("target_id", target_id)
        .eq("status", "pending").execute()
    )


async def list_follow_requests(
    target_id: str, limit: int = 20, offset: int = 0
) -> list[FollowUserItem]:
    """target(본인)에게 온 pending 요청 목록, 최신순 — requester 프로필 포함."""
    limit = max(1, min(limit, _MAX_PAGE))
    offset = max(0, offset)
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("follow_requests")
        .select("requester_id, created_at")
        .eq("target_id", target_id).eq("status", "pending")
        .order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    )
    rows = res.data
    if not rows:
        return []
    ids = [r["requester_id"] for r in rows]
    briefs, following = await asyncio.gather(
        profile_service.get_profile_briefs(ids),
        _following_set(target_id, ids),
    )
    return [
        FollowUserItem(
            user_id=r["requester_id"],
            nickname=briefs.get(r["requester_id"], {}).get("nickname"),
            avatar_url=briefs.get(r["requester_id"], {}).get("avatar_url"),
            followed_at=r["created_at"],
            is_following=r["requester_id"] in following,
        )
        for r in rows
    ]


async def decide_follow_request(
    target_id: str, requester_id: str, *, approve: bool
) -> None:
    """target(본인)이 요청을 승인/거절. 승인 시 follows 생성 + 알림.

    UPDATE 반환행 있을 때만 알림/follows 삽입 — 동시 승인 이중 처리 방지(L8).
    """
    supabase = get_supabase_admin()
    upd = await asyncio.to_thread(
        lambda: supabase.table("follow_requests")
        .update({"status": "approved" if approve else "rejected",
                 "decided_at": _now_iso()})
        .eq("requester_id", requester_id).eq("target_id", target_id)
        .eq("status", "pending").execute()
    )
    if not upd.data:
        raise FollowRequestNotFound()  # 없거나 이미 처리됨
    if not approve:
        return  # 거절은 무알림 (crew 패턴과 동일)

    # M-8 레이스 봉쇄: block_user의 pending 삭제와 approve가 동시 실행돼 pending을
    # 먼저 잠근 경우에도, follows 삽입 전 차단 재검증으로 차단 두 유저 간 엣지 생성
    # 차단(요청은 이미 approved로 소진 — 승인은 무효 처리, 없던 요청과 동일 404).
    if await profile_service.is_blocked_either(target_id, requester_id):
        raise FollowRequestNotFound()

    # 승인: follows 생성 (멱등) + follow_request_approved 알림
    try:
        await asyncio.to_thread(
            lambda: supabase.table("follows")
            .insert({"follower_id": requester_id, "following_id": target_id})
            .execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:  # 이미 팔로우 중이면 무해
            raise
    try:
        await notification_service.create_notification(
            recipient_id=requester_id, actor_id=target_id,
            type="follow_request_approved", target_id=target_id, target_type="user",
        )
    except Exception:  # noqa: BLE001
        logger.warning("follow_request_approved 알림 생성 실패", exc_info=True)


# ── 차단 (docs/PRIVATE_PROFILE_DESIGN.md v3) ─────────────────────────────────


class SelfBlockNotAllowed(Exception):
    """자기 자신은 차단할 수 없다."""


async def block_user(target_id: str, blocker_id: str) -> None:
    """target 차단 (멱등). 양방향 팔로우·pending 요청 4행을 즉시 정리 —
    차단은 관계를 끊는다(재팔로우는 차단 해제 후에만). PK로 중복 멱등."""
    if target_id == blocker_id:
        raise SelfBlockNotAllowed()
    await _ensure_user_exists(target_id)
    supabase = get_supabase_admin()
    try:
        await asyncio.to_thread(
            lambda: supabase.table("blocks")
            .insert({"blocker_id": blocker_id, "blocked_id": target_id}).execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:  # 이미 차단 중 = 멱등
            raise
    # 양방향 follows 삭제 (2행) — PostgREST or로 한 번에
    await asyncio.to_thread(
        lambda: supabase.table("follows").delete().or_(
            f"and(follower_id.eq.{blocker_id},following_id.eq.{target_id}),"
            f"and(follower_id.eq.{target_id},following_id.eq.{blocker_id})"
        ).execute()
    )
    # 양방향 pending follow_requests 삭제 (2행)
    await asyncio.to_thread(
        lambda: supabase.table("follow_requests").delete().or_(
            f"and(requester_id.eq.{blocker_id},target_id.eq.{target_id}),"
            f"and(requester_id.eq.{target_id},target_id.eq.{blocker_id})"
        ).execute()
    )


async def unblock_user(target_id: str, blocker_id: str) -> None:
    """차단 해제 (멱등). 팔로우는 복구 안 됨 — 다시 팔로우해야 함(정책)."""
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("blocks").delete()
        .eq("blocker_id", blocker_id).eq("blocked_id", target_id).execute()
    )


async def list_blocks(blocker_id: str, limit: int = 50, offset: int = 0) -> list[FollowUserItem]:
    """내가 차단한 유저 목록 (프로필 설정 화면용), 최신순."""
    limit = max(1, min(limit, _MAX_PAGE))
    offset = max(0, offset)
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("blocks").select("blocked_id, created_at")
        .eq("blocker_id", blocker_id)
        .order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    )
    rows = res.data
    if not rows:
        return []
    ids = [r["blocked_id"] for r in rows]
    briefs = await profile_service.get_profile_briefs(ids)
    return [
        FollowUserItem(
            user_id=r["blocked_id"],
            nickname=briefs.get(r["blocked_id"], {}).get("nickname"),
            avatar_url=briefs.get(r["blocked_id"], {}).get("avatar_url"),
            followed_at=r["created_at"],   # 차단 시각 (필드 재사용)
            is_following=False,            # 차단 시 관계 끊김
        )
        for r in rows
    ]
