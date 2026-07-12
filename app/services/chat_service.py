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


class RunNotShareable(Exception):
    """공유할 run이 없거나 본인 run이 아님 — 404 은닉(본인 run만 공유 가능)."""


class PrivateRunNotShareable(Exception):
    """비공개(private) run은 채팅 공유 불가 — 422."""


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


# run_share 스냅샷에 박제할 필드(화이트리스트) — 타인 상세 정제와 동일 기준.
# notes·verification·is_flagged·liked·feedback_* 등 내부/개인 필드는 제외.
_SHARE_RUN_COLS = ("id, user_id, distance_km, duration_sec, avg_pace_sec_per_km, "
                   "title, area, ran_at, photos, visibility")


async def post_system(crew_id: str, author_id: str, content_key: str,
                      payload: dict) -> None:
    """시스템 메시지 삽입 (공지 생성 등 이벤트 유입 — 단일 소스).

    content=렌더 키(프론트가 문구 조립, 다국어·문구 변경이 서버 배포 불요),
    payload=딥링크 파라미터. sender_id=이벤트 주체(운영진 표기용, **null 아님**).
    호출측(create_announcement 등)이 best-effort로 감싼다 — 실패해도 원 이벤트 성공.
    """
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("crew_messages").insert({
            "crew_id": crew_id, "sender_id": author_id,
            "type": "system", "content": content_key, "payload": payload,
        }).execute()
    )


async def _polyline_thumb(run_id: str) -> list | None:
    """run_tracks의 polyline_thumb (카드 지도용) — best-effort, 없으면 None."""
    supabase = get_supabase_admin()
    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("run_tracks").select("polyline_thumb")
            .eq("run_id", run_id).limit(1).execute()
        )
        return res.data[0]["polyline_thumb"] if res.data else None
    except Exception:  # noqa: BLE001
        logger.warning("run_share polyline_thumb 조회 실패 (run=%s)", run_id, exc_info=True)
        return None


async def share_run(crew_id: str, sender_id: str, run_id: str,
                    caption: str | None) -> ChatMessageResponse:
    """본인 run을 크루 채팅에 공유 (스냅샷 박제). 크루원만·본인 run·public/followers만.

    스냅샷은 전송 시점 값으로 payload에 박제 — **원본 삭제·비공개 전환 후에도
    카드 요약은 남는다**(카톡 사진 선례). run_id는 "상세로 이동" 링크용이며 탭 시
    GET /runs/{id}가 현재 가시성으로 재평가(삭제·비공개면 404). notes 등 화이트
    리스트 밖 필드는 박제하지 않음(타인 상세 정제 규칙과 동일). photo_thumb는
    경로(서명 URL 아님) — 이미지 바이트는 상세 진입 시 현재 권한 서명 URL로만.
    """
    await crew_service.ensure_member(crew_id, sender_id)
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("runs").select(_SHARE_RUN_COLS)
        .eq("id", run_id).limit(1).execute()
    )
    if not res.data or res.data[0]["user_id"] != sender_id:
        raise RunNotShareable()          # 없음 or 타인 run → 404 은닉(본인 것만)
    run = res.data[0]
    if run.get("visibility") == "private":
        raise PrivateRunNotShareable()   # 비공개 run 공유 불가 → 422

    photos = run.get("photos") or []
    snapshot = {
        "run_id": run_id,
        "distance_km": run.get("distance_km"),
        "duration_sec": run.get("duration_sec"),
        "avg_pace_sec_per_km": run.get("avg_pace_sec_per_km"),
        "title": run.get("title"),
        "area": run.get("area"),
        "ran_at": run.get("ran_at"),
        "polyline_thumb": await _polyline_thumb(run_id),
        "photo_thumb": photos[0] if photos else None,
    }
    row = (await asyncio.to_thread(
        lambda: supabase.table("crew_messages").insert({
            "crew_id": crew_id, "sender_id": sender_id, "type": "run_share",
            "content": caption, "payload": snapshot,
        }).execute()
    )).data[0]
    brief = (await profile_service.get_profile_briefs([sender_id])).get(sender_id, {})
    return ChatMessageResponse(
        id=row["id"], crew_id=crew_id, sender_id=sender_id,
        sender_nickname=brief.get("nickname"), sender_avatar_url=brief.get("avatar_url"),
        type="run_share", content=caption, payload=snapshot,
        created_at=row["created_at"],
    )


async def _get_message(crew_id: str, message_id: str) -> dict:
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("crew_messages")
        .select("id, sender_id, type, content")
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
    msg = await _get_message(crew_id, message_id)  # 404 은닉
    # M-9: soft-deleted 메시지(content null인 text)엔 새 반응 불가 — 404 은닉.
    # 기존 반응·맥락은 유지(delete_message가 반응은 안 지움)지만 신규는 막는다.
    if msg["type"] == "text" and msg.get("content") is None:
        raise MessageNotFound()
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
