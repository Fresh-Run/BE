"""AI 오디오 코치: 코스별 코칭 멘트 스크립트 생성 + 캐시 (coach_scripts).

확정 구조(2026-06-16 회의): Gemini가 스크립트 JSON을 route당 1회 생성하고
프론트가 폰 내장 TTS로 러닝 중 재생한다. 실시간 스트리밍 아님. 실시간 수치
안내(거리/페이스/칼로리)와 날씨 멘트는 프론트 로컬 몫 — 여기서는 위치·구간
기반 정적 멘트만 만든다.
"""

from __future__ import annotations

import asyncio
import logging

from postgrest.exceptions import APIError

from app.core.config import settings
from app.core.supabase_client import get_supabase_admin
from app.models.schemas import CoachCue, CoachScriptResponse
from app.services import openai_service, profile_service

_UNIQUE_VIOLATION = "23505"

logger = logging.getLogger(__name__)

MAX_CUES = 12


class RouteNotFound(Exception):
    """Route does not exist or isn't owned by the caller."""


def _sanitize_cues(cues: list[CoachCue], distance_km: float, waypoint_count: int) -> list[CoachCue]:
    """모델 출력 후처리: at 범위 검증 → 재생 순서 정렬 → 상한 절삭.

    - distance_km 멘트는 0 < at < 코스 거리, waypoint 멘트는 유효 인덱스만 유지
      (범위 밖은 조용히 제거). start/finish는 각 1개만.
    - 정렬: start → (distance_km·waypoint를 진행 순서로) → finish.
      waypoint의 진행 위치는 인덱스 비율 × 거리로 근사 (waypoints는 경로 순서).
    - MAX_CUES 초과 시 start/finish를 보존하고 중간 멘트를 앞에서부터 유지.
    """
    start = [c for c in cues if c.trigger == "start"][:1]
    finish = [c for c in cues if c.trigger == "finish"][:1]

    middle: list[tuple[float, CoachCue]] = []
    for c in cues:
        if c.trigger == "distance_km" and c.at is not None and 0 < c.at < distance_km:
            middle.append((float(c.at), c))
        elif c.trigger == "waypoint" and c.at is not None:
            idx = int(c.at)
            if 0 <= idx < waypoint_count:
                c.at = float(idx)  # 정수화 보정
                # 진행 위치 근사: 인덱스 비율 × 코스 거리
                pos = (idx / max(waypoint_count - 1, 1)) * distance_km
                middle.append((pos, c))
    middle.sort(key=lambda t: t[0])

    keep = MAX_CUES - len(start) - len(finish)
    body = [c for _, c in middle[:max(keep, 0)]]
    return start + body + finish


async def _runner_context(user_id: str) -> tuple[int | None, int | None]:
    """(run_count, avg_pace_sec_per_km) — best-effort, 실패 시 (None, None)."""
    try:
        supabase = get_supabase_admin()
        res = await asyncio.to_thread(
            lambda: supabase.table("runs")
            .select("distance_km, duration_sec")
            .eq("user_id", user_id)
            .execute()
        )
        rows = res.data
        if not rows:
            return None, None
        total_dist = sum(r["distance_km"] for r in rows)
        total_dur = sum(r["duration_sec"] for r in rows)
        avg = round(total_dur / total_dist) if total_dist > 0 else None
        return len(rows), avg
    except Exception:  # noqa: BLE001 - 개인화 컨텍스트는 보너스
        logger.warning("러너 컨텍스트 조회 실패 — 기본 톤으로 생성", exc_info=True)
        return None, None


async def _cached_script(route_id: str) -> dict | None:
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("coach_scripts")
        .select("script, created_at")
        .eq("route_id", route_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def get_or_create_script(route_id: str, user_id: str) -> CoachScriptResponse:
    """캐시가 있으면 재반환(from_cache), 없으면 Gemini로 1회 생성 후 저장.

    프리미엄 게이트는 API 레이어(quota_service.ensure_premium)에서 선행.
    쿼터(주 3회 AI 생성)와는 별개 — 미차감.
    """
    supabase = get_supabase_admin()

    # 본인 소유 route만 (남의 route는 404와 동일 취급 — 존재를 숨김)
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("id, user_id, summary, total_distance_km, waypoints")
        .eq("id", route_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise RouteNotFound()
    route = res.data[0]

    cached = await _cached_script(route_id)
    if cached:
        return CoachScriptResponse(
            route_id=route_id,
            cues=[CoachCue.model_validate(c) for c in cached["script"].get("cues", [])],
            from_cache=True,
            created_at=cached["created_at"],
        )

    waypoints = route.get("waypoints") or []
    distance_km = float(route.get("total_distance_km") or 5.0)

    run_count, avg_pace = await _runner_context(user_id)
    try:
        user_settings = await profile_service.get_settings(user_id)
        cue_interval = user_settings.audio_coach.cue_interval_km
    except Exception:  # noqa: BLE001 - 설정은 밀도 힌트일 뿐
        cue_interval = 1.0

    cues = await openai_service.generate_coach_script(
        distance_km=distance_km,
        summary=route.get("summary") or "러닝 코스",
        waypoints=waypoints,
        run_count=run_count,
        avg_pace_sec_per_km=avg_pace,
        cue_interval_km=cue_interval,
    )
    cues = _sanitize_cues(cues, distance_km, len(waypoints))

    record = {
        "route_id": route_id,
        "user_id": user_id,
        "script": {"cues": [c.model_dump() for c in cues]},
        "model": settings.openai_model,
    }
    try:
        saved = await asyncio.to_thread(
            lambda: supabase.table("coach_scripts").insert(record).execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:
            raise
        # 동시 생성 레이스: 먼저 저장된 쪽을 정본으로 재반환.
        cached = await _cached_script(route_id)
        return CoachScriptResponse(
            route_id=route_id,
            cues=[CoachCue.model_validate(c) for c in cached["script"].get("cues", [])],
            from_cache=True,
            created_at=cached["created_at"],
        )
    logger.info("Coach script 생성 (route=%s, cues=%d)", route_id, len(cues))
    return CoachScriptResponse(
        route_id=route_id,
        cues=cues,
        from_cache=False,
        created_at=saved.data[0]["created_at"],
    )
