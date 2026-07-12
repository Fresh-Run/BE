"""Orchestration: combine the OpenAI route generation with Map API data.

This is the business-logic glue the API layer calls. It asks OpenAI for a
candidate route, optionally resolves the pitstop against the real Map API,
and enriches the response with actual pedestrian routing geometry.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import defaultdict

from openai import APIError as OpenAIAPIError
from postgrest.exceptions import APIError
from pydantic import ValidationError

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import (
    AiCourseSettings,
    CommentResponse,
    PublicRouteResponse,
    RouteRequest,
    RouteResponse,
    StoredRoute,
)
from app.services import feedback_service, map_service, notification_service, openai_service, profile_service

logger = logging.getLogger(__name__)


class RouteNotFound(Exception):
    """Route does not exist, or is hidden from this user."""


class CommentNotFound(Exception):
    """Comment does not exist under the given route."""


class CommentAccessDenied(Exception):
    """Caller is neither the comment author nor the route owner."""


class RouteGenerationFailed(Exception):
    """Gemini never produced a usable route across all radius attempts."""


async def _course_context(user_id: str | None) -> tuple[AiCourseSettings, str]:
    """(ai_course 선호, lang) — 한 번의 get_settings로 둘 다 (쿼리 증가 0).

    Best-effort like the feedback loop: a settings hiccup must never block
    route generation. 실패 시 서버 기본값 + 'ko'.
    """
    if not user_id:
        return AiCourseSettings(), "ko"
    try:
        s = await profile_service.get_settings(user_id)
        return s.ai_course, s.lang
    except Exception:  # noqa: BLE001 - settings are a preference, not a gate
        logger.warning("Failed to load settings; using defaults.", exc_info=True)
        return AiCourseSettings(), "ko"


def _resolve_course_prefs(
    req: RouteRequest, saved: AiCourseSettings
) -> tuple[float, AiCourseSettings]:
    """Merge body values over saved settings (body > 설정 > 기본값), per field.

    Returns (effective target distance, effective prefs). The saved object
    already has server defaults merged in (get_settings), so only the body
    override step happens here. terrain='hill' + avoid_hills=true resolves
    to avoid_hills winning (terrain drops to 'mixed').
    """
    target_km = (
        req.target_distance_km
        if req.target_distance_km is not None
        else saved.default_distance_km
    )
    prefs = AiCourseSettings(
        terrain=req.terrain if req.terrain is not None else saved.terrain,
        default_distance_km=saved.default_distance_km,
        scenic=req.scenic if req.scenic is not None else saved.scenic,
        avoid_hills=req.avoid_hills if req.avoid_hills is not None else saved.avoid_hills,
        prefer_loop=req.prefer_loop if req.prefer_loop is not None else saved.prefer_loop,
        surface=req.surface if req.surface is not None else saved.surface,
    )
    if prefs.avoid_hills and prefs.terrain == "hill":
        prefs.terrain = "mixed"
    return target_km, prefs


# ── 동적 탐색 반경 ─────────────────────────────────────────────────────────────

_SHORT_RATIO = 0.6      # 실측이 목표×0.6 미만이면 SHORT (미달 방향만 판정)
_MAX_RADIUS_KM = 8.0


def _radius_schedule(target_km: float) -> list[float]:
    """목표 거리 비례 탐색 반경 시퀀스 (최대 4시도, 상한 8km, 중복 제거).

    루프 코스 L km는 기하학상 반경 ~L/4가 필요하므로 r0=clamp(target/4, 1, 8),
    이후 +1.0 → +2.5 → 8.0으로 점증 (기획의 +500m×16회 대신 비용·지연 통제형).
    """
    r0 = min(_MAX_RADIUS_KM, max(1.0, round(target_km / 4, 1)))
    out: list[float] = []
    for r in (r0, r0 + 1.0, r0 + 2.5, _MAX_RADIUS_KM):
        r = min(round(r, 1), _MAX_RADIUS_KM)
        if r not in out:
            out.append(r)
    return out


def _filter_conflicting_avoid_tags(
    avoid_tags: list[str], prefs: AiCourseSettings
) -> list[str]:
    """Drop community hints that contradict the user's explicit preference.

    명시적 유저 선호 > 커뮤니티 힌트: terrain='hill'이면 '오르막많음' 회피를,
    surface='trail'이면 '노면나쁨'(→ well-paved 유도) 회피를 제외한다.
    """
    dropped = set()
    if prefs.terrain == "hill":
        dropped.add("오르막많음")
    if prefs.surface == "trail":
        dropped.add("노면나쁨")
    return [t for t in avoid_tags if t not in dropped]


async def create_running_route(
    req: RouteRequest, user_id: str | None = None
) -> RouteResponse:
    """Produce a running route for the given request.

    Steps:
      1. Ask OpenAI to design a route (structured via function calling).
      2. (Optional) Resolve the pitstop keyword to a real nearby place.
      3. (Optional) Fetch real pedestrian path geometry from the Map API.

    user_id (from a validated token) is stored on the saved route; None for
    anonymous requests.
    """
    # Step 0: learning loop — gather what nearby runners disliked, so the
    # model can avoid it. Best-effort: returns [] on any failure. The user's
    # saved ai_course settings load concurrently (also best-effort).
    avoid_tags, (saved_prefs, lang) = await asyncio.gather(
        feedback_service.collect_avoidance_hints(req.start),
        _course_context(user_id),
    )

    # If the client points at a specific past route, add its negative
    # feedback on top of the location-based hints (union, de-duplicated).
    if req.avoid_from_route_id:
        # owner_id 전달 — 본인 소유 route만 학습 (남의 비공개 route 프로브 차단, M4)
        for tag in await feedback_service.collect_route_avoidance_hints(
            req.avoid_from_route_id, owner_id=user_id
        ):
            if tag not in avoid_tags:
                avoid_tags.append(tag)

    # 우선순위: body 명시값 > 유저 설정 > 서버 기본값. 그리고 명시적 선호와
    # 모순되는 커뮤니티 회피 힌트는 제거 (선호가 이긴다).
    target_km, prefs = _resolve_course_prefs(req, saved_prefs)
    avoid_tags = _filter_conflicting_avoid_tags(avoid_tags, prefs)

    # Step 1~3을 동적 탐색 반경 루프로: 좁은 반경에서 시작해 실패(경로 연결
    # 불가 / 실측 미달)하면 반경을 넓혀 재시도. 출발지는 고정.
    best: RouteResponse | None = None
    short_candidates: list[tuple[float, RouteResponse]] = []  # (실측 km, route)
    nopath_candidate: RouteResponse | None = None
    pitstop_places: list | None = None  # Kakao 검색은 결정적 — 첫 성공 결과 재사용

    # 구간별 계측 (병목 관측용 — 항상 켜둔 경량 타이머)
    _t0 = time.perf_counter()
    _perf = {"gemini_s": 0.0, "gemini_calls": 0, "tmap_s": 0.0, "tmap_legs": 0,
             "attempts": 0}

    for i, radius_km in enumerate(_radius_schedule(target_km)):
        _perf["attempts"] += 1
        try:
            _g = time.perf_counter()
            route = await openai_service.generate_route(
                target_distance_km=target_km,
                start=req.start,
                end=req.end,
                pitstop_keyword=req.pitstop_keyword,
                notes=req.notes,
                avoid_tags=avoid_tags,
                prefs=prefs,
                radius_km=radius_km,
                lang=lang,
            )
            _perf["gemini_s"] += time.perf_counter() - _g
            _perf["gemini_calls"] += 1
        except OpenAIAPIError:
            # ①-a API 장애: 반경과 무관 — 확장 재시도는 낭비. 이미 확보한
            # 후보가 있으면 그걸로 마무리, 없으면 그대로 실패.
            if short_candidates or nopath_candidate is not None:
                logger.warning("Gemini API 장애 (radius=%skm) — 기존 후보로 마무리", radius_km)
                break
            raise
        except (ValueError, ValidationError):
            # ①-b/c/d tool call 없음·파싱·검증 실패: 비결정적 — 이 시도만
            # 무효 처리하고 다음 반경으로 (반경이 커져도 손해 없음).
            logger.warning(
                "Gemini 응답 파싱/검증 실패 (radius=%skm) — 다음 반경으로 재시도",
                radius_km, exc_info=True,
            )
            continue

        # Step 2: snap the pitstop to a real place if a keyword was given.
        if req.pitstop_keyword:
            try:
                if pitstop_places is None:
                    pitstop_places = await map_service.search_places(
                        req.pitstop_keyword, near=req.start
                    )
                if pitstop_places:
                    nearest = pitstop_places[0]
                    for wp in route.waypoints:
                        if wp.is_pitstop:
                            wp.name = nearest.name
                            wp.coordinate = nearest.coordinate
                            wp.description = nearest.address
                            break
            except Exception:  # noqa: BLE001 - map enrichment is best-effort
                # If the Map API fails, keep the AI-suggested pitstop as-is.
                logger.warning(
                    "Pitstop place lookup failed for %r; keeping AI suggestion.",
                    req.pitstop_keyword,
                    exc_info=True,
                )

        route.search_radius_km = radius_km
        route.radius_expanded = i > 0

        # Step 3: 보행 경로 연결 + 실측 거리로 성공 판정.
        #   OK      — 연결됐고 실측 >= 목표×0.6 → 즉시 채택
        #   SHORT   — 연결됐지만 실측 미달       → 후보 보관, 반경 확장
        #   NO_PATH — 연결 실패(또는 waypoint<2) → AI 추정 폴백 보관, 반경 확장
        status = "NO_PATH"
        actual_km = route.total_distance_km
        if len(route.waypoints) >= 2:
            try:
                via = [wp.coordinate for wp in route.waypoints[1:-1]] or None
                _m = time.perf_counter()
                pedestrian = await map_service.get_pedestrian_route(
                    origin=route.waypoints[0].coordinate,
                    destination=route.waypoints[-1].coordinate,
                    waypoints=via,
                )
                _perf["tmap_s"] += time.perf_counter() - _m
                _perf["tmap_legs"] += len(route.waypoints) - 1
                route.polyline = pedestrian.path
                # 표시용: 거리 소수 1자리, 소요시간 정수 분 (소수점 노출 방지)
                route.total_distance_km = round(pedestrian.distance_m / 1000.0, 1)
                route.estimated_duration_min = float(round(pedestrian.duration_s / 60.0))
                actual_km = route.total_distance_km
                status = "OK" if actual_km >= _SHORT_RATIO * target_km else "SHORT"
            except Exception:  # noqa: BLE001 - keep AI estimates if routing fails
                logger.warning(
                    "Pedestrian routing (%s) failed; falling back to AI distance "
                    "estimate. Polyline will be unavailable.",
                    map_service.settings.map_provider,
                    exc_info=True,
                )

        if status == "OK":
            best = route
            break
        if status == "SHORT":
            short_candidates.append((actual_km, route))
        else:
            nopath_candidate = route
        logger.info(
            "코스 생성 %s (radius=%skm, 실측 %.2f / 목표 %skm) — 반경 확장 재시도",
            status, radius_km, actual_km, target_km,
        )

    if best is None:
        # 루프 소진: "짧지만 이거라도" — 연결된 후보 중 목표에 가장 가까운 것,
        # 없으면 마지막 AI 추정 폴백. 유효 응답이 한 번도 없었으면 실패.
        if short_candidates:
            best = min(short_candidates, key=lambda t: abs(t[0] - target_km))[1]
        elif nopath_candidate is not None:
            best = nopath_candidate
        else:
            raise RouteGenerationFailed()

    # 계측 요약 — 병목 분포 관측 (총합/Gemini/T-map/재시도)
    _total = time.perf_counter() - _t0
    logger.info(
        "[PERF] route generate: total=%.1fs | gemini=%.1fs(%d call) | "
        "tmap=%.1fs(%d leg) | attempts=%d | expanded=%s",
        _total, _perf["gemini_s"], _perf["gemini_calls"],
        _perf["tmap_s"], _perf["tmap_legs"], _perf["attempts"],
        best.radius_expanded,
    )

    # Step 4: persist the generated route to Supabase (best-effort).
    await _save_route(req, best, user_id, target_distance_km=target_km)

    return best


async def _save_route(
    req: RouteRequest,
    route: RouteResponse,
    user_id: str | None = None,
    target_distance_km: float | None = None,
) -> None:
    """Insert the generated route into the Supabase `routes` table.

    Best-effort: saving is a side feature, so any failure is logged and
    swallowed rather than breaking route generation. user_id is left NULL
    until authentication is wired up.

    supabase-py is synchronous, so the blocking call is run in a worker
    thread to avoid stalling the async event loop.
    """
    # Start coordinate (from the first waypoint) powers the location-based
    # learning loop; store it as top-level columns for fast proximity queries.
    start_coord = route.waypoints[0].coordinate if route.waypoints else None

    record = {
        # Owner (from a validated token; None when anonymous)
        "user_id": user_id,
        # Input values (RouteRequest; target은 설정 폴백이 반영된 최종값)
        "target_distance_km": (
            target_distance_km
            if target_distance_km is not None
            else req.target_distance_km
        ),
        "pitstop_keyword": req.pitstop_keyword,
        "notes": req.notes,
        # Start coordinate (for the learning loop)
        "start_lat": start_coord.lat if start_coord else None,
        "start_lng": start_coord.lng if start_coord else None,
        # Generated result (RouteResponse)
        "summary": route.summary,
        "total_distance_km": route.total_distance_km,
        "estimated_duration_min": route.estimated_duration_min,
        "waypoints": [wp.model_dump() for wp in route.waypoints],
        "polyline": (
            [c.model_dump() for c in route.polyline]
            if route.polyline is not None
            else None
        ),
    }

    try:
        supabase = get_supabase_admin()
        result = await asyncio.to_thread(
            lambda: supabase.table("routes").insert(record).execute()
        )
        saved_id = result.data[0]["id"] if result.data else "?"
        logger.info("Saved generated route to Supabase (id=%s).", saved_id)
    except Exception:  # noqa: BLE001 - persistence is best-effort
        logger.warning(
            "Failed to save generated route to Supabase; "
            "route generation still succeeded.",
            exc_info=True,
        )


async def list_routes(user_id: str, limit: int = 20) -> list[StoredRoute]:
    """Return the caller's saved routes, newest first.

    Scoped to `user_id` in app code (the service_role client bypasses RLS,
    so this filter is what enforces "my data only" until RLS is enabled).
    """
    limit = max(1, min(limit, 100))
    supabase = get_supabase_admin()
    result = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [StoredRoute(**row) for row in result.data]


async def get_route(route_id: str, user_id: str) -> StoredRoute | None:
    """Return one of the caller's saved routes by id, or None.

    Returns None if the route doesn't exist OR isn't owned by `user_id`,
    so a non-owner cannot fetch someone else's route.
    """
    supabase = get_supabase_admin()
    result = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("id", route_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return StoredRoute(**result.data[0])


_UNIQUE_VIOLATION = "23505"


async def _copy_counts(route_ids: list[str]) -> dict[str, int]:
    """Return {route_id: copy_count} for the given route ids (one IN query)."""
    if not route_ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("copied_from")
        .in_("copied_from", route_ids)
        .execute()
    )
    counts: dict[str, int] = defaultdict(int)
    for row in res.data:
        counts[row["copied_from"]] += 1
    return dict(counts)


async def _like_counts(route_ids: list[str]) -> dict[str, int]:
    """Return {route_id: like_count} for the given ids (one IN query)."""
    if not route_ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("route_likes")
        .select("route_id")
        .in_("route_id", route_ids)
        .execute()
    )
    counts: dict[str, int] = defaultdict(int)
    for row in res.data:
        counts[row["route_id"]] += 1
    return dict(counts)


async def _liked_by_me(route_ids: list[str], user_id: str) -> set[str]:
    """Return the set of route_ids that `user_id` has liked (one IN + eq query)."""
    if not route_ids:
        return set()
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("route_likes")
        .select("route_id")
        .in_("route_id", route_ids)
        .eq("user_id", user_id)
        .execute()
    )
    return {row["route_id"] for row in res.data}


async def _comment_counts(route_ids: list[str]) -> dict[str, int]:
    """Return {route_id: comment_count} for the given ids (one IN query)."""
    if not route_ids:
        return {}
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("route_comments")
        .select("route_id")
        .in_("route_id", route_ids)
        .execute()
    )
    counts: dict[str, int] = defaultdict(int)
    for row in res.data:
        counts[row["route_id"]] += 1
    return dict(counts)


async def like_route(route_id: str, user_id: str) -> None:
    """Add a like to a public route. Idempotent: double-liking is silently ignored.

    Raises RouteNotFound if the route doesn't exist or is not public (treats
    private routes the same as missing to avoid revealing their existence).
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("is_public, user_id")
        .eq("id", route_id)
        .limit(1)
        .execute()
    )
    if not res.data or not res.data[0]["is_public"]:
        raise RouteNotFound()

    route_owner = res.data[0].get("user_id")
    if route_owner and route_owner != user_id and not await profile_service.feed_allows(
        route_owner, "allow_likes"
    ):
        raise profile_service.FeedActionDisabled("likes")
    liked_new = True
    try:
        await asyncio.to_thread(
            lambda: supabase.table("route_likes")
            .insert({"route_id": route_id, "user_id": user_id})
            .execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:  # 23505 = already liked, that's fine
            raise
        liked_new = False

    if liked_new and route_owner:
        try:
            await notification_service.create_notification(
                recipient_id=route_owner,
                actor_id=user_id,
                type="route_liked",
                target_id=route_id,
                target_type="route",
            )
        except Exception:
            logger.warning("route_liked 알림 생성 실패", exc_info=True)


async def unlike_route(route_id: str, user_id: str) -> None:
    """Remove a like from a route. Idempotent: unliking a non-liked route is a no-op."""
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("route_likes")
        .delete()
        .eq("route_id", route_id)
        .eq("user_id", user_id)
        .execute()
    )


