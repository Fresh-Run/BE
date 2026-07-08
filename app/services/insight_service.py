"""AI 월간 인사이트 (프리미엄): 수치 블록 계산 + AI 텍스트 캐시.

수치(stats/weeks/records/pattern)는 매 요청 runs에서 계산 — 항상 최신.
AI 블록(coaching + plan)만 monthly_insights에 캐시하며, 캐시 키는
(user, year, month) + 생성 시점 run_count: 이번 달은 러닝할 때만 재생성되고
지난달은 run_count가 변하지 않아 자동 영구 캐시가 된다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.supabase_client import get_supabase_admin
from app.models.schemas import (
    InsightAi,
    InsightPattern,
    InsightPlanItem,
    MonthlyInsightResponse,
    MonthRecordEntry,
    PaceTrendPoint,
    WeekStat,
)
from app.services import openai_service, profile_service
from app.services.run_service import (
    _KST,
    _aggregate,
    _compute_records,
    _fetch_runs_range,
    _month_range_utc,
)

logger = logging.getLogger(__name__)

_SLOT_ORDER = ["goal", "focus", "challenge"]

# KST 시간대 버킷: (이름, 시작시각(포함), 끝시각(미포함)) — night는 랩어라운드
_TOD_BUCKETS = [
    ("dawn", 4, 6),
    ("morning", 6, 9),
    ("day", 9, 17),
    ("evening", 17, 21),
]


def _kst_dt(ran_at: str) -> datetime:
    return datetime.fromisoformat(ran_at).astimezone(_KST)


def _split_weeks(rows: list[dict], year: int, month: int) -> list[WeekStat]:
    """월 내 캘린더 주차(KST 월요일 시작)별 합계 — 빈 주도 포함 (차트용)."""
    first = datetime(year, month, 1, tzinfo=_KST)
    offset = first.weekday()  # 월=0 … 일=6 (1일이 낀 주의 앞쪽 빈 칸 수)
    if month == 12:
        days_in_month = 31
    else:
        days_in_month = (datetime(year, month + 1, 1, tzinfo=_KST)
                         - first).days
    total_weeks = (days_in_month + offset + 6) // 7

    buckets: dict[int, list[dict]] = {i: [] for i in range(1, total_weeks + 1)}
    for r in rows:
        d = _kst_dt(r["ran_at"])
        idx = (d.day - 1 + offset) // 7 + 1
        buckets[idx].append(r)

    out = []
    for idx in range(1, total_weeks + 1):
        rs = buckets[idx]
        dist = round(sum(r["distance_km"] for r in rs), 1)
        dur = sum(r["duration_sec"] for r in rs)
        out.append(WeekStat(
            index=idx,
            distance_km=dist,
            run_count=len(rs),
            avg_pace_sec_per_km=round(dur / dist) if dist > 0 else None,
        ))
    return out


def _month_records(
    month_rows: list[dict], rows_until_month_end: list[dict], year: int, month: int
) -> list[MonthRecordEntry]:
    """해당 월 종목별 최고 + all_time_best(그 달에 올타임 경신했는지).

    all_time_best는 '월 말까지의 전체 runs' 기준 올타임 PB의 달성 월이 해당
    월인지로 판정 — 과거 달을 조회해도 그 시점 기준으로 정확하다.
    """
    month_best = _compute_records(month_rows)
    all_best = _compute_records(rows_until_month_end)

    def _in_month(ran_at: str) -> bool:
        d = _kst_dt(ran_at)
        return d.year == year and d.month == month

    out: list[MonthRecordEntry] = []
    for rtype in ("best_pace", "best_5k", "longest_distance", "longest_duration"):
        entry = getattr(month_best, rtype)
        if entry is None:
            continue
        at_entry = getattr(all_best, rtype)
        out.append(MonthRecordEntry(
            type=rtype,
            value=entry.value,
            ran_at=entry.ran_at,
            distance_km=entry.distance_km,
            all_time_best=bool(at_entry and _in_month(at_entry.ran_at)),
        ))
    return out


def _compute_pattern(rows: list[dict]) -> InsightPattern:
    """요일 분포 · 최빈 시간대 · 월 내 최장 연속 러닝 일수 (전부 KST)."""
    weekday = [0] * 7
    tod_counts = {"dawn": 0, "morning": 0, "day": 0, "evening": 0, "night": 0}
    days: set[str] = set()
    for r in rows:
        d = _kst_dt(r["ran_at"])
        weekday[d.weekday()] += 1
        days.add(d.date().isoformat())
        for name, lo, hi in _TOD_BUCKETS:
            if lo <= d.hour < hi:
                tod_counts[name] += 1
                break
        else:
            tod_counts["night"] += 1  # 21시~익일 4시

    time_of_day = None
    pct = None
    if rows:
        time_of_day = max(tod_counts, key=lambda k: tod_counts[k])
        pct = round(tod_counts[time_of_day] / len(rows) * 100)

    # 월 내 연속 일수 (rows가 이미 월 범위라 자연히 월 내 한정)
    streak = best = 0
    prev = None
    for day in sorted(days):
        cur = datetime.fromisoformat(day).date()
        streak = streak + 1 if prev is not None and (cur - prev).days == 1 else 1
        best = max(best, streak)
        prev = cur
    return InsightPattern(
        weekday_counts=weekday,
        time_of_day=time_of_day,
        time_of_day_pct=pct,
        longest_streak_days=best,
        run_days=len(days),
    )


def _sanitize_plan(raw: list[dict]) -> list[InsightPlanItem]:
    """slot 검증 + goal/focus/challenge 순 정렬 + 슬롯당 1개."""
    by_slot: dict[str, InsightPlanItem] = {}
    for item in raw:
        p = InsightPlanItem.model_validate(item)
        by_slot.setdefault(p.slot, p)
    plan = [by_slot[s] for s in _SLOT_ORDER if s in by_slot]
    if not plan:
        raise ValueError("Insight plan came back empty.")
    return plan


async def _cached_ai(user_id: str, year: int, month: int) -> dict | None:
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("monthly_insights")
        .select("run_count, coaching, plan, created_at")
        .eq("user_id", user_id)
        .eq("year", year)
        .eq("month", month)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def _ai_block(
    user_id: str,
    year: int,
    month: int,
    run_count: int,
    stats_kwargs: dict,
) -> InsightAi | None:
    """AI 텍스트 — run 0회면 None, 캐시 유효하면 재사용, 아니면 생성 후 upsert."""
    if run_count == 0:
        return None

    cached = await _cached_ai(user_id, year, month)
    if cached and cached["run_count"] == run_count:
        return InsightAi(
            coaching=cached["coaching"],
            plan=_sanitize_plan(cached["plan"]),
            generated_at=cached["created_at"],
            from_cache=True,
        )

    # 본인 언어 설정 조회 (생성 시에만 — 캐시 히트면 위에서 이미 반환). 실패 시 ko.
    try:
        lang = (await profile_service.get_settings(user_id)).lang
    except Exception:  # noqa: BLE001
        lang = "ko"
    raw = await openai_service.generate_monthly_insight(lang=lang, **stats_kwargs)
    coaching = str(raw.get("coaching") or "").strip()
    if not coaching:
        raise ValueError("Insight coaching came back empty.")
    plan = _sanitize_plan(raw.get("plan") or [])

    now = datetime.now(timezone.utc).isoformat()
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("monthly_insights").upsert({
            "user_id": user_id,
            "year": year,
            "month": month,
            "run_count": run_count,
            "coaching": coaching,
            "plan": [p.model_dump() for p in plan],
            "model": settings.openai_model,
            "created_at": now,
        }).execute()
    )
    logger.info("Monthly insight 생성 (user=%s, %d-%02d)", user_id, year, month)
    return InsightAi(coaching=coaching, plan=plan, generated_at=now, from_cache=False)


async def get_monthly_insight(
    user_id: str, year: int, month: int
) -> MonthlyInsightResponse:
    """프리미엄 월간 리포트 — 프리미엄 게이트는 API 레이어에서 선행."""
    start, end = _month_range_utc(year, month)
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    prev_start, _ = _month_range_utc(prev_year, prev_month)
    p2_year, p2_month = ((prev_year - 1, 12) if prev_month == 1
                         else (prev_year, prev_month - 1))
    p2_start, _ = _month_range_utc(p2_year, p2_month)

    month_rows, prev_rows, prev2_rows, rows_until_end = await asyncio.gather(
        _fetch_runs_range(user_id, start, end),
        _fetch_runs_range(user_id, prev_start, start),
        _fetch_runs_range(user_id, p2_start, prev_start),
        _fetch_runs_range(user_id, None, end),
    )

    dist = sum(r["distance_km"] for r in month_rows)
    prev_dist = sum(r["distance_km"] for r in prev_rows)
    stats = _aggregate(month_rows, round(dist - prev_dist, 1))
    weeks = _split_weeks(month_rows, year, month)
    records = _month_records(month_rows, rows_until_end, year, month)
    pattern = _compute_pattern(month_rows)
    # 페이스 추이(최근 3개월, 오래된 달부터) — 기준을 stats와 단일 소스로
    # 맞추기 위해 같은 _aggregate를 재사용 (마지막 값 == stats.avg_pace 보장).
    pace_trend = [
        PaceTrendPoint(year=y, month=m,
                       avg_pace_sec_per_km=_aggregate(rows, None).avg_pace_sec_per_km)
        for (y, m, rows) in ((p2_year, p2_month, prev2_rows),
                             (prev_year, prev_month, prev_rows),
                             (year, month, month_rows))
    ]

    # AI 블록(coaching·plan) 생성 중단 (2026-07-09 결정: Gemini 비용 + 로딩
    # UX, 프론트는 렌더 제거·타입 유지). ai 필드는 하위 호환용으로 항상 null.
    # 복원: 아래를 _ai_block(...) 호출로 되돌리면 됨. _ai_block·
    # generate_monthly_insight·monthly_insights 캐시의 완전 제거는 출시기 정리.
    ai = None

    return MonthlyInsightResponse(
        year=year, month=month, stats=stats, weeks=weeks,
        records=records, pattern=pattern, pace_trend=pace_trend, ai=ai,
    )
