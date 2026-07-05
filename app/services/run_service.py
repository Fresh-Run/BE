"""Persistence for actual run logs (the `runs` table)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from postgrest.exceptions import APIError

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import (
    ActivityFeedItem,
    DailyRunStat,
    FeedbackTag,
    KudosUserItem,
    MonthlyStatsResponse,
    NewRecord,
    PeriodStats,
    RecordEntry,
    RecordsBlock,
    RunRequest,
    RunResponse,
    StatsResponse,
)
from app.services import profile_service

_UNIQUE_VIOLATION = "23505"


class RunNotFound(Exception):
    """No run with that id."""


class SelfKudos(Exception):
    """A user tried to kudos their own run (not allowed, Strava-style)."""

logger = logging.getLogger(__name__)


async def create_run(req: RunRequest, user_id: str | None = None) -> RunResponse:
    """Insert a run log into Supabase and return the stored record.

    Unlike route persistence, saving IS the purpose here, so a failure
    propagates to the caller (the API layer turns it into an HTTP error).

    user_id (from a validated token) is stored as the owner; None for
    anonymous requests. supabase-py is synchronous, so the blocking call
    runs in a worker thread.
    """
    # PB 경신 감지 — 저장 "전" 스냅샷과 비교해야 자기 자신이 끼지 않는다.
    # Best-effort: 감지 실패가 run 저장을 막으면 안 됨 (new_records=[]로 진행).
    new_records: list[NewRecord] = []
    if user_id:
        try:
            prev_rows = await _fetch_runs_range(user_id, None, None)
            new_records = _detect_new_records(prev_rows, req)
        except Exception:  # noqa: BLE001 - celebration is a bonus, not a gate
            logger.warning("PB 경신 감지 실패 — new_records 없이 저장 진행", exc_info=True)

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
    run = RunResponse(**saved, new_records=new_records)

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


# ── personal bests (PB) ──────────────────────────────────────────────────────
# PB 테이블 없음 — 조회 시 runs에서 집계 (개인당 수백 개 규모, 항상 정확).

_MIN_PACE_DISTANCE_KM = 1.0  # 최고 페이스 자격: 100m 스퍼트 방지
_FIVE_K_KM = 5.0


def _run_pace(row: dict) -> float | None:
    """sec/km — 저장된 avg_pace_sec_per_km, 없으면 duration/distance 파생."""
    pace = row.get("avg_pace_sec_per_km")
    if pace:
        return float(pace)
    dist = row.get("distance_km") or 0
    if dist <= 0:
        return None
    return float(round(row["duration_sec"] / dist))


def _compute_records(rows: list[dict]) -> RecordsBlock:
    """All-time PB 4종 (rows: id, ran_at, distance_km, duration_sec, avg_pace_sec_per_km).

    ran_at 오름차순으로 순회하며 strict 비교로만 갱신 → 동률이면 먼저
    달성한 run이 유지된다.
    """
    best = RecordsBlock()
    for r in sorted(rows, key=lambda r: r["ran_at"]):
        dist, dur = r["distance_km"], r["duration_sec"]

        def _entry(value: float) -> RecordEntry:
            return RecordEntry(value=value, run_id=r["id"], ran_at=r["ran_at"],
                               distance_km=round(dist, 2))

        pace = _run_pace(r)
        if pace is not None and dist >= _MIN_PACE_DISTANCE_KM:
            if best.best_pace is None or pace < best.best_pace.value:
                best.best_pace = _entry(pace)
        if dist >= _FIVE_K_KM:
            t5k = round(dur * _FIVE_K_KM / dist)
            if best.best_5k is None or t5k < best.best_5k.value:
                best.best_5k = _entry(t5k)
        if best.longest_distance is None or dist > best.longest_distance.value:
            best.longest_distance = _entry(round(dist, 2))
        if best.longest_duration is None or dur > best.longest_duration.value:
            best.longest_duration = _entry(dur)
    return best


def _improvement_pct(previous: float, current: float, lower_is_better: bool) -> float:
    delta = (previous - current) if lower_is_better else (current - previous)
    return round(delta / previous * 100, 1)


def _detect_new_records(prev_rows: list[dict], req: RunRequest) -> list[NewRecord]:
    """저장 전 스냅샷(prev_rows) 대비 새 run(req)이 경신한 PB 목록.

    "경신"은 종전 기록의 존재를 전제 — 첫 run(또는 그 종류의 첫 자격 run)은
    빈 목록/미포함이라 축하 모달이 도배되지 않는다.
    """
    if not prev_rows:
        return []
    prev = _compute_records(prev_rows)
    dist, dur = req.distance_km, req.duration_sec
    pace = float(req.avg_pace_sec_per_km) if req.avg_pace_sec_per_km else float(round(dur / dist))

    out: list[NewRecord] = []
    if (prev.best_pace is not None and dist >= _MIN_PACE_DISTANCE_KM
            and pace < prev.best_pace.value):
        out.append(NewRecord(type="best_pace", previous=prev.best_pace.value, current=pace,
                             improvement_pct=_improvement_pct(prev.best_pace.value, pace, True)))
    if prev.best_5k is not None and dist >= _FIVE_K_KM:
        t5k = round(dur * _FIVE_K_KM / dist)
        if t5k < prev.best_5k.value:
            out.append(NewRecord(type="best_5k", previous=prev.best_5k.value, current=t5k,
                                 improvement_pct=_improvement_pct(prev.best_5k.value, t5k, True)))
    if prev.longest_distance is not None and dist > prev.longest_distance.value:
        out.append(NewRecord(
            type="longest_distance", previous=prev.longest_distance.value, current=round(dist, 2),
            improvement_pct=_improvement_pct(prev.longest_distance.value, dist, False)))
    if prev.longest_duration is not None and dur > prev.longest_duration.value:
        out.append(NewRecord(
            type="longest_duration", previous=prev.longest_duration.value, current=dur,
            improvement_pct=_improvement_pct(prev.longest_duration.value, dur, False)))
    return out


async def _fetch_runs_range(
    user_id: str, start: str | None, end: str | None
) -> list[dict]:
    """Return run rows for user_id within [start, end).

    id/ran_at/avg_pace는 PB 집계(_compute_records)용 — 통계 집계(_aggregate)는
    distance_km/duration_sec만 쓴다.
    """
    supabase = get_supabase_admin()

    def _q():
        q = (
            supabase.table("runs")
            .select("id, ran_at, distance_km, duration_sec, avg_pace_sec_per_km")
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
        # PB는 이미 읽은 all_time rows에서 계산 — 추가 쿼리 없음.
        records=_compute_records(all_time),
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


async def _kudos_counts(run_ids: list[str]) -> dict[str, int]:
    """Return {run_id: kudos_count} for the given ids (one IN query)."""
    if not run_ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("run_kudos")
        .select("run_id")
        .in_("run_id", run_ids)
        .execute()
    )
    counts: dict[str, int] = {}
    for row in res.data:
        counts[row["run_id"]] = counts.get(row["run_id"], 0) + 1
    return counts


async def _my_kudos_set(run_ids: list[str], user_id: str) -> set[str]:
    """Return the set of run_ids that user_id has kudoed (one IN + eq query)."""
    if not run_ids:
        return set()
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("run_kudos")
        .select("run_id")
        .in_("run_id", run_ids)
        .eq("user_id", user_id)
        .execute()
    )
    return {row["run_id"] for row in res.data}


async def _run_owner(run_id: str) -> str:
    """Return the run owner's user_id, or raise RunNotFound."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("user_id")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise RunNotFound()
    return res.data[0]["user_id"]