async def bookmark_route(route_id: str, user_id: str) -> None:
    """Bookmark a public route. Idempotent: re-bookmarking is silently ignored.

    Same visibility rule as likes (404 for missing/private routes). Bookmarks
    are a private action, so unlike likes no notification is sent.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("is_public")
        .eq("id", route_id)
        .limit(1)
        .execute()
    )
    if not res.data or not res.data[0]["is_public"]:
        raise RouteNotFound()

    try:
        await asyncio.to_thread(
            lambda: supabase.table("route_bookmarks")
            .insert({"route_id": route_id, "user_id": user_id})
            .execute()
        )
    except APIError as exc:
        if exc.code != _UNIQUE_VIOLATION:  # 23505 = already bookmarked, fine
            raise


async def unbookmark_route(route_id: str, user_id: str) -> None:
    """Remove a bookmark. Idempotent: removing a non-bookmark is a no-op."""
    supabase = get_supabase_admin()
    await asyncio.to_thread(
        lambda: supabase.table("route_bookmarks")
        .delete()
        .eq("route_id", route_id)
        .eq("user_id", user_id)
        .execute()
    )


async def list_bookmarked_routes(
    user_id: str, limit: int = 20, offset: int = 0
) -> list[PublicRouteResponse]:
    """The caller's bookmarked routes, most recently bookmarked first.

    Routes that went private after being bookmarked are hidden (same
    don't-reveal rule as elsewhere), so a page can come back shorter than
    `limit` even when more bookmarks exist.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("route_bookmarks")
        .select("route_id")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    route_ids = [row["route_id"] for row in res.data]
    if not route_ids:
        return []

    routes_res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .in_("id", route_ids)
        .eq("is_public", True)
        .execute()
    )
    if not routes_res.data:
        return []

    # Preserve bookmark order (the IN query returns rows unordered).
    by_id = {r["id"]: r for r in routes_res.data}
    rows = [by_id[rid] for rid in route_ids if rid in by_id]
    return await _to_public_responses(rows, user_id)


