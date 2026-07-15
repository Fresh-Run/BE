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
from app.models.schemas import ReportCreate, ReportItem, ReportRunBrief, ReportUserBrief
from app.services import profile_service, run_service

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
    """신고 적재 (성공 204). target_type 'user'(v1)·'run'(2026-07-15 오픈).

    게이트 순서는 follow/block과 동형: self(400) → 존재(404) → 차단·비가시(404 은닉).
    run은 _can_see_run(결정 A′·visibility 합성·차단 포함) 그대로 재사용 — 내가 볼 수
    없는 run은 존재 자체를 은닉(피드에 안 뜨는 run의 존재를 신고 API가 누설 금지).
    중복 pending은 멱등 — 부분 유니크 충돌을 성공으로 흡수(재신고·동시요청 안전).
    """
    if req.target_type == "run":
        await _ensure_run_reportable(reporter_id, req.target_id)
    else:
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


async def _ensure_run_reportable(reporter_id: str, run_id: str) -> None:
    """run 신고 게이트: 존재(404) → self run(400) → 가시성·차단(404 은닉)."""
    try:
        owner_id, visibility = await run_service._run_owner(run_id)
    except run_service.RunNotFound:
        raise ReportTargetNotFound()
    if owner_id == reporter_id:
        raise SelfReportNotAllowed()
    # 차단(양방향)은 _can_see_run이 최우선 False — user 신고의 은닉 계약과 동일
    if not await run_service._can_see_run(owner_id, reporter_id, visibility):
        raise ReportTargetNotFound()


async def list_reports(
    status: str = "pending", limit: int = 20, offset: int = 0
) -> list[ReportItem]:
    """운영진 신고 목록, 최신순 — reporter/target(user형) 프로필 brief +
    run형은 run 요약(제목·소유자) 포함. 삭제된 run은 target_run=null(행은 잔존)."""
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

    # run형 target은 runs 배치 조회(1쿼리) — 삭제된 run은 결과에 없음(brief null)
    run_ids = [r["target_id"] for r in rows if r["target_type"] == "run"]
    runs_by_id: dict[str, dict] = {}
    if run_ids:
        run_res = await asyncio.to_thread(
            lambda: supabase.table("runs").select("id, title, user_id")
            .in_("id", run_ids).execute()
        )
        runs_by_id = {r["id"]: r for r in run_res.data}

    # reporter 전원 + user형 target + run형 소유자 프로필 brief 배치 조회(1쿼리)
    ids = [r["reporter_id"] for r in rows] + [
        r["target_id"] for r in rows if r["target_type"] == "user"
    ] + [r["user_id"] for r in runs_by_id.values()]
    briefs = await profile_service.get_profile_briefs(ids)

    def _brief(uid: str) -> ReportUserBrief:
        b = briefs.get(uid, {})
        return ReportUserBrief(
            user_id=uid, nickname=b.get("nickname"), avatar_url=b.get("avatar_url")
        )

    def _run_brief(run_id: str) -> ReportRunBrief | None:
        run = runs_by_id.get(run_id)
        if run is None:  # 삭제된 run — 신고 행은 남되 대상 요약만 null
            return None
        return ReportRunBrief(
            run_id=run["id"], title=run.get("title"), owner=_brief(run["user_id"])
        )

    return [
        ReportItem(
            id=r["id"],
            reporter=_brief(r["reporter_id"]),
            target_type=r["target_type"],
            target_id=r["target_id"],
            target=_brief(r["target_id"]) if r["target_type"] == "user" else None,
            target_run=_run_brief(r["target_id"]) if r["target_type"] == "run" else None,
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
