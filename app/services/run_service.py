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
    RunCommentResponse,
    RunRequest,
    RunResponse,
    RunSplit,
    RunTrackResponse,
    StatsResponse,
)
from app.services import profile_service, track_service

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
    # ── GPS 서버 검증 (설계 2026-07-06): gps_track이 있으면 필터→거리→스플릿.
    # Best-effort: 처리 실패가 기록 저장을 막으면 안 됨 (unverified로 진행).
    processed: track_service.ProcessedTrack | None = None
    verification = "unverified"
    final_distance = req.distance_km
    reported: float | None = None
    is_flagged = False
    if req.gps_track:
        try:
            pts = [
                track_service.TrackPoint(lat=g.lat, lng=g.lng, t_ms=g.t,
                                         acc=g.acc, alt=g.alt)
                for g in req.gps_track
            ]
            processed = track_service.process_track(pts)
            verification = track_service.classify(processed, req.distance_km)
            # DB 체계는 3종(unverified/verified/suspect) + is_flagged —
            # 파이프라인의 'adjusted'는 "verified + is_flagged + 거리 대체"로 매핑.
            if verification == "adjusted":
                reported = req.distance_km          # 앱 신고값 보존
                final_distance = processed.server_distance_km  # 서버 계산이 정본
                verification = "verified"
                is_flagged = True
            elif verification == "suspect":
                is_flagged = True
        except Exception:  # noqa: BLE001 - 검증은 부가 기능, 기록 유실 금지
            logger.warning("GPS 트랙 처리 실패 — unverified로 저장", exc_info=True)
            processed = None
            verification = "unverified"
            is_flagged = False

    # PB 경신 감지 — 저장 "전" 스냅샷과 비교해야 자기 자신이 끼지 않는다.
    # suspect run은 PB 후보가 아니므로 감지 자체를 스킵 (부정 방지).
    new_records: list[NewRecord] = []
    if user_id and verification != "suspect":
        try:
            prev_rows = await _fetch_runs_range(user_id, None, None)
            eff_req = req if final_distance == req.distance_km else req.model_copy(
                update={"distance_km": final_distance, "avg_pace_sec_per_km": None}
            )
            new_records = _detect_new_records(prev_rows, eff_req)
        except Exception:  # noqa: BLE001 - celebration is a bonus, not a gate
            logger.warning("PB 경신 감지 실패 — new_records 없이 저장 진행", exc_info=True)

    # 완료 화면 "평소보다 N초 빨라요" — 최근 30일 평균 페이스(이번 run 제외).
    # 저장 전 스냅샷으로 계산 (best-effort, 실패 시 null — 저장은 막지 않음).
    recent_avg_pace, pace_delta = None, None
    if user_id:
        try:
            recent_avg_pace, pace_delta = await _pace_vs_recent(
                user_id, final_distance, req.duration_sec, req.avg_pace_sec_per_km
            )
        except Exception:  # noqa: BLE001
            logger.warning("페이스 비교 계산 실패", exc_info=True)

    record = {
        "user_id": user_id,
        "route_id": req.route_id,
        "distance_km": final_distance,
        "duration_sec": req.duration_sec,
        "avg_pace_sec_per_km": req.avg_pace_sec_per_km,
        "notes": req.notes,
        "title": req.title,
        "visibility": req.visibility,
        "verification": verification,
        "distance_km_reported": reported,
        "is_flagged": is_flagged,
    }

    supabase = get_supabase_admin()
    result = await asyncio.to_thread(
        lambda: supabase.table("runs").insert(record).execute()
    )

    if not result.data:
        raise RuntimeError("Supabase insert returned no row for the run.")

    saved = result.data[0]
    logger.info("Saved run to Supabase (id=%s, verification=%s).",
                saved.get("id"), verification)

    # 트랙 저장 (best-effort — 실패해도 run은 유지, has_track만 False)
    has_track = False
    splits_out: list[RunSplit] | None = None
    if processed is not None:
        try:
            splits_out = [
                RunSplit(km=s.km, sec=s.sec, elev_gain_m=s.elev_gain_m,
                         partial=s.partial)
                for s in processed.splits
            ]
            await asyncio.to_thread(
                lambda: supabase.table("run_tracks").insert({
                    "run_id": saved["id"],
                    "points": processed.polyline,
                    "splits": [s.model_dump() for s in splits_out],
                    "raw_point_count": processed.point_count_raw,
                    "kept_point_count": processed.point_count_kept,
                    "max_speed_kmh": processed.max_speed_kmh,
                    "avg_accuracy_m": processed.avg_accuracy_m,
                }).execute()
            )
            has_track = True
        except Exception:  # noqa: BLE001
            logger.warning("run_tracks 저장 실패 — run은 유지", exc_info=True)
            splits_out = None

    run = RunResponse(**saved, new_records=new_records,
                      has_track=has_track, splits=splits_out,
                      recent_avg_pace_sec_per_km=recent_avg_pace,
                      pace_delta_sec=pace_delta)

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