async def _to_public_responses(
    rows: list[dict], user_id: str
) -> list[PublicRouteResponse]:
    """Enrich raw route rows with counts/is_liked/nicknames (batch, no N+1)."""
    route_ids = [r["id"] for r in rows]
    copy_counts, like_counts, liked_set, comment_counts, nicknames = await asyncio.gather(
        _copy_counts(route_ids),
        _like_counts(route_ids),
        _liked_by_me(route_ids, user_id),
        _comment_counts(route_ids),
        profile_service.get_profile_briefs([r.get("user_id") for r in rows]),
    )
    return [
        PublicRouteResponse(
            **row,
            owner_id=row.get("user_id"),
            is_mine=(row.get("user_id") == user_id),
            owner_nickname=nicknames.get(row.get("user_id"), {}).get("nickname"),
            owner_avatar_url=nicknames.get(row.get("user_id"), {}).get("avatar_url"),
            copy_count=copy_counts.get(row["id"], 0),
            like_count=like_counts.get(row["id"], 0),
            is_liked=row["id"] in liked_set,
            comment_count=comment_counts.get(row["id"], 0),
        )
        for row in rows
    ]


async def list_following_feed(
    user_id: str, limit: int = 20, offset: int = 0
) -> list[PublicRouteResponse]:
    """Public routes by users the caller follows, newest first (limit+offset).

    Returns [] when the caller follows no one. The IN-list approach is fine
    at MVP scale; switch to a join/RPC if following counts grow very large.
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
    following_ids = [row["following_id"] for row in res.data]
    if not following_ids:
        return []

    result = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("is_public", True)
        .in_("user_id", following_ids)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    if not result.data:
        return []
    return await _to_public_responses(result.data, user_id)


async def list_public_routes(
    user_id: str, limit: int = 20, sort: str = "newest"
) -> list[PublicRouteResponse]:
    """Return public routes for the discovery feed.

    sort='newest'  — DB-level ORDER BY created_at DESC + LIMIT (fast).
    sort='popular' — fetch all public routes, batch-count copies, sort in
                     Python by copy_count DESC, then apply limit. Suitable
                     while the public route count is small; switch to an RPC
                     aggregate when scale demands it.
    """
    limit = max(1, min(limit, 100))
    supabase = get_supabase_admin()

    if sort == "newest":
        result = await asyncio.to_thread(
            lambda: supabase.table("routes")
            .select("*")
            .eq("is_public", True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = result.data
    else:  # popular — need all rows to rank, then limit
        result = await asyncio.to_thread(
            lambda: supabase.table("routes")
            .select("*")
            .eq("is_public", True)
            .execute()
        )
        rows = result.data

    if not rows:
        return []

    route_ids = [r["id"] for r in rows]
    copy_counts, like_counts, liked_set, comment_counts, nicknames = await asyncio.gather(
        _copy_counts(route_ids),
        _like_counts(route_ids),
        _liked_by_me(route_ids, user_id),
        _comment_counts(route_ids),
        profile_service.get_profile_briefs([r.get("user_id") for r in rows]),
    )

    if sort == "popular":
        rows = sorted(rows, key=lambda r: copy_counts.get(r["id"], 0), reverse=True)[:limit]

    return [
        PublicRouteResponse(
            **row,
            owner_id=row.get("user_id"),
            is_mine=(row.get("user_id") == user_id),
            owner_nickname=nicknames.get(row.get("user_id"), {}).get("nickname"),
            owner_avatar_url=nicknames.get(row.get("user_id"), {}).get("avatar_url"),
            copy_count=copy_counts.get(row["id"], 0),
            like_count=like_counts.get(row["id"], 0),
            is_liked=row["id"] in liked_set,
            comment_count=comment_counts.get(row["id"], 0),
        )
        for row in rows
    ]


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two (lat, lng) points in kilometres."""
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lng2 - lng1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def search_nearby_routes(
    lat: float,
    lng: float,
    radius_km: float,
    sort_by: str,
    user_id: str,
    limit: int = 20,
) -> list[PublicRouteResponse]:
    """Return public routes whose start point lies within radius_km of (lat, lng).

    Step 1 — SQL bounding box (fast, uses indexes on start_lat / start_lng).
    Step 2 — Python Haversine to drop box-corner false positives.
    Step 3 — sort and limit in Python (copy_count for 'popular', created_at for 'newest').
    """
    limit = max(1, min(limit, 100))
    radius_km = max(0.1, min(radius_km, 50.0))  # 상한 없으면 전 공개코스 풀스캔
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.0 * math.cos(math.radians(lat)))

    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("is_public", True)
        .gte("start_lat", lat - lat_delta)
        .lte("start_lat", lat + lat_delta)
        .gte("start_lng", lng - lng_delta)
        .lte("start_lng", lng + lng_delta)
        .order("created_at", desc=True)
        .execute()
    )

    # Step 2: precise circle filter (removes box-corner false positives)
    rows = [
        r for r in res.data
        if r.get("start_lat") is not None
        and r.get("start_lng") is not None
        and _haversine_km(lat, lng, r["start_lat"], r["start_lng"]) <= radius_km
    ]
    if not rows:
        return []
    # 결정 B: 비공개 계정 owner의 코스는 검색(근처)에서 제외
    visible = await profile_service.visible_owners(user_id, [r.get("user_id") for r in rows])
    rows = [r for r in rows if r.get("user_id") in visible or r.get("user_id") is None]
    if not rows:
        return []

    route_ids = [r["id"] for r in rows]
    copy_counts, like_counts, liked_set, comment_counts, nicknames = await asyncio.gather(
        _copy_counts(route_ids),
        _like_counts(route_ids),
        _liked_by_me(route_ids, user_id),
        _comment_counts(route_ids),
        profile_service.get_profile_briefs([r.get("user_id") for r in rows]),
    )

    if sort_by == "popular":
        rows = sorted(rows, key=lambda r: copy_counts.get(r["id"], 0), reverse=True)

    rows = rows[:limit]

    return [
        PublicRouteResponse(
            **row,
            owner_id=row.get("user_id"),
            is_mine=(row.get("user_id") == user_id),
            owner_nickname=nicknames.get(row.get("user_id"), {}).get("nickname"),
            owner_avatar_url=nicknames.get(row.get("user_id"), {}).get("avatar_url"),
            copy_count=copy_counts.get(row["id"], 0),
            like_count=like_counts.get(row["id"], 0),
            is_liked=row["id"] in liked_set,
            comment_count=comment_counts.get(row["id"], 0),
        )
        for row in rows
    ]


