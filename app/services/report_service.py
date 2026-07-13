"""Report service: 유저/콘텐츠 신고 적재 + 운영진 조회·처리 (docs/REPORT_DESIGN.md).

차단(block) 스택과 동형 additive 패턴: 별도 테이블 + 404 은닉 게이트 + self 400.
중복 pending은 부분 유니크 인덱스(reports_one_pending)가 DB에서 봉쇄(TOCTOU 포함)
— 충돌(23505)은 멱등 성공으로 흡수. 무알림(1차 — 운영진은 폴링).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from postgrest.exceptions import APIError

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import ReportCreate, ReportItem, ReportUserBrief
from app.services import profile_service

logger = logging.getLogger(__name__)

_UNIQUE_VIOLATION = "23505"  # 중복 pending (부분 유니크) — 멱등 흡수
_MAX_PAGE = 100


class SelfReportNotAllowed(Exception):
    """자기 자신은 신고할 수 없다 (400)."""


class ReportTargetNotFound(Exception):
    """대상 없음 또는 차단 관계 — 존재 은닉 (404)."""


class ReportNotFound(Exception):
    """처리할 pending 신고 없음(없는 id / 이미 처리됨) — 404."""


async def create_report(reporter_id: str, req: ReportCreate) -> None:
    """신고 적재 (성공 204). v1은 target_type='user'만(스키마 Literal이 보증).

    게이트 순서는 follow/block과 동형: self(400) → 존재(404) → 차단(404 은닉).
    중복 pending은 멱등 — 부분 유니크 충돌을 성공으로 흡수(재신고·동시요청 안전).
    """
    if req.target_id == reporter_id:
        raise SelfReportNotAllowed()
    # 대상 유저 존재 확인 — 프로필 없는 유저는 렌더 불가라 신고 대상도 아님
    if await profile_service.get_profile(req.target_id) is None:
        raise ReportTargetNotFound()
    # 차단 게이트(양방향) — 존재 은닉이 최우선(블록 통일 계약)
    if await profile_service.is_blocked_either(req.target_id, reporter_id):
        raise ReportTargetNotFound()

    supabase = get_supabase_admin()
    try:
        await asyncio.to_thread(
            lambda: supabase.table("reports").insert({
                "reporter_id": reporter_id,
                "target_type": req.target_type,
                "target_id": req.target_id,
                "reason": req.reason,
                "detail": req.detail,
            }).execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:
            raise
        # 이미 같은 대상 pending 존재 — 멱등 성공(스팸 재신고·레이스 흡수)


async def list_reports(
    status: str = "pending", limit: int = 20, offset: int = 0
) -> list[ReportItem]:
    """운영진 신고 목록, 최신순 — reporter/target(user형) 프로필 brief 포함."""
    limit = max(1, min(limit, _MAX_PAGE))
    offset = max(0, offset)
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("reports").select("*")
        .eq("status", status)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data
    if not rows:
        return []

    # reporter 전원 + target 중 user형만 프로필 brief 배치 조회(1쿼리)
    ids = [r["reporter_id"] for r in rows] + [
        r["target_id"] for r in rows if r["target_type"] == "user"
    ]
    briefs = await profile_service.get_profile_briefs(ids)

    def _brief(uid: str) -> ReportUserBrief:
        b = briefs.get(uid, {})
        return ReportUserBrief(
            user_id=uid, nickname=b.get("nickname"), avatar_url=b.get("avatar_url")
        )

    return [
        ReportItem(
            id=r["id"],
            reporter=_brief(r["reporter_id"]),
            target_type=r["target_type"],
            target_id=r["target_id"],
            target=_brief(r["target_id"]) if r["target_type"] == "user" else None,
            reason=r["reason"],
            detail=r.get("detail"),
            status=r["status"],
            created_at=r["created_at"],
            reviewed_at=r.get("reviewed_at"),
        )
        for r in rows
    ]


async def decide_report(report_id: str, *, status: str) -> None:
    """pending 신고를 reviewed/dismissed로 처리(단방향) + reviewed_at 기록.

    UPDATE에 status='pending' 조건 — 반환행 없으면 없는 id 또는 이미 처리됨(404).
    동시 처리도 첫 승자만 반영(decide_follow_request L8 패턴).
    """
    supabase = get_supabase_admin()
    upd = await asyncio.to_thread(
        lambda: supabase.table("reports")
        .update({"status": status,
                 "reviewed_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", report_id).eq("status", "pending")
        .execute()
    )
    if not upd.data:
        raise ReportNotFound()
