"""HTTP route handlers for the running route API."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from openai import InternalServerError as GeminiOverloaded
from openai import RateLimitError as GeminiRateLimited
from fastapi.responses import JSONResponse

from app.core.auth import get_current_user, require_admin
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
    RunCommentCreate,
    RunDetailResponse,
    RunCommentResponse,
    Coordinate,
    CrewCreate,
    CrewMemberResponse,
    CrewRankingEntry,
    ChatMessageCreate,
    ChatShareRunRequest,
    ChatMessageResponse,
    ChatMuteRequest,
    ChatReactRequest,
    ChatUnreadResponse,
    CrewPermissionsPatch,
    CrewPermissionsResponse,
    CrewRoleResponse,
    CrewRoleUpdate,
    CrewResponse,
    CrewRunItem,
    CrewUpdate,
    CurrentUser,
    FollowDecisionRequest,
    FeedbackRequest,
    FollowUserItem,
    IapVerifyRequest,
    IapVerifyResponse,
    CrewInviteRequest,
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
    PushTokenRequest,
    ReportCreate,
    ReportDecision,
    ReportItem,
    PublicProfileResponse,
    PublicRouteResponse,
    PublishRequest,
    QuotaResponse,
    RsvpRequest,
    RouteRequest,
    RouteResponse,
    RunPhotoUploadUrlRequest,
    RunPhotoUploadUrlResponse,
    RunRequest,
    RunUpdate,
    CourseRunShareResponse,
    RunResponse,
    RunTrackResponse,
    SettingsPatch,
    StatsResponse,
    StoredRoute,
    TransferRequest,
    SuggestedUserItem,
    UserSearchItem,
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
    push_service,
    chat_service,
    quota_service,
    report_service,
    route_service,
    run_service,
    stats_service,
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


def _parse_before_cursor(before: str | None) -> str | None:
    """ISO 8601+tz 커서 검증 (단일 소스 — /runs·/chat 공용).

    감사 M-A: '+'를 URL 인코딩 안 한 흔한 실수는 공백으로 도착 → tz 오프셋
    위치의 공백만 '+'로 복원. tz 없으면 422 (naive는 UTC 오해석 방지).
    """
    if before is None:
        return None
    before = re.sub(r" (\d{2}:?\d{2})$", r"+\1", before)
    try:
        parsed = datetime.fromisoformat(before)
    except ValueError:
        raise HTTPException(status_code=422, detail="before must be ISO 8601")
    if parsed.tzinfo is None:
        raise HTTPException(
            status_code=422,
            detail="before must include a timezone offset (e.g. +09:00 or Z)",
        )
    return before


@router.get("/me", response_model=CurrentUser, summary="Who am I (auth check)")
async def me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Return the currently authenticated user. Requires a valid Bearer token."""
    return user


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="회원 탈퇴 (계정·전체 데이터 삭제)",
)
async def delete_my_account(
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """계정과 모든 데이터를 즉시 삭제 (docs/ACCOUNT_DELETION_DESIGN.md).

    다른 멤버가 있는 크루를 소유 중이면 409 crew_owner — 프론트는 위임/삭제
    화면으로 유도. 본인뿐인 소유 크루는 함께 삭제된다.
    """
    try:
        await profile_service.delete_account(user.user_id, email=user.email)
    except profile_service.DemoAccountError:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "demo_account",
                "message": "데모 계정은 탈퇴할 수 없어요.",
            },
        )
    except profile_service.CrewOwnerError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "crew_owner",
                "crew_ids": exc.crew_ids,
                "message": "운영 중인 크루를 위임하거나 삭제한 후 탈퇴할 수 있어요.",
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to delete account", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    except profile_service.NicknameRequired:
        raise HTTPException(status_code=422, detail="nickname is required to create a profile")
    except profile_service.NicknameTaken:
        raise HTTPException(status_code=409, detail="Nickname already taken")
    except profile_service.ProfileNotFound:  # M-12: 갱신 중 행 소멸(탈퇴 레이스)
        raise HTTPException(status_code=404, detail="Profile not found")
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
    "/users/search",
    response_model=list[UserSearchItem],
    summary="유저 검색 (닉네임 부분 일치 — 통합 검색 화면)",
)
async def search_users(
    q: str = Query(..., min_length=2, max_length=20,
                   description="닉네임 부분 일치(대소문자 무관). 최소 2자(전 유저 열거 방지)."),
    limit: int = Query(20, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
) -> list[UserSearchItem]:
    """닉네임 contains 검색. 차단 상대 제외·본인 제외·잠금 계정은 bio null로 포함.
    q<2자는 422. 프론트: 잠금 계정도 결과에 뜨고 프로필 진입 시 🔒."""
    try:
        rows = await profile_service.search_users(user.user_id, q, limit=limit)
        return [UserSearchItem(**r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("User search failed", exc)


@router.get(
    "/users/suggested",
    response_model=list[SuggestedUserItem],
    summary="추천 러너 (팔로우 추천 카드, v1)",
)
async def suggested_users(
    limit: int = Query(20, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
) -> list[SuggestedUserItem]:
    """팔로우할 만한 러너 — 본인·이미 팔로우 중·차단(양방향) 제외, 잠금 계정은
    bio null로 포함(유저 검색 계약 상속). 랭킹 v1: public run 수 → 최근 가입순
    (응답 형태 안정이 목적 — 랭킹은 추후 변경 전제)."""
    try:
        rows = await profile_service.suggested_users(user.user_id, limit=limit)
        return [SuggestedUserItem(**r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Suggested users failed", exc)


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
    summary="팔로우 (승인제면 202 요청)",
)
async def follow_user(
    user_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Follow a user. 즉시 팔로우/멱등이면 **204**, 승인제 계정이면 **202**
    (pending 요청 생성 — `GET /users/{id}/profile`의 follow 관계로 상태 판단).
    이미 pending인 재요청은 409(멱등이나 명시)."""
    try:
        result = await follow_service.follow_user(user_id, follower_id=user.user_id)
    except follow_service.SelfFollowNotAllowed:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")
    except follow_service.UserNotFound:
        raise HTTPException(status_code=404, detail="User not found")
    except follow_service.FollowRequestPending:
        raise HTTPException(status_code=409, detail={
            "error": "follow_request_pending", "message": "이미 팔로우를 요청했어요."})
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to follow", exc)
    code = status.HTTP_202_ACCEPTED if result == "requested" else status.HTTP_204_NO_CONTENT
    return Response(status_code=code)


@router.get(
    "/me/follow-requests",
    response_model=list[FollowUserItem],
    summary="내게 온 팔로우 요청 목록 (승인제, 최신순)",
)
async def list_my_follow_requests(
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[FollowUserItem]:
    try:
        return await follow_service.list_follow_requests(user.user_id, limit=limit, offset=offset)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list follow requests", exc)


@router.patch(
    "/me/follow-requests/{requester_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="팔로우 요청 승인/거절 (본인)",
)
async def decide_follow_request(
    requester_id: str,
    req: FollowDecisionRequest,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """승인 시 follows 생성 + 알림, 거절은 무알림. 없거나 이미 처리됨 404."""
    try:
        await follow_service.decide_follow_request(
            user.user_id, requester_id, approve=req.approve
        )
    except follow_service.FollowRequestNotFound:
        raise HTTPException(status_code=404, detail="Follow request not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to decide follow request", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/users/{user_id}/follow-request",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="내 팔로우 요청 취소 (멱등)",
)
async def cancel_follow_request(
    user_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """target에게 보낸 내 pending 요청 취소 — 없으면 no-op."""
    try:
        await follow_service.cancel_follow_request(user_id, requester_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to cancel follow request", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/users/{user_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="사용자 차단 (멱등, 양방향 팔로우 해제)",
)
async def block_user(
    user_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """차단 시 상호 노출 차단(프로필·러닝 404 은닉) + 양방향 팔로우·요청 해제.
    재팔로우는 차단 해제 후에만."""
    try:
        await follow_service.block_user(user_id, blocker_id=user.user_id)
    except follow_service.SelfBlockNotAllowed:
        raise HTTPException(status_code=400, detail="Cannot block yourself")
    except follow_service.UserNotFound:
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to block user", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/users/{user_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="차단 해제 (멱등 — 팔로우는 복구 안 됨)",
)
async def unblock_user(
    user_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    try:
        await follow_service.unblock_user(user_id, blocker_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to unblock user", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me/blocks",
    response_model=list[FollowUserItem],
    summary="내가 차단한 사용자 목록 (프로필 설정용)",
)
async def list_my_blocks(
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[FollowUserItem]:
    try:
        return await follow_service.list_blocks(user.user_id, limit=limit, offset=offset)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list blocks", exc)


@router.post(
    "/reports",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="신고 (user·run)",
)
async def create_report(
    req: ReportCreate,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """유저/run 신고 접수 — 성공/중복 pending(멱등) 모두 **204**(block·follow 관성).
    self(자기 자신·자기 run) 400. 없는 대상·차단 관계·**비가시 run**(내게 안 보이는
    visibility) 404 은닉. target_type은 'user'·'run'(댓글·코스 등은 422).
    차단과 독립(신고가 차단을 유발하지 않음 — 프론트는 별도 2호출). 무알림."""
    try:
        await report_service.create_report(user.user_id, req)
    except report_service.SelfReportNotAllowed:
        raise HTTPException(status_code=400, detail="Cannot report yourself")
    except report_service.ReportTargetNotFound:
        raise HTTPException(
            status_code=404,
            detail="Run not found" if req.target_type == "run" else "User not found",
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to create report", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/admin/reports",
    response_model=list[ReportItem],
    summary="신고 목록 (운영 전용 — 비운영진 404)",
)
async def list_reports(
    report_status: str = Query("pending", alias="status",
                               pattern="^(pending|reviewed|dismissed)$"),
    limit: int = 20,
    offset: int = 0,
    admin: CurrentUser = Depends(require_admin),
) -> list[ReportItem]:
    """운영진 신고 목록(최신순) — reporter/target(user형) 프로필 brief +
    run형은 target_run(제목·소유자 brief, 삭제된 run은 null) 포함.
    게이트는 require_admin — 비운영진·ADMIN_USER_IDS 미설정 시 404(존재 은닉)."""
    try:
        return await report_service.list_reports(report_status, limit=limit, offset=offset)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list reports", exc)


@router.patch(
    "/admin/reports/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="신고 처리 (운영 전용 — reviewed/dismissed 단방향)",
)
async def decide_report(
    report_id: str,
    req: ReportDecision,
    admin: CurrentUser = Depends(require_admin),
) -> Response:
    """pending → reviewed/dismissed(단방향 — pending 되돌리기는 스키마 422).
    reviewed_at 기록. 없는 id·이미 처리된 신고 404."""
    try:
        await report_service.decide_report(report_id, status=req.status)
    except report_service.ReportNotFound:
        raise HTTPException(status_code=404, detail="Report not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to decide report", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# TEMP — 에어코리아 서빙 프로세스 400 미스터리 진단 프로브 (2026-08-04).
# 제거 트리거: 미스터리 해소 시 이 엔드포인트 + weather_service 프로브 블록 +
# scripts/diag_airkorea_shell.py + tests/test_airkorea_probe_integration.py 삭제.
# API_GUIDE 비등재(임시 admin 진단 — 유저 표면 노출 0).
@router.get(
    "/admin/diag/airkorea-probe",
    summary="에어코리아 전송 관측 프로브 (TEMP·운영 전용 — 비운영진 404)",
)
async def airkorea_probe_diag(
    admin: CurrentUser = Depends(require_admin),
) -> dict:
    """실기능 동일 경로(동기 클라이언트+to_thread)로 에어코리아 1회 요청,
    TLS·소켓·헤더 관측 반환. DB 쓰기 0·부수효과 0·serviceKey 마스킹(뒤 4자만)."""
    return await weather_service.airkorea_probe()


@router.delete(
    "/me/followers/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="팔로워 제거 (내 팔로워 목록에서 상대 떼기, 멱등)",
)
async def remove_follower(
    user_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """내 팔로워 목록에서 `user_id`를 제거 — 상대가 나를 팔로우하던 관계를 끊는다.
    언팔로우(내가 남 팔로우 취소)와 **정반대 방향**. 무알림. 재팔로우 허용(차단과
    구분). 이미 내 팔로워가 아니면 멱등 204, self 400, 없는 유저·차단 관계 404."""
    try:
        await follow_service.remove_follower(user_id, remover_id=user.user_id)
    except follow_service.SelfFollowNotAllowed:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")
    except follow_service.UserNotFound:
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to remove follower", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    # 쿼터 슬롯을 Gemini 전에 원자 예약 (M3): 동시 N건 중 한도 내만 통과.
    # tier→limit 해석은 Python(lazy IAP 강등 포함).
    try:
        tier = await quota_service.get_tier(user.user_id)
        limit = None if tier == "premium" else quota_service.AI_WEEKLY_LIMIT
        reservation_id = await quota_service.reserve_ai_generation(user.user_id, limit)
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
        raise _bad_gateway("Failed to reserve quota", exc)

    try:
        route = await route_service.create_running_route(req, user_id=user.user_id)
    except route_service.OneWayEndTooFar as exc:
        # 일방 실행가능성 게이트(v2.3) — 유저 입력 문제라 422(쿼터 미소모)
        await quota_service.release_ai_generation(reservation_id)
        raise HTTPException(
            status_code=422,
            detail={
                "error": "one_way_end_too_far",
                "message": (
                    f"도착지가 목표 거리에 비해 너무 멀어요 — 직선거리 "
                    f"{exc.distance_km}km인 이 도착지까지는 목표를 "
                    f"{exc.min_target_km}km 이상으로 설정해 주세요."
                ),
                "min_target_km": exc.min_target_km,
            },
        )
    except route_service.LoopTargetTooShort as exc:
        # 순환 최소거리 게이트(small-ask 2026-07-22) — 물리적으로 불가한 단거리 루프,
        # 유저 입력 문제라 422(쿼터 미소모·Gemini 0콜). one-way 게이트와 동형 계약.
        await quota_service.release_ai_generation(reservation_id)
        raise HTTPException(
            status_code=422,
            detail={
                "error": "loop_target_too_short",
                "message": (
                    f"순환 코스는 최소 {exc.min_target_km}km부터 만들 수 있어요 — "
                    f"목표를 {exc.min_target_km}km 이상으로 설정해 주세요."
                ),
                "min_target_km": exc.min_target_km,
            },
        )
    except route_service.RouteGenerationUnavailable:
        # T-map 쿼터 소진(429 지배) — 산포 전패(502)와 구분한 정직한 일시 실패.
        # nopath 폴백(폴리라인 없는 가짜 코스 200)을 대체(2026-07-21 오너 승격).
        # 생성 실패 = 무료: 예약 해제(쿼터 미소모 시맨틱 보존).
        await quota_service.release_ai_generation(reservation_id)
        logger.warning("코스 생성 불가 — T-map 쿼터 소진(503)")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "route_generation_unavailable",
                "message": "일시적인 문제로 코스를 만들 수 없어요. 잠시 후 다시 시도해주세요.",
            },
        )
    except (GeminiRateLimited, GeminiOverloaded):
        # Gemini 업스트림 한계(전 롤 429/오버로드 — 서비스 판별 후 재raise분)를
        # 503으로 정직화(2026-07-30) — "조건 바꿔 재시도"(502)가 아니라 "잠시 후
        # 재시도"가 맞는 상황. T-map 쿼터 정직화와 시맨틱 통일. 쿼터 환급 동일 보장.
        await quota_service.release_ai_generation(reservation_id)
        logger.warning("Gemini 업스트림 한계(429/오버로드) — 503 정직화", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "route_generation_unavailable",
                "message": "코스 생성이 잠시 혼잡해요. 잠시 후 다시 시도해 주세요.",
            },
        )
    except Exception:  # noqa: BLE001
        # 생성 실패 = 무료: 예약 해제 (기존 "실패는 쿼터 미소모" 시맨틱 보존)
        await quota_service.release_ai_generation(reservation_id)
        logger.warning("코스 생성 실패", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "route_generation_failed",
                "message": "코스 생성에 실패했어요. 잠시 후 다시 시도해 주세요.",
            },
        )

    # 성공: 예약이 곧 소모 기록 — 별도 record 없음.
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


@router.get(
    "/feed/nearby",
    response_model=list[ActivityFeedItem],
    summary="위치 기반 public run 탐색 피드 (홈 '전체' 탭, 반경 N km)",
)
async def nearby_feed(
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float = 10.0,
    limit: int = 20,
    offset: int = 0,
    scope: Literal["nearby", "all"] = "nearby",
    user: CurrentUser = Depends(get_current_user),
) -> list[ActivityFeedItem]:
    """내 위치 반경 내 public run(본인·팔로우·비공개 계정 제외), 최신순.

    홈 "전체" 탭 데이터소스(NEARBY_FEED_DESIGN). scope(2026-08-01 additive,
    Ivan 계약): "nearby"(기본)=현행 그대로 — lat/lng 필수(누락 400)·한국 bbox
    밖 400·radius_km 기본 10·상한 20(서비스 clamp). "all"=전국(전 세계) 모드 —
    반경·좌표 무시(전송돼도 무시·bbox 게이트 스킵: 국가 필터 없음이 오너
    결정이라 해외 좌표 400이면 모순). 허용 외 값은 422(validation_error).
    가시성·정렬·페이지네이션 규칙은 두 모드 동일.
    """
    if scope == "nearby":
        if lat is None or lng is None:
            raise HTTPException(status_code=400, detail="lat, lng are required")
        # 한국 bbox 검증 (Coordinate 모델과 동일 범위) — 극점 좌표 차단
        if not (33.0 <= lat <= 39.0 and 124.0 <= lng <= 132.0):
            raise HTTPException(status_code=400, detail="lat/lng out of Korea bounds")
    try:
        return await run_service.list_nearby_feed(
            user.user_id, lat=lat, lng=lng,
            radius_km=radius_km, limit=limit, offset=offset, scope=scope,
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Nearby feed failed", exc)


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


@router.delete(
    "/routes/{route_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="코스 삭제 (소유자 · 하드 삭제 · 복구 없음)",
)
async def delete_route(
    route_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """본인 코스 하드 삭제 — 성공 **204**. 타인·없음·재삭제 전부 **404 은닉**.
    북마크·좋아요·댓글·오디오코치 캐시는 FK cascade 소멸, 연결된 러닝 기록과
    복사본 코스는 잔존(연결만 끊김). run-delete 계약 관성(재삭제 404)."""
    try:
        await route_service.delete_route(route_id, user_id=user.user_id)
    except route_service.RouteNotFound:
        raise HTTPException(status_code=404, detail="Route not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to delete route", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    except profile_service.FeedActionDisabled:
        raise HTTPException(status_code=403, detail={
            "error": "likes_disabled",
            "message": "이 사용자는 좋아요를 받지 않아요."})
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
    except profile_service.FeedActionDisabled:
        raise HTTPException(status_code=403, detail={
            "error": "comments_disabled",
            "message": "이 사용자는 댓글을 받지 않아요."})
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
    """Return comments for a public route, oldest first (차단 발신자 제외)."""
    try:
        return await route_service.list_comments(route_id, viewer_id=user.user_id, limit=limit)
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
    except run_service.CrewTagNotAllowed:
        raise HTTPException(status_code=400, detail="Cannot tag a crew you are not a member of")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to save run", exc)


@router.patch(
    "/runs/{run_id}",
    response_model=RunResponse,
    summary="러닝 기록 편집 (제목·공개 범위·메모)",
)
async def update_run(
    run_id: str,
    req: RunUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> RunResponse:
    """본인 run의 title/visibility/notes/photos 수정 (보낸 필드만). 404 if 없음/남의 것.

    photos는 업로드 3-step의 path 배열(≤3) — 빠진 기존 경로는 Storage에서
    삭제됨. 이 run의 prefix 밖 경로는 422.
    """
    fields = req.model_dump(exclude_none=True)
    try:
        run = await run_service.update_run(run_id, user_id=user.user_id, fields=fields)
    except run_service.PhotoPathInvalid:
        raise HTTPException(
            status_code=422,
            detail="photos paths must belong to this run ({run_id}/... only)",
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to update run", exc)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.delete(
    "/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="러닝 기록 삭제 (본인만 — 복구 없음)",
)
async def delete_run(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """하드 삭제 — kudos·댓글·GPS트랙(cascade)·사진(Storage)·run 대상 알림이
    함께 소멸. 타인/없음/**재삭제 모두 404 은닉**(프론트는 404를 '이미 삭제됨'
    처리 — 연타 안전). 크루 채팅에 공유된 카드는 스냅샷이라 잔존, 탭 시 404
    (기존 계약). PB·통계·세션 카운트는 라이브 계산이라 자동 반영."""
    try:
        await run_service.delete_run(run_id, user.user_id)
    except run_service.RunNotFound:
        raise HTTPException(status_code=404, detail="Run not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to delete run", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/runs/{run_id}/photos/upload-url",
    response_model=RunPhotoUploadUrlResponse,
    summary="러닝 사진 업로드 URL 발급 (소유자, 슬롯 1~3)",
)
async def create_run_photo_upload_url(
    run_id: str,
    req: RunPhotoUploadUrlRequest,
    user: CurrentUser = Depends(get_current_user),
) -> RunPhotoUploadUrlResponse:
    """3-step 흐름의 1단계 (avatar와 동형) — ① 발급 ② 이미지 PUT(5MB·타입은
    Storage가 강제) ③ PATCH /runs/{id}의 photos에 응답의 path 추가.

    ⚠️ 업로드 전 클라이언트에서 재인코딩으로 EXIF(GPS 좌표) 제거 필수 — 계약.
    """
    try:
        res = await run_service.create_run_photo_upload_url(
            run_id, user_id=user.user_id, slot=req.slot, content_type=req.content_type
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to create photo upload url", exc)
    if res is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return res


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
    "/stats/course-run-share",
    response_model=CourseRunShareResponse,
    summary="코스-런 비율 (소셜프루프 — global/me)",
)
async def course_run_share(
    window_days: int = Query(30, ge=1, le=90),
    scope: str = Query("global", pattern="^(global|me)$"),
    user: CurrentUser = Depends(get_current_user),
) -> CourseRunShareResponse:
    """최근 window 내 코스 연결 run 비율. global은 비실사용 계정(시드/데모/QA/운영진)
    제외 전체, me는 본인. total<20이면 share=null. 집계는 카운트만(개별 노출 없음)."""
    try:
        return await stats_service.course_run_share(scope, window_days, user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to compute course-run share", exc)


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
    before: str | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[RunResponse]:
    """Return the caller's logged runs, newest first; optionally filter by route_id.

    before: 커서 페이지네이션 — 직전 페이지 마지막 run의 ran_at(ISO 8601 +
    타임존)을 그대로 보내면 그 이전 run들이 온다. 응답이 limit보다 짧으면 끝.
    """
    before = _parse_before_cursor(before)
    try:
        return await run_service.list_runs(
            user_id=user.user_id, limit=limit, route_id=route_id, before=before
        )
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list runs", exc)


@router.get(
    "/runs/{run_id}",
    response_model=RunDetailResponse,
    summary="러닝 기록 단건 조회 (본인 전체 / 타인은 공개범위 내 정제 필드)",
)
async def get_run(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """본인은 전체 필드, 타인은 run 공개범위 게이트(track·kudos와 동일) 통과 시
    정제된 필드만(notes·feedback·verification 등 미노출 — API_GUIDE 참조).
    404 if 없음/범위 밖 (존재 은닉)."""
    try:
        run = await run_service.get_run(run_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch run", exc)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    # photo_paths는 본인 상세에서만 존재 — 타인/None이면 키 자체 제거(경로 미노출).
    # JSONResponse로 직렬화(RunResponse는 alias 없어 model_dump(json)이 동일 출력).
    payload = run.model_dump(mode="json")
    if payload.get("photo_paths") is None:
        payload.pop("photo_paths", None)
    return JSONResponse(payload)


@router.get(
    "/runs/{run_id}/track",
    response_model=RunTrackResponse,
    summary="러닝 경로 (GPS 폴리라인, 상세 화면 전용)",
)
async def get_run_track(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> RunTrackResponse:
    """The run's simplified GPS polyline.

    본인 + 공개범위 내 타인(run visibility 게이트 — kudos·댓글과 동일).
    404 if not visible or no track (존재 은닉).
    """
    try:
        track = await run_service.get_run_track(run_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to fetch track", exc)
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")
    return track


@router.post(
    "/runs/{run_id}/copy-as-route",
    response_model=StoredRoute,
    summary="러닝을 코스로 저장 ('이 경로 달리기')",
)
async def copy_run_as_route(
    run_id: str,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
) -> StoredRoute:
    """볼 수 있는 러닝의 GPS 트랙을 내 private 코스로 저장. 신규 **201**, 멱등
    재저장 **200**(같은 run은 1개만). 비가시·차단 **404**, 트랙 없는 수동 기록
    **400**. run 주인에게 route_saved 알림(자기 run이면 self 스킵)."""
    try:
        route, created = await run_service.copy_run_as_route(run_id, viewer_id=user.user_id)
    except run_service.RunNotFound:
        raise HTTPException(status_code=404, detail="Run not found")
    except run_service.RunTrackMissing:
        raise HTTPException(status_code=400, detail="Run has no GPS track to save as a course")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to save run as route", exc)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return route


@router.post(
    "/runs/{run_id}/kudos",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="run에 kudos (멱등 — 본인 run 허용, 2026-07-30)",
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
    except profile_service.FeedActionDisabled as exc:
        raise HTTPException(status_code=403, detail={
            "error": "likes_disabled",
            "message": "이 사용자는 좋아요를 받지 않아요."})
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


@router.get(
    "/runs/{run_id}/comments",
    response_model=list[RunCommentResponse],
    summary="run 댓글 목록 (최신순)",
)
async def list_run_comments(
    run_id: str,
    limit: int = 20,
    offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
) -> list[RunCommentResponse]:
    """run 댓글 최신순. 보이는 run만(본인·public·팔로우/크루의 followers) — 아니면 404."""
    try:
        return await run_service.list_run_comments(
            run_id, caller_id=user.user_id, limit=limit, offset=offset
        )
    except (run_service.RunNotFound, run_service.RunNotVisible):
        raise HTTPException(status_code=404, detail="Run not found")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to list comments", exc)


@router.post(
    "/runs/{run_id}/comments",
    response_model=RunCommentResponse,
    summary="run 댓글 작성",
)
async def create_run_comment(
    run_id: str,
    req: RunCommentCreate,
    user: CurrentUser = Depends(get_current_user),
) -> RunCommentResponse:
    """보이는 run에 댓글 작성. run 주인에게 알림(본인 댓글 제외). 안 보이면 404.
    1-레벨 답글: parent_comment_id 동봉(부모 무효 422·깊이 초과 422)."""
    try:
        return await run_service.create_run_comment(
            run_id, caller_id=user.user_id, content=req.content,
            parent_comment_id=req.parent_comment_id,
        )
    except run_service.CommentParentInvalid:
        raise HTTPException(status_code=422, detail={
            "error": "comment_parent_invalid",
            "message": "답글 대상 댓글을 찾을 수 없어요."})
    except run_service.ReplyDepthExceeded:
        raise HTTPException(status_code=422, detail={
            "error": "reply_depth_exceeded",
            "message": "답글에는 답글을 달 수 없어요."})
    except (run_service.RunNotFound, run_service.RunNotVisible):
        raise HTTPException(status_code=404, detail="Run not found")
    except profile_service.FeedActionDisabled:
        raise HTTPException(status_code=403, detail={
            "error": "comments_disabled",
            "message": "이 사용자는 댓글을 받지 않아요."})
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to create comment", exc)


@router.delete(
    "/runs/{run_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="run 댓글 삭제 (작성자 또는 run 주인)",
)
async def delete_run_comment(
    run_id: str,
    comment_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """댓글 삭제 — 작성자 또는 run 주인만. 없으면 404, 권한 없으면 403."""
    try:
        await run_service.delete_run_comment(run_id, comment_id, caller_id=user.user_id)
    except run_service.RunCommentNotFound:
        raise HTTPException(status_code=404, detail="Comment not found")
    except run_service.RunCommentAccessDenied:
        raise HTTPException(status_code=403, detail="Not allowed")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to delete comment", exc)


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
    # tier→limit 해석은 Python(lazy IAP 강등 포함), 한도 검사+생성은 원자 RPC(M8).
    try:
        tier = await quota_service.get_tier(user.user_id)
        limit = None if tier == "premium" else quota_service.FREE_CREW_LIMIT
        return await crew_service.create_crew(req, owner_id=user.user_id, limit=limit)
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


@router.post(
    "/crews/preview-by-code",
    response_model=CrewResponse,
    summary="초대 코드로 크루 미리보기 (권장 — 코드가 URL/로그에 안 남음)",
)
async def preview_crew_by_code_post(
    req: JoinByCodeRequest,
    user: CurrentUser = Depends(get_current_user),
) -> CrewResponse:
    """미리보기 (권장 경로): 초대 코드를 body로 받아 access log 노출을 막는다.
    GET 버전과 동작 동일 — 프론트는 이 POST로 붙일 것을 권장."""
    try:
        return await crew_service.preview_by_code(req.code)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    except Exception:  # noqa: BLE001 — 코드 값이 에러에 실리지 않게 고정 메시지
        raise HTTPException(status_code=502, detail="Failed to preview invite code")


@router.get(
    "/crews/preview-by-code",
    response_model=CrewResponse,
    summary="초대 코드로 크루 미리보기 (레거시 — 코드가 쿼리스트링에 노출, POST 권장)",
)
async def preview_crew_by_code(
    code: str,
    user: CurrentUser = Depends(get_current_user),
) -> CrewResponse:
    """Which crew does this code open? Works for private crews too.

    ⚠️ 코드가 쿼리스트링 → access log에 평문으로 남음. 하위 호환 위해 유지하되
    신규/변경은 POST /crews/preview-by-code(body) 사용 권장.
    """
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


@router.post(
    "/crews/{crew_id}/invitations",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="인앱 개인 초대 (크루원 발송 — crew_invited 알림)",
)
async def invite_to_crew(
    crew_id: str,
    req: CrewInviteRequest,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """크루원이 비크루원을 초대 → 대상에게 crew_invited 알림(payload에 초대코드).
    비크루원 발송자·차단 관계·없는 유저 404(은닉), 이미 크루원 409. 수신자는
    payload.invite_code로 preview→join 흐름 재사용."""
    try:
        await crew_service.invite_member(crew_id, user.user_id, req.user_id)
    except (crew_service.CrewNotFound, crew_service.CrewAccessDenied,
            crew_service.InviteTargetNotFound):
        raise HTTPException(status_code=404, detail="Not found")
    except crew_service.AlreadyMember:
        raise HTTPException(status_code=409, detail="Already a member")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to invite", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/crews/{crew_id}/cover/upload-url",
    response_model=AvatarUploadUrlResponse,
    summary="크루 커버 업로드 URL 발급 (운영진; Storage 직접 업로드용)",
)
async def create_crew_cover_upload_url(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> AvatarUploadUrlResponse:
    """3-step: ① 이 URL 발급 ② 앱이 이미지 PUT ③ PATCH /crews/{id} cover_url에 public_url 저장."""
    return await _crew_image_upload_url(crew_id, user.user_id, "cover")


@router.post(
    "/crews/{crew_id}/icon/upload-url",
    response_model=AvatarUploadUrlResponse,
    summary="크루 아이콘 업로드 URL 발급 (운영진; Storage 직접 업로드용)",
)
async def create_crew_icon_upload_url(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> AvatarUploadUrlResponse:
    """3-step: ① 이 URL 발급 ② 앱이 이미지 PUT ③ PATCH /crews/{id} icon_url에 public_url 저장."""
    return await _crew_image_upload_url(crew_id, user.user_id, "icon")


async def _crew_image_upload_url(
    crew_id: str, caller_id: str, kind: str
) -> AvatarUploadUrlResponse:
    """크루 커버/아이콘 업로드 URL 발급 공통 — 권한(운영진) 404/403 매핑."""
    try:
        return await crew_service.create_crew_image_upload_url(crew_id, caller_id, kind)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Only managers can change crew images")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to create crew image upload url", exc)


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
    summary="Kick a member (owner·admin — admin은 member만)",
)
async def kick_member(
    crew_id: str,
    target_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """owner·admin: remove a member. admin은 member만 강퇴 가능(admin·owner
    대상은 403). Owner cannot kick themselves (400)."""
    try:
        await crew_service.kick_member(crew_id, caller_id=user.user_id, target_id=target_id)
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(
            status_code=403, detail="Only the owner or an admin can kick members"
        )
    except crew_service.OwnerCannotKickSelf:
        raise HTTPException(
            status_code=400,
            detail="Cannot kick yourself — use leave (owner: transfer or delete) instead.",
        )
    except crew_service.NotAMember:
        raise HTTPException(status_code=404, detail="User is not a member of this crew")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to kick member", exc)


@router.patch(
    "/crews/{crew_id}/members/{target_id}/role",
    response_model=CrewRoleResponse,
    summary="멤버 role 전환 (owner 또는 manage_admins admin, admin↔member)",
)
async def set_member_role(
    crew_id: str,
    target_id: str,
    req: CrewRoleUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> CrewRoleResponse:
    """owner 또는 manage_admins admin·멱등. 승격 시 시안 기본 permissions 자동 부여,
    강등 시 permissions null. owner의 role은 불변(422) — 위임은 transfer."""
    try:
        res = await crew_service.set_member_role(
            crew_id, caller_id=user.user_id, target_id=target_id, role=req.role
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Missing manage_admins permission")
    except crew_service.RoleTargetIsOwner:
        raise HTTPException(
            status_code=422,
            detail="Owner role cannot be changed here; use PATCH /crews/{id}/transfer",
        )
    except crew_service.NotAMember:
        raise HTTPException(status_code=404, detail="User is not a member of this crew")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to change member role", exc)
    return CrewRoleResponse(**res)


@router.patch(
    "/crews/{crew_id}/members/{target_id}/permissions",
    response_model=CrewPermissionsResponse,
    summary="운영진 세부 권한 조정 (owner 또는 manage_admins admin — v2)",
)
async def set_member_permissions(
    crew_id: str,
    target_id: str,
    req: CrewPermissionsPatch,
    user: CurrentUser = Depends(get_current_user),
) -> CrewPermissionsResponse:
    """보낸 키만 갱신. 대상은 admin이어야(422). §3: 비owner는 주의 2키
    (kick_members·manage_admins) 부여 불가·자기 미보유 키 부여 불가(403)."""
    try:
        res = await crew_service.set_member_permissions(
            crew_id, caller_id=user.user_id, target_id=target_id,
            patch=req.model_dump(exclude_none=True),
        )
    except crew_service.CrewNotFound:
        raise HTTPException(status_code=404, detail="Crew not found")
    except crew_service.NotOwner:
        raise HTTPException(status_code=403, detail="Missing manage_admins permission")
    except crew_service.PermissionGrantDenied:
        raise HTTPException(status_code=403, detail="Cannot grant this permission (owner-only or not held)")
    except crew_service.RoleTargetIsOwner:
        raise HTTPException(status_code=422, detail="Owner permissions are implicit and immutable")
    except crew_service.TargetNotAdmin:
        raise HTTPException(status_code=422, detail="Target must be an admin")
    except crew_service.NotAMember:
        raise HTTPException(status_code=404, detail="User is not a member of this crew")
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to set permissions", exc)
    return CrewPermissionsResponse(**res)


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
    "/me/push-token",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Expo 푸시 토큰 등록/갱신 (멱등)",
)
async def register_push_token(
    req: PushTokenRequest,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """로그인 후·토큰 갱신 시 호출 — upsert 멱등. 같은 기기에 다른 계정이
    로그인하면 소유가 자동 이전된다(전 주인 오발송 차단)."""
    try:
        await push_service.register_token(user.user_id, req.token, req.platform)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to register push token", exc)


@router.delete(
    "/me/push-token",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Expo 푸시 토큰 해제 (로그아웃 시, 멱등)",
)
async def delete_push_token(
    req: PushTokenRequest,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """본인 소유 행만 삭제 (남의 토큰 해제 불가). body로 받는 이유: 토큰이
    쿼리스트링에 실리면 access log에 남는다."""
    try:
        await push_service.delete_token(user.user_id, req.token)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to delete push token", exc)


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
    except crew_service.InvalidCrewImageUrl:
        raise HTTPException(status_code=422, detail="cover_url/icon_url must point to this crew's crew-images path")
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
    session_only: bool = False,
    user: CurrentUser = Depends(get_current_user),
) -> list[CrewRunItem]:
    """Current members' recent runs. Personal notes/feedback are never included;
    route_summary appears only for public courses.

    session_only=true면 이 크루의 정기런(태그런)만 반환(additive — 기본 false는
    현행 파이어호스). 태그런 뷰라 is_crew_session이 전부 true, 태그런 없으면 빈 배열."""
    try:
        return await crew_service.list_crew_runs(
            crew_id, caller_id=user.user_id, limit=limit, offset=offset,
            session_only=session_only,
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


# --- Crew chat (docs/CREW_CHAT_DESIGN.md v1) ---------------------------------
# 크루원만(비크루원·미존재 모두 404 은닉). 고정 경로(unread/read/mute)는
# /{message_id} 패턴보다 위 — 여기선 세그먼트가 겹치지 않아 순서 무관.


def _chat_404_403(exc: Exception) -> HTTPException:
    """채팅 공용 에러 매핑 — 크루 없음·비크루원·메시지 없음은 전부 404 은닉."""
    if isinstance(exc, (crew_service.CrewNotFound, crew_service.CrewAccessDenied,
                        chat_service.MessageNotFound)):
        return HTTPException(status_code=404, detail="Not found")
    if isinstance(exc, chat_service.NotDeletable):
        return HTTPException(status_code=403, detail="Cannot delete this message")
    if isinstance(exc, chat_service.RunNotShareable):  # 없음/타인 run → 은닉
        return HTTPException(status_code=404, detail="Not found")
    if isinstance(exc, chat_service.PrivateRunNotShareable):
        return HTTPException(status_code=422, detail="Private runs cannot be shared")
    return _bad_gateway("Chat operation failed", exc)


@router.get(
    "/crews/{crew_id}/chat/messages",
    response_model=list[ChatMessageResponse],
    summary="채팅 메시지 목록 (역순 커서, 크루원)",
)
async def list_chat_messages(
    crew_id: str,
    limit: int = 30,
    before: str | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[ChatMessageResponse]:
    """최신→과거 역순. 다음 페이지는 `before=<마지막(가장 오래된) created_at>`."""
    before = _parse_before_cursor(before)
    try:
        return await chat_service.list_messages(
            crew_id, caller_id=user.user_id, limit=limit, before=before
        )
    except Exception as exc:  # noqa: BLE001
        raise _chat_404_403(exc)


@router.post(
    "/crews/{crew_id}/chat/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="채팅 메시지 전송 (text, 크루원)",
)
async def post_chat_message(
    crew_id: str,
    req: ChatMessageCreate,
    user: CurrentUser = Depends(get_current_user),
) -> ChatMessageResponse:
    try:
        return await chat_service.post_message(crew_id, user.user_id, req.content)
    except Exception as exc:  # noqa: BLE001
        raise _chat_404_403(exc)


@router.post(
    "/crews/{crew_id}/chat/share-run",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="기록 카드 공유 (본인 run, 스냅샷 박제 — v1.5)",
)
async def share_run_to_chat(
    crew_id: str,
    req: ChatShareRunRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ChatMessageResponse:
    """본인 run(public·followers)을 크루 채팅에 카드로 공유. 타인 run·없음 404,
    private run 422. payload에 전송 시점 스냅샷 박제 — 상세 진입은 현재 권한 재평가."""
    try:
        return await chat_service.share_run(crew_id, user.user_id, req.run_id, req.caption)
    except Exception as exc:  # noqa: BLE001
        raise _chat_404_403(exc)


@router.get(
    "/crews/{crew_id}/chat/unread",
    response_model=ChatUnreadResponse,
    summary="안 읽은 수 + mute 상태 (배지용)",
)
async def chat_unread(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> ChatUnreadResponse:
    try:
        return await chat_service.unread(crew_id, user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _chat_404_403(exc)


@router.post(
    "/crews/{crew_id}/chat/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="읽음 처리 (last_read_at = now)",
)
async def chat_mark_read(
    crew_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    try:
        await chat_service.mark_read(crew_id, user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _chat_404_403(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/crews/{crew_id}/chat/mute",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="방별 채팅 mute 토글 (전역 알림과 독립)",
)
async def chat_set_mute(
    crew_id: str,
    req: ChatMuteRequest,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    try:
        await chat_service.set_mute(crew_id, user.user_id, req.muted)
    except Exception as exc:  # noqa: BLE001
        raise _chat_404_403(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/crews/{crew_id}/chat/messages/{message_id}/react",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="이모지 반응 (👍🔥👏💪, 멱등)",
)
async def chat_react(
    crew_id: str,
    message_id: str,
    req: ChatReactRequest,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    try:
        await chat_service.react(crew_id, user.user_id, message_id, req.emoji)
    except Exception as exc:  # noqa: BLE001
        raise _chat_404_403(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/crews/{crew_id}/chat/messages/{message_id}/react",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="이모지 반응 취소 (멱등)",
)
async def chat_unreact(
    crew_id: str,
    message_id: str,
    req: ChatReactRequest,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    try:
        await chat_service.unreact(crew_id, user.user_id, message_id, req.emoji)
    except Exception as exc:  # noqa: BLE001
        raise _chat_404_403(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/crews/{crew_id}/chat/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="메시지 삭제 (본인·운영진, soft — system 불가)",
)
async def delete_chat_message(
    crew_id: str,
    message_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    try:
        await chat_service.delete_message(crew_id, user.user_id, message_id)
    except Exception as exc:  # noqa: BLE001
        raise _chat_404_403(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@router.delete(
    "/notifications",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="알림 전체 삭제 (모두 지우기)",
)
async def delete_all_notifications(
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Delete all of the caller's notifications. 멱등(0건이어도 204)."""
    try:
        await notification_service.delete_all(user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to delete notifications", exc)


@router.delete(
    "/notifications/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="알림 개별 삭제 (스와이프)",
)
async def delete_notification(
    notification_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Delete one notification; 404 if not found or not owned (존재 은닉)."""
    try:
        found = await notification_service.delete_notification(notification_id, user.user_id)
    except Exception as exc:  # noqa: BLE001
        raise _bad_gateway("Failed to delete notification", exc)
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

    async def _settings_or_none():
        # Best-effort: 설정 조회 실패가 날씨 응답을 막으면 안 됨.
        try:
            return await profile_service.get_settings(user.user_id)
        except Exception:  # noqa: BLE001
            logger.warning("weather 설정 조회 실패 — 개인화·i18n 없이 응답", exc_info=True)
            return None

    try:
        weather, user_settings = await asyncio.gather(
            weather_service.get_weather(lat, lng),
            _settings_or_none(),
        )
        # i18n(2026-07-29): 텍스트는 수신자 lang으로 응답 시점 조립 — 캐시는 ko
        # 원데이터 공용(키 무변·deep copy로 오염 0). 푸시와 동일 lang 소스·ko 폴백.
        lang = (user_settings.lang
                if user_settings and user_settings.lang in ("ko", "en") else "ko")
        if user_settings is not None:
            weather = weather_service.personalize_index(
                weather, user_settings.weather, lang)
        weather = weather_service.localize_weather(weather, lang)
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


@router.get("/places", response_model=list[Place], summary="Search places (경유지·출발지)")
async def search_places(
    keyword: str = Query(..., min_length=1, max_length=50),
    lat: float | None = Query(None, ge=33.0, le=39.0),
    lng: float | None = Query(None, ge=124.0, le=132.0),
    radius_m: int | None = Query(None, ge=1, le=20000),
    limit: int = Query(5, ge=1, le=15),
    user: CurrentUser = Depends(get_current_user),
) -> list[Place]:
    """Keyword place search — 좌표 유무로 모드가 갈린다.

    - lat+lng: 좌표 기준 **거리순** (경유지 검색, radius_m 기본 2000 —
      20km 캡은 카카오 API 자체 제약).
    - 좌표 생략: **전국 정확도순** (출발지 검색). 이때 radius_m 동반은 422.
    - 한쪽 좌표만 오면 422 (모호 거부).
    인증 필수 (외부 지도 API 키 보호 — 익명 쿼터 남용 방지).
    """
    if (lat is None) != (lng is None):
        raise HTTPException(
            status_code=422, detail="lat and lng must be provided together"
        )
    if lat is None and radius_m is not None:
        raise HTTPException(
            status_code=422,
            detail="radius_m requires lat/lng (nationwide search has no radius)",
        )
    try:
        return await map_service.search_places(
            keyword=keyword,
            near=Coordinate(lat=lat, lng=lng) if lat is not None else None,
            radius_m=radius_m if radius_m is not None else 2000,
            limit=limit,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception:  # noqa: BLE001 - 예외 텍스트에 요청 상세가 실리지 않도록 고정 문자열
        logger.warning("장소 검색 실패", exc_info=True)
        raise HTTPException(status_code=502, detail="장소 검색을 일시적으로 사용할 수 없습니다.")
