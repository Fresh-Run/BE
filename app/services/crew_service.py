"""Crew (community) persistence and membership logic.

Data access uses the service_role client (bypasses RLS); visibility rules
(public vs private, membership) are enforced here in app code. supabase-py is
synchronous, so blocking calls run in worker threads.
"""

from __future__ import annotations

import asyncio
import logging
import math
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from postgrest.exceptions import APIError

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import (
    ChallengeCreate,
    ChallengeResponse,
    CrewCreate,
    CrewMemberResponse,
    CrewRankingEntry,
    CrewResponse,
    CrewRunItem,
    CrewUpdate,
    JoinRequestItem,
    JoinRequestResponse,
    MyJoinRequestItem,
)
from app.services import notification_service, profile_service
# 주 경계(월 00:00 KST) 계산은 run_service 단일 정의를 재사용 — 드리프트 방지(L7)
from app.services.run_service import _week_start_utc

_UNIQUE_VIOLATION = "23505"

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


class AlreadyRequested(CrewError):
    """The user already has a pending join request for this crew."""


class JoinRequestNotFound(CrewError):
    """No pending join request with that id in this crew."""


class AlreadyOwner(CrewError):
    """Transfer target is already the owner (no-op)."""


class RoleTargetIsOwner(CrewError):
    """owner의 role은 이 API로 못 바꾼다 (위임은 transfer 경유) — 422."""


# --- Helpers -----------------------------------------------------------------


def _to_response(
    crew: dict, member_count: int, owner_nickname: str | None = None,
    distance_km: float | None = None,
) -> CrewResponse:
    """Build a CrewResponse from a crew row dict + computed member count.

    `**crew`가 sido/sigungu/lat/lng/tags 등 신규 컬럼을 자동 전달한다
    (CrewResponse에 동명 필드 존재). distance_km만 계산값이라 별도 인자.
    """
    return CrewResponse(
        **crew, member_count=member_count, owner_nickname=owner_nickname,
        distance_km=distance_km,
    )


def _crew_haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 대권거리(km). nearby routes와 동일 공식 (자립 헬퍼)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


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