async def _pace_vs_recent(
    user_id: str, this_dist: float, this_dur: int, this_pace: int | None
) -> tuple[int | None, int | None]:
    """(최근 30일 평균 페이스, 이번 run 페이스 − 평균). 음수 delta = 빠름.

    이번 run은 아직 저장 전이라 자동으로 제외됨. 최근 30일 run이 없으면
    (None, None). 평균은 sum(duration)/sum(distance) — 거리 가중.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("distance_km, duration_sec")
        .eq("user_id", user_id)
        .gte("ran_at", cutoff)
        .execute()
    )
    rows = res.data
    total_dist = sum(r["distance_km"] for r in rows)
    if not rows or total_dist <= 0:
        return None, None
    recent_avg = round(sum(r["duration_sec"] for r in rows) / total_dist)
    this = this_pace if this_pace else round(this_dur / this_dist) if this_dist > 0 else None
    delta = (this - recent_avg) if this is not None else None
    return recent_avg, delta


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
    rows = [r for r in rows if r.get("verification") != "suspect"]  # 부정 의심 제외
    for r in sorted(rows, key=lambda r: r["ran_at"]):
        dist, dur = r["distance_km"], r["duration_sec"]

        def _entry(value: float) -> RecordEntry:
            return RecordEntry(value=value, run_id=r["id"], ran_at=r["ran_at"],
                               distance_km=round(dist, 1))

        pace = _run_pace(r)
        if pace is not None and dist >= _MIN_PACE_DISTANCE_KM:
            if best.best_pace is None or pace < best.best_pace.value:
                best.best_pace = _entry(pace)
        if dist >= _FIVE_K_KM:
            t5k = round(dur * _FIVE_K_KM / dist)
            if best.best_5k is None or t5k < best.best_5k.value:
                best.best_5k = _entry(t5k)
        if best.longest_distance is None or dist > best.longest_distance.value:
            best.longest_distance = _entry(round(dist, 1))
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
            type="longest_distance", previous=prev.longest_distance.value, current=round(dist, 1),
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
            .select("id, ran_at, distance_km, duration_sec, avg_pace_sec_per_km, "
                    "verification")
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
    raw_dist = sum(r["distance_km"] for r in rows)   # pace 계산은 raw로 (정밀)
    total_dur = sum(r["duration_sec"] for r in rows)
    return PeriodStats(
        total_distance_km=round(raw_dist, 1),        # 표시용 거리 1자리
        run_count=len(rows),
        total_duration_sec=total_dur,
        avg_pace_sec_per_km=round(total_dur / raw_dist) if raw_dist > 0 else None,
        longest_run_km=round(max(r["distance_km"] for r in rows), 1),
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
        week=_aggregate(this_week, round(week_dist - last_week_dist, 1)),
        month=_aggregate(this_month, round(month_dist - last_month_dist, 1)),
        all_time=_aggregate(all_time, delta_distance_km=None),
        # PB는 이미 읽은 all_time rows에서 계산 — 추가 쿼리 없음.
        records=_compute_records(all_time),
    )


async def _track_summaries(run_ids: list[str]) -> dict[str, list[RunSplit]]:
    """{run_id: splits} — 트랙 있는 run만. 목록/단건 응답 enrich용 (배치 1쿼리).

    Best-effort: 실패 시 빈 dict (has_track=False로 표시될 뿐, 조회는 성공).
    """
    if not run_ids:
        return {}
    try:
        supabase = get_supabase_admin()
        res = await asyncio.to_thread(
            lambda: supabase.table("run_tracks")
            .select("run_id, splits")
            .in_("run_id", run_ids)
            .execute()
        )
        return {
            r["run_id"]: [RunSplit.model_validate(s) for s in (r["splits"] or [])]
            for r in res.data
        }
    except Exception:  # noqa: BLE001
        logger.warning("run_tracks 요약 조회 실패 — splits 없이 응답", exc_info=True)
        return {}


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
    row = res.data[0]
    tracks, kudos, comments = await asyncio.gather(
        _track_summaries([row["id"]]),
        _kudos_counts([row["id"]]),
        _comment_counts([row["id"]]),
    )
    return RunResponse(**row, has_track=row["id"] in tracks,
                       splits=tracks.get(row["id"]), kudos_count=kudos.get(row["id"], 0),
                       comment_count=comments.get(row["id"], 0))


async def get_run_track(run_id: str, user_id: str) -> RunTrackResponse | None:
    """run의 경로(폴리라인) — 본인 소유 + 트랙 존재 시에만 (아니면 None → 404)."""
    supabase = get_supabase_admin()
    own = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("id")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not own.data:
        return None
    res = await asyncio.to_thread(
        lambda: supabase.table("run_tracks")
        .select("points, splits, raw_point_count, kept_point_count")
        .eq("run_id", run_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    # server_distance/elev는 컬럼이 없어 splits에서 파생:
    # 총거리 = partial 랩의 km(=총거리) 또는 정수 랩 수, 상승 = 랩 상승 합.
    splits = row.get("splits") or []
    if splits and splits[-1].get("partial"):
        dist = float(splits[-1]["km"])
    else:
        dist = float(len(splits))
    gains = [s["elev_gain_m"] for s in splits if s.get("elev_gain_m") is not None]
    return RunTrackResponse(
        polyline=row["points"],
        server_distance_km=dist,
        elev_gain_m=sum(gains) if gains else None,
        point_count_raw=row["raw_point_count"],
        point_count_kept=row["kept_point_count"],
    )


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
        daily[day].distance_km = round(daily[day].distance_km + r["distance_km"], 1)
        daily[day].run_count += 1

    return MonthlyStatsResponse(
        year=year,
        month=month,
        stats=_aggregate(rows, round(dist - prev_dist, 1)),
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


async def _comment_counts(run_ids: list[str]) -> dict[str, int]:
    """Return {run_id: comment_count} for the given ids (one IN query)."""
    if not run_ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("run_comments")
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


async def _run_owner(run_id: str) -> tuple[str, str]:
    """Return (owner user_id, visibility), or raise RunNotFound."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("user_id, visibility")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise RunNotFound()
    row = res.data[0]
    return row["user_id"], row.get("visibility") or "followers"