def _sanitize(q: str) -> str:
    """Remove chars that break PostgREST filter syntax or inject extra wildcards."""
    return q.strip().replace(",", "").replace("*", "")


async def search_public_routes(
    q: str, user_id: str, limit: int = 20
) -> list[PublicRouteResponse]:
    """Search public routes by summary (case-insensitive partial match).

    Returns [] when q is blank after sanitization.
    Enriches results with copy_count, like_count, is_liked, comment_count, owner_nickname
    using the same batch pattern as list_public_routes.
    """
    safe = _sanitize(q)
    if not safe:
        return []

    limit = max(1, min(limit, 100))
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("is_public", True)
        .ilike("summary", f"%{safe}%")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = res.data
    if not rows:
        return []
    # 결정 B: owner가 비공개 계정이면 코스가 public이어도 검색에서 제외
    visible = await profile_service.visible_owners(user_id, [r.get("user_id") for r in rows])
    rows = [r for r in rows if r.get("user_id") in visible or r.get("user_id") is None]
    if not rows:
        return []

    route_ids = [r["id"] for r in rows]
    copy_counts, like_counts, liked_set, comment_counts, nicknames = await asyncio.gather(
        _copy_counts(route_ids),
        _like_counts(route_ids),
        _liked_by_me(route_ids, user_id),
        _comment_counts(route_ids),
        profile_service.get_profile_briefs([r.get("user_id") for r in rows]),
    )

    return [
        PublicRouteResponse(
            **row,
            owner_id=row.get("user_id"),
            is_mine=(row.get("user_id") == user_id),
            owner_nickname=nicknames.get(row.get("user_id"), {}).get("nickname"),
            owner_avatar_url=nicknames.get(row.get("user_id"), {}).get("avatar_url"),
            copy_count=copy_counts.get(row["id"], 0),
            like_count=like_counts.get(row["id"], 0),
            is_liked=row["id"] in liked_set,
            comment_count=comment_counts.get(row["id"], 0),
        )
        for row in rows
    ]