async def _crew_row(crew_id: str, columns: str = "owner_id") -> dict:
    """Fetch one crews row, or raise CrewNotFound."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crews")
        .select(columns)
        .eq("id", crew_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise CrewNotFound()
    return res.data[0]


async def ensure_member(crew_id: str, user_id: str) -> None:
    """Guard: crew must exist (CrewNotFound) and user must be a member
    (CrewAccessDenied). Shared by crew sub-resources (announcements, RSVPs)."""
    await _crew_row(crew_id)
    if not await _is_member(crew_id, user_id):
        raise CrewAccessDenied()


async def ensure_owner(crew_id: str, caller_id: str, columns: str = "owner_id") -> dict:
    """Guard: crew must exist and caller must be the owner. Returns the crew row.

    위임·삭제·role 변경 등 owner 전용 액션에만 사용 — 운영진에게 열린 액션은
    ensure_manager를 쓴다 (분류표: CREW_ADMIN_AND_RUN_AREA_DESIGN §3).
    """
    crew = await _crew_row(crew_id, columns)
    if crew["owner_id"] != caller_id:
        raise NotOwner()
    return crew


async def _member_role(crew_id: str, user_id: str) -> str | None:
    """crew_members.role, 비멤버면 None."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .select("role")
        .eq("crew_id", crew_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return res.data[0]["role"] if res.data else None


async def ensure_manager(crew_id: str, caller_id: str) -> None:
    """Guard: owner 또는 admin(운영진). 아니면 NotOwner(기존 403 계약 유지).

    admin role v1 — 공지 CRUD·챌린지 생성·member 강퇴에 사용.
    """
    crew = await _crew_row(crew_id)
    if crew["owner_id"] == caller_id:
        return
    if await _member_role(crew_id, caller_id) != "admin":
        raise NotOwner()


async def _cleanup_member_rsvps(crew_id: str, user_id: str) -> None:
    """Drop a departing member's RSVP votes (best-effort; tallies stay member-only)."""
    from app.services import announcement_service  # local import: avoids circular

    try:
        await announcement_service.remove_member_rsvps(crew_id, user_id)
    except Exception:  # noqa: BLE001 — leaving must not fail on vote cleanup
        logger.warning("탈퇴/강퇴 멤버 RSVP 정리 실패 (crew=%s)", crew_id, exc_info=True)


# --- Operations --------------------------------------------------------------


async def create_crew(
    req: CrewCreate, owner_id: str, limit: int | None = None
) -> CrewResponse:
    """Create a crew + owner membership atomically (M8).

    create_crew_limited RPC가 owner advisory lock으로 per-owner 직렬화 후 count를
    검사하고 crews·crew_members insert를 한 트랜잭션으로 수행 → 동시 2건이 free
    한도를 초과할 수 없음. limit=None이면 검사 없이 생성(premium). tier→limit
    해석은 호출부(핸들러)가 담당. 한도 초과 시 CrewLimitExceeded(기존 계약).
    """
    supabase = get_supabase_admin()
    try:
        res = await asyncio.to_thread(
            lambda: supabase.rpc(
                "create_crew_limited",
                {
                    "_owner_id": owner_id,
                    "_limit": limit,
                    "_crew": req.model_dump(mode="json"),  # level enum→str 등
                },
            ).execute()
        )
    except APIError as exc:
        if "crew_limit_exceeded" in str(exc):
            from app.services.quota_service import CrewLimitExceeded
            raise CrewLimitExceeded(limit) from exc
        raise
    # 단일 composite(public.crews) 반환 → res.data는 dict (TABLE 반환과 달리 list 아님)
    crew = res.data[0] if isinstance(res.data, list) else res.data
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

    limit = max(1, min(limit, 100))
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


async def list_browse_crews(
    user_id: str,
    sido: str | None = None,
    sigungu: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    include_full: bool = False,
    limit: int = 50,
) -> list[CrewResponse]:
    """Return public crews (+ my private crews) for the discovery tab.

    파라미터 전무 = 기존 동작(공개 전체 + 내 비공개, 최신순). 확장:
    - sido/sigungu: 행정구역 정확 일치 필터
    - lat+lng: distance_km 계산 + 거리 오름차순 정렬 (좌표 없는 크루는 후미·null)
    - include_full=false(기본): 정원 찬 크루 제외
    - limit: 1~100 클램프
    """
    limit = max(1, min(limit, 100))
    supabase = get_supabase_admin()

    def _pub_query():
        q = supabase.table("crews").select("*").eq("is_public", True)
        if sido:
            q = q.eq("sido", sido)
        if sigungu:
            q = q.eq("sigungu", sigungu)
        return q.execute()

    pub = await asyncio.to_thread(_pub_query)
    crews_by_id: dict[str, dict] = {c["id"]: c for c in pub.data}

    # 내 비공개 크루도 포함 (공개 쿼리에 안 잡힘). 행정구역 필터도 동일 적용.
    my_ids = await _my_crew_ids(user_id)
    missing = [cid for cid in my_ids if cid not in crews_by_id]
    if missing:
        def _mine_query():
            q = supabase.table("crews").select("*").in_("id", missing)
            if sido:
                q = q.eq("sido", sido)
            if sigungu:
                q = q.eq("sigungu", sigungu)
            return q.execute()
        mine = await asyncio.to_thread(_mine_query)
        for c in mine.data:
            crews_by_id[c["id"]] = c

    crews = list(crews_by_id.values())
    counts = await _member_counts([c["id"] for c in crews])

    # include_full=false → 정원 찬 크루 제외
    if not include_full:
        crews = [
            c for c in crews
            if c.get("max_members") is None
            or counts.get(c["id"], 0) < c["max_members"]
        ]

    # 거리 계산 (요청 좌표 + 크루 좌표 둘 다 있을 때만)
    has_origin = lat is not None and lng is not None
    dist: dict[str, float | None] = {}
    for c in crews:
        if has_origin and c.get("lat") is not None and c.get("lng") is not None:
            dist[c["id"]] = round(_crew_haversine_km(lat, lng, c["lat"], c["lng"]), 1)
        else:
            dist[c["id"]] = None

    # 정렬: 좌표 있으면 거리순(null=후미), 없으면 created_at desc
    if has_origin:
        crews.sort(key=lambda c: (dist[c["id"]] is None, dist[c["id"]] or 0.0))
    else:
        crews.sort(key=lambda c: c["created_at"], reverse=True)

    crews = crews[:limit]
    nicknames = await profile_service.get_nicknames([c["owner_id"] for c in crews])
    return [
        _to_response(c, counts.get(c["id"], 0), nicknames.get(c["owner_id"]),
                     distance_km=dist[c["id"]])
        for c in crews
    ]


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
        raise CrewAccessDenied()  # no invite flow yet (join_policy와 무관하게 차단)
    if await _is_member(crew_id, user_id):
        raise AlreadyMember()

    if crew.get("join_policy", "open") == "approval":
        return await _create_join_request(crew, user_id)

    current = await _admit_member(crew, user_id)
    # approval→open 전환 잔여 정리: 남아 있던 본인 pending 신청 자동 삭제.
    await _clear_my_pending(crew_id, user_id)
    return await _one_response(crew, current)


async def _admit_member(crew: dict, user_id: str, *, notify_owner: bool = True) -> int:
    """Capacity-check + membership insert. Returns the new member count.

    Shared by open joins and request approval. A concurrent duplicate insert
    (23505) counts as already-admitted (idempotent). notify_owner=False for
    approvals — the owner just approved it themselves.
    """
    crew_id = crew["id"]
    supabase = get_supabase_admin()
    # 정원 검사+삽입을 admit_crew_member RPC로 원자화 (H3): crews 행 FOR UPDATE로
    # per-crew 직렬화 → 동시 가입/승인이 max_members를 초과할 수 없음.
    res = await asyncio.to_thread(
        lambda: supabase.rpc(
            "admit_crew_member",
            {"_crew_id": crew_id, "_user_id": user_id, "_role": "member"},
        ).execute()
    )
    row = res.data[0]  # {'status':..., 'member_count':...}
    status = row["status"]
    if status == "crew_full":
        raise CrewFull()
    if status == "crew_not_found":
        raise CrewNotFound()
    current = row["member_count"]
    if status == "already_member":  # 멱등 — 함수 내부 잠금이라 중복 insert 자체가 없음
        return current
    logger.info("User %s joined crew %s.", user_id, crew_id)

    # status == 'admitted' — 실제 새 가입일 때만 알림
    if notify_owner:
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

    return current  # RPC member_count = admitted 후 새 카운트


async def _create_join_request(crew: dict, user_id: str) -> JoinRequestResponse:
    """Create a pending join request (approval crews) + notify the owner."""
    supabase = get_supabase_admin()
    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("crew_join_requests")
            .insert({"crew_id": crew["id"], "user_id": user_id})
            .execute()
        )
    except APIError as exc:
        if exc.code == _UNIQUE_VIOLATION:  # partial unique: one pending per user
            raise AlreadyRequested() from exc
        raise
    row = res.data[0]

    # TOCTOU 방어: join_crew의 멤버십 체크와 이 insert 사이에 크루장의 승인이
    # 끼어들면 "멤버 + 새 pending"이 생긴다 (기존 pending이 approved로 바뀌면
    # partial unique를 통과하므로). 사후 재확인으로 창을 닫는다 — 승인의
    # 멤버십 insert는 항상 status 갱신보다 먼저라, 여기서 멤버가 아니면
    # 이 신청을 삼킬 수 있는 승인은 존재하지 않는다.
    if await _is_member(crew["id"], user_id):
        await asyncio.to_thread(
            lambda: supabase.table("crew_join_requests")
            .delete()
            .eq("id", row["id"])
            .execute()
        )
        raise AlreadyMember()

    try:
        await notification_service.create_notification(
            recipient_id=crew["owner_id"],
            actor_id=user_id,
            type="join_requested",
            target_id=crew["id"],
            target_type="crew",
        )
    except Exception:
        logger.warning("join_requested 알림 생성 실패", exc_info=True)

    nicknames = await profile_service.get_nicknames([user_id])
    return JoinRequestResponse(**row, nickname=nicknames.get(user_id))


