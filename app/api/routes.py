"""HTTP route handlers for the running route API."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.core.auth import get_current_user
from app.models.schemas import (
    ActivityFeedItem,
    AnnouncementCreate,
    AvatarUploadUrlResponse,
    AnnouncementDetailResponse,
    AnnouncementResponse,
    AnnouncementUpdate,
    ChallengeCreate,
    ChallengeResponse,
    CoachScriptResponse,
    CommentCreate,
    CommentResponse,
    Coordinate,
    CrewCreate,
    CrewMemberResponse,
    CrewRankingEntry,
    CrewResponse,
    CrewRunItem,
    CrewUpdate,
    CurrentUser,
    FeedbackRequest,
    FollowUserItem,
    IapVerifyRequest,
    IapVerifyResponse,
    InviteCodeResponse,
    JoinByCodeRequest,
    JoinRequestItem,
    JoinRequestResponse,
    KudosUserItem,
    MonthlyInsightResponse,
    MonthlyStatsResponse,
    MyJoinRequestItem,
    NotificationResponse,
    Place,
    ProfileResponse,
    ProfileUpdate,
    PublicProfileResponse,
    PublicRouteResponse,
    PublishRequest,
    QuotaResponse,
    RsvpRequest,
    RouteRequest,
    RouteResponse,
    RunRequest,
    RunResponse,
    RunTrackResponse,
    SettingsPatch,
    StatsResponse,
    StoredRoute,
    TransferRequest,
    UserSettings,
    WeatherResponse,
)
from app.services import (
    announcement_service,
    coach_service,
    crew_service,
    iap_service,
    insight_service,
    follow_service,
    map_service,
    notification_service,
    profile_service,
    quota_service,
    route_service,
    run_service,
    weather_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["routes"])


def _bad_gateway(context: str, exc: Exception) -> HTTPException:
    """502 헬퍼 (감사 L3): 예외 전문은 서버 로그에만, 응답 detail은 고정 문자열.

    이전엔 detail=f"...{exc}"로 postgrest APIError 원문(DB 제약·컬럼/테이블명,
    본인 데이터 파편)이 클라이언트에 노출됐다. 디버깅용 전문은 로그에 유지.
    """
    logger.warning("%s: %s", context, exc, exc_info=True)
    return HTTPException(status_code=502, detail="일시적인 서버 오류입니다. 잠시 후 다시 시도해 주세요.")


@router.get("/me", response_model=CurrentUser, summary="Who am I (auth check)")
async def me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Return the currently authenticated user. Requires a valid Bearer token."""
    return user


