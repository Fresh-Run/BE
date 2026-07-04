"""Persistence for actual run logs (the `runs` table)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import (
    DailyRunStat,
    FeedbackTag,
    MonthlyStatsResponse,
    PeriodStats,
    RunRequest,
    RunResponse,
    StatsResponse,
)

logger = logging.getLogger(__name__)


async def create_run(req: RunRequest, user_id: str | None = None) -> RunResponse:
    """Insert a run log into Supabase and return the stored record.

    Unlike route persistence, saving IS the purpose here, so a failure
    propagates to the caller (the API layer turns it into an HTTP error).

    user_id (from a validated token) is stored as the owner; None for
    anonymous requests. supabase-py is synchronous, so the blocking call
    runs in a worker thread.
    """
    record = {
        "user_id": user_id,
        "route_id": req.route_id,
        "distance_km": req.distance_km,
        "duration_sec": req.duration_sec,
        "avg_pace_sec_per_km": req.avg_pace_sec_per_km,
        "notes": req.notes,
    }

    supabase = get_supabase_admin()
    result = await asyncio.to_thread(
        lambda: supabase.table("runs").insert(record).execute()
    )

    if not result.data:
        raise RuntimeError("Supabase insert returned no row for the run.")

    saved = result.data[0]
    logger.info("Saved run to Supabase (id=%s).", saved.get("id"))
    run = RunResponse(**saved)

    if user_id:
        try:
            await _check_challenge_completion(user_id)
        except Exception:
            logger.warning("챌린지 달성 알림 실패", exc_info=True)

    return run


_KST = timezone(timedelta(hours=9))


def _week_start_utc() -> str:
    """Return this Monday 00:00 KST as a UTC ISO string."""
    now_kst = datetime.now(_KST)
    monday = (now_kst - timedelta(days=now_kst.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday.astimezone(timezone.utc).isoformat()


def _month_boundaries_utc() -> tuple[str, str]:
    """Return (this_month_start, last_month_start) as UTC ISO strings."""
    now_kst = datetime.now(_KST)
    this_month = now_kst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day_prev = this_month - timedelta(days=1)
    last_month = last_day_prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (
        this_month.astimezone(timezone.utc).isoformat(),
        last_month.astimezone(timezone.utc).isoformat(),
    )


async def _fetch_runs_range(
    user_id: str, start: str | None, end: str | None
) -> list[dict]:
    """Return distance_km + duration_sec rows for user_id within [start, end)."""
    supabase = get_supabase_admin()

    def _q():
        q = (
            supabase.table("runs")
            .select("distance_km, duration_sec")
            .eq("user_id", user_id)
        )
        if start:
            q = q.gte("ran_at", start)
        if end:
            q = q.lt("ran_at", end)
        return q.execute()

    return (await asyncio.to_thread(_q)).data


def _aggregate(rows: list[dict], delta_distance_km: float | None) -> PeriodStats:
    """Compute PeriodStats from a list of {distance_km, duration_sec} rows."""
    if not rows:
        return PeriodStats(
            total_distance_km=0.0,
            run_count=0,
            total_duration_sec=0,
            avg_pace_sec_per_km=None,
            longest_run_km=None,
            delta_distance_km=delta_distance_km,
        )
    total_dist = round(sum(r["distance_km"] for r in rows), 2)
    total_dur = sum(r["duration_sec"] for r in rows)
    return PeriodStats(
        total_distance_km=total_dist,
        run_count=len(rows),
        total_duration_sec=total_dur,
        avg_pace_sec_per_km=round(total_dur / total_dist) if total_dist > 0 else None,
        longest_run_km=round(max(r["distance_km"] for r in rows), 2),
        delta_distance_km=delta_distance_km,
    )


async def get_my_stats(user_id: str) -> StatsResponse:
    """Return week / month / all_time running statistics for the caller (KST-based)."""
    week_start = _week_start_utc()
    last_week_start = (
        datetime.fromisoformat(week_start) - timedelta(weeks=1)
    ).isoformat()
    month_start, last_month_start = _month_boundaries_utc()

    (this_week, last_week, this_month, last_month, all_time) = await asyncio.gather(
        _fetch_runs_range(user_id, week_start, None),
        _fetch_runs_range(user_id, last_week_start, week_start),
        _fetch_runs_range(user_id, month_start, None),
        _fetch_runs_range(user_id, last_month_start, month_start),
        _fetch_runs_range(user_id, None, None),
    )

    week_dist = sum(r["distance_km"] for r in this_week)
    last_week_dist = sum(r["distance_km"] for r in last_week)
    month_dist = sum(r["distance_km"] for r in this_month)
    last_month_dist = sum(r["distance_km"] for r in last_month)

    return StatsResponse(
        week=_aggregate(this_week, round(week_dist - last_week_dist, 2)),
        month=_aggregate(this_month, round(month_dist - last_month_dist, 2)),
        all_time=_aggregate(all_time, delta_distance_km=None),
    )


async def get_run(run_id: str, user_id: str) -> RunResponse | None:
    """Return one run, or None if it doesn't exist or isn't the caller's."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("*")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    return RunResponse(**res.data[0])


