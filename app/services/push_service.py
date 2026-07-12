"""Expo 원격 푸시 — 인앱 알림 생성 훅에서 best-effort 발송.

설계: docs/PUSH_NOTIFICATION_DESIGN.md.
- 발송은 create_notification의 fire-and-forget 태스크에서만 호출 — 어떤
  실패도 로그만 남기고 삼킨다 (본 요청·알림 생성에 절대 전파 금지).
- 본문은 닉네임 + 행위 유형만 (콘텐츠 제목·내용 미포함 — 잠금화면 유출 차단).
- 티켓 레벨 DeviceNotRegistered만 즉시 정리, 영수증 폴링은 v2.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.config import settings
from app.core.supabase_client import get_supabase_admin
from app.services import profile_service

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0
_MAX_TOKENS_PER_USER = 10  # 감사 M-B: 초과 등록 시 오래된 것 정리 + 발송도 최근 10대만

# type별 본문 템플릿 — {nickname} 치환. 제목은 앱명 고정.
_TITLE = "FreshRun"
_TEMPLATES: dict[str, dict[str, str]] = {
    "route_liked": {"ko": "{nickname}님이 회원님의 코스를 좋아해요",
                    "en": "{nickname} liked your course"},
    "route_commented": {"ko": "{nickname}님이 회원님의 코스에 댓글을 남겼어요",
                        "en": "{nickname} commented on your course"},
    "run_kudoed": {"ko": "{nickname}님이 회원님의 러닝을 응원해요",
                   "en": "{nickname} gave kudos to your run"},
    "run_commented": {"ko": "{nickname}님이 회원님의 러닝에 댓글을 남겼어요",
                      "en": "{nickname} commented on your run"},
    "user_followed": {"ko": "{nickname}님이 회원님을 팔로우해요",
                      "en": "{nickname} started following you"},
    "follow_requested": {"ko": "{nickname}님이 팔로우를 요청했어요",
                         "en": "{nickname} requested to follow you"},
    "follow_request_approved": {"ko": "{nickname}님이 팔로우 요청을 수락했어요",
                                "en": "{nickname} accepted your follow request"},
    "crew_joined": {"ko": "{nickname}님이 크루에 가입했어요",
                    "en": "{nickname} joined your crew"},
    "join_requested": {"ko": "{nickname}님이 크루 가입을 신청했어요",
                       "en": "{nickname} requested to join your crew"},
    "join_approved": {"ko": "크루 가입이 승인됐어요",
                      "en": "Your crew join request was approved"},
    "crew_announcement": {"ko": "크루에 새 공지가 올라왔어요",
                          "en": "New announcement in your crew"},
    "challenge_completed": {"ko": "크루 챌린지를 달성했어요! 🎉",
                            "en": "Crew challenge completed! 🎉"},
}


async def register_token(user_id: str, token: str, platform: str) -> None:
    """토큰 등록/갱신 — upsert 멱등. PK=token이라 기기 주인 교체 시 자동 이전.

    유저당 최근 10대 초과분은 정리 — 행 폭탄 + Expo 100개 한도 초과로 본인
    푸시가 전멸하는 축 차단 (감사 M-B).
    """
    from datetime import datetime, timezone

    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("push_tokens").upsert({
            "token": token,
            "user_id": user_id,
            "platform": platform,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    )
    rows = await asyncio.to_thread(
        lambda: supabase.table("push_tokens")
        .select("token")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    )
    stale = [r["token"] for r in rows.data[_MAX_TOKENS_PER_USER:]]
    if stale:
        await _drop_tokens(stale)


async def delete_token(user_id: str, token: str) -> None:
    """토큰 해제 (로그아웃) — 본인 소유 행만, 멱등."""
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("push_tokens")
        .delete()
        .eq("token", token)
        .eq("user_id", user_id)
        .execute()
    )


async def _drop_tokens(tokens: list[str]) -> None:
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("push_tokens").delete().in_("token", tokens).execute()
    )


async def send_for_notification(
    recipient_id: str,
    actor_id: str,
    type: str,
    target_id: str,
    target_type: str,
    payload: dict | None,
) -> None:
    """알림 1건의 푸시 발송 (백그라운드 태스크 본체) — 전 구간 best-effort."""
    try:
        supabase = get_supabase_admin()
        rows = await asyncio.to_thread(
            lambda: supabase.table("push_tokens")
            .select("token")
            .eq("user_id", recipient_id)
            .order("updated_at", desc=True)
            .limit(_MAX_TOKENS_PER_USER)  # 최근 기기만 — Expo 100개 한도 방어
            .execute()
        )
        tokens = [r["token"] for r in rows.data]
        if not tokens:
            return

        template = _TEMPLATES.get(type)
        if template is None:  # 신규 type이 템플릿보다 먼저 생기면 발송 스킵
            logger.warning("푸시 템플릿 없는 type=%s — 발송 스킵", type)
            return
        nicknames, recipient_settings = await asyncio.gather(
            profile_service.get_nicknames([actor_id]),
            profile_service.get_settings(recipient_id),
        )
        lang = recipient_settings.lang if recipient_settings.lang in ("ko", "en") else "ko"
        body = template[lang].format(nickname=nicknames.get(actor_id) or "러너")

        messages = [{
            "to": t,
            "title": _TITLE,
            "body": body,
            # 딥링크: 알림 라우팅 표 재사용 (프론트가 인앱 탭 핸들러 공유)
            "data": {"type": type, "target_id": target_id,
                     "target_type": target_type, "payload": payload},
        } for t in tokens]

        headers = {"Content-Type": "application/json"}
        if settings.expo_access_token:  # EAS 푸시 보안 활성화 시에만
            headers["Authorization"] = f"Bearer {settings.expo_access_token}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(settings.expo_push_url, json=messages,
                                     headers=headers)
        if resp.status_code != 200:
            logger.warning("Expo push %s — 드랍 (type=%s)", resp.status_code, type)
            return

        # 티켓 검사 — DeviceNotRegistered 토큰 즉시 정리 (영수증 폴링은 v2)
        tickets = resp.json().get("data") or []
        dead = [t for t, ticket in zip(tokens, tickets)
                if isinstance(ticket, dict) and ticket.get("status") == "error"
                and (ticket.get("details") or {}).get("error") == "DeviceNotRegistered"]
        if dead:
            await _drop_tokens(dead)
            logger.info("DeviceNotRegistered 토큰 %d개 정리", len(dead))
    except Exception:  # noqa: BLE001 — 푸시는 부가 기능, 어떤 실패도 전파 금지
        logger.warning("푸시 발송 실패 — 무시 (type=%s)", type, exc_info=True)