@router.get(
    "/me/profile",
    response_model=ProfileResponse | None,
    summary="Get my profile",
)
async def get_my_profile(
    user: CurrentUser = Depends(get_current_user),
) -> ProfileResponse | None:
    """Return the caller's profile, or null if they haven't created one yet."""
    try:
        return await profile_service.get_profile(user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch profile", exc)


@router.patch(
    "/me/profile",
    response_model=ProfileResponse,
    summary="Create/update my profile",
)
async def update_my_profile(
    req: ProfileUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> ProfileResponse:
    """Create or update the caller's profile (nickname must be unique)."""
    try:
        return await profile_service.upsert_profile(user.user_id, req)
    except profile_service.NicknameTaken:
        raise HTTPException(status_code=409, detail="Nickname already taken")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to update profile", exc)


@router.get(
    "/me/settings",
    response_model=UserSettings,
    summary="내 설정 (기본값 머지된 완전한 객체)",
)
async def get_my_settings(
    user: CurrentUser = Depends(get_current_user),
) -> UserSettings:
    """Account settings; users who never saved anything get the defaults."""
    try:
        return await profile_service.get_settings(user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch settings", exc)


@router.patch(
    "/me/settings",
    response_model=UserSettings,
    summary="설정 부분 업데이트 (보낸 키만 deep merge, 멱등)",
)
async def patch_my_settings(
    req: SettingsPatch,
    user: CurrentUser = Depends(get_current_user),
) -> UserSettings:
    """Merge the provided keys and return the full merged object.

    Unknown keys / out-of-range values are rejected with 422 (whitelist).
    """
    try:
        return await profile_service.patch_settings(user.user_id, req)
    except profile_service.ProfileNotFound:
        raise HTTPException(status_code=404, detail="Create a profile first")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to update settings", exc)


@router.get(
    "/me/quota",
    response_model=QuotaResponse,
    summary="내 티어 + AI 생성 쿼터 (이번 주 사용량)",
)
async def get_my_quota(
    user: CurrentUser = Depends(get_current_user),
) -> QuotaResponse:
    """Return the caller's tier and weekly AI-generation quota state."""
    try:
        return await quota_service.get_quota(user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch quota", exc)


@router.post(
    "/iap/verify",
    response_model=IapVerifyResponse,
    summary="Apple 인앱 구독 검증 → premium 전환",
)
async def iap_verify(
    req: IapVerifyRequest,
    user: CurrentUser = Depends(get_current_user),
) -> IapVerifyResponse:
    """Verify a StoreKit 2 signed transaction and activate premium.

    apple 모드: 구매 완료 직후 받은 signedTransaction(JWS)을 jws로 전송.
    같은 거래 재전송은 멱등(갱신 거래는 만료 연장). 다른 계정의 거래 재사용은 409.
    """
    try:
        return await iap_service.verify_purchase(user.user_id, req)
    except iap_service.IapNotConfigured:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "iap_not_configured",
                "message": "구매 검증이 아직 준비되지 않았습니다.",
            },
        )
    except iap_service.InvalidTransaction:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_transaction", "message": "유효하지 않은 구매 정보입니다."},
        )
    except iap_service.TransactionExpired:
        raise HTTPException(
            status_code=400,
            detail={"error": "transaction_expired", "message": "이미 만료된 구독 거래입니다."},
        )
    except iap_service.TransactionAlreadyUsed:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "transaction_already_used",
                "message": "다른 계정에서 이미 사용된 구매입니다.",
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning("IAP 검증 실패", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={"error": "iap_verify_failed", "message": "구매 검증에 실패했습니다."},
        )


_IAP_NOTIF_MAX_BYTES = 50 * 1024  # Apple JWS 알림은 수 KB — 50KB면 넉넉


@router.post("/iap/notifications", summary="App Store Server Notifications V2 수신")
async def iap_notifications(request: Request, body: dict) -> dict:
    """Apple 서버 알림 수신 — 현재는 raw 저장만 (처리는 출시기, iap_service TODO).

    Apple은 200이 아니면 재시도하므로 저장 실패도 200으로 응답하고 로그로 추적.
    인증 없음 (Apple이 호출) — 무인증 raw 적재 DoS 방어로 크기 상한(L2).
    """
    # Content-Length 가드 — 거대 페이로드는 파싱·저장 전에 413으로 차단
    clen = request.headers.get("content-length")
    if clen and clen.isdigit() and int(clen) > _IAP_NOTIF_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        await iap_service.store_notification(body.get("signedPayload") or "")
    except Exception:  # noqa: BLE001
        logger.warning("IAP notification 저장 실패 (200 반환)", exc_info=True)
    return {"status": "ok"}


# --- Users: public profiles & follows ----------------------------------------
# NOTE: any future fixed path (e.g. /users/search) must be declared BEFORE
# these /users/{user_id}/... routes.


@router.get(
    "/users/{user_id}/profile",
    response_model=PublicProfileResponse,
    summary="공개 프로필 조회 (팔로우 수·관계 포함)",
)
async def get_user_profile(
    user_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> PublicProfileResponse:
    """Another user's public profile with follower/following counts and the
    caller's relationship (is_following / is_followed_by)."""
    try:
        return await follow_service.get_public_profile(user_id, viewer_id=user.user_id)
    except follow_service.UserNotFound:
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch profile", exc)


@router.post(
    "/users/{user_id}/follow",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="팔로우",
)
async def follow_user(
    user_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Follow a user. Idempotent: re-following returns 204 as well."""
    try:
        await follow_service.follow_user(user_id, follower_id=user.user_id)
    except follow_service.SelfFollowNotAllowed:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")
    except follow_service.UserNotFound:
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to follow", exc)


@router.delete(
    "/users/{user_id}/follow",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="언팔로우",
)
async def unfollow_user(
    user_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Unfollow a user. Idempotent: unfollowing a non-followed user is a no-op."""
    try:
        await follow_service.unfollow_user(user_id, follower_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to unfollow", exc)


@router.get(
    "/users/{user_id}/followers",
    response_model=list[FollowUserItem],
    summary="팔로워 목록 (최신순)",
)
async def list_user_followers(
    user_id: str,
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[FollowUserItem]:
    """Users who follow user_id, newest first, with per-item is_following."""
    try:
        return await follow_service.list_followers(
            user_id, viewer_id=user.user_id, limit=limit, offset=offset
        )
    except follow_service.UserNotFound:
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list followers", exc)


@router.get(
    "/users/{user_id}/following",
    response_model=list[FollowUserItem],
    summary="팔로잉 목록 (최신순)",
)
async def list_user_following(
    user_id: str,
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[FollowUserItem]:
    """Users whom user_id follows, newest first, with per-item is_following."""
    try:
        return await follow_service.list_following(
            user_id, viewer_id=user.user_id, limit=limit, offset=offset
        )
    except follow_service.UserNotFound:
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list following", exc)


@router.get(
    "/users/{user_id}/runs",
    response_model=list[ActivityFeedItem],
    summary="공개 프로필 러닝 목록 (조회자 가시성 필터)",
)
async def list_public_user_runs(
    user_id: str,
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[ActivityFeedItem]:
    """그 유저의 '게시한 러닝' — 조회자가 볼 수 있는 run만 (본인=전부, public=
    누구나, followers=팔로우 시, private=제외). 활동 피드와 동일 카드 shape."""
    try:
        return await run_service.list_user_runs(
            user_id, caller_id=user.user_id, limit=limit, offset=offset
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list user runs", exc)


@router.post(
    "/routes/generate",
    response_model=RouteResponse,
    summary="Generate a running route",
)
async def generate_route(
    req: RouteRequest,
    user: CurrentUser = Depends(get_current_user),
) -> RouteResponse:
    """Generate an AI running route, enriched with real Map API data.

    Requires authentication; the route is saved under the caller's user_id.
    Free-tier users are limited to 3 generations per KST week (429 when
    exceeded, checked before any external API call). Premium is unlimited.
    """
    try:
        await quota_service.check_ai_quota(user.user_id)
    except quota_service.QuotaExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exceeded",
                "limit": exc.limit,
                "used": exc.used,
                "remaining": 0,
                "reset_at": exc.reset_at,
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to check quota", exc)

    try:
        route = await route_service.create_running_route(req, user_id=user.user_id)
    except Exception:  # noqa: BLE001
        logger.warning("코스 생성 실패", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "route_generation_failed",
                "message": "코스 생성에 실패했어요. 잠시 후 다시 시도해 주세요.",
            },
        )

    # Only successful generations consume quota (a 502 above costs nothing).
    await quota_service.record_ai_generation(user.user_id)
    return route


@router.get(
    "/routes",
    response_model=list[StoredRoute],
    summary="List saved routes",
)
async def list_routes(
    limit: int = 20,
    user: CurrentUser = Depends(get_current_user),
) -> list[StoredRoute]:
    """Return the caller's saved routes, newest first."""
    try:
        return await route_service.list_routes(user_id=user.user_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list routes", exc)


@router.post(
    "/routes/{route_id}/coach-script",
    response_model=CoachScriptResponse,
    summary="AI 오디오 코치 스크립트 (프리미엄, route당 1회 생성 후 캐시)",
)
async def create_coach_script(
    route_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> CoachScriptResponse:
    """Generate (or return the cached) TTS coach script for one of my routes.

    Premium only (403 premium_required). Weekly AI quota is NOT consumed —
    the per-route cache is the natural cap. 404 for missing/others' routes.
    """
    try:
        await quota_service.ensure_premium(user.user_id, "audio_coach")
    except quota_service.PremiumRequired:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "premium_required",
                "message": "AI 오디오 코치는 프리미엄 전용 기능이에요.",
                "feature": "audio_coach",
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to check tier", exc)

    try:
        return await coach_service.get_or_create_script(route_id, user.user_id)
    except coach_service.RouteNotFound:
        raise HTTPException(status_code=404, detail="Route not found")
    except Exception:  # noqa: BLE001
        logger.warning("코치 스크립트 생성 실패", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "coach_script_failed",
                "message": "코치 스크립트 생성에 실패했어요. 잠시 후 다시 시도해 주세요.",
            },
        )


@router.get(
    "/feed",
    response_model=list[PublicRouteResponse],
    summary="팔로잉 피드 (팔로우한 유저들의 공개 코스, 최신순)",
)
async def following_feed(
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[PublicRouteResponse]:
    """Public routes by users the caller follows, newest first.

    Returns an empty list when the caller follows no one.
    """
    try:
        return await route_service.list_following_feed(
            user.user_id, limit=limit, offset=offset
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch feed", exc)


@router.get(
    "/feed/activities",
    response_model=list[ActivityFeedItem],
    summary="활동 피드 (팔로우한 유저 + 내 run, 최신 활동순)",
)
async def activity_feed(
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[ActivityFeedItem]:
    """Runs by followed users plus my own, newest ran_at first, with kudos.

    v1 home uses GET /feed (course feed); this is the v2 activity feed.
    """
    try:
        return await run_service.list_activity_feed(
            user.user_id, limit=limit, offset=offset
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch activity feed", exc)


# NOTE: /routes/search and /routes/public must be declared BEFORE /routes/{route_id}.
@router.get(
    "/routes/search",
    response_model=list[PublicRouteResponse],
    summary="Search public routes by summary keyword",
)
async def search_public_routes(
    q: str = "",
    limit: int = 20,
    user: CurrentUser = Depends(get_current_user),
) -> list[PublicRouteResponse]:
    """Case-insensitive partial match on summary. Returns [] for blank query."""
    try:
        return await route_service.search_public_routes(q, user_id=user.user_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Route search failed", exc)


@router.get(
    "/routes/public",
    response_model=list[PublicRouteResponse],
    summary="Browse public routes (discovery feed)",
)
async def list_public_routes(
    limit: int = 20,
    sort: Literal["newest", "popular"] = "newest",
    user: CurrentUser = Depends(get_current_user),
) -> list[PublicRouteResponse]:
    """Return public routes; sort='newest' (default) or 'popular' (most copied first)."""
    try:
        return await route_service.list_public_routes(user.user_id, limit=limit, sort=sort)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list public routes", exc)


@router.get(
    "/routes/nearby",
    response_model=list[PublicRouteResponse],
    summary="내 근처 공개 코스 (반경 N km)",
)
async def list_nearby_routes(
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float | None = None,
    limit: int = 20,
    sort_by: Literal["newest", "popular"] = "newest",
    user: CurrentUser = Depends(get_current_user),
) -> list[PublicRouteResponse]:
    """Public routes whose start point is within radius_km of (lat, lng).

    lat, lng, radius_km are all required; returns 400 if any is missing.
    """
    if lat is None or lng is None or radius_km is None:
        raise HTTPException(status_code=400, detail="lat, lng, radius_km are required")
    try:
        return await route_service.search_nearby_routes(
            lat=lat, lng=lng, radius_km=radius_km,
            sort_by=sort_by, user_id=user.user_id, limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Nearby route search failed", exc)


@router.get(
    "/routes/bookmarked",
    response_model=list[PublicRouteResponse],
    summary="저장한(북마크) 코스 목록 (최신 저장순)",
)
async def list_bookmarked_routes(
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[PublicRouteResponse]:
    """The caller's bookmarked routes; routes that went private are hidden."""
    try:
        return await route_service.list_bookmarked_routes(
            user.user_id, limit=limit, offset=offset
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list bookmarks", exc)


@router.get(
    "/routes/{route_id}",
    response_model=StoredRoute,
    summary="Get a saved route by id",
)
async def get_route(
    route_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> StoredRoute:
    """Return one of the caller's saved routes, or 404 if not found/not theirs."""
    try:
        route = await route_service.get_route(route_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch route", exc)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


@router.patch(
    "/routes/{route_id}",
    response_model=StoredRoute,
    summary="Publish/unpublish a route",
)
async def publish_route(
    route_id: str,
    req: PublishRequest,
    user: CurrentUser = Depends(get_current_user),
) -> StoredRoute:
    """Toggle a route's public visibility (owner only); 404 if not found/not theirs."""
    try:
        route = await route_service.set_route_public(
            route_id, user_id=user.user_id, is_public=req.is_public
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to update route", exc)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


@router.post(
    "/routes/{route_id}/copy",
    response_model=StoredRoute,
    summary="Copy a route into my account ('이 코스 달리기')",
)
async def copy_route(
    route_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> StoredRoute:
    """Copy a public (or own) route into the caller's account as a private route."""
    try:
        return await route_service.copy_route(route_id, user_id=user.user_id)
    except route_service.RouteNotFound:
        raise HTTPException(status_code=404, detail="Route not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to copy route", exc)


@router.post(
    "/routes/{route_id}/like",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Like a public route (idempotent)",
)
async def like_route(
    route_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Like a public route. Safe to call twice (double-like is silently ignored)."""
    try:
        await route_service.like_route(route_id, user_id=user.user_id)
    except route_service.RouteNotFound:
        raise HTTPException(status_code=404, detail="Route not found or not public")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to like route", exc)


@router.delete(
    "/routes/{route_id}/like",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlike a route (idempotent)",
)
async def unlike_route(
    route_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Remove a like. Safe to call when not already liked (no-op)."""
    try:
        await route_service.unlike_route(route_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to unlike route", exc)


@router.post(
    "/routes/{route_id}/bookmark",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="코스 북마크 (멱등)",
)
async def bookmark_route(
    route_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Bookmark a public route. Idempotent: re-bookmarking returns 204 too."""
    try:
        await route_service.bookmark_route(route_id, user_id=user.user_id)
    except route_service.RouteNotFound:
        raise HTTPException(status_code=404, detail="Route not found or not public")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to bookmark route", exc)


@router.delete(
    "/routes/{route_id}/bookmark",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="코스 북마크 해제 (멱등)",
)
async def unbookmark_route(
    route_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Remove a bookmark. Safe to call when not bookmarked (no-op)."""
    try:
        await route_service.unbookmark_route(route_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to unbookmark route", exc)


@router.post(
    "/routes/{route_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a comment to a public route",
)
async def create_comment(
    route_id: str,
    req: CommentCreate,
    user: CurrentUser = Depends(get_current_user),
) -> CommentResponse:
    """Add a comment (1–500 chars). Route must be public; 404 otherwise."""
    try:
        return await route_service.create_comment(route_id, user_id=user.user_id, content=req.content)
    except route_service.RouteNotFound:
        raise HTTPException(status_code=404, detail="Route not found or not public")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to create comment", exc)


@router.get(
    "/routes/{route_id}/comments",
    response_model=list[CommentResponse],
    summary="List comments on a public route (oldest first)",
)
async def list_comments(
    route_id: str,
    limit: int = 50,
    user: CurrentUser = Depends(get_current_user),
) -> list[CommentResponse]:
    """Return comments for a public route, oldest first."""
    try:
        return await route_service.list_comments(route_id, limit=limit)
    except route_service.RouteNotFound:
        raise HTTPException(status_code=404, detail="Route not found or not public")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch comments", exc)


@router.delete(
    "/routes/{route_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a comment (author or route owner)",
)
async def delete_comment(
    route_id: str,
    comment_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Delete a comment. Allowed for the comment author or the route owner; 403 otherwise."""
    try:
        await route_service.delete_comment(route_id, comment_id=comment_id, caller_id=user.user_id)
    except route_service.CommentNotFound:
        raise HTTPException(status_code=404, detail="Comment not found")
    except route_service.CommentAccessDenied:
        raise HTTPException(status_code=403, detail="Not authorized to delete this comment")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to delete comment", exc)


@router.post("/runs", response_model=RunResponse, summary="Log an actual run")
async def create_run(
    req: RunRequest,
    user: CurrentUser = Depends(get_current_user),
) -> RunResponse:
    """Save a completed run (under the caller's user_id) and return the record."""
    try:
        return await run_service.create_run(req, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to save run", exc)


@router.patch(
    "/runs/{run_id}/feedback",
    response_model=RunResponse,
    summary="Submit feedback for a run",
)
async def submit_feedback(
    run_id: str,
    req: FeedbackRequest,
    user: CurrentUser = Depends(get_current_user),
) -> RunResponse:
    """Attach feedback to one of the caller's runs; 404 if not found/not theirs."""
    try:
        run = await run_service.set_feedback(
            run_id, liked=req.liked, tags=req.tags, user_id=user.user_id
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to save feedback", exc)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get(
    "/me/stats",
    response_model=StatsResponse,
    summary="내 러닝 통계 (이번 주·이번 달·전체)",
)
async def my_stats(
    user: CurrentUser = Depends(get_current_user),
) -> StatsResponse:
    """Return this-week / this-month / all-time stats with delta vs previous period."""
    try:
        return await run_service.get_my_stats(user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to compute stats", exc)


@router.get(
    "/me/stats/monthly",
    response_model=MonthlyStatsResponse,
    summary="월 선택 통계 + 일별 내역 (기록 탭 캘린더용)",
)
async def my_monthly_stats(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    user: CurrentUser = Depends(get_current_user),
) -> MonthlyStatsResponse:
    """Stats for one KST month; `days` lists only dates that have runs."""
    try:
        return await run_service.get_monthly_stats(user.user_id, year=year, month=month)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to compute monthly stats", exc)


@router.get("/runs", response_model=list[RunResponse], summary="List logged runs")
async def list_runs(
    limit: int = 20,
    route_id: str | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[RunResponse]:
    """Return the caller's logged runs, newest first; optionally filter by route_id."""
    try:
        return await run_service.list_runs(
            user_id=user.user_id, limit=limit, route_id=route_id
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list runs", exc)


@router.get(
    "/runs/{run_id}",
    response_model=RunResponse,
    summary="러닝 기록 단건 조회 (본인 것만)",
)
async def get_run(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> RunResponse:
    """Return one of the caller's runs; 404 if missing or not theirs."""
    try:
        run = await run_service.get_run(run_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch run", exc)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get(
    "/runs/{run_id}/track",
    response_model=RunTrackResponse,
    summary="러닝 경로 (GPS 폴리라인, 상세 화면 전용)",
)
async def get_run_track(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> RunTrackResponse:
    """The run's simplified GPS polyline. 404 if not mine or no track."""
    try:
        track = await run_service.get_run_track(run_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch track", exc)
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")
    return track


@router.post(
    "/runs/{run_id}/kudos",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="run에 kudos (멱등, 본인 run 불가)",
)
async def give_kudos(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Kudos a run. Double-tap safe; the owner is notified once."""
    try:
        await run_service.give_kudos(run_id, user_id=user.user_id)
    except run_service.RunNotFound:
        raise HTTPException(status_code=404, detail="Run not found")
    except run_service.RunNotVisible:
        raise HTTPException(status_code=404, detail="Run not found")  # 존재 은닉
    except run_service.SelfKudos:
        raise HTTPException(status_code=400, detail="Cannot kudos your own run")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to give kudos", exc)


@router.delete(
    "/runs/{run_id}/kudos",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="kudos 취소 (멱등)",
)
async def remove_kudos(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Remove a kudos. Safe to call when not kudoed (no-op)."""
    try:
        await run_service.remove_kudos(run_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to remove kudos", exc)


@router.get(
    "/runs/{run_id}/kudos",
    response_model=list[KudosUserItem],
    summary="kudos 누른 사람 목록 (최신순)",
)
async def list_kudos_users(
    run_id: str,
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[KudosUserItem]:
    """Users who kudoed this run, newest first. 보이는 run만 (본인·팔로우·크루)."""
    try:
        return await run_service.list_kudos_users(
            run_id, caller_id=user.user_id, limit=limit, offset=offset
        )
    except (run_service.RunNotFound, run_service.RunNotVisible):
        raise HTTPException(status_code=404, detail="Run not found")  # 존재 은닉
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list kudos", exc)


# --- Community: crews --------------------------------------------------------


@router.post("/crews", response_model=CrewResponse, summary="Create a crew")
async def create_crew(
    req: CrewCreate,
    user: CurrentUser = Depends(get_current_user),
) -> CrewResponse:
    """Create a crew; the caller becomes its owner and first member.

    Free tier may own FREE_CREW_LIMIT(=1) crews; premium is unlimited.
    Deleting a crew or transferring ownership frees the slot again.
    """
    try:
        await quota_service.ensure_crew_creation(user.user_id)
    except quota_service.CrewLimitExceeded as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "premium_required",
                "message": (
                    f"무료 플랜은 크루를 {exc.limit}개까지 만들 수 있어요. "
                    "프리미엄으로 업그레이드하면 무제한이에요."
                ),
                "feature": "crew_create",
                "limit": exc.limit,
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to check crew limit", exc)

    try:
        return await crew_service.create_crew(req, owner_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to create crew", exc)


@router.get(
    "/crews",
    response_model=list[CrewResponse],
    summary="Browse crews (지역 필터·거리순·정원 토글, 파라미터 없으면 기존 동작)",
)
async def browse_crews(
    sido: str | None = None,
    sigungu: str | None = None,
    lat: float | None = Query(None, ge=33.0, le=39.0),
    lng: float | None = Query(None, ge=124.0, le=132.0),
    include_full: bool = False,
    limit: int = 50,
    user: CurrentUser = Depends(get_current_user),
) -> list[CrewResponse]:
    """공개 크루(+내 비공개)를 둘러보기용으로. lat/lng 있으면 거리순+distance_km,
    sido/sigungu로 행정구역 필터, include_full=false면 정원 찬 크루 제외.
    """
    try:
        return await crew_service.list_browse_crews(
            user.user_id, sido=sido, sigungu=sigungu, lat=lat, lng=lng,
            include_full=include_full, limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list crews", exc)


@router.get(
    "/crews/search",
    response_model=list[CrewResponse],
    summary="Search public crews by name, area, or description",
)
async def search_crews(
    q: str = "",
    limit: int = 20,
    user: CurrentUser = Depends(get_current_user),
) -> list[CrewResponse]:
    """Case-insensitive partial match across name, area, description. Returns [] for blank query."""
    try:
        return await crew_service.search_crews(q, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Crew search failed", exc)


@router.get(
    "/crews/mine",
    response_model=list[CrewResponse],
    summary="List my crews",
)
async def my_crews(
    user: CurrentUser = Depends(get_current_user),
) -> list[CrewResponse]:
    """List crews the caller is a member of."""
    try:
        return await crew_service.list_my_crews(user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list my crews", exc)


# NOTE: /crews/preview-by-code and /crews/join-by-code are FIXED paths and
# must stay declared BEFORE /crews/{crew_id} (else {crew_id} swallows them).


@router.get(
    "/crews/preview-by-code",
    response_model=CrewResponse,
    summary="초대 코드로 크루 미리보기 (가입 확정 전 확인)",
)
async def preview_crew_by_code(
    code: str,
    user: CurrentUser = Depends(get_current_user),
) -> CrewResponse:
    """Which crew does this code open? Works for private crews too."""
    try:
        return await crew_service.preview_by_code(code)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    except Exception:  # noqa: BLE001 — 코드 값이 에러에 실리지 않게 고정 메시지
        raise HTTPException(status_code=502, detail="Failed to preview invite code")


@router.post(
    "/crews/join-by-code",
    response_model=CrewResponse,
    summary="초대 코드로 가입 (join_policy·비공개 무관 즉시 가입)",
)
async def join_crew_by_code(
    req: JoinByCodeRequest,
    user: CurrentUser = Depends(get_current_user),
) -> CrewResponse:
    """Invite = pre-approval: joins immediately, even for private/approval
    crews. Clears any leftover pending join request."""
    try:
        return await crew_service.join_by_code(req.code, user.user_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    except crew_service.AlreadyMember:
        raise HTTPException(status_code=409, detail="Already a member")
    except crew_service.CrewFull:
        raise HTTPException(status_code=409, detail="Crew is full")
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Failed to join by invite code")


@router.get(
    "/crews/{crew_id}/invite",
    response_model=InviteCodeResponse,
    summary="초대 코드 조회 (크루장; 미발급이면 404)",
)
async def get_invite_code(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> InviteCodeResponse:
    """Current invite code. 404 until first issued (frontend then POSTs)."""
    try:
        code = await crew_service.get_invite_code(crew_id, caller_id=user.user_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can view the invite code")
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Failed to fetch invite code")
    if code is None:
        raise HTTPException(status_code=404, detail="No invite code issued yet")
    return InviteCodeResponse(code=code)


@router.post(
    "/crews/{crew_id}/invite",
    response_model=InviteCodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="초대 코드 생성/재생성 (크루장; 이전 코드 즉시 무효)",
)
async def regenerate_invite_code(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> InviteCodeResponse:
    """Issue a fresh code (leak response: old code stops working)."""
    try:
        code = await crew_service.regenerate_invite_code(crew_id, caller_id=user.user_id)
        return InviteCodeResponse(code=code)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can issue invite codes")
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Failed to issue invite code")


@router.get(
    "/crews/{crew_id}/challenges/current",
    response_model=ChallengeResponse | None,
    summary="Get current crew challenge with progress",
)
async def get_current_challenge(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> ChallengeResponse | None:
    """Return the active/upcoming challenge + real-time progress, or null if none."""
    try:
        return await crew_service.get_current_challenge(crew_id, caller_id=user.user_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch challenge", exc)


@router.post(
    "/crews/{crew_id}/challenges",
    response_model=ChallengeResponse,
    summary="Create a crew challenge (owner only)",
)
async def create_challenge(
    crew_id: str,
    req: ChallengeCreate,
    user: CurrentUser = Depends(get_current_user),
) -> ChallengeResponse:
    """Owner-only: create a challenge. 409 if a non-ended challenge already exists."""
    try:
        return await crew_service.create_challenge(crew_id, caller_id=user.user_id, req=req)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can create a challenge")
    except crew_service.ChallengeAlreadyActive:
        raise HTTPException(status_code=409, detail="A challenge is already active or scheduled")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to create challenge", exc)


@router.get(
    "/crews/{crew_id}/ranking",
    response_model=list[CrewRankingEntry],
    summary="Weekly distance ranking for a crew",
)
async def crew_ranking(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> list[CrewRankingEntry]:
    """Members ranked by distance run since Monday 00:00 KST. Members with no runs this week are omitted."""
    try:
        return await crew_service.get_weekly_ranking(crew_id, caller_id=user.user_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch ranking", exc)


@router.get(
    "/crews/{crew_id}/members",
    response_model=list[CrewMemberResponse],
    summary="List crew members",
)
async def list_crew_members(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> list[CrewMemberResponse]:
    """Return the member roster (public crew: anyone; private: members only)."""
    try:
        return await crew_service.list_members(crew_id, caller_id=user.user_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch members", exc)


@router.delete(
    "/crews/{crew_id}/members/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Kick a member (owner only)",
)
async def kick_member(
    crew_id: str,
    target_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Owner-only: remove a member. Owner cannot kick themselves (400)."""
    try:
        await crew_service.kick_member(crew_id, caller_id=user.user_id, target_id=target_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can kick members")
    except crew_service.OwnerCannotKickSelf:
        raise HTTPException(
            status_code=400,
            detail="Owner cannot kick themselves; use leave, transfer, or delete instead.",
        )
    except crew_service.NotAMember:
        raise HTTPException(status_code=404, detail="User is not a member of this crew")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to kick member", exc)


@router.get(
    "/crews/{crew_id}",
    response_model=CrewResponse,
    summary="Get a crew by id",
)
async def get_crew(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> CrewResponse:
    """Return a crew if public or the caller is a member; otherwise 404."""
    try:
        crew = await crew_service.get_crew(crew_id, user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch crew", exc)
    if crew is None:
        raise HTTPException(status_code=404, detail="Crew not found")
    return crew


@router.post(
    "/crews/{crew_id}/join",
    response_model=CrewResponse | JoinRequestResponse,
    summary="Join a crew (open=200 즉시 가입 / approval=202 신청)",
)
async def join_crew(
    crew_id: str,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
) -> CrewResponse | JoinRequestResponse:
    """Join a public crew.

    Open crews admit immediately (200, CrewResponse — unchanged behaviour).
    Approval crews create a pending request instead (202, JoinRequestResponse)
    and notify the owner.
    """
    try:
        result = await crew_service.join_crew(crew_id, user.user_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.CrewAccessDenied:
        raise HTTPException(status_code=403, detail="This crew is private")
    except crew_service.AlreadyMember:
        raise HTTPException(status_code=409, detail="Already a member")
    except crew_service.CrewFull:
        raise HTTPException(status_code=409, detail="Crew is full")
    except crew_service.AlreadyRequested:
        raise HTTPException(
            status_code=409,
            detail={"error": "already_requested", "message": "이미 가입 신청이 대기 중입니다."},
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to join crew", exc)
    if isinstance(result, JoinRequestResponse):
        response.status_code = status.HTTP_202_ACCEPTED
    return result


@router.post(
    "/me/avatar/upload-url",
    response_model=AvatarUploadUrlResponse,
    summary="아바타 업로드 URL 발급 (Storage 직접 업로드용)",
)
async def create_avatar_upload_url(
    user: CurrentUser = Depends(get_current_user),
) -> AvatarUploadUrlResponse:
    """3단계 업로드 흐름의 1단계 — ① 이 URL 발급 ② 앱이 이미지를 PUT
    ③ PATCH /me/profile로 public_url을 avatar_url에 저장.
    """
    try:
        return await profile_service.create_avatar_upload_url(user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to create upload url", exc)


@router.get(
    "/me/insights/monthly",
    response_model=MonthlyInsightResponse,
    summary="AI 월간 인사이트 (프리미엄 월간 리포트)",
)
async def get_monthly_insight(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    user: CurrentUser = Depends(get_current_user),
) -> MonthlyInsightResponse:
    """Premium monthly report: fresh stats blocks + cached AI coaching text.

    수치 블록은 매 요청 계산, ai 블록만 캐시(이번 달은 러닝할 때만 재생성).
    run 0회 달은 ai=null (Gemini 미호출). free는 403 premium_required.
    """
    try:
        await quota_service.ensure_premium(user.user_id, "monthly_insight")
    except quota_service.PremiumRequired:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "premium_required",
                "message": "AI 월간 인사이트는 프리미엄 전용 기능이에요.",
                "feature": "monthly_insight",
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to check tier", exc)

    try:
        return await insight_service.get_monthly_insight(user.user_id, year, month)
    except Exception:  # noqa: BLE001
        logger.warning("월간 인사이트 생성 실패", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "insight_failed",
                "message": "월간 인사이트 생성에 실패했어요. 잠시 후 다시 시도해 주세요.",
            },
        )


@router.get(
    "/me/join-requests",
    response_model=list[MyJoinRequestItem],
    summary="내 가입 신청 전체 목록 (모든 크루, 최신순)",
)
async def list_my_join_requests_all(
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[MyJoinRequestItem]:
    """The caller's join requests across all crews (all statuses), newest first.

    둘러보기 화면의 '신청됨' 뱃지를 한 번에 채우는 용도. 크루별 단건 조회
    (GET /crews/{id}/join-requests/me)는 그대로 유지된다.
    """
    try:
        return await crew_service.list_my_join_requests(
            user.user_id, limit=limit, offset=offset
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list join requests", exc)


# NOTE: /join-requests/me must be declared before /join-requests/{request_id}/...


@router.get(
    "/crews/{crew_id}/join-requests/me",
    response_model=JoinRequestResponse,
    summary="내 가입 신청 상태 (pending/rejected 등)",
)
async def get_my_join_request(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> JoinRequestResponse:
    """The caller's most recent join request for this crew; 404 if none."""
    try:
        result = await crew_service.get_my_join_request(crew_id, user.user_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch join request", exc)
    if result is None:
        raise HTTPException(status_code=404, detail="No join request")
    return result


@router.delete(
    "/crews/{crew_id}/join-requests/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="내 가입 신청 취소 (멱등)",
)
async def cancel_my_join_request(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Cancel the caller's pending request; 204 even when there is none."""
    try:
        await crew_service.cancel_my_join_request(crew_id, user.user_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to cancel join request", exc)


@router.get(
    "/crews/{crew_id}/join-requests",
    response_model=list[JoinRequestItem],
    summary="가입 신청 목록 (크루장, 최신순)",
)
async def list_join_requests(
    crew_id: str,
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[JoinRequestItem]:
    """Pending join requests with nicknames (owner only)."""
    try:
        return await crew_service.list_join_requests(
            crew_id, caller_id=user.user_id, limit=limit, offset=offset
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can view join requests")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list join requests", exc)


@router.post(
    "/crews/{crew_id}/join-requests/{request_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="가입 신청 승인 (크루장 → 멤버 추가 + 알림)",
)
async def approve_join_request(
    crew_id: str,
    request_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Approve: admit as member and notify the requester (join_approved)."""
    try:
        await crew_service.decide_join_request(
            crew_id, caller_id=user.user_id, request_id=request_id, approve=True
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can approve")
    except crew_service.JoinRequestNotFound:
        raise HTTPException(status_code=404, detail="Join request not found or already decided")
    except crew_service.CrewFull:
        raise HTTPException(status_code=409, detail="Crew is full")  # 신청은 pending 유지
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to approve join request", exc)


@router.post(
    "/crews/{crew_id}/join-requests/{request_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="가입 신청 거절 (크루장, 무알림)",
)
async def reject_join_request(
    crew_id: str,
    request_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Reject silently (no notification by design; requester can re-apply)."""
    try:
        await crew_service.decide_join_request(
            crew_id, caller_id=user.user_id, request_id=request_id, approve=False
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can reject")
    except crew_service.JoinRequestNotFound:
        raise HTTPException(status_code=404, detail="Join request not found or already decided")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to reject join request", exc)


@router.delete(
    "/crews/{crew_id}/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Leave a crew",
)
async def leave_crew(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Leave a crew. The owner cannot leave (delete/transfer instead)."""
    try:
        await crew_service.leave_crew(crew_id, user.user_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotAMember:
        raise HTTPException(status_code=404, detail="You are not a member of this crew")
    except crew_service.OwnerCannotLeave:
        raise HTTPException(
            status_code=400,
            detail="Owner cannot leave; delete the crew or transfer ownership.",
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to leave crew", exc)


@router.patch(
    "/crews/{crew_id}",
    response_model=CrewResponse,
    summary="Update crew info (owner only)",
)
async def update_crew(
    crew_id: str,
    req: CrewUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> CrewResponse:
    """Partially update a crew. Only provided fields are changed; owner_id is immutable."""
    try:
        return await crew_service.update_crew(crew_id, caller_id=user.user_id, req=req)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can update the crew")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to update crew", exc)


@router.patch(
    "/crews/{crew_id}/transfer",
    response_model=CrewResponse,
    summary="Transfer crew ownership",
)
async def transfer_crew(
    crew_id: str,
    req: TransferRequest,
    user: CurrentUser = Depends(get_current_user),
) -> CrewResponse:
    """Owner-only: hand ownership to another member (optionally leave after)."""
    try:
        return await crew_service.transfer_ownership(
            crew_id,
            caller_id=user.user_id,
            new_owner_id=req.new_owner_id,
            leave_after=req.leave_after,
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can transfer")
    except crew_service.AlreadyOwner:
        raise HTTPException(status_code=400, detail="Target is already the owner")
    except crew_service.TargetNotMember:
        raise HTTPException(
            status_code=400, detail="Target must be a member of the crew"
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to transfer crew", exc)


@router.delete(
    "/crews/{crew_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a crew",
)
async def delete_crew(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Owner-only: delete the crew (memberships cascade)."""
    try:
        await crew_service.delete_crew(crew_id, caller_id=user.user_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can delete")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to delete crew", exc)


@router.get(
    "/crews/{crew_id}/runs",
    response_model=list[CrewRunItem],
    summary="크루 러닝 피드 (크루원, 최신 활동순)",
)
async def list_crew_runs(
    crew_id: str,
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[CrewRunItem]:
    """Current members' recent runs. Personal notes/feedback are never included;
    route_summary appears only for public courses."""
    try:
        return await crew_service.list_crew_runs(
            crew_id, caller_id=user.user_id, limit=limit, offset=offset
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.CrewAccessDenied:
        raise HTTPException(status_code=403, detail="Members only")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list crew runs", exc)


# --- Crew announcements + RSVP ------------------------------------------------


@router.post(
    "/crews/{crew_id}/announcements",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="크루 공지 작성 (크루장, 크루원 전체 알림)",
)
async def create_announcement(
    crew_id: str,
    req: AnnouncementCreate,
    user: CurrentUser = Depends(get_current_user),
) -> AnnouncementResponse:
    """Create an announcement (owner only). All members get one notification."""
    try:
        return await announcement_service.create_announcement(
            crew_id, caller_id=user.user_id, req=req
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can post announcements")
    except announcement_service.InvalidAnnouncement:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_announcement",
                    "message": "좌표는 쌍으로, 마감시각은 러닝 일시가 있을 때 그 이전으로 설정하세요."},
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to create announcement", exc)


@router.get(
    "/crews/{crew_id}/announcements",
    response_model=list[AnnouncementResponse],
    summary="크루 공지 목록 (크루원, 최신순)",
)
async def list_announcements(
    crew_id: str,
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[AnnouncementResponse]:
    """Announcements with RSVP tallies and my_rsvp, newest first."""
    try:
        return await announcement_service.list_announcements(
            crew_id, caller_id=user.user_id, limit=limit, offset=offset
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.CrewAccessDenied:
        raise HTTPException(status_code=403, detail="Members only")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list announcements", exc)


@router.get(
    "/crews/{crew_id}/announcements/{announcement_id}",
    response_model=AnnouncementDetailResponse,
    summary="크루 공지 상세 (집계 + 참석자 명단)",
)
async def get_announcement(
    crew_id: str,
    announcement_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> AnnouncementDetailResponse:
    """Announcement detail with the going-member roster."""
    try:
        return await announcement_service.get_announcement(
            crew_id, caller_id=user.user_id, announcement_id=announcement_id
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.CrewAccessDenied:
        raise HTTPException(status_code=403, detail="Members only")
    except announcement_service.AnnouncementNotFound:
        raise HTTPException(status_code=404, detail="Announcement not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch announcement", exc)


@router.patch(
    "/crews/{crew_id}/announcements/{announcement_id}",
    response_model=AnnouncementResponse,
    summary="크루 공지 수정 (크루장, 알림 없음)",
)
async def update_announcement(
    crew_id: str,
    announcement_id: str,
    req: AnnouncementUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> AnnouncementResponse:
    """Partial update (owner only). Edits do not re-notify members."""
    try:
        return await announcement_service.update_announcement(
            crew_id, caller_id=user.user_id, announcement_id=announcement_id, req=req
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can edit announcements")
    except announcement_service.AnnouncementNotFound:
        raise HTTPException(status_code=404, detail="Announcement not found")
    except announcement_service.InvalidAnnouncement:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_announcement",
                    "message": "좌표는 쌍으로, 마감시각은 러닝 일시가 있을 때 그 이전으로 설정하세요."},
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to update announcement", exc)


@router.delete(
    "/crews/{crew_id}/announcements/{announcement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="크루 공지 삭제 (크루장, 투표도 함께 삭제)",
)
async def delete_announcement(
    crew_id: str,
    announcement_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Delete an announcement (owner only); its RSVPs cascade."""
    try:
        await announcement_service.delete_announcement(
            crew_id, caller_id=user.user_id, announcement_id=announcement_id
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only the owner can delete announcements")
    except announcement_service.AnnouncementNotFound:
        raise HTTPException(status_code=404, detail="Announcement not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to delete announcement", exc)


@router.put(
    "/crews/{crew_id}/announcements/{announcement_id}/rsvp",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="참석 투표 (크루원, 재투표=덮어쓰기)",
)
async def rsvp_announcement(
    crew_id: str,
    announcement_id: str,
    req: RsvpRequest,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Cast or overwrite the caller's attendance vote (one per member)."""
    try:
        await announcement_service.rsvp(
            crew_id, caller_id=user.user_id,
            announcement_id=announcement_id, status=req.status,
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.CrewAccessDenied:
        raise HTTPException(status_code=403, detail="Members only")
    except announcement_service.AnnouncementNotFound:
        raise HTTPException(status_code=404, detail="Announcement not found")
    except announcement_service.RsvpNotAvailable:
        raise HTTPException(
            status_code=400,
            detail={"error": "rsvp_not_available",
                    "message": "러닝 일시가 없는 공지에는 투표할 수 없습니다."},
        )
    except announcement_service.RsvpClosed:
        raise HTTPException(
            status_code=409,
            detail={"error": "rsvp_closed", "message": "참석 투표가 마감되었습니다."},
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to submit RSVP", exc)


# --- Notifications -----------------------------------------------------------
# NOTE: fixed paths (unread-count, read-all) must come before /{id}/read


@router.get(
    "/notifications",
    response_model=list[NotificationResponse],
    summary="내 알림 목록 (최신순)",
)
async def list_notifications(
    limit: int = 20,
    user: CurrentUser = Depends(get_current_user),
) -> list[NotificationResponse]:
    """Return the caller's notifications, newest first."""
    try:
        return await notification_service.list_notifications(user.user_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch notifications", exc)


@router.get(
    "/notifications/unread-count",
    summary="안 읽은 알림 개수",
)
async def notifications_unread_count(
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return the number of unread notifications for the caller."""
    try:
        count = await notification_service.unread_count(user.user_id)
        return {"count": count}
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to count notifications", exc)


@router.patch(
    "/notifications/read-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="전체 읽음 처리",
)
async def mark_all_notifications_read(
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Mark all of the caller's notifications as read."""
    try:
        await notification_service.mark_all_read(user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to mark notifications read", exc)


@router.patch(
    "/notifications/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="개별 읽음 처리",
)
async def mark_notification_read(
    notification_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Mark one notification as read; 404 if not found or not owned."""
    try:
        found = await notification_service.mark_read(notification_id, user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to mark notification read", exc)
    if not found:
        raise HTTPException(status_code=404, detail="Notification not found")


@router.get(
    "/weather",
    response_model=WeatherResponse,
    summary="현재 날씨 + 미세먼지 + AI 러닝지수",
)
async def get_weather(
    lat: float,
    lng: float,
    user: CurrentUser = Depends(get_current_user),
) -> WeatherResponse:
    """Current weather, PM grades, and the rule-based running index.

    Cached ~10min per ~1.1km grid cell; the cache holds the shared raw data
    only. The comment is personalized per user (weather settings) outside the
    cache — score/label stay shared. Error messages are fixed strings so the
    OpenWeather key can never leak through exception text.
    """

    async def _weather_settings_or_none():
        # Best-effort: 설정 조회 실패가 날씨 응답을 막으면 안 됨.
        try:
            return (await profile_service.get_settings(user.user_id)).weather
        except Exception:  # noqa: BLE001
            logger.warning("weather 설정 조회 실패 — 개인화 없이 응답", exc_info=True)
            return None

    try:
        weather, weather_settings = await asyncio.gather(
            weather_service.get_weather(lat, lng),
            _weather_settings_or_none(),
        )
        if weather_settings is not None:
            weather = weather_service.personalize_index(weather, weather_settings)
        return weather
    except weather_service.WeatherNotConfigured:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "weather_not_configured",
                "message": "날씨 API 키가 설정되지 않았습니다 (OPENWEATHER_API_KEY).",
            },
        )
    except weather_service.WeatherKeyInactive:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "weather_key_inactive",
                "message": "OpenWeather 키가 아직 활성화되지 않았습니다. 발급 후 최대 몇 시간 걸릴 수 있어요.",
            },
        )
    except Exception:  # noqa: BLE001 — no exc text: never leak the key
        raise HTTPException(
            status_code=502,
            detail={
                "error": "weather_unavailable",
                "message": "날씨 서비스를 일시적으로 사용할 수 없습니다.",
            },
        )


@router.get("/places", response_model=list[Place], summary="Search nearby places")
async def search_places(
    keyword: str = Query(..., min_length=1, max_length=50),
    lat: float = Query(..., ge=33.0, le=39.0),
    lng: float = Query(..., ge=124.0, le=132.0),
    radius_m: int = Query(2000, ge=1, le=20000),
    limit: int = Query(5, ge=1, le=15),
    user: CurrentUser = Depends(get_current_user),
) -> list[Place]:
    """Search for pitstop candidates (e.g. '편의점') near a coordinate.

    인증 필수 (외부 지도 API 키 보호 — 익명 쿼터 남용 방지). 파라미터는
    한국 bbox·반경·개수 상한으로 클램프.
    """
    try:
        return await map_service.search_places(
            keyword=keyword,
            near=Coordinate(lat=lat, lng=lng),
            radius_m=radius_m,
            limit=limit,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception:  # noqa: BLE001 - 예외 텍스트에 요청 상세가 실리지 않도록 고정 문자열
        logger.warning("장소 검색 실패", exc_info=True)
        raise HTTPException(status_code=502, detail="장소 검색을 일시적으로 사용할 수 없습니다.")