async def _clear_my_pending(crew_id: str, user_id: str) -> None:
    """Best-effort: drop the caller's leftover pending request for this crew."""
    try:
        supabase = get_supabase_admin()
        await asyncio.to_thread(
            lambda: supabase.table("crew_join_requests")
            .delete()
            .eq("crew_id", crew_id)
            .eq("user_id", user_id)
            .eq("status", "pending")
            .execute()
        )
    except Exception:  # noqa: BLE001 — joining must not fail on cleanup
        logger.warning("pending 가입신청 정리 실패 (crew=%s)", crew_id, exc_info=True)


async def get_my_join_request(crew_id: str, user_id: str) -> JoinRequestResponse | None:
    """The caller's most recent join request for this crew (any status)."""
    await _crew_row(crew_id)
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_join_requests")
        .select("*")
        .eq("crew_id", crew_id)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    return JoinRequestResponse(**res.data[0])


async def list_my_join_requests(
    user_id: str, limit: int = 50, offset: int = 0
) -> list[MyJoinRequestItem]:
    """The caller's join requests across ALL crews, newest first.

    전체 상태 포함 (pending/approved/rejected) — 둘러보기 화면 뱃지를 한 번에
    채우는 용도라 프론트가 필터한다. 삭제된 크루의 신청은 FK cascade로 행
    자체가 사라지므로 걸러낼 필요 없음.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_join_requests")
        .select("crew_id, status, created_at, decided_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data
    if not rows:
        return []

    crew_ids = list({r["crew_id"] for r in rows})
    crews_res = await asyncio.to_thread(
        lambda: supabase.table("crews").select("id, name").in_("id", crew_ids).execute()
    )
    names = {c["id"]: c["name"] for c in crews_res.data}
    return [
        MyJoinRequestItem(**row, crew_name=names.get(row["crew_id"]))
        for row in rows
    ]


async def cancel_my_join_request(crew_id: str, user_id: str) -> None:
    """Cancel the caller's pending request. Idempotent: no-op when absent."""
    await _crew_row(crew_id)
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("crew_join_requests")
        .delete()
        .eq("crew_id", crew_id)
        .eq("user_id", user_id)
        .eq("status", "pending")
        .execute()
    )


