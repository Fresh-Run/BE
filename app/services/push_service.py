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
# 닉네임 미해석 폴백 — 수신자 lang 분기(body 조립부의 lang과 동일 소스). 영문은
# 문장 시작이라 관사 포함("A runner liked your course")이 자연스러움.
_NICKNAME_FALLBACK = {"ko": "러너", "en": "A runner"}
# 알림 type → NotifSettings 카테고리 토글 키 (시안 FrNotifSettings).
# 매핑 없는 type은 카테고리 게이트 없이 master만 적용(안전 기본 — 신규 type이
# 매핑보다 먼저 생겨도 master ON이면 발송). 승인제 2종(follow_requested·
# follow_request_approved)은 전용 토글이 없어 followers 계열로 묶음(팔로우 관계
# 알림). crew_invited·crew_chat은 선등록 type이라 매핑만(발송은 각 기능 사이클).
_CATEGORY: dict[str, str] = {
    "route_liked": "likes",
    "run_kudoed": "likes",
    "route_saved": "likes",              # 러닝→코스 저장 (kudos 클래스 — likes 그룹 재사용)
    "route_commented": "comments",
    "run_commented": "comments",
    "user_followed": "followers",
    "follow_requested": "followers",
    "follow_request_approved": "followers",
    "crew_joined": "crewJoin",
    "join_requested": "crewJoin",
    "join_approved": "crewJoin",
    "crew_invited": "crewJoin",          # 선등록
    "crew_announcement": "crewNotice",
    "challenge_completed": "crewChallenge",
    "crew_chat": "crewChat",             # 선등록
    "pb_achieved": "pb",                 # PB 축하 (자기 대상)
}


# PB 축하 문구 — 기록 종류별(new_records[].type). 단일 기록이면 종류별 문구,
# 복수·미지면 _TEMPLATES["pb_achieved"] 제네릭. self 알림이라 {nickname} 없음.
_PB_MESSAGES: dict[str, dict[str, str]] = {
    "best_pace":        {"ko": "최고 페이스 경신! ⚡", "en": "New fastest pace! ⚡"},
    "best_5k":          {"ko": "5km 최고 기록! 🏅",   "en": "New 5K best! 🏅"},
    "longest_distance": {"ko": "최장 거리 경신! 🏃",   "en": "Longest run yet! 🏃"},
    "longest_duration": {"ko": "최장 시간 경신! ⏱️",   "en": "Longest duration yet! ⏱️"},
}


_TEMPLATES: dict[str, dict[str, str]] = {
    "route_liked": {"ko": "{nickname}님이 회원님의 코스를 좋아해요",
                    "en": "{nickname} liked your course"},
    "route_commented": {"ko": "{nickname}님이 회원님의 코스에 댓글을 남겼어요",
                        "en": "{nickname} commented on your course"},
    "run_kudoed": {"ko": "{nickname}님이 회원님의 러닝을 응원해요",
                   "en": "{nickname} gave kudos to your run"},
    "route_saved": {"ko": "{nickname}님이 회원님의 러닝을 코스로 저장했어요",
                    "en": "{nickname} saved your run as a course"},
    "run_commented": {"ko": "{nickname}님이 회원님의 러닝에 댓글을 남겼어요",
                      "en": "{nickname} commented on your run"},
    "user_followed": {"ko": "{nickname}님이 회원님을 팔로우해요",
                      "en": "{nickname} started following you"},
    "follow_requested": {"ko": "{nickname}님이 팔로우를 요청했어요",
                         "en": "{nickname} requested to follow you"},
    "follow_request_approved": {"ko": "{nickname}님이 팔로우 요청을 수락했어요",
                                "en": "{nickname} accepted your follow request"},
    "crew_chat": {"ko": "{nickname}님이 크루 채팅에 메시지를 보냈어요",
                  "en": "{nickname} sent a message in crew chat"},
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
    # PB 축하 — 제네릭(복수 기록·미지 종류 폴백). 단일 종류는 _PB_MESSAGES로 세분.
    "pb_achieved": {"ko": "새 기록을 세웠어요! 🎉", "en": "New personal record! 🎉"},
    # 인앱 개인 초대 (crew_invited는 _CATEGORY에 이미 crewJoin — 이제 발송 시작)
    "crew_invited": {"ko": "{nickname}님이 크루에 초대했어요",
                     "en": "{nickname} invited you to a crew"},
}

# M-11 (감사 3차): 로드 시 정합 강제 — 템플릿 있는 type(=실제 발송)은 반드시
# 카테고리 매핑이 있어야 한다. 없으면 send_for_notification에서 category=None →
# master만으로 발송돼 사용자의 카테고리 토글을 무시하는 우회가 생긴다(fail-closed).
# 신규 발송 type 추가 시 _CATEGORY 매핑을 빠뜨리면 여기서 즉시 ImportError.
_missing_category = set(_TEMPLATES) - set(_CATEGORY)
assert not _missing_category, (
    f"_TEMPLATES에 있으나 _CATEGORY 매핑 누락: {sorted(_missing_category)} "
    "— 카테고리 없이 발송되면 토글 우회. _CATEGORY에 추가하세요."
)


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
        # 푸시 발송 게이트 (인앱 알림은 이미 저장됨 — 여기선 푸시만 스킵).
        # master OFF → 전부 스킵. 아니면 해당 카테고리 토글 확인. 미설정 유저는
        # NotifSettings 기본값(전부 True, marketing만 False)이라 정상 발송.
        notif = recipient_settings.notif
        if not notif.master:
            logger.info("푸시 스킵: master OFF (recipient=%s, type=%s)", recipient_id, type)
            return
        category = _CATEGORY.get(type)
        if category is not None and not getattr(notif, category):
            logger.info("푸시 스킵: %s OFF (recipient=%s, type=%s)", category, recipient_id, type)
            return
        lang = recipient_settings.lang if recipient_settings.lang in ("ko", "en") else "ko"
        if type == "pb_achieved":
            # PB는 자기 대상 — {nickname} 없이 기록 종류별 문구. 단일 종류면 세분,
            # 복수·미지면 제네릭 템플릿. record_types는 payload에 실려 옴.
            rtypes = (payload or {}).get("record_types") or []
            body = (_PB_MESSAGES[rtypes[0]][lang]
                    if len(rtypes) == 1 and rtypes[0] in _PB_MESSAGES
                    else template[lang])
        else:
            # 닉네임 미해석 폴백도 lang-aware(2026-07-29 Ivan 합의) — 같은 lang 소스 재사용.
            body = template[lang].format(
                nickname=nicknames.get(actor_id) or _NICKNAME_FALLBACK[lang])

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

        # 발송 성공 요약 — 토큰 값·유저 식별정보는 남기지 않고 카운트/상태만
        # (관측성: 실 Expo 발송 확인용. status별 집계 — 대부분 ok, error면 세부는
        # 위 DeviceNotRegistered 처리·영수증 폴링 v2에서).
        ok_n = sum(1 for tk in tickets
                   if isinstance(tk, dict) and tk.get("status") == "ok")
        err_n = len(tickets) - ok_n
        logger.info("push sent: type=%s recipients=%d tickets=ok:%d err:%d",
                    type, len(tokens), ok_n, err_n)
    except Exception:  # noqa: BLE001 — 푸시는 부가 기능, 어떤 실패도 전파 금지
        logger.warning("푸시 발송 실패 — 무시 (type=%s)", type, exc_info=True)
