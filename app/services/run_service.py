"""Persistence for actual run logs (the `runs` table)."""

from __future__ import annotations

import asyncio
import logging
import math
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
    RunDetailResponse,
    RunCommentResponse,
    RunPhotoUploadUrlResponse,
    RunRequest,
    RunResponse,
    RunSplit,
    RunTrackResponse,
    StatsResponse,
    StoredRoute,
)
from app.services import notification_service, profile_service, track_service

_UNIQUE_VIOLATION = "23505"


class RunNotFound(Exception):
    """No run with that id."""


class SelfKudos(Exception):
    """DEPRECATED(2026-07-30 오너 정책: 자기 좋아요 허용) — 미사용, 하위 임포트 호환용."""


class CrewTagNotAllowed(Exception):
    """비멤버가 남의 크루 정기런 태그 시도 — 400 (핸들러가 매핑)."""


class RunTrackMissing(Exception):
    """트랙(GPS 경로) 없는 run을 코스로 저장 시도 — 400 (수동 기록은 폴리라인 없음)."""

logger = logging.getLogger(__name__)


async def _resolve_crew_session(
    user_id: str | None, crew_id: str | None, announcement_id: str | None
) -> tuple[str | None, str | None]:
    """크루 러닝 세션 태깅 L1 — (crew_id, session_key) 파생.

    crew_id 없으면 (None, None) — 일반 러닝. 있으면 caller 멤버십 검증(비멤버·
    없는 크루 → CrewTagNotAllowed=400, 남의 크루 태그 방지). session_key: 유효한
    announcement_id(그 크루 소속)면 'a:{ann}'(정밀 세션), 아니면 'c:{crew}:{KST date}'
    (즉흥런 날짜 버킷). ran_at은 저장 시각(now)이라 KST 오늘 날짜로 그룹.
    """
    if not crew_id:
        return None, None
    if user_id is None:
        raise CrewTagNotAllowed()
    from app.services import crew_service  # local: run_service↔crew_service 순환 회피
    if not await crew_service._is_member(crew_id, user_id):
        raise CrewTagNotAllowed()   # 비멤버·없는 크루 → 태그 거부(400)
    supabase = get_supabase_admin()
    if announcement_id:
        ann = await asyncio.to_thread(
            lambda: supabase.table("crew_announcements").select("id")
            .eq("id", announcement_id).eq("crew_id", crew_id).limit(1).execute()
        )
        if ann.data:
            return crew_id, f"a:{announcement_id}"   # 공지 연결 = 정밀 세션
    today_kst = datetime.now(_KST).date().isoformat()
    return crew_id, f"c:{crew_id}:{today_kst}"       # 크루+날짜 버킷