async def list_join_requests(
    crew_id: str, caller_id: str, limit: int = 20, offset: int = 0
) -> list[JoinRequestItem]:
    """Pending join requests, newest first, with nicknames (owner only)."""
    await ensure_owner(crew_id, caller_id)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_join_requests")
        .select("id, user_id, created_at")
        .eq("crew_id", crew_id)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data
    if not rows:
        return []
    nicknames = await profile_service.get_nicknames([r["user_id"] for r in rows])
    return [
        JoinRequestItem(**row, nickname=nicknames.get(row["user_id"]))
        for row in rows
    ]


# 혼동 문자(I/O/0/1) 제외 32문자셋 — 8자 = 32^8 ≈ 1.1조 공간 (무차별 대입 비현실적)
_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _gen_invite_code() -> str:
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(8))


async def get_invite_code(crew_id: str, caller_id: str) -> str | None:
    """Return the crew's current invite code (owner only); None if not issued."""
    crew = await ensure_owner(crew_id, caller_id, "owner_id, invite_code")
    return crew.get("invite_code")


async def regenerate_invite_code(crew_id: str, caller_id: str) -> str:
    """Issue a new invite code (owner only). The previous code dies with the
    UPDATE — regeneration is the leak response. Retries on the ~impossible
    UNIQUE collision. Code values are never logged."""
    await ensure_owner(crew_id, caller_id)
    supabase = get_supabase_admin()
    for _ in range(5):
        code = _gen_invite_code()
        try:
            await asyncio.to_thread(
                lambda code=code: supabase.table("crews")
                .update({"invite_code": code})
                .eq("id", crew_id)
                .execute()
            )
            return code
        except APIError as exc:
            if exc.code != _UNIQUE_VIOLATION:
                raise
    raise RuntimeError("invite code collision retries exhausted")


async def _crew_by_code(code: str) -> dict:
    """Find a crew by invite code (normalized). Invalid → CrewNotFound (단일 404)."""
    normalized = code.strip().upper()
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crews")
        .select("*")
        .eq("invite_code", normalized)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise CrewNotFound()
    return res.data[0]