class RunNotVisible(Exception):
    """Caller can't see this run (visibility·관계상 차단) — kudos·목록 차단."""


async def _can_see_run(owner_id: str, caller_id: str, visibility: str) -> bool:
    """run이 caller에게 보이는가 — 노출 경로 정책과 일치.

    ① 본인 → 항상 ② private → 본인만(False) ③ public → 누구나(공개 프로필로
    노출되므로) ④ followers → 팔로우 중이거나 같은 크루 소속.
    """
    if owner_id == caller_id:
        return True
    if visibility == "private":
        return False
    if visibility == "public":
        return True
    # visibility == "followers": 팔로우 or 같은 크루
    supabase = get_supabase_admin()
    follow = await asyncio.to_thread(
        lambda: supabase.table("follows")
        .select("follower_id")
        .eq("follower_id", caller_id)
        .eq("following_id", owner_id)
        .limit(1)
        .execute()
    )
    if follow.data:
        return True
    # 같은 크루 소속 여부 — caller의 크루 목록과 owner의 교집합
    my = await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .select("crew_id")
        .eq("user_id", caller_id)
        .execute()
    )
    crew_ids = [r["crew_id"] for r in my.data]
    if not crew_ids:
        return False
    shared = await asyncio.to_thread(
        lambda: supabase.table("crew_members")
        .select("crew_id")
        .eq("user_id", owner_id)
        .in_("crew_id", crew_ids)
        .limit(1)
        .execute()
    )
    return bool(shared.data)


async def give_kudos(run_id: str, user_id: str) -> None:
    """Kudos a run. Idempotent (double-tap safe); own runs are rejected.

    Fires a best-effort run_kudoed notification only on a genuinely new kudos.
    보이지 않는 run(팔로우·크루 무관)에는 kudos 불가 — 알림 스팸 방지 (L1).
    """
    owner_id, visibility = await _run_owner(run_id)
    if owner_id == user_id:
        raise SelfKudos()
    if not await _can_see_run(owner_id, user_id, visibility):
        raise RunNotVisible()

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
    run_id: str, caller_id: str, limit: int = 20, offset: int = 0
) -> list[KudosUserItem]:
    """Users who kudoed a run, newest first, with nickname/avatar (batched).

    가시성 게이트(L1): 보이는 run(본인·팔로우·크루)만 명단 조회 — 아니면
    RunNotVisible (핸들러가 404로 매핑, 존재 은닉).
    """
    owner_id, visibility = await _run_owner(run_id)  # RunNotFound if missing
    if not await _can_see_run(owner_id, caller_id, visibility):
        raise RunNotVisible()
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


# ── run 댓글 (route 댓글과 동형, 가시성은 _can_see_run 게이트 재사용) ──────────