def _month_range_utc(year: int, month: int) -> tuple[str, str]:
    """Return [month start, next month start) for a KST month, as UTC ISO."""
    start = datetime(year, month, 1, tzinfo=_KST)
    end = datetime(year + 1, 1, 1, tzinfo=_KST) if month == 12 else datetime(
        year, month + 1, 1, tzinfo=_KST
    )
    return (
        start.astimezone(timezone.utc).isoformat(),
        end.astimezone(timezone.utc).isoformat(),
    )


async def get_monthly_stats(
    user_id: str, year: int, month: int
) -> MonthlyStatsResponse:
    """Stats for one KST month + per-day breakdown (기록 탭 캘린더용).

    `days` lists only the dates that have runs, so the calendar can dot
    them directly; `stats.delta_distance_km` compares to the previous month.
    """
    start, end = _month_range_utc(year, month)
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    prev_start, _ = _month_range_utc(prev_year, prev_month)

    def _q():
        return (
            get_supabase_admin()
            .table("runs")
            .select("ran_at, distance_km, duration_sec")
            .eq("user_id", user_id)
            .gte("ran_at", start)
            .lt("ran_at", end)
            .execute()
        )

    rows, prev_rows = await asyncio.gather(
        asyncio.to_thread(_q),
        _fetch_runs_range(user_id, prev_start, start),
    )
    rows = rows.data

    dist = sum(r["distance_km"] for r in rows)
    prev_dist = sum(r["distance_km"] for r in prev_rows)

    daily: dict[str, DailyRunStat] = {}
    for r in rows:
        day = datetime.fromisoformat(r["ran_at"]).astimezone(_KST).date().isoformat()
        if day not in daily:
            daily[day] = DailyRunStat(date=day, distance_km=0.0, run_count=0)
        daily[day].distance_km = round(daily[day].distance_km + r["distance_km"], 2)
        daily[day].run_count += 1

    return MonthlyStatsResponse(
        year=year,
        month=month,
        stats=_aggregate(rows, round(dist - prev_dist, 2)),
        days=sorted(daily.values(), key=lambda d: d.date),
    )


