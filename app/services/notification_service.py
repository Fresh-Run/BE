"""Notification service: create and query in-app notifications."""
from __future__ import annotations

import asyncio
import logging

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import NotificationResponse
from app.services import profile_service, push_service

logger = logging.getLogger(__name__)


async def create_notification(
    recipient_id: str,
    actor_id: str,
    type: str,
    target_id: str,
    target_type: str,
    allow_self: bool = False,
    payload: dict | None = None,
) -> None:
    """Insert one notification row.

    Silently skips when recipient == actor, unless allow_self=True
    (used for challenge_completed where the triggering runner should
    also receive the notification).

    payload: 딥링크 보조 데이터(jsonb). 예: crew_announcement는
    {"crew_id": ...}로 공지가 속한 크루로 이동. target_id로 충분한 타입은 None.
    """
    if not allow_self and recipient_id == actor_id:
        return

    record = {
        "user_id": recipient_id,
        "actor_id": actor_id,
        "type": type,
        "target_id": target_id,
        "target_type": target_type,
    }
    if payload is not None:
        record["payload"] = payload

    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("notifications").insert(record).execute()
    )

    # 원격 푸시 — fire-and-forget (요청 경로가 Expo 왕복을 기다리지 않음,
    # 실패는 태스크 내부에서 전부 삼킴). 인앱 알림은 위에서 이미 저장됨.
    try:
        asyncio.create_task(push_service.send_for_notification(
            recipient_id, actor_id, type, target_id, target_type, payload
        ))
    except Exception:  # noqa: BLE001 — 태스크 생성 실패조차 본 요청을 못 막음
        logger.warning("푸시 태스크 생성 실패 — 무시", exc_info=True)


async def list_notifications(user_id: str, limit: int = 20) -> list[NotificationResponse]:
    """Return the caller's notifications, newest first."""
    limit = max(1, min(limit, 100))
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("notifications")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = res.data
    if not rows:
        return []

    briefs = await profile_service.get_profile_briefs(list({r["actor_id"] for r in rows}))
    return [
        NotificationResponse(
            **row,
            actor_nickname=briefs.get(row["actor_id"], {}).get("nickname"),
            actor_avatar_url=briefs.get(row["actor_id"], {}).get("avatar_url"),
        )
        for row in rows
    ]


async def unread_count(user_id: str) -> int:
    """Return the number of unread notifications for the caller."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("notifications")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("is_read", False)
        .execute()
    )
    return res.count or 0


async def delete_for_target(target_type: str, target_id: str) -> None:
    """대상이 삭제될 때 그 대상을 가리키는 알림을 정리 (감사 M10).

    notifications.target_id에 FK가 없어, 크루/공지 삭제 후 404 대상 알림이
    알림함·unread_count에 유령으로 남는다. best-effort — 실패해도 삭제 자체는
    성공시킨다 (호출부에서 스왈로).
    """
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("notifications")
        .delete()
        .eq("target_type", target_type)
        .eq("target_id", target_id)
        .execute()
    )


async def mark_read(notification_id: str, user_id: str) -> bool:
    """Mark one notification as read. Returns False if not found or not owned."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("notifications")
        .update({"is_read": True})
        .eq("id", notification_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(res.data)


async def mark_all_read(user_id: str) -> None:
    """Mark all of the caller's unread notifications as read."""
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("notifications")
        .update({"is_read": True})
        .eq("user_id", user_id)
        .eq("is_read", False)
        .execute()
    )


async def delete_notification(notification_id: str, user_id: str) -> bool:
    """Delete one notification (스와이프). Returns False if not found or not owned.

    user_id로 스코프해 남의 알림은 0행 삭제(→False→404, 존재 은닉). mark_read와
    동일 패턴 — 성공 삭제 204, 없음/남의 것 404.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("notifications")
        .delete()
        .eq("id", notification_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(res.data)


async def delete_all(user_id: str) -> None:
    """Delete all of the caller's notifications (모두 지우기). 멱등 — 0건이어도 204."""
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("notifications")
        .delete()
        .eq("user_id", user_id)
        .execute()
    )