class RunCommentNotFound(Exception):
    """이 run에 그 댓글이 없음 (핸들러가 404로 매핑)."""


class RunCommentAccessDenied(Exception):
    """작성자도 run 주인도 아님 — 삭제 불가 (핸들러가 403)."""


async def list_run_comments(
    run_id: str, caller_id: str, limit: int = 20, offset: int = 0
) -> list[RunCommentResponse]:
    """run 댓글 최신순 — 가시성 게이트(보이는 run만), 닉네임 배치, 페이지네이션.

    안 보이는 run(private 비소유·미팔로우 followers 등)은 RunNotVisible → 404.
    """
    owner_id, visibility = await _run_owner(run_id)  # RunNotFound if missing
    if not await _can_see_run(owner_id, caller_id, visibility):
        raise RunNotVisible()
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("run_comments")
        .select("*")
        .eq("run_id", run_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data
    if not rows:
        return []
    nicknames = await profile_service.get_nicknames([r["user_id"] for r in rows])
    return [
        RunCommentResponse(**row, nickname=nicknames.get(row["user_id"]))
        for row in rows
    ]


async def create_run_comment(
    run_id: str, caller_id: str, content: str
) -> RunCommentResponse:
    """run에 댓글 작성 — 가시성 게이트 통과 시. run 주인에게 run_commented 알림
    (본인 댓글은 미발송). 안 보이는 run이면 RunNotVisible → 404."""
    owner_id, visibility = await _run_owner(run_id)  # RunNotFound if missing
    if not await _can_see_run(owner_id, caller_id, visibility):
        raise RunNotVisible()

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("run_comments")
        .insert({"run_id": run_id, "user_id": caller_id, "content": content})
        .execute()
    )
    row = res.data[0]

    # run 주인에게 알림 (본인 댓글은 self-skip). payload에 run_id (딥링크).
    from app.services import notification_service  # local to avoid circular risk
    try:
        await notification_service.create_notification(
            recipient_id=owner_id,
            actor_id=caller_id,
            type="run_commented",
            target_id=run_id,
            target_type="run",
            payload={"run_id": run_id},
        )
    except Exception:  # noqa: BLE001 - 알림 실패가 댓글 작성을 막지 않음
        logger.warning("run_commented 알림 생성 실패", exc_info=True)

    nick = (await profile_service.get_nicknames([caller_id])).get(caller_id)
    return RunCommentResponse(**row, nickname=nick)


async def delete_run_comment(run_id: str, comment_id: str, caller_id: str) -> None:
    """댓글 삭제 — 작성자 또는 run 주인만. 없으면 RunCommentNotFound(404),
    권한 없으면 RunCommentAccessDenied(403)."""
    supabase = get_supabase_admin()
    c = await asyncio.to_thread(
        lambda: supabase.table("run_comments")
        .select("user_id")
        .eq("id", comment_id)
        .eq("run_id", run_id)
        .limit(1)
        .execute()
    )
    if not c.data:
        raise RunCommentNotFound()

    if c.data[0]["user_id"] != caller_id:
        # 작성자가 아니면 run 주인인지 확인
        owner_id, _ = await _run_owner(run_id)
        if owner_id != caller_id:
            raise RunCommentAccessDenied()

    await asyncio.to_thread(
        lambda: supabase.table("run_comments")
        .delete()
        .eq("id", comment_id)
        .execute()
    )


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
                "avg_pace_sec_per_km, route_id, title")
        .in_("user_id", audience)
        # private run은 본인 것만 (팔로우 대상의 private는 활동 피드에서 제외)
        .or_(f"visibility.neq.private,user_id.eq.{user_id}")
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

    briefs, summaries, kudos_counts, my_kudos, comment_counts = await asyncio.gather(
        profile_service.get_profile_briefs([r["user_id"] for r in rows]),
        _public_route_summaries(),
        _kudos_counts(run_ids),
        _my_kudos_set(run_ids, user_id),
        _comment_counts(run_ids),
    )
    return [
        ActivityFeedItem(
            run_id=row["id"],
            user_id=row["user_id"],
            nickname=briefs.get(row["user_id"], {}).get("nickname"),
            avatar_url=briefs.get(row["user_id"], {}).get("avatar_url"),
            ran_at=row["ran_at"],
            title=row.get("title"),
            distance_km=row["distance_km"],
            duration_sec=row["duration_sec"],
            avg_pace_sec_per_km=row.get("avg_pace_sec_per_km"),
            route_id=row.get("route_id"),
            route_summary=summaries.get(row.get("route_id")),
            comment_count=comment_counts.get(row["id"], 0),
            is_mine=(row["user_id"] == user_id),
            kudos_count=kudos_counts.get(row["id"], 0),
            my_kudos=row["id"] in my_kudos,
        )
        for row in rows
    ]