async def create_run(req: RunRequest, user_id: str | None = None) -> RunResponse:
    """Insert a run log into Supabase and return the stored record.

    Unlike route persistence, saving IS the purpose here, so a failure
    propagates to the caller (the API layer turns it into an HTTP error).

    user_id (from a validated token) is stored as the owner; None for
    anonymous requests. supabase-py is synchronous, so the blocking call
    runs in a worker thread.
    """
    # auto_publish OFF + visibility 미지정 시 기본 private (결정 D — 명시는 존중,
    # 기존 유저는 auto_publish 기본 True라 무영향). 명시/미지정은 model_fields_set.
    final_visibility = req.visibility
    if user_id and "visibility" not in req.model_fields_set:
        try:
            if not (await profile_service.get_settings(user_id)).feed.auto_publish:
                final_visibility = "private"
        except Exception:  # noqa: BLE001 — 설정 조회 실패 시 기본(public) 유지
            logger.warning("auto_publish 조회 실패 — 기본 visibility 유지", exc_info=True)

    # ── GPS 서버 검증 (설계 2026-07-06): gps_track이 있으면 필터→거리→스플릿.
    # Best-effort: 처리 실패가 기록 저장을 막으면 안 됨 (unverified로 진행).
    processed: track_service.ProcessedTrack | None = None
    verification = "unverified"
    final_distance = req.distance_km
    final_avg_pace = req.avg_pace_sec_per_km   # 거리 대체(adjusted) 시 서버거리로 재계산
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
                # 거리 대체 시 파생 필드(avg_pace) 재계산 — 신고거리 기준 페이스가
                # 서버거리와 불일치하던 버그 수정(2026-07-23, Ivan 리포트 2cada94c 계기).
                # runs의 유일한 거리파생 컬럼은 avg_pace_sec_per_km(칼로리 등 없음).
                final_avg_pace = (round(req.duration_sec / final_distance)
                                  if final_distance > 0 else req.avg_pace_sec_per_km)
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
    # verified만 PB 후보 (suspect=부정 방지, unverified=트랙 없는 기록 오염 방지).
    new_records: list[NewRecord] = []
    if user_id and verification == "verified":
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
                user_id, final_distance, req.duration_sec, final_avg_pace
            )
        except Exception:  # noqa: BLE001
            logger.warning("페이스 비교 계산 실패", exc_info=True)

    # 크루 러닝 세션 태깅 L1 — crew_id 있으면 멤버십 검증 후 session_key 파생.
    crew_id, session_key = await _resolve_crew_session(
        user_id, req.crew_id, req.announcement_id
    )

    # 위치 피드용 출발 좌표 — 트랙 첫 점에서 파생(NEARBY_FEED_DESIGN §1). run insert와
    # 원자적으로 박음(별도 UPDATE 불요). 트랙 없으면 null → /feed/nearby 자연 미노출.
    start_lat = start_lng = None
    if processed is not None and processed.polyline:
        start_lat = processed.polyline[0]["lat"]
        start_lng = processed.polyline[0]["lng"]

    record = {
        "user_id": user_id,
        "route_id": req.route_id,
        "distance_km": final_distance,
        "duration_sec": req.duration_sec,
        "avg_pace_sec_per_km": final_avg_pace,
        "notes": req.notes,
        "title": req.title,
        "area": req.area,
        "visibility": final_visibility,
        "verification": verification,
        "distance_km_reported": reported,
        "is_flagged": is_flagged,
        "crew_id": crew_id,
        "session_key": session_key,
        "start_lat": start_lat,
        "start_lng": start_lng,
    }
    # 클라 빌드/OTA 식별(2026-07-31 additive) — 미전송 시 키 생략(컬럼 default
    # null). SQL 선실행→배포 순서가 역전돼도(컬럼 미적용 DB) 기존 경로 무해.
    if req.app_version is not None:
        record["app_version"] = req.app_version
    # K1 크루 배너 초이스 — 미전송 키 생략(컬럼 default 위임 — 2026-08-02부터 OFF)
    if req.show_crew is not None:
        record["show_crew"] = req.show_crew

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
                         partial=s.partial, moving_sec=s.moving_sec)
                for s in processed.splits
            ]
            await asyncio.to_thread(
                lambda: supabase.table("run_tracks").insert({
                    "run_id": saved["id"],
                    "points": processed.polyline,
                    "splits": [s.model_dump() for s in splits_out],
                    "raw_point_count": processed.point_count_raw,
                    "kept_point_count": processed.point_count_kept,
                    "server_distance_km": round(processed.server_distance_km, 2),
                    "polyline_thumb": track_service.make_polyline_thumb(processed.polyline),
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
                      moving_sec=_moving_total(splits_out),
                      recent_avg_pace_sec_per_km=recent_avg_pace,
                      pace_delta_sec=pace_delta)

    if user_id:
        try:
            await _check_challenge_completion(user_id)
        except Exception:
            logger.warning("챌린지 달성 알림 실패", exc_info=True)

    # PB 축하 알림 — new_records가 비어있지 않으면 본인에게 1건(인앱+푸시).
    # ⚠️ 유일한 '자기 자신 대상' 알림(recipient==actor) — self-skip의 의도적
    # 예외라 allow_self=True. 저장 직후 PB 모달(new_records 응답)과 별개로,
    # 인앱은 알림함 기록·푸시는 앱 밖일 때 의미. best-effort(저장 성공 불변).
    if user_id and new_records:
        try:
            from app.services import notification_service  # local (circular 회피)
            await notification_service.create_notification(
                recipient_id=user_id,
                actor_id=user_id,
                type="pb_achieved",
                target_id=saved["id"],      # 딥링크: run 상세
                target_type="run",
                allow_self=True,            # self-only 알림 — 의도된 예외
                payload={"record_types": [r.type for r in new_records]},
            )
        except Exception:  # noqa: BLE001
            logger.warning("PB 축하 알림 실패 — 저장은 성공", exc_info=True)

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
    # verified만 PB 자격 — 트랙 없는 run(차량 이동 등)의 오염 방지 (집계 정합 정책)
    rows = [r for r in rows if r.get("verification") == "verified"]
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


def _moving_total(splits: list[RunSplit] | None) -> int | None:
    """run-level 총 이동시간 = Σ split.moving_sec (Ivan ②). splits 없음(트랙 없음) 또는
    구 run(moving_sec 미기록=None 혼재)이면 None — 부분합으로 오도하지 않는다."""
    if not splits:
        return None
    vals = [s.moving_sec for s in splits]
    if any(v is None for v in vals):
        return None
    return sum(vals)


# ── 러닝 사진 (run-photos private 버킷 — 읽기는 서명 URL로만) ─────────────────

_PHOTO_BUCKET = "run-photos"
_PHOTO_MAX_BYTES = 5 * 1024 * 1024
_PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_PHOTO_URL_TTL_S = 3600  # 서명 URL 만료 — 가시성 게이트 재평가 주기 겸용


class PhotoPathInvalid(Exception):
    """photos 경로가 이 run의 prefix 밖 (남의 run 사진 참조 차단) — 422."""


async def _signed_photo_urls(paths: list[str]) -> dict[str, str]:
    """{경로: 서명 URL(1h)} — 배치 1콜. best-effort: 실패 시 빈 dict (표시 생략)."""
    if not paths:
        return {}
    try:
        supabase = get_supabase_admin()
        res = await asyncio.to_thread(
            lambda: supabase.storage.from_(_PHOTO_BUCKET)
            .create_signed_urls(paths, _PHOTO_URL_TTL_S)
        )
        out: dict[str, str] = {}
        for path, item in zip(paths, res):
            url = item.get("signedURL") or item.get("signed_url") or item.get("signedUrl")
            if url and not item.get("error"):
                out[path] = url
        return out
    except Exception:  # noqa: BLE001 — 사진은 부가 정보, 조회를 막지 않는다
        logger.warning("사진 서명 URL 발급 실패 — 사진 없이 응답", exc_info=True)
        return {}


async def create_run_photo_upload_url(
    run_id: str, user_id: str, slot: int, content_type: str
) -> RunPhotoUploadUrlResponse | None:
    """사진 서명 업로드 URL (avatar 3-step 동형) — 소유자만 (아니면 None → 404).

    경로는 {run_id}/{slot}.{ext} 고정. 같은 슬롯의 다른 확장자 잔재를 지워
    교체가 파일을 남기지 않게 한다 (아바타 잔존 사례 방지).
    """
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
    ext = _PHOTO_TYPES[content_type]
    path = f"{run_id}/{slot}.{ext}"

    def _issue() -> dict:
        storage = supabase.storage.from_(_PHOTO_BUCKET)
        try:  # 슬롯 교체 시 이전 확장자 파일 제거 — 없어도 무해
            storage.remove([f"{run_id}/{slot}.{e}" for e in _PHOTO_TYPES.values()])
        except Exception:  # noqa: BLE001
            pass
        return storage.create_signed_upload_url(path)

    res = await asyncio.to_thread(_issue)
    upload_url = res.get("signed_url") or res.get("signedUrl") or res.get("signedURL")
    if not upload_url:
        raise RuntimeError("Storage did not return a signed upload URL.")
    return RunPhotoUploadUrlResponse(
        upload_url=upload_url, path=path,
        max_bytes=_PHOTO_MAX_BYTES, allowed_types=list(_PHOTO_TYPES),
    )


# 타인이 보는 run 상세의 화이트리스트 — 여기 없는 필드는 기본값(미노출).
# notes(개인 메모)·feedback류·is_flagged/distance_km_reported(부정 판정 내부)·
# verification(suspect 낙인)·visibility는 의도적으로 제외 (설계 §1).
_PUBLIC_DETAIL_FIELDS = (
    "id", "created_at", "user_id", "ran_at", "distance_km",
    "duration_sec", "avg_pace_sec_per_km", "title", "area",
)


async def _crew_session_fields(
    rows: list[dict], viewer_id: str | None
) -> dict[str, dict]:
    """크루 필드 단일 게이트(통일 규칙 2026-08-03) — {run_id: 4필드 dict}.

    전 표면 공통 3-tier: **본인**=전 필드+show_crew 실값 / **크루 멤버**=크루
    필드 표시(플래그 null) / **타인**=크루 is_public AND show_crew=true일 때만
    (플래그 null — true+이름null 조합으로 비공개 크루를 추론하는 누출 차단).
    비공개는 필드 전부 null(session_key가 crew_id 내포). 비세션 런은 크루 필드
    null(show_crew는 본인이면 실값 — 런 속성). 배치 고정 쿼리 — crews 1 +
    (타인 소유 태그런 있을 때만) crew_members 1. rows엔 id·user_id·crew_id·
    session_key·show_crew 필요(select "*" 경로 충족).
    """
    nulls = {"crew_id": None, "crew_name": None, "session_key": None,
             "show_crew": None}
    out = {}
    for r in rows:
        f = dict(nulls)
        if viewer_id is not None and r.get("user_id") == viewer_id:
            f["show_crew"] = bool(r.get("show_crew"))   # 본인 한정 서빙
        out[r["id"]] = f
    tagged = [r for r in rows if r.get("crew_id") and r.get("session_key")]
    if not tagged:
        return out
    supabase = get_supabase_admin()
    crew_ids = list({r["crew_id"] for r in tagged})
    need_membership = (viewer_id is not None
                       and any(r["user_id"] != viewer_id for r in tagged))

    async def _crews():
        res = await asyncio.to_thread(
            lambda: supabase.table("crews").select("id, name, is_public")
            .in_("id", crew_ids).execute())
        return {c["id"]: c for c in res.data}

    async def _member_of():
        if not need_membership:
            return set()
        res = await asyncio.to_thread(
            lambda: supabase.table("crew_members").select("crew_id")
            .eq("user_id", viewer_id).in_("crew_id", crew_ids).execute())
        return {m["crew_id"] for m in res.data}

    crews, member_of = await asyncio.gather(_crews(), _member_of())
    for r in tagged:
        crew = crews.get(r["crew_id"])
        if crew is None:
            continue  # 크루 삭제됨 — null 유지
        visible = (r["user_id"] == viewer_id
                   or r["crew_id"] in member_of
                   or (bool(crew.get("is_public")) and bool(r.get("show_crew"))))
        if visible:
            out[r["id"]].update({"crew_id": r["crew_id"], "crew_name": crew["name"],
                                 "session_key": r["session_key"]})
    return out


async def _polyline_thumbs(run_ids: list[str]) -> dict[str, list]:
    """{run_id: polyline_thumb} — 트랙 있는 run만, 배치 1쿼리 (카드 지도용).

    Best-effort: 실패 시 빈 dict (thumb null로 표시될 뿐, 조회는 성공).
    """
    if not run_ids:
        return {}
    try:
        supabase = get_supabase_admin()
        res = await asyncio.to_thread(
            lambda: supabase.table("run_tracks")
            .select("run_id, polyline_thumb")
            .in_("run_id", run_ids)
            .execute()
        )
        return {r["run_id"]: r["polyline_thumb"] for r in res.data
                if r.get("polyline_thumb")}
    except Exception:  # noqa: BLE001
        logger.warning("polyline_thumb 조회 실패 — thumb 없이 응답", exc_info=True)
        return {}


async def delete_run(run_id: str, user_id: str) -> None:
    """본인 run 하드 삭제 (docs/RUN_DELETE_DESIGN.md). 복구 없음.

    소유 확인(타인/없음/기삭제 전부 404 은닉 — 존재 숨김 표준) → 행 삭제
    (run_kudos·run_comments·run_tracks는 FK cascade, 유일한 커밋 지점) →
    best-effort 정리(Storage 사진·run 대상 알림 — 실패해도 로그만).

    정리를 행 삭제 **뒤에** 두는 이유: 반대 순서면 "정리 성공 + 삭제 실패" 시
    run은 살아있는데 사진 파일만 소멸하는 사용자 가시 손상이 남는다. 이 순서면
    최악이 고아 파일(private 버킷 — 접근 불가)·stale 알림(탭 404)뿐.

    집계(PB·주간/월간 통계·세션 카운트·챌린지 achieved_km)는 전부 라이브 계산
    이라 재계산 코드가 없다 — 다음 조회가 자동 반영(PB 차순위 승계 포함).
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("id, photos")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise RunNotFound()  # 타인/없음/기삭제 — 동일 404(은닉)
    photos: list[str] = res.data[0].get("photos") or []

    deleted = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .delete()
        .eq("id", run_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not deleted.data:
        raise RunNotFound()  # 동시 삭제 레이스 — 패자는 반환행 0 → 404 (L8 패턴)

    # best-effort 정리 (CLAUDE.md — 실패는 치명 처리하지 않고 로그만)
    if photos:
        try:
            await asyncio.to_thread(
                lambda: supabase.storage.from_(_PHOTO_BUCKET).remove(photos)
            )
        except Exception:  # noqa: BLE001
            logger.warning("run %s 사진 Storage 정리 실패 — 고아 파일(무해)",
                           run_id, exc_info=True)
    try:
        # run을 target으로 한 알림 전부(run_kudoed·run_commented·pb_achieved,
        # 수신자 무관) — 방치 시 stale 404 탭이라 함께 정리(설계 §8 확정).
        await asyncio.to_thread(
            lambda: supabase.table("notifications")
            .delete()
            .eq("target_type", "run")
            .eq("target_id", run_id)
            .execute()
        )
    except Exception:  # noqa: BLE001
        logger.warning("run %s 알림 정리 실패 — stale 알림 잔존(탭 404)",
                       run_id, exc_info=True)


async def get_run(run_id: str, user_id: str) -> RunResponse | None:
    """Return one run — 본인은 전체, 타인은 공개범위 내에서 정제된 필드만.

    게이트는 track·kudos·댓글과 동일(_can_see_run). 차단·부재 모두 None(404 은닉).
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("*")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    owner_id = row["user_id"]
    is_own = owner_id == user_id
    if not is_own and not await _can_see_run(
        owner_id, user_id, row.get("visibility") or "followers"
    ):
        return None

    photo_paths = row.get("photos") or []
    tracks, kudos, comments, signed, mine, thumbs, flags = await asyncio.gather(
        _track_summaries([row["id"]]),
        _kudos_counts([row["id"]]),
        _comment_counts([row["id"]]),
        _signed_photo_urls(photo_paths),
        _my_kudos_set([row["id"]], user_id),
        _polyline_thumbs([row["id"]]),
        profile_service.feed_flags_batch([owner_id]),
    )
    # 서명 성공분만 유지 — photos(URL)와 photo_paths(경로)가 같은 순서·길이로 정렬.
    kept_paths = [p for p in photo_paths if p in signed]
    photos = [signed[p] for p in kept_paths]
    owner_flags = flags.get(owner_id, {})
    common = dict(
        has_track=row["id"] in tracks, splits=tracks.get(row["id"]),
        moving_sec=_moving_total(tracks.get(row["id"])),
        kudos_count=kudos.get(row["id"], 0),
        # 피드 my_kudos와 동일 계산 (2026-07-30부터 본인 kudos 허용 — 본인도 true 가능)
        my_kudos=row["id"] in mine,
        comment_count=comments.get(row["id"], 0), photos=photos,
        polyline_thumb=thumbs.get(row["id"]),
        # 피드 설정 렌더 힌트 — 소유자값(본인·타인 상세 공통, owner_id 기준)
        allow_likes=owner_flags.get("allow_likes", True),
        allow_comments=owner_flags.get("allow_comments", True),
    )
    # 크루 세션 필드(A 규칙) + 전역 참여자 수(크루 피드와 단일 소스 헬퍼)
    crew_fields = (await _crew_session_fields([row], user_id))[row["id"]]
    spc = None
    if crew_fields["session_key"]:
        from app.services import crew_service  # local: 순환 import 회피
        spc = (await crew_service._session_participant_counts(
            [crew_fields["session_key"]])).get(crew_fields["session_key"])
    common = dict(common, **crew_fields, session_participant_count=spc)
    if is_own:
        # photo_paths는 본인 상세에서만 — 서명된 photos와 같은 순서(kept_paths).
        # 편집 시 PATCH /runs {photos}에 재사용(Ivan own-run 사진 편집 블로커 해제).
        return RunDetailResponse(**{k: v for k, v in row.items()
                                    if k not in ("photos", "crew_id", "session_key",
                                                 "show_crew")},
                                 photo_paths=kept_paths, **common)

    # 타인: 화이트리스트 + route_id는 연결 코스가 public일 때만 (프로브 차단)
    public_route_id = None
    if row.get("route_id"):
        pub = await asyncio.to_thread(
            lambda: supabase.table("routes")
            .select("id")
            .eq("id", row["route_id"])
            .eq("is_public", True)
            .limit(1)
            .execute()
        )
        public_route_id = row["route_id"] if pub.data else None
    return RunDetailResponse(
        **{k: row[k] for k in _PUBLIC_DETAIL_FIELDS},
        route_id=public_route_id, visibility=None, **common,
    )


async def get_run_track(run_id: str, user_id: str) -> RunTrackResponse | None:
    """run의 경로(폴리라인) — 공개범위 내에서만 + 트랙 존재 시 (아니면 None → 404).

    궤적은 위치정보라 kudos·run 댓글과 동일한 _can_see_run 게이트를 탄다
    (본인 항상 / public 누구나 / followers는 팔로우·같은 크루 / private 본인만).
    """
    try:
        owner_id, visibility = await _run_owner(run_id)
    except RunNotFound:
        return None
    if not await _can_see_run(owner_id, user_id, visibility):
        return None
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("run_tracks")
        .select("points, splits, raw_point_count, kept_point_count, server_distance_km")
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
    if row.get("server_distance_km") is not None:
        # 저장된 정확값 (2026-07-11~). 구 행은 아래 splits 파생 폴백 —
        # 0.2km 미만은 splits가 비어 0.0이 되는 결함이 있었음 (조사 §1).
        dist = float(row["server_distance_km"])
    elif splits and splits[-1].get("partial"):
        dist = float(splits[-1]["km"])
    else:
        dist = float(len(splits))
    gains = [s["elev_gain_m"] for s in splits if s.get("elev_gain_m") is not None]
    # 총 이동시간 = Σ split.moving_sec (Ivan ②). 구 트랙(moving_sec 미기록)은 None.
    movings = [s.get("moving_sec") for s in splits]
    moving_sec = sum(movings) if splits and all(v is not None for v in movings) else None
    return RunTrackResponse(
        polyline=row["points"],
        server_distance_km=dist,
        elev_gain_m=sum(gains) if gains else None,
        moving_sec=moving_sec,
        point_count_raw=row["raw_point_count"],
        point_count_kept=row["kept_point_count"],
    )


async def copy_run_as_route(run_id: str, viewer_id: str) -> tuple[StoredRoute, bool]:
    """러닝을 viewer 소유의 private 코스로 저장('이 경로 달리기'). 반환 (route, created).

    게이트는 track·kudos와 동일 _can_see_run(비가시·차단 404 은닉). 트랙 없는 run은
    RunTrackMissing(400 — 수동 기록은 폴리라인 없음). 멱등: (viewer, source_run_id)
    유니크라 재호출 시 기존 코스 반환(created=False). 자기 run 복사도 허용(내 러닝을
    코스로 재사용 — 무해). Gemini·쿼터 미소모. 성공 시 run 주인에게 route_saved 알림
    (자기 run 복사면 self 스킵 — create_notification이 recipient==actor 무발송).
    """
    owner_id, visibility = await _run_owner(run_id)  # RunNotFound → 핸들러 404
    if not await _can_see_run(owner_id, viewer_id, visibility):
        raise RunNotFound()  # 비가시·차단 — 존재 은닉(404)

    supabase = get_supabase_admin()
    # 멱등: 이미 이 run을 코스로 저장했으면 그 코스 반환
    existing = await asyncio.to_thread(
        lambda: supabase.table("routes").select("*")
        .eq("user_id", viewer_id).eq("source_run_id", run_id).limit(1).execute()
    )
    if existing.data:
        return StoredRoute(**existing.data[0]), False

    # run 메타 + 트랙 조회
    run_res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("title, distance_km, duration_sec").eq("id", run_id).limit(1).execute()
    )
    if not run_res.data:
        raise RunNotFound()
    run = run_res.data[0]
    track_res = await asyncio.to_thread(
        lambda: supabase.table("run_tracks").select("points")
        .eq("run_id", run_id).limit(1).execute()
    )
    points = track_res.data[0]["points"] if track_res.data else None
    if not points:
        raise RunTrackMissing()  # 트랙 없는 수동 기록 — 400

    # summary: 런 제목 우선, 없으면 "{owner}님의 러닝 N.Nkm"
    dist = float(run.get("distance_km") or 0.0)
    if run.get("title"):
        summary = run["title"]
    else:
        briefs = await profile_service.get_profile_briefs([owner_id])
        nick = briefs.get(owner_id, {}).get("nickname") or "러너"
        summary = f"{nick}님의 러닝 {dist:.1f}km"
    dur_sec = run.get("duration_sec") or 0
    # is_one_way: 시작·끝 좌표 거리로 판별(형제 관성 — 200m 이상 벌어지면 편도)
    p0, pN = points[0], points[-1]
    one_way = _haversine_km(p0["lat"], p0["lng"], pN["lat"], pN["lng"]) > 0.2

    record = {
        "user_id": viewer_id,
        "is_public": False,           # 저장 코스는 private 시작(copy_route 관성)
        "source_run_id": run_id,
        "summary": summary,
        "total_distance_km": round(dist, 1),
        "estimated_duration_min": float(round(dur_sec / 60.0)),  # 실런 기록 그대로
        "waypoints": [],              # 트랙 기반이라 웨이포인트 없음
        "polyline": points,
        "start_lat": p0["lat"],
        "start_lng": p0["lng"],
        "is_one_way": one_way,
    }
    try:
        out = await asyncio.to_thread(
            lambda: supabase.table("routes").insert(record).execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:
            raise
        # 동시 저장 레이스 — 유니크 충돌을 멱등 흡수(패자는 기존 조회)
        again = await asyncio.to_thread(
            lambda: supabase.table("routes").select("*")
            .eq("user_id", viewer_id).eq("source_run_id", run_id).limit(1).execute()
        )
        return StoredRoute(**again.data[0]), False

    route = StoredRoute(**out.data[0])
    # (a′) 알림 — run 주인에게 route_saved (자기 run이면 create_notification이 self 스킵)
    try:
        await notification_service.create_notification(
            recipient_id=owner_id, actor_id=viewer_id, type="route_saved",
            target_id=run_id, target_type="run",
        )
    except Exception:  # noqa: BLE001 — 알림 실패가 저장을 막지 않음
        logger.warning("route_saved 알림 생성 실패 (run=%s)", run_id, exc_info=True)
    return route, True


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
    """run이 caller에게 보이는가 — 노출 경로 정책과 일치 (결정 A′ + 엣지 ⓑ).

    ① 본인 → 항상 ② 차단 → 항상 False(최우선) ③ **엣지 ⓑ 크루 탭스루**: 크루
    공유 + private 아님 → 허용(프로필 잠금과 독립 — 크루 피드에 뜬 카드는 크루원이
    상세까지 탭 가능, "서피스에 보이는 것은 그 서피스 안에서 완결") ④ 그 외는
    프로필 게이트(A′=팔로우만) + run visibility: private 본인만·public 누구나·
    followers 팔로우.
    """
    if owner_id == caller_id:
        return True
    # 차단 최우선 — 차단이면 크루 탭스루도 막힘
    if await profile_service.is_blocked_either(owner_id, caller_id):
        return False
    # 엣지 ⓑ(A′): 크루 서피스 노출 run(private 아님)은 크루원이 상세 탭 가능.
    # 프로필이 A′로 잠겨도 크루 문맥 run은 열림 — 크루 피드가 이미 private 제외라
    # "피드에 보이는 카드 = 탭 가능"이 성립. 응답은 기존 화이트리스트 정제 그대로.
    if visibility != "private" and await profile_service._are_crewmates(caller_id, owner_id):
        return True
    # 크루 아니면 프로필 게이트(A′: 팔로우만) + run visibility 합성
    if not await profile_service.can_see_user(owner_id, caller_id):
        return False
    if visibility == "private":
        return False
    if visibility == "public":
        return True
    # visibility == "followers": 팔로우만 (A′ — 크루 탭스루는 위 ⓑ에서 이미 처리,
    # 여기 도달 시 caller는 비크루원이므로 크루 재검사 불필요/제거).
    return await profile_service._follows(caller_id, owner_id)


async def give_kudos(run_id: str, user_id: str) -> None:
    """Kudos a run. Idempotent (double-tap safe). 본인 run 허용(2026-07-30 오너 정책 —
    route like와 일관). 자기 kudos 알림은 create_notification의 self-skip이 자동 억제.

    Fires a best-effort run_kudoed notification only on a genuinely new kudos.
    보이지 않는 run(팔로우·크루 무관)에는 kudos 불가 — 알림 스팸 방지 (L1).
    """
    owner_id, visibility = await _run_owner(run_id)
    if owner_id != user_id:   # 게이트는 타인 kudos에만(route like와 동일 패턴)
        if not await _can_see_run(owner_id, user_id, visibility):
            raise RunNotVisible()
        if not await profile_service.feed_allows(owner_id, "allow_likes"):
            raise profile_service.FeedActionDisabled("likes")

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
    kudoser_ids = [r["user_id"] for r in rows]
    # v3.6: 차단 관계 유저는 명단에서 제외(크루 피드 카드와 동형). kudos_count는
    # 전역 유지(뷰어별 카운트화는 전 소비처 재작업 — 목록만 필터, count 정합 주석 참고).
    briefs, blocked = await asyncio.gather(
        profile_service.get_profile_briefs(kudoser_ids),
        profile_service.blocked_ids_batch(caller_id, kudoser_ids),
    )
    return [
        KudosUserItem(
            user_id=row["user_id"],
            nickname=briefs.get(row["user_id"], {}).get("nickname"),
            avatar_url=briefs.get(row["user_id"], {}).get("avatar_url"),
            created_at=row["created_at"],
        )
        for row in rows if row["user_id"] not in blocked
    ]


# ── run 댓글 (route 댓글과 동형, 가시성은 _can_see_run 게이트 재사용) ──────────

class RunCommentNotFound(Exception):
    """이 run에 그 댓글이 없음 (핸들러가 404로 매핑)."""


class CommentParentInvalid(Exception):
    """답글 부모가 없거나 다른 run 소속 — 422 comment_parent_invalid."""


class ReplyDepthExceeded(Exception):
    """부모가 이미 답글(1-레벨 강제) — 422 reply_depth_exceeded."""



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
    commenter_ids = [r["user_id"] for r in rows]
    # v3.6: 차단 발신자 댓글은 목록에서 제외(마스킹 아닌 제외 — 댓글은 독립 항목이라
    # 제거가 자연스럽고 인스타도 제외). comment_count는 전역 유지(정합 주석 참고).
    briefs, blocked = await asyncio.gather(
        profile_service.get_profile_briefs(commenter_ids),
        profile_service.blocked_ids_batch(caller_id, commenter_ids),
    )
    return [
        RunCommentResponse(
            **row,
            nickname=briefs.get(row["user_id"], {}).get("nickname"),
            avatar_url=briefs.get(row["user_id"], {}).get("avatar_url"),
        )
        for row in rows if row["user_id"] not in blocked
    ]


async def create_run_comment(
    run_id: str, caller_id: str, content: str,
    parent_comment_id: str | None = None,
) -> RunCommentResponse:
    """run에 댓글 작성 — 가시성 게이트 통과 시. run 주인에게 run_commented 알림
    (본인 댓글은 미발송). 안 보이는 run이면 RunNotVisible → 404.

    1-레벨 답글(2026-08-01, Ivan 계약): parent_comment_id 지정 시 부모 검증
    3종 — 부모 미존재/타 run 소속(CommentParentInvalid)·부모가 이미 답글
    (ReplyDepthExceeded — 서버 강제 1-레벨). 권한·가시성은 일반 댓글과 동일
    경로. 부모 작성자에게도 기존 run_commented 타입 그대로 알림(target=run —
    딥링크 라우팅 표 무변경). 부모 작성자==run 주인이면 중복 없이 1건."""
    owner_id, visibility = await _run_owner(run_id)  # RunNotFound if missing
    if not await _can_see_run(owner_id, caller_id, visibility):
        raise RunNotVisible()
    if owner_id != caller_id and not await profile_service.feed_allows(
        owner_id, "allow_comments"
    ):
        raise profile_service.FeedActionDisabled("comments")

    supabase = get_supabase_admin()
    parent = None
    if parent_comment_id is not None:
        pres = await asyncio.to_thread(
            lambda: supabase.table("run_comments")
            .select("id, run_id, user_id, parent_comment_id")
            .eq("id", parent_comment_id).limit(1).execute())
        parent = pres.data[0] if pres.data else None
        if parent is None or parent["run_id"] != run_id:
            raise CommentParentInvalid()
        if parent.get("parent_comment_id") is not None:
            raise ReplyDepthExceeded()

    record = {"run_id": run_id, "user_id": caller_id, "content": content}
    if parent_comment_id is not None:
        # 미전송 시 키 생략 — SQL 선실행→배포 순서 보호(app_version 전례)
        record["parent_comment_id"] = parent_comment_id
    res = await asyncio.to_thread(
        lambda: supabase.table("run_comments").insert(record).execute()
    )
    row = res.data[0]

    # run 주인에게 알림 (본인 댓글은 self-skip). payload에 run_id (딥링크).
    # 엣지 (b) 확정(오너+Ivan 2026-08-05): 주인이 부모 댓글 작성자인 답글이면
    # 주인 경로에도 is_reply·parent_comment_id — 답글은 소유 무관하게 답글(문구
    # 정확성). 일반 댓글·타인 부모 답글의 주인 발송은 종전 바이트 불변({run_id}).
    owner_payload: dict = {"run_id": run_id}
    if parent is not None and parent["user_id"] == owner_id:
        owner_payload.update({"is_reply": True,
                              "parent_comment_id": parent_comment_id})
    from app.services import notification_service  # local to avoid circular risk
    try:
        await notification_service.create_notification(
            recipient_id=owner_id,
            actor_id=caller_id,
            type="run_commented",
            target_id=run_id,
            target_type="run",
            payload=owner_payload,
        )
    except Exception:  # noqa: BLE001 - 알림 실패가 댓글 작성을 막지 않음
        logger.warning("run_commented 알림 생성 실패", exc_info=True)
    # 부모 작성자 알림 — 기존 타입 재사용(라우팅 표 무변경). 자기 답글 미발송,
    # 부모 작성자==run 주인이면 위에서 이미 1건(중복 방지).
    # payload additive 2종(2026-08-04, Ivan): is_reply·parent_comment_id는
    # **이 발송 건에만** — 주인 발송 건은 바이트 불변(미전송 키 생략, §D).
    if (parent is not None and parent["user_id"] != caller_id
            and parent["user_id"] != owner_id):
        try:
            await notification_service.create_notification(
                recipient_id=parent["user_id"],
                actor_id=caller_id,
                type="run_commented",
                target_id=run_id,
                target_type="run",
                payload={"run_id": run_id, "is_reply": True,
                         "parent_comment_id": parent_comment_id},
            )
        except Exception:  # noqa: BLE001
            logger.warning("답글 부모 작성자 알림 생성 실패", exc_info=True)

    brief = (await profile_service.get_profile_briefs([caller_id])).get(caller_id)
    return RunCommentResponse(**row, nickname=brief.get("nickname") if brief else None,
                              avatar_url=brief.get("avatar_url") if brief else None)


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


# 활동 피드 카드 select 컬럼 — list_activity_feed·list_nearby_feed 공유(같은 shape).
_ACTIVITY_SELECT = ("id, user_id, ran_at, distance_km, duration_sec, "
                    "avg_pace_sec_per_km, route_id, title, area, photos")


async def _k1_crew_names(run_ids: list[str], viewer_id: str | None) -> dict[str, str]:
    """피드류 크루 배너 — {run_id: 실명}. 통일 게이트(_crew_session_fields)에
    위임(2026-08-03): 크루원 뷰어는 옵트인 무관 표시, 타인은 공개 AND 옵트인.
    행 조회 1 + 게이트 ≤2 = 고정 ≤3쿼리. show_crew 컬럼 미적용 환경(롤백)은
    42703 → 전부 null 폴백."""
    if not run_ids:
        return {}
    supabase = get_supabase_admin()
    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .select("id, user_id, crew_id, session_key, show_crew")
            .in_("id", run_ids).not_.is_("crew_id", "null").execute())
    except APIError:
        logger.warning("show_crew 컬럼 미적용 — 크루 배너 전부 null 폴백")
        return {}
    fields = await _crew_session_fields(res.data, viewer_id)
    return {rid: f["crew_name"] for rid, f in fields.items() if f["crew_name"]}


async def _build_activity_items(
    rows: list[dict], viewer_id: str
) -> list[ActivityFeedItem]:
    """runs 행 목록(_ACTIVITY_SELECT) → ActivityFeedItem[] (배치 집계, N+1 없음).

    활동 피드/위치 피드 공유 빌더 — 카드 shape·프라이버시 규칙 단일 소스.
    rows는 이미 가시성·순서·페이지네이션이 적용된 최종 목록이어야 함.
    """
    if not rows:
        return []
    supabase = get_supabase_admin()
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

    firsts = {r["id"]: (r.get("photos") or [None])[0] for r in rows}
    (briefs, summaries, kudos_counts, my_kudos, comment_counts, signed, thumbs,
     flags, crew_names) = await asyncio.gather(
        profile_service.get_profile_briefs([r["user_id"] for r in rows]),
        _public_route_summaries(),
        _kudos_counts(run_ids),
        _my_kudos_set(run_ids, viewer_id),
        _comment_counts(run_ids),
        _signed_photo_urls([p for p in firsts.values() if p]),
        _polyline_thumbs(run_ids),
        profile_service.feed_flags_batch([r["user_id"] for r in rows]),
        _k1_crew_names(run_ids, viewer_id),
    )
    return [
        ActivityFeedItem(
            run_id=row["id"],
            crew_name=crew_names.get(row["id"]),
            user_id=row["user_id"],
            nickname=briefs.get(row["user_id"], {}).get("nickname"),
            avatar_url=briefs.get(row["user_id"], {}).get("avatar_url"),
            ran_at=row["ran_at"],
            title=row.get("title"),
            area=row.get("area"),
            distance_km=row["distance_km"],
            duration_sec=row["duration_sec"],
            avg_pace_sec_per_km=row.get("avg_pace_sec_per_km"),
            route_id=row.get("route_id"),
            route_summary=summaries.get(row.get("route_id")),
            comment_count=comment_counts.get(row["id"], 0),
            is_mine=(row["user_id"] == viewer_id),
            kudos_count=kudos_counts.get(row["id"], 0),
            my_kudos=row["id"] in my_kudos,
            photo_thumb=signed.get(firsts.get(row["id"])),
            polyline_thumb=thumbs.get(row["id"]),
            allow_likes=flags.get(row["user_id"], {}).get("allow_likes", True),
            allow_comments=flags.get(row["user_id"], {}).get("allow_comments", True),
        )
        for row in rows
    ]


async def list_activity_feed(
    user_id: str, limit: int = 20, offset: int = 0
) -> list[ActivityFeedItem]:
    """Following activity feed: runs by followed users only, newest ran_at.

    2026-07-20 스펙 변경(오너 룰링): **본인 run 제외**. 초기 설계는 "팔로우+본인"
    이었으나 홈 친구 탭이 이 피드를 소비하면서 본인 포함이 부자연해짐(본인 run은
    기록 탭·프로필 서피스). is_mine 필드는 하위호환으로 유지(이제 항상 False).

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
    audience = [row["following_id"] for row in res.data]
    if not audience:  # 팔로우 0명 — 본인 제외 후엔 조회 대상 자체가 없음
        return []

    runs_res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select(_ACTIVITY_SELECT)
        .in_("user_id", audience)
        # 팔로우 대상의 private run은 활동 피드에서 제외 (본인은 audience에 없음)
        .neq("visibility", "private")
        .order("ran_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return await _build_activity_items(runs_res.data, user_id)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 대권 거리(km) — bbox 정사각형을 원형으로 컷하는 후필터용."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# 위치 피드 후보 안전 상한 — bbox 범위 스캔 후 haversine·가시성 후필터 대상.
# 베타 소규모(수십 run)라 넉넉. 초과 시 로그(스케일 트리거 신호 → PostGIS 전환).
_NEARBY_CANDIDATE_CAP = 500


async def list_nearby_feed(
    user_id: str, lat: float | None = None, lng: float | None = None,
    radius_km: float = 10.0, limit: int = 20, offset: int = 0,
    scope: str = "nearby",
) -> list[ActivityFeedItem]:
    """홈 "전체" 탭 — 내 위치 반경 내 public run 탐색 피드 (NEARBY_FEED_DESIGN).

    필터 합성(순서): visibility='public' → bbox 범위 → 본인 제외 → 팔로우 유저
    제외 → visible_owners(차단 양방향+비공개 계정 제외) → haversine 원형 후필터.
    최신순(ran_at desc), 반경 내 0건이면 []. 서버 자동 반경 확장 없음.

    scope="all"(2026-08-01 additive): 반경·bbox·원형 후필터 스킵 — 전 세계
    public run(좌표 null 미노출 불변). 가시성·정렬·페이지네이션은 동일 경로.
    keyset(ran_at 커서) 전환 트리거: runs 5만+ 행 또는 offset 스캔 p95 300ms+
    — 그 전엔 offset 유지(오버엔지니어링 경계). 후보 상한 경보는 기존
    _NEARBY_CANDIDATE_CAP 로그가 겸한다.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    radius_km = max(0.1, min(radius_km, 20.0))  # 상한 20 (크루 선례 정합, 확답 B)
    world = scope == "all"

    if not world:
        # bounding box (위도 1도≈111km, 경도는 cos(lat) 보정)
        dlat = radius_km / 111.0
        coslat = math.cos(math.radians(lat))
        dlng = radius_km / (111.0 * coslat) if coslat > 1e-9 else 180.0

    supabase = get_supabase_admin()

    # 팔로우 중 유저 + 본인 → 제외 집합 (본인 포함이라 항상 비지 않음)
    fol = await asyncio.to_thread(
        lambda: supabase.table("follows")
        .select("following_id").eq("follower_id", user_id).execute()
    )
    exclude_ids = {row["following_id"] for row in fol.data} | {user_id}

    # bbox 범위 스캔 (부분 인덱스) + public + 제외 집합. 후필터로 줄어드므로
    # range() 없이 후보를 모아(cap) haversine·가시성 필터 후 파이썬에서 페이지네이션.
    def _cand_query():
        q = (supabase.table("runs")
             .select(_ACTIVITY_SELECT + ", start_lat, start_lng")
             .eq("visibility", "public"))
        if not world:
            q = (q.gte("start_lat", lat - dlat).lte("start_lat", lat + dlat)
                 .gte("start_lng", lng - dlng).lte("start_lng", lng + dlng))
        return (q.not_.in_("user_id", list(exclude_ids))
                .order("ran_at", desc=True)
                .limit(_NEARBY_CANDIDATE_CAP)
                .execute())

    cand_res = await asyncio.to_thread(_cand_query)
    cand = cand_res.data
    if len(cand) >= _NEARBY_CANDIDATE_CAP:
        logger.warning("nearby feed 후보 상한(%d) 도달 — PostGIS 전환 검토 신호",
                       _NEARBY_CANDIDATE_CAP)
    if not cand:
        return []

    # haversine 원형 후필터 (bbox 정사각형 모서리 컷 — 확답 A)
    in_circle = [
        r for r in cand
        if r.get("start_lat") is not None   # 좌표 null 미노출 — 두 모드 공통 불변
        and (world
             or _haversine_km(lat, lng, r["start_lat"], r["start_lng"]) <= radius_km)
    ]
    if not in_circle:
        return []

    # visible_owners: 차단 양방향 제외 + 비공개 계정 제외 (프라이버시 핵심).
    # 팔로우 유저는 이미 제외됐으므로 여기서 남는 건 공개계정·비팔로우·비차단.
    owner_ids = list({r["user_id"] for r in in_circle})
    visible = await profile_service.visible_owners(user_id, owner_ids)
    visible_rows = [r for r in in_circle if r["user_id"] in visible]

    # 최신순 유지(쿼리 order 보존) → 파이썬 페이지네이션
    page = visible_rows[offset:offset + limit]
    return await _build_activity_items(page, user_id)


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

    # 프로필 잠금 선행 (v1): 비공개 계정을 볼 권한 없으면 빈 목록
    if caller_id != target_id and not await profile_service.can_see_user(
        target_id, caller_id
    ):
        return []

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
                "avg_pace_sec_per_km, route_id, title, area, visibility, photos")
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

    firsts = {r["id"]: (r.get("photos") or [None])[0] for r in rows}
    (brief, summaries, kudos_counts, my_kudos, comment_counts, signed, thumbs,
     crew_names) = await asyncio.gather(
        profile_service.get_profile_briefs([target_id]),
        _public_route_summaries(),
        _kudos_counts(run_ids),
        _my_kudos_set(run_ids, caller_id),
        _comment_counts(run_ids),
        _signed_photo_urls([p for p in firsts.values() if p]),
        _polyline_thumbs(run_ids),
        # 크루 배너 — 통일 게이트(2026-08-03, 공백 수리: 제3 빌더가 게이트 미경유)
        _k1_crew_names(run_ids, caller_id),
    )
    is_own = caller_id == target_id
    return [
        ActivityFeedItem(
            run_id=row["id"],
            crew_name=crew_names.get(row["id"]),
            user_id=row["user_id"],
            nickname=brief.get(target_id, {}).get("nickname"),
            avatar_url=brief.get(target_id, {}).get("avatar_url"),
            ran_at=row["ran_at"],
            title=row.get("title"),
            area=row.get("area"),
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
            photo_thumb=signed.get(firsts.get(row["id"])),
            polyline_thumb=thumbs.get(row["id"]),
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


async def followers_run_count(target_id: str) -> int:
    """target이 'followers 공개'로 게시한 run 수 (공개 프로필 — "팔로워 공개 M개").

    A′ "숫자는 사실값, 리스트는 잠금"의 숫자 축: 비팔로워에게도 이 카운트는
    노출해 "팔로우하면 M개를 더 볼 수 있다"를 성립시킨다. 목록(GET /users/{id}/runs)은
    현행대로 public만 — followers run 내용(트랙·제목·날짜)은 절대 미노출.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("runs")
        .select("id", count="exact")
        .eq("user_id", target_id)
        .eq("visibility", "followers")
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

        # ④ Sum runs within the challenge period (verified만 — 집계 정합 정책)
        runs_res = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .select("distance_km")
            .in_("user_id", member_ids)
            .gte("ran_at", ch_starts_at)
            .lte("ran_at", ch_ends_at)
            .eq("verification", "verified")
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
                # crew_id는 target_id, challenge_id는 payload로 — 특정 챌린지 딥링크용
                payload={"crew_id": ch_crew_id, "challenge_id": ch_id},
            )
            for mid in member_ids
        ])
        logger.info(
            "Challenge %s completed (achieved=%.2fkm, goal=%.2fkm); notified %d members.",
            ch_id, achieved_km, ch_goal_km, len(member_ids),
        )


async def list_runs(
    user_id: str,
    limit: int = 20,
    route_id: str | None = None,
    before: str | None = None,
) -> list[RunResponse]:
    """Return the caller's logged runs, newest first; optionally filter by route.

    before: 커서(직전 페이지 마지막 run의 ran_at) — 그 시각 "이전" run만.
    최신순이라 offset처럼 삽입·삭제에 밀리지 않는다 (같은 초 동률은 strict
    lt로 스킵 허용 — 실사용상 희귀).
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
        if before is not None:
            q = q.lt("ran_at", before)
        return q.execute()

    result = await asyncio.to_thread(_query)
    run_ids = [row["id"] for row in result.data]
    # 배치 집계로 kudos·댓글 수 (활동 피드와 동일 방식, N+1 방지)
    # 썸네일: 행마다 첫 사진만, 서명 URL은 배치 1콜 (목록 정책 — 설계 §2-E)
    firsts = [(row["photos"] or [None])[0] for row in result.data]
    tracks, kudos, comments, signed, thumbs, crew_fields = await asyncio.gather(
        _track_summaries(run_ids),
        _kudos_counts(run_ids),
        _comment_counts(run_ids),
        _signed_photo_urls([p for p in firsts if p]),
        _polyline_thumbs(run_ids),
        _crew_session_fields(result.data, user_id),
    )
    return [
        RunResponse(**{k: v for k, v in row.items()
                       if k not in ("photos", "crew_id", "session_key", "show_crew")},
                    **crew_fields[row["id"]],
                    has_track=row["id"] in tracks,
                    splits=tracks.get(row["id"]), kudos_count=kudos.get(row["id"], 0),
                    moving_sec=_moving_total(tracks.get(row["id"])),
                    comment_count=comments.get(row["id"], 0),
                    photo_thumb=signed.get(first) if first else None,
                    polyline_thumb=thumbs.get(row["id"]))
        for row, first in zip(result.data, firsts)
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
    # photos 컬럼은 raw 경로 — 응답 계약은 서명 URL이라 여기선 제외
    return RunResponse(**{k: v for k, v in updated.items() if k != "photos"})


async def update_run(
    run_id: str, user_id: str, fields: dict
) -> RunResponse | None:
    """저장 화면 편집: 본인 run의 title/visibility/notes/photos만 (보낸 것만).

    거리·시간·검증값은 불변. user_id로 스코프해 남의 run은 0행(None→404).
    빈 patch면 조회만 해서 현재 상태 반환. splits/has_track도 채워 반환.
    photos: {run_id}/ prefix 밖 경로는 PhotoPathInvalid(→422), 배열에서
    빠진 기존 경로는 Storage에서 best-effort 삭제 (교체·삭제 연동).
    """
    supabase = get_supabase_admin()
    removed_paths: list[str] = []
    if "photos" in fields:
        new_photos = fields["photos"]
        if any(not p.startswith(f"{run_id}/") for p in new_photos):
            raise PhotoPathInvalid()
        cur = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .select("photos")
            .eq("id", run_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not cur.data:
            return None
        removed_paths = [p for p in (cur.data[0].get("photos") or [])
                         if p not in new_photos]
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
        if removed_paths:  # 커밋 후 정리 — 실패해도 다음 교체/탈퇴가 회수 (best-effort)
            try:
                await asyncio.to_thread(
                    lambda: supabase.storage.from_(_PHOTO_BUCKET).remove(removed_paths)
                )
            except Exception:  # noqa: BLE001
                logger.warning("사진 Storage 정리 실패 — 진행 (run=%s)", run_id,
                               exc_info=True)
    # 편집 후(또는 빈 patch) 최신 상태를 splits까지 채워 반환
    return await get_run(run_id, user_id)