async def _check_challenge_completion(user_id: str) -> None:
    """After a run is saved, check if any active crew challenge just hit its goal.

    Sends challenge_completed notifications to all crew members (including the
    triggering runner). Atomic "first-to-claim" via UPDATE WHERE
    completed_notified=false — so concurrent requests never double-notify.
    """
    from app.services import notification_service  # local to avoid circular risk

    supabase = get_supabase_admin()
    now_utc = datetime.now(timezone.utc).isoformat()

    # ① Early exit: is this user in any crew?
    crews_res = await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .select("crew_id")
        .eq("user_id", user_id)
        .execute()
    )
    crew_ids = [r["crew_id"] for r in crews_res.data]
    if not crew_ids:
        return

    # ② Early exit: any active uncompleted challenges in those crews?
    chal_res = await asyncio.to_thread(
        lambda: supabase.table("crew_challenges")
        .select("id, crew_id, goal_km, starts_at, ends_at")
        .in_("crew_id", crew_ids)
        .lte("starts_at", now_utc)
        .gte("ends_at", now_utc)
        .eq("completed_notified", False)
        .execute()
    )
    if not chal_res.data:
        return

    for ch in chal_res.data:
        ch_id = ch["id"]
        ch_crew_id = ch["crew_id"]
        ch_starts_at = ch["starts_at"]
        ch_ends_at = ch["ends_at"]
        ch_goal_km = float(ch["goal_km"])

        # ③ Get all crew members
        members_res = await asyncio.to_thread(
            lambda: supabase.table("crew_members")
            .select("user_id")
            .eq("crew_id", ch_crew_id)
            .execute()
        )
        member_ids = [r["user_id"] for r in members_res.data]
        if not member_ids:
            continue

        # ④ Sum runs within the challenge period
        runs_res = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .select("distance_km")
            .in_("user_id", member_ids)
            .gte("ran_at", ch_starts_at)
            .lte("ran_at", ch_ends_at)
            .execute()
        )
        achieved_km = sum(r["distance_km"] for r in runs_res.data)
        if achieved_km < ch_goal_km:
            continue

        # ⑤ Atomic claim: only the first request that flips the flag sends notifications
        upd_res = await asyncio.to_thread(
            lambda: supabase.table("crew_challenges")
            .update({"completed_notified": True})
            .eq("id", ch_id)
            .eq("completed_notified", False)
            .execute()
        )
        if not upd_res.data:
            continue  # another concurrent request already claimed it

        # ⑥ Notify all members (self-notification allowed: triggering runner included)
        await asyncio.gather(*[
            notification_service.create_notification(
                recipient_id=mid,
                actor_id=user_id,
                type="challenge_completed",
                target_id=ch_crew_id,
                target_type="crew",
                allow_self=True,
            )
            for mid in member_ids
        ])
        logger.info(
            "Challenge %s completed (achieved=%.2fkm, goal=%.2fkm); notified %d members.",
            ch_id, achieved_km, ch_goal_km, len(member_ids),
        )


async def list_runs(
    user_id: str, limit: int = 20, route_id: str | None = None
) -> list[RunResponse]:
    """Return the caller's logged runs, newest first; optionally filter by route.

    Scoped to `user_id` in app code (service_role bypasses RLS).
    """
    supabase = get_supabase_admin()

    def _query():
        q = (
            supabase.table("runs")
            .select("*")
            .eq("user_id", user_id)
            .order("ran_at", desc=True)
            .limit(limit)
        )
        if route_id is not None:
            q = q.eq("route_id", route_id)
        return q.execute()

    result = await asyncio.to_thread(_query)
    return [RunResponse(**row) for row in result.data]


async def set_feedback(
    run_id: str, liked: bool, tags: list[FeedbackTag], user_id: str
) -> RunResponse | None:
    """Attach feedback to one of the caller's runs; return the row, or None.

    The update is scoped to `user_id`, so it affects 0 rows (returns None ->
    404) if the run doesn't exist OR isn't owned by the caller. This enforces
    "feedback only on my own runs" without a separate read. The run's owner
    (user_id) is never modified.
    """
    update = {
        "liked": liked,
        "feedback_tags": [t.value for t in tags],
        "feedback_at": datetime.now(timezone.utc).isoformat(),
    }

    supabase = get_supabase_admin()
    result = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .update(update)
        .eq("id", run_id)
        .eq("user_id", user_id)
        .execute()
    )

    if not result.data:
        return None

    updated = result.data[0]
    logger.info("Saved feedback for run (id=%s, liked=%s).", run_id, liked)
    return RunResponse(**updated)