async def preview_by_code(code: str) -> CrewResponse:
    """Crew preview for an invite code — 가입 확정 전에 어느 크루인지 확인."""
    crew = await _crew_by_code(code)
    counts = await _member_counts([crew["id"]])
    return await _one_response(crew, counts.get(crew["id"], 0))


async def join_by_code(code: str, user_id: str) -> CrewResponse:
    """Join via invite code — 초대 = 사전 승인.

    Skips both is_public and join_policy gates on purpose: the code is the
    only door into private crews, and invited users bypass approval. Reuses
    _admit_member (capacity 409, idempotent insert, crew_joined notification)
    and clears any leftover pending join request.
    """
    crew = await _crew_by_code(code)
    if await _is_member(crew["id"], user_id):
        raise AlreadyMember()

    current = await _admit_member(crew, user_id)
    await _clear_my_pending(crew["id"], user_id)
    return await _one_response(crew, current)


async def list_crew_runs(
    crew_id: str, caller_id: str, limit: int = 20, offset: int = 0
) -> list[CrewRunItem]:
    """Crew activity feed: current members' runs, newest ran_at first.

    Two-step query (member ids → runs IN). Fine up to ~200 members; for much
    larger crews the IN-list URL gets long — switch to a Postgres RPC then.
    Departed members drop out automatically (current-members semantics, same
    as the ranking). Personal fields (notes/feedback) are never selected.
    """
    await ensure_member(crew_id, caller_id)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    supabase = get_supabase_admin()
    members_res = await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .select("user_id")
        .eq("crew_id", crew_id)
        .execute()
    )
    member_ids = [r["user_id"] for r in members_res.data]
    if not member_ids:
        return []

    runs_res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("id, user_id, ran_at, distance_km, duration_sec, "
                "avg_pace_sec_per_km, route_id, title, area, photos")
        .in_("user_id", member_ids)
        # 크루 피드는 private만 제외 (public·followers는 크루원에게 노출 — 기존 동작 보존)
        .neq("visibility", "private")
        .order("ran_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = runs_res.data
    if not rows:
        return []

    route_ids = list({r["route_id"] for r in rows if r.get("route_id")})

    async def _public_route_summaries() -> dict[str, str]:
        """{route_id: summary} for PUBLIC routes only — a private course must
        not leak through the crew feed."""
        if not route_ids:
            return {}
        res = await asyncio.to_thread(
            lambda: supabase.table("routes")
            .select("id, summary")
            .in_("id", route_ids)
            .eq("is_public", True)
            .execute()
        )
        return {r["id"]: r["summary"] for r in res.data}

    from app.services.run_service import (  # local: 순환 import 회피
        _comment_counts,
        _polyline_thumbs,
        _signed_photo_urls,
    )
    firsts = {r["id"]: (r.get("photos") or [None])[0] for r in rows}
    briefs, summaries, comment_counts, signed, thumbs = await asyncio.gather(
        profile_service.get_profile_briefs([r["user_id"] for r in rows]),
        _public_route_summaries(),
        _comment_counts([r["id"] for r in rows]),
        _signed_photo_urls([p for p in firsts.values() if p]),
        _polyline_thumbs([r["id"] for r in rows]),
    )
    return [
        CrewRunItem(
            run_id=row["id"],
            user_id=row["user_id"],
            nickname=briefs.get(row["user_id"], {}).get("nickname"),
            avatar_url=briefs.get(row["user_id"], {}).get("avatar_url"),
            ran_at=row["ran_at"],
            title=row.get("title"),
            area=row.get("area"),
            distance_km=row["distance_km"],
            duration_sec=row["duration_sec"],
            avg_pace_sec_per_km=row.get("avg_pace_sec_per_km"),
            route_id=row.get("route_id"),
            route_summary=summaries.get(row.get("route_id")),
            comment_count=comment_counts.get(row["id"], 0),
            photo_thumb=signed.get(firsts.get(row["id"])),
            polyline_thumb=thumbs.get(row["id"]),
        )
        for row in rows
    ]


async def decide_join_request(
    crew_id: str, caller_id: str, request_id: str, *, approve: bool
) -> None:
    """Approve (admit + notify requester) or reject (silent) a pending request.

    Works regardless of the crew's current join_policy, so an owner can keep
    processing leftovers after switching approval → open.
    """
    crew = await ensure_owner(crew_id, caller_id, "*")

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_join_requests")
        .select("*")
        .eq("id", request_id)
        .eq("crew_id", crew_id)
        .eq("status", "pending")
        .limit(1)
        .execute()
    )
    if not res.data:
        raise JoinRequestNotFound()  # missing or already decided
    requester_id = res.data[0]["user_id"]

    if approve:
        # CrewFull propagates and the request stays pending (retry when space frees).
        await _admit_member(crew, requester_id, notify_owner=False)

    upd = await asyncio.to_thread(
        lambda: supabase.table("crew_join_requests")
        .update({
            "status": "approved" if approve else "rejected",
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "decided_by": caller_id,
        })
        .eq("id", request_id)
        .eq("status", "pending")
        .execute()
    )

    # 이 호출이 실제로 pending→approved를 뒤집었을 때만 알림 (동시 승인 2건 중
    # 하나는 0행 반환 → 이중 발송 방지, L8). 거절은 무알림(설계 결정).
    if approve and upd.data:
        try:
            await notification_service.create_notification(
                recipient_id=requester_id,
                actor_id=caller_id,
                type="join_approved",
                target_id=crew_id,
                target_type="crew",
            )
        except Exception:
            logger.warning("join_approved 알림 생성 실패", exc_info=True)


