"""크루 채팅 (docs/CREW_CHAT_DESIGN.md v1) — text 메시지·이모지 반응·읽음 상태.

전송은 폴링(클라이언트 20~30초 주기). 전 접근 service_role + 앱 게이트
(ensure_member/ensure_manager 재사용). 안읽은수는 last_read_at 파생(카운터
드리프트 회피), mute는 crew_read_state.muted.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import (
    CHAT_EMOJIS,
    ChatMessageResponse,
    ChatUnreadResponse,
)
from app.services import crew_service, profile_service

logger = logging.getLogger(__name__)


class MessageNotFound(Exception):
    """메시지가 없거나 이 크루 소속이 아님 — 404 은닉."""


class NotDeletable(Exception):
    """본인 메시지도 운영진도 아님 / system 메시지 삭제 시도 — 403."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _reactions_for(message_ids: list[str], caller_id: str) -> dict:
    """{message_id: (counts dict, my list)} — 배치 1쿼리 (N+1 방지)."""
    if not message_ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_message_reactions")
        .select("message_id, user_id, emoji")
        .in_("message_id", message_ids)
        .execute()
    )
    out: dict[str, tuple[dict, list]] = {mid: ({}, []) for mid in message_ids}
    for r in res.data:
        counts, mine = out[r["message_id"]]
        counts[r["emoji"]] = counts.get(r["emoji"], 0) + 1
        if r["user_id"] == caller_id:
            mine.append(r["emoji"])
    return out


async def list_messages(
    crew_id: str, caller_id: str, limit: int = 30, before: str | None = None
) -> list[ChatMessageResponse]:
    """역순(최신→과거) 커서. 크루원만(ensure_member — CrewNotFound/AccessDenied)."""
    await crew_service.ensure_member(crew_id, caller_id)
    limit = max(1, min(limit, 50))
    supabase = get_supabase_admin()

    def _q():
        q = (
            supabase.table("crew_messages")
            .select("*")
            .eq("crew_id", crew_id)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if before is not None:
            q = q.lt("created_at", before)
        return q.execute()

    rows = (await asyncio.to_thread(_q)).data
    if not rows:
        return []

    msg_ids = [r["id"] for r in rows]
    reacts, briefs = await asyncio.gather(
        _reactions_for(msg_ids, caller_id),
        profile_service.get_profile_briefs([r.get("sender_id") for r in rows]),
    )
    out = []
    for r in rows:
        counts, mine = reacts.get(r["id"], ({}, []))
        brief = briefs.get(r["sender_id"], {}) if r.get("sender_id") else {}
        out.append(ChatMessageResponse(
            id=r["id"], crew_id=r["crew_id"], sender_id=r.get("sender_id"),
            sender_nickname=brief.get("nickname"),
            sender_avatar_url=brief.get("avatar_url"),
            type=r["type"], content=r.get("content"), payload=r.get("payload"),
            created_at=r["created_at"], reactions=counts, my_reactions=mine,
            deleted=(r["type"] == "text" and r.get("content") is None),
        ))
    return out


async def post_message(crew_id: str, sender_id: str, content: str) -> ChatMessageResponse:
    """text 메시지 전송 (크루원만)."""
    await crew_service.ensure_member(crew_id, sender_id)
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_messages").insert({
            "crew_id": crew_id, "sender_id": sender_id,
            "type": "text", "content": content,
        }).execute()
    )
    row = res.data[0]
    brief = (await profile_service.get_profile_briefs([sender_id])).get(sender_id, {})
    return ChatMessageResponse(
        id=row["id"], crew_id=crew_id, sender_id=sender_id,
        sender_nickname=brief.get("nickname"), sender_avatar_url=brief.get("avatar_url"),
        type="text", content=content, created_at=row["created_at"],
    )


async def _get_message(crew_id: str, message_id: str) -> dict:
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_messages")
        .select("id, sender_id, type")
        .eq("id", message_id)
        .eq("crew_id", crew_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise MessageNotFound()
    return res.data[0]


async def delete_message(crew_id: str, caller_id: str, message_id: str) -> None:
    """soft 삭제 (content→null, 반응·맥락 유지). 본인 or 운영진. system 불가."""
    await crew_service.ensure_member(crew_id, caller_id)
    msg = await _get_message(crew_id, message_id)
    if msg["type"] == "system":
        raise NotDeletable()
    if msg["sender_id"] != caller_id:
        try:
            await crew_service.ensure_manager(crew_id, caller_id)
        except crew_service.NotOwner:
            raise NotDeletable()
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("crew_messages")
        .update({"content": None})
        .eq("id", message_id)
        .execute()
    )


async def react(crew_id: str, caller_id: str, message_id: str, emoji: str) -> None:
    """이모지 반응 추가 (멱등 — PK 충돌 무시). 크루원만·메시지 존재 확인."""
    await crew_service.ensure_member(crew_id, caller_id)
    await _get_message(crew_id, message_id)  # 404 은닉
    supabase = get_supabase_admin()
    try:
        await asyncio.to_thread(
            lambda: supabase.table("crew_message_reactions").insert({
                "message_id": message_id, "user_id": caller_id, "emoji": emoji,
            }).execute()
        )
    except Exception:  # noqa: BLE001 — PK 중복(이미 누름) 등은 멱등 성공 취급
        pass


async def unreact(crew_id: str, caller_id: str, message_id: str, emoji: str) -> None:
    """반응 취소 (멱등)."""
    await crew_service.ensure_member(crew_id, caller_id)
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("crew_message_reactions")
        .delete()
        .eq("message_id", message_id)
        .eq("user_id", caller_id)
        .eq("emoji", emoji)
        .execute()
    )


async def _read_row(crew_id: str, user_id: str) -> dict | None:
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_read_state")
        .select("last_read_at, muted")
        .eq("crew_id", crew_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def mark_read(crew_id: str, user_id: str) -> None:
    """last_read_at = now (화면 진입·이탈). muted는 보존 (upsert)."""
    await crew_service.ensure_member(crew_id, user_id)
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("crew_read_state").upsert(
            {"crew_id": crew_id, "user_id": user_id, "last_read_at": _now()},
        ).execute()
    )


async def unread(crew_id: str, user_id: str) -> ChatUnreadResponse:
    """안읽은수(last_read_at 이후, 본인 메시지 제외) + mute 상태. 크루원만."""
    await crew_service.ensure_member(crew_id, user_id)
    row = await _read_row(crew_id, user_id)
    last_read = row["last_read_at"] if row else "1970-01-01T00:00:00+00:00"
    muted = bool(row["muted"]) if row else False
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_messages")
        .select("id", count="exact")
        .eq("crew_id", crew_id)
        .gt("created_at", last_read)
        .neq("sender_id", user_id)   # 본인 메시지는 안읽음에서 제외
        .execute()
    )
    return ChatUnreadResponse(unread_count=res.count or 0, muted=muted)


async def set_mute(crew_id: str, user_id: str, muted: bool) -> None:
    """방별 채팅 mute 토글 (발송 게이트는 v2). last_read_at 보존 upsert."""
    await crew_service.ensure_member(crew_id, user_id)
    row = await _read_row(crew_id, user_id)
    supabase = get_supabase_admin()
    record = {"crew_id": crew_id, "user_id": user_id, "muted": muted}
    if row is None:
        record["last_read_at"] = _now()
    await asyncio.to_thread(
        lambda: supabase.table("crew_read_state").upsert(record).execute()
    )