async def set_route_public(
    route_id: str, user_id: str, is_public: bool
) -> StoredRoute | None:
    """Publish/unpublish one of the caller's routes. None if not found/not theirs."""
    supabase = get_supabase_admin()
    result = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .update({"is_public": is_public})
        .eq("id", route_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        return None
    return StoredRoute(**result.data[0])


async def copy_route(route_id: str, user_id: str) -> StoredRoute:
    """Copy a route ('이 코스 달리기') into the caller's account.

    The source must be public OR owned by the caller. The copy is created
    private, owned by the caller, with copied_from pointing at the source.
    The source is left unchanged. Raises RouteNotFound otherwise.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("*")
        .eq("id", route_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise RouteNotFound()
    src = res.data[0]
    # Can't copy someone else's private route (don't reveal it exists).
    if not src["is_public"] and src.get("user_id") != user_id:
        raise RouteNotFound()

    record = {
        "user_id": user_id,
        "is_public": False,  # copies start private
        "copied_from": route_id,
        # Copy the route content (but not the source owner's private notes)
        "target_distance_km": src.get("target_distance_km"),
        "pitstop_keyword": src.get("pitstop_keyword"),
        "start_lat": src.get("start_lat"),
        "start_lng": src.get("start_lng"),
        "summary": src["summary"],
        "total_distance_km": src["total_distance_km"],
        "estimated_duration_min": src.get("estimated_duration_min"),
        "waypoints": src.get("waypoints") or [],
        "polyline": src.get("polyline"),
    }
    out = await asyncio.to_thread(
        lambda: supabase.table("routes").insert(record).execute()
    )
    logger.info("User %s copied route %s -> %s.", user_id, route_id, out.data[0]["id"])
    return StoredRoute(**out.data[0])


async def create_comment(route_id: str, user_id: str, content: str) -> CommentResponse:
    """Add a comment to a public route.

    Raises RouteNotFound if the route doesn't exist or is not public.
    """
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("is_public, user_id")
        .eq("id", route_id)
        .limit(1)
        .execute()
    )
    if not res.data or not res.data[0]["is_public"]:
        raise RouteNotFound()

    route_owner = res.data[0].get("user_id")
    if route_owner and route_owner != user_id and not await profile_service.feed_allows(
        route_owner, "allow_comments"
    ):
        raise profile_service.FeedActionDisabled("comments")

    out = await asyncio.to_thread(
        lambda: supabase.table("route_comments")
        .insert({"route_id": route_id, "user_id": user_id, "content": content})
        .execute()
    )
    row = out.data[0]
    nicknames = await profile_service.get_profile_briefs([user_id])

    if route_owner:
        try:
            await notification_service.create_notification(
                recipient_id=route_owner,
                actor_id=user_id,
                type="route_commented",
                target_id=route_id,
                target_type="route",
            )
        except Exception:
            logger.warning("route_commented 알림 생성 실패", exc_info=True)

    brief = nicknames.get(user_id) or {}
    return CommentResponse(**row, nickname=brief.get("nickname"),
                           avatar_url=brief.get("avatar_url"))


async def list_comments(route_id: str, limit: int = 50) -> list[CommentResponse]:
    """Return comments on a public route, oldest first.

    Raises RouteNotFound if the route doesn't exist or is not public.
    """
    limit = max(1, min(limit, 100))
    supabase = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: supabase.table("routes")
        .select("is_public")
        .eq("id", route_id)
        .limit(1)
        .execute()
    )
    if not res.data or not res.data[0]["is_public"]:
        raise RouteNotFound()

    comments_res = await asyncio.to_thread(
        lambda: supabase.table("route_comments")
        .select("*")
        .eq("route_id", route_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    rows = comments_res.data
    if not rows:
        return []

    briefs = await profile_service.get_profile_briefs([r["user_id"] for r in rows])
    return [CommentResponse(**row,
                            nickname=briefs.get(row["user_id"], {}).get("nickname"),
                            avatar_url=briefs.get(row["user_id"], {}).get("avatar_url"))
            for row in rows]


async def delete_comment(route_id: str, comment_id: str, caller_id: str) -> None:
    """Delete a comment. Caller must be the comment author or the route owner.

    Raises CommentNotFound if the comment doesn't exist under this route.
    Raises CommentAccessDenied if the caller has neither permission.
    """
    supabase = get_supabase_admin()
    comment_res = await asyncio.to_thread(
        lambda: supabase.table("route_comments")
        .select("user_id")
        .eq("id", comment_id)
        .eq("route_id", route_id)
        .limit(1)
        .execute()
    )
    if not comment_res.data:
        raise CommentNotFound()

    if comment_res.data[0]["user_id"] != caller_id:
        route_res = await asyncio.to_thread(
            lambda: supabase.table("routes")
            .select("user_id")
            .eq("id", route_id)
            .limit(1)
            .execute()
        )
        if not route_res.data or route_res.data[0]["user_id"] != caller_id:
            raise CommentAccessDenied()

    await asyncio.to_thread(
        lambda: supabase.table("route_comments")
        .delete()
        .eq("id", comment_id)
        .execute()
    )