async def give_kudos(run_id: str, user_id: str) -> None:
    """Kudos a run. Idempotent (double-tap safe); own runs are rejected.

    Fires a best-effort run_kudoed notification only on a genuinely new kudos.
    """
    owner_id = await _run_owner(run_id)
    if owner_id == user_id:
        raise SelfKudos()

    supabase = get_supabase_admin()
    kudos_new = True
    try:
        await asyncio.to_thread(
            lambda: supabase.table("run_kudos")
            .insert({"run_id": run_id, "user_id": user_id})
            .execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:  # 23505 = already kudoed, fine
            raise
        kudos_new = False

    if kudos_new:
        from app.services import notification_service  # local to avoid circular risk

        try:
            await notification_service.create_notification(
                recipient_id=owner_id,
                actor_id=user_id,
                type="run_kudoed",
                target_id=run_id,
                target_type="run",
            )
        except Exception:  # noqa: BLE001
            logger.warning("run_kudoed 알림 생성 실패", exc_info=True)


async def remove_kudos(run_id: str, user_id: str) -> None:
    """Remove a kudos. Idempotent: removing a non-kudos is a no-op."""
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("run_kudos")
        .delete()
        .eq("run_id", run_id)
        .eq("user_id", user_id)
        .execute()
    )


async def list_kudos_users(
    run_id: str, limit: int = 20, offset: int = 0
) -> list[KudosUserItem]:
    """Users who kudoed a run, newest first, with nickname/avatar (batched)."""
    await _run_owner(run_id)  # 404 if the run doesn't exist
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("run_kudos")
        .select("user_id, created_at")
        .eq("run_id", run_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data
    if not rows:
        return []
    briefs = await profile_service.get_profile_briefs([r["user_id"] for r in rows])
    return [
        KudosUserItem(
            user_id=row["user_id"],
            nickname=briefs.get(row["user_id"], {}).get("nickname"),
            avatar_url=briefs.get(row["user_id"], {}).get("avatar_url"),
            created_at=row["created_at"],
        )
        for row in rows
    ]


async def list_activity_feed(
    user_id: str, limit: int = 20, offset: int = 0
) -> list[ActivityFeedItem]:
    """Following activity feed: runs by followed users + my own, newest ran_at.

    Same shape/privacy rules as the crew feed (CrewRunItem base), plus kudos.
    Kept separate from crew_service.list_crew_runs on purpose — different
    audience rule (follows vs membership) and item schema; the batch helpers
    (_kudos_counts/_my_kudos_set) are the shared parts.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("follows")
        .select("following_id")
        .eq("follower_id", user_id)
        .execute()
    )
    audience = [row["following_id"] for row in res.data] + [user_id]

    runs_res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("id, user_id, ran_at, distance_km, duration_sec, "
                "avg_pace_sec_per_km, route_id")
        .in_("user_id", audience)
        .order("ran_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = runs_res.data
    if not rows:
        return []

    run_ids = [r["id"] for r in rows]
    route_ids = list({r["route_id"] for r in rows if r.get("route_id")})

    async def _public_route_summaries() -> dict[str, str]:
        """Public courses only — private ones must not leak into the feed."""
        if not route_ids:
            return {}
        r = await asyncio.to_thread(
            lambda: supabase.table("routes")
            .select("id, summary")
            .in_("id", route_ids)
            .eq("is_public", True)
            .execute()
        )
        return {row["id"]: row["summary"] for row in r.data}

    briefs, summaries, kudos_counts, my_kudos = await asyncio.gather(
        profile_service.get_profile_briefs([r["user_id"] for r in rows]),
        _public_route_summaries(),
        _kudos_counts(run_ids),
        _my_kudos_set(run_ids, user_id),
    )
    return [
        ActivityFeedItem(
            run_id=row["id"],
            user_id=row["user_id"],
            nickname=briefs.get(row["user_id"], {}).get("nickname"),
            avatar_url=briefs.get(row["user_id"], {}).get("avatar_url"),
            ran_at=row["ran_at"],
            distance_km=row["distance_km"],
            duration_sec=row["duration_sec"],
            avg_pace_sec_per_km=row.get("avg_pace_sec_per_km"),
            route_id=row.get("route_id"),
            route_summary=summaries.get(row.get("route_id")),
            is_mine=(row["user_id"] == user_id),
            kudos_count=kudos_counts.get(row["id"], 0),
            my_kudos=row["id"] in my_kudos,
        )
        for row in rows
    ]


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