async def leave_crew(crew_id: str, user_id: str) -> None:
    """Remove the user from a crew. The owner cannot leave."""
    crew = await _crew_row(crew_id)
    if crew["owner_id"] == user_id:
        raise OwnerCannotLeave()
    if not await _is_member(crew_id, user_id):
        raise NotAMember()

    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .delete()
        .eq("crew_id", crew_id)
        .eq("user_id", user_id)
        .execute()
    )
    await _cleanup_member_rsvps(crew_id, user_id)
    logger.info("User %s left crew %s.", user_id, crew_id)


async def transfer_ownership(
    crew_id: str, caller_id: str, new_owner_id: str, leave_after: bool = False
) -> CrewResponse:
    """Hand crew ownership to another member.

    Only the current owner may call. The target must already be a member.
    The old owner becomes a regular 'member' (and leaves too if leave_after).

    Atomicity: no DB transaction available. crews.owner_id is the *sole*
    authority (ensure_owner checks it), and crew_members.role is secondary
    roster data. So we set the cosmetic roles first and flip owner_id LAST as
    the commit point; on any failure before/at the commit we best-effort
    restore the original state (roles + owner_id). Transfers are rare, so this
    bounds the tiny window and self-heals instead of leaving a split state.
    A single RPC could make it truly atomic later (race backlog).
    """
    supabase = get_supabase_admin()
    crew = await ensure_owner(crew_id, caller_id, "*")
    if new_owner_id == caller_id:
        raise AlreadyOwner()
    if not await _is_member(crew_id, new_owner_id):
        raise TargetNotMember()

    def _set_role(uid: str, role: str):
        return (supabase.table("crew_members").update({"role": role})
                .eq("crew_id", crew_id).eq("user_id", uid).execute())

    def _set_owner(uid: str):
        return (supabase.table("crews").update({"owner_id": uid})
                .eq("id", crew_id).execute())

    try:
        # 1) roles first (부차적) → 2) owner_id 플립 = 커밋 지점(권한 이전 확정)
        await asyncio.to_thread(lambda: _set_role(new_owner_id, "owner"))
        await asyncio.to_thread(lambda: _set_role(caller_id, "member"))
        await asyncio.to_thread(lambda: _set_owner(new_owner_id))
    except Exception:
        # 보상 복구: 원상태로 되돌림 (best-effort — 로그만 남기고 원래 예외 전파)
        logger.warning("소유권 이전 실패 (crew=%s) — 원상 복구 시도", crew_id, exc_info=True)
        for restore in (lambda: _set_owner(caller_id),
                        lambda: _set_role(caller_id, "owner"),
                        lambda: _set_role(new_owner_id, "member")):
            try:
                await asyncio.to_thread(restore)
            except Exception:  # noqa: BLE001
                logger.error("소유권 보상 복구 일부 실패 (crew=%s)", crew_id, exc_info=True)
        raise
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
    members.sort(key=lambda r: ({"owner": 0, "admin": 1}.get(r["role"], 2), r["joined_at"]))

    # 5. Batch nickname lookup — one IN query, no N+1.
    briefs = await profile_service.get_profile_briefs([m["user_id"] for m in members])

    return [
        CrewMemberResponse(
            user_id=m["user_id"],
            nickname=briefs.get(m["user_id"], {}).get("nickname"),
            avatar_url=briefs.get(m["user_id"], {}).get("avatar_url"),
            role=m["role"],
            joined_at=m["joined_at"],
        )
        for m in members
    ]


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
    #    (verified만 랭킹 집계 — 트랙 없는 run·부정 의심 제외, 집계 정합 정책)
    week_start = _week_start_utc()
    runs_res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("user_id, distance_km")
        .in_("user_id", member_ids)
        .gte("ran_at", week_start)
        .eq("verification", "verified")
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
    briefs = await profile_service.get_profile_briefs([uid for _, uid, _ in ranked])

    return [
        CrewRankingEntry(
            rank=rank,
            user_id=uid,
            nickname=briefs.get(uid, {}).get("nickname"),
            avatar_url=briefs.get(uid, {}).get("avatar_url"),
            distance_km=round(dist, 2),
            me=(uid == caller_id),
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
    await ensure_manager(crew_id, caller_id)

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
    #    (verified만 챌린지 집계 — 트랙 없는 run·부정 의심 제외, 집계 정합 정책)
    if member_ids:
        runs_res = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .select("distance_km")
            .in_("user_id", member_ids)
            .gte("ran_at", ch["starts_at"])
            .lte("ran_at", ch["ends_at"])
            .eq("verification", "verified")
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
    crew = await ensure_owner(crew_id, caller_id, "*")

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
    await ensure_manager(crew_id, caller_id)
    if target_id == caller_id:
        raise OwnerCannotKickSelf()
    target_role = await _member_role(crew_id, target_id)
    if target_role is None:
        raise NotAMember()
    # admin은 member만 강퇴 가능 (admin·owner 강퇴 불가 — owner는 무제한 유지)
    crew = await _crew_row(crew_id)
    if crew["owner_id"] != caller_id and target_role != "member":
        raise NotOwner()

    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .delete()
        .eq("crew_id", crew_id)
        .eq("user_id", target_id)
        .execute()
    )
    await _cleanup_member_rsvps(crew_id, target_id)
    logger.info("User %s kicked from crew %s by owner %s.", target_id, crew_id, caller_id)


async def set_member_role(
    crew_id: str, caller_id: str, target_id: str, role: str
) -> dict:
    """멤버 role 전환 (owner 전용): admin↔member 양방향·멱등.

    owner의 role은 불변(RoleTargetIsOwner → 422) — 위임은 transfer 경유.
    비멤버 target은 NotAMember(→404 은닉). 반환: {user_id, role}.
    """
    crew = await ensure_owner(crew_id, caller_id)
    if target_id == crew["owner_id"]:
        raise RoleTargetIsOwner()
    if await _member_role(crew_id, target_id) is None:
        raise NotAMember()

    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .update({"role": role})
        .eq("crew_id", crew_id)
        .eq("user_id", target_id)
        .execute()
    )
    logger.info("Crew %s: %s role → %s (by owner).", crew_id, target_id, role)
    return {"user_id": target_id, "role": role}


async def delete_crew(crew_id: str, caller_id: str) -> None:
    """Delete a crew (owner only). Memberships, announcements, and RSVPs are
    removed via the ON DELETE CASCADE chain (crews → announcements → rsvps)."""
    await ensure_owner(crew_id, caller_id)

    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("crews").delete().eq("id", crew_id).execute()
    )
    # 이 크루를 가리키던 알림 정리 (M10 — 유령 알림·unread_count 방지)
    try:
        await notification_service.delete_for_target("crew", crew_id)
    except Exception:  # noqa: BLE001
        logger.warning("크루 삭제 후 알림 정리 실패 (crew=%s)", crew_id, exc_info=True)
    logger.info("Crew %s deleted by owner %s.", crew_id, caller_id)