async def list_user_runs(
    target_id: str, caller_id: str, limit: int = 20, offset: int = 0
) -> list[ActivityFeedItem]:
    """공개 프로필의 '게시한 러닝' — target의 run 중 caller가 볼 수 있는 것만.

    가시성: 본인이면 전부 / public은 누구나 / followers는 caller가 target을
    팔로우할 때 / private은 절대. 카드 shape는 활동 피드와 동일 + title·visibility.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    supabase = get_supabase_admin()

    # caller가 볼 수 있는 visibility 집합 결정 (관계 1쿼리로 판정)
    if caller_id == target_id:
        allowed = ["public", "followers", "private"]
    else:
        follow = await asyncio.to_thread(
            lambda: supabase.table("follows")
            .select("follower_id")
            .eq("follower_id", caller_id)
            .eq("following_id", target_id)
            .limit(1)
            .execute()
        )
        allowed = ["public", "followers"] if follow.data else ["public"]

    runs_res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("id, user_id, ran_at, distance_km, duration_sec, "
                "avg_pace_sec_per_km, route_id, title, visibility")
        .eq("user_id", target_id)
        .in_("visibility", allowed)
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

    brief, summaries, kudos_counts, my_kudos, comment_counts = await asyncio.gather(
        profile_service.get_profile_briefs([target_id]),
        _public_route_summaries(),
        _kudos_counts(run_ids),
        _my_kudos_set(run_ids, caller_id),
        _comment_counts(run_ids),
    )
    is_own = caller_id == target_id
    return [
        ActivityFeedItem(
            run_id=row["id"],
            user_id=row["user_id"],
            nickname=brief.get(target_id, {}).get("nickname"),
            avatar_url=brief.get(target_id, {}).get("avatar_url"),
            ran_at=row["ran_at"],
            title=row.get("title"),
            distance_km=row["distance_km"],
            duration_sec=row["duration_sec"],
            avg_pace_sec_per_km=row.get("avg_pace_sec_per_km"),
            route_id=row.get("route_id"),
            route_summary=summaries.get(row.get("route_id")),
            comment_count=comment_counts.get(row["id"], 0),
            is_mine=is_own,
            kudos_count=kudos_counts.get(row["id"], 0),
            my_kudos=row["id"] in my_kudos,
            # 본인 프로필에서만 visibility 뱃지 렌더 (타인 프로필엔 노출 불필요)
            visibility=row.get("visibility") if is_own else None,
        )
        for row in rows
    ]


async def public_run_count(target_id: str) -> int:
    """target이 '전체 공개'로 게시한 run 수 (공개 프로필 헤더 'N개')."""
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("id", count="exact")
        .eq("user_id", target_id)
        .eq("visibility", "public")
        .execute()
    )
    return res.count or 0


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

        # ④ Sum runs within the challenge period (부정 의심 run 제외)
        runs_res = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .select("distance_km")
            .in_("user_id", member_ids)
            .gte("ran_at", ch_starts_at)
            .lte("ran_at", ch_ends_at)
            .neq("verification", "suspect")
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
    limit = max(1, min(limit, 100))
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
    run_ids = [row["id"] for row in result.data]
    # 배치 집계로 kudos·댓글 수 (활동 피드와 동일 방식, N+1 방지)
    tracks, kudos, comments = await asyncio.gather(
        _track_summaries(run_ids),
        _kudos_counts(run_ids),
        _comment_counts(run_ids),
    )
    return [
        RunResponse(**row, has_track=row["id"] in tracks,
                    splits=tracks.get(row["id"]), kudos_count=kudos.get(row["id"], 0),
                    comment_count=comments.get(row["id"], 0))
        for row in result.data
    ]


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


async def update_run(
    run_id: str, user_id: str, fields: dict
) -> RunResponse | None:
    """저장 화면 편집: 본인 run의 title/visibility/notes만 수정 (보낸 것만).

    거리·시간·검증값은 불변. user_id로 스코프해 남의 run은 0행(None→404).
    빈 patch면 조회만 해서 현재 상태 반환. splits/has_track도 채워 반환.
    """
    supabase = get_supabase_admin()
    if fields:
        result = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .update(fields)
            .eq("id", run_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            return None
        logger.info("Updated run (id=%s, fields=%s).", run_id, list(fields))
    # 편집 후(또는 빈 patch) 최신 상태를 splits까지 채워 반환
    return await get_run(run_id, user_id)
