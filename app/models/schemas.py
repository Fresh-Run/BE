"""Pydantic schemas shared across the API and services.

Coordinate convention: South Korea uses WGS84 lat/lng. Note that Kakao's
REST API expects coordinates as `x=longitude, y=latitude`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FeedbackTag(str, Enum):
    """Allowed detail tags for the run feedback loop (positive + negative).

    Stored as plain strings in runs.feedback_tags. Keep this list as the
    single source of truth so the frontend and AI loop share one vocabulary.
    """

    # 긍정 태그
    SCENIC = "경치좋음"
    GOOD_SURFACE = "노면좋음"
    FLAT = "평탄함"
    QUIET = "한적함"
    GOOD_DISTANCE = "적당한거리"

    # 부정 태그
    HILLY = "오르막많음"
    MANY_LIGHTS = "신호등많음"
    BAD_SURFACE = "노면나쁨"
    CROWDED = "사람많음"
    TOO_LONG = "너무김"
    TOO_SHORT = "너무짧음"


# Convenience groupings (for the frontend / AI loop).
POSITIVE_TAGS = [
    FeedbackTag.SCENIC,
    FeedbackTag.GOOD_SURFACE,
    FeedbackTag.FLAT,
    FeedbackTag.QUIET,
    FeedbackTag.GOOD_DISTANCE,
]
NEGATIVE_TAGS = [
    FeedbackTag.HILLY,
    FeedbackTag.MANY_LIGHTS,
    FeedbackTag.BAD_SURFACE,
    FeedbackTag.CROWDED,
    FeedbackTag.TOO_LONG,
    FeedbackTag.TOO_SHORT,
]


class Coordinate(BaseModel):
    """A WGS84 geographic point."""

    lat: float = Field(..., description="Latitude (위도)", ge=33.0, le=39.0)
    lng: float = Field(..., description="Longitude (경도)", ge=124.0, le=132.0)


class CurrentUser(BaseModel):
    """The authenticated user resolved from a Supabase JWT."""

    user_id: str = Field(..., description="Supabase auth user id (UUID).")
    email: Optional[str] = Field(None, description="User's email, if available.")


class ProfileResponse(BaseModel):
    """The caller's own profile (GET/PATCH /me/profile 전용).

    프라이버시: 신체 정보 4종(birth_year/weight_kg/height_cm/gender)은 이
    모델에만 존재한다 — 다른 유저가 보는 모든 응답(PublicProfileResponse,
    팔로우 목록, 크루 로스터, 피드, kudos, RSVP 명단 등)은 각자 명시 필드
    모델이라 스키마 차원에서 노출이 차단된다. 이 필드들을 다른 모델에
    복사하지 말 것.
    """

    user_id: str
    nickname: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    tier: str = Field("free", description="'free' or 'premium'. Admin/IAP-managed.")
    # 신체 정보 (선택 입력, 본인 전용 — 체중은 프론트 칼로리 로컬 계산용)
    birth_year: Optional[int] = None
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    gender: Optional[Literal["female", "male", "undisclosed"]] = None
    visibility: str = Field("public", description="계정 공개범위 public/followers/private.")
    # DEPRECATED (FOLLOW_CHANGES_DESIGN.md Part B): 승인제가 visibility='private'로
    # 통합되어 이 필드는 **항상 false 고정 반환**(DB 실값 무시 — 구 True 유저의
    # 설정 토글이 ON으로 남아 UI-동작 불일치를 만드는 것을 방지). build #1에 제거.
    follow_approval: bool = Field(False, description="[DEPRECATED] 항상 false. 승인제는 visibility='private'로 통합.")
    created_at: str
    updated_at: str

    @field_validator("follow_approval")
    @classmethod
    def _follow_approval_always_false(cls, _v: bool) -> bool:
        return False  # Part B 유예: DB 실값 무시하고 응답은 항상 false 고정


class ProfileUpdate(BaseModel):
    """Input to create/update the caller's profile. user_id comes from the token."""

    # 오타/미지 키는 422 — visibility·follow_approval 같은 보안 필드가 오타로
    # silent swallow(200)되던 갭 봉쇄(감사 3차 M-7). settings 모델들과 정합.
    model_config = ConfigDict(extra="forbid")

    # 부분 PATCH 시맨틱: 생략=유지(아바타 "생략=유지" 선례와 정합). 최초 생성
    # 시엔 필수 — upsert_profile이 프로필 유무로 분기해 강제(없으면 422).
    # 명시 null은 거부(닉네임은 삭제 개념 없음 — 아래 validator), ""는 min_length=2로 422.
    nickname: Optional[str] = Field(None, min_length=2, max_length=20, description="Display name. 생략=유지, 최초 생성 시 필수.")
    # 명시 null = 아바타 삭제 (PATCH 명시 null 시맨틱의 선례 필드 — API_GUIDE).
    # ""는 422 (min_length — normalize 금지, null과 혼동 차단).
    avatar_url: Optional[str] = Field(None, min_length=1, max_length=500,
                                      description="Avatar image URL. 명시 null=삭제.")
    bio: Optional[str] = Field(None, max_length=500, description="Short bio.")
    # 신체 정보 (전부 선택 — 보낸 것만 갱신, null 해제는 v1 미지원)
    birth_year: Optional[int] = Field(None, ge=1920, le=2026)
    weight_kg: Optional[float] = Field(None, ge=20, le=300)
    height_cm: Optional[float] = Field(None, ge=100, le=250)
    gender: Optional[Literal["female", "male", "undisclosed"]] = Field(
        None, description="시안 선택지: 여성(female)/남성(male)/선택 안 함(undisclosed)."
    )
    visibility: Optional[Literal["public", "followers", "private"]] = Field(
        None, description="계정 공개범위. 비공개면 비팔로워에게 잠금 화면."
    )
    # DEPRECATED (Part B): 받되 저장 안 함(no-op). 필드 유지 이유는 extra="forbid"
    # — 지우면 기존 프론트가 보내던 follow_approval이 422로 깨진다. build #1에 제거.
    follow_approval: Optional[bool] = Field(
        None, description="[DEPRECATED] no-op. 승인제는 visibility='private'로 통합."
    )

    @model_validator(mode="after")
    def _reject_explicit_null_nickname(self) -> "ProfileUpdate":
        # 명시 null(키를 보냈는데 값 null) = 422. 미전송(생략)과 구분은
        # model_fields_set으로 — 생략은 "유지", null은 삭제 시도라 거부.
        if "nickname" in self.model_fields_set and self.nickname is None:
            raise ValueError("nickname cannot be null (omit to keep, non-null to change)")
        return self


class AvatarUploadUrlResponse(BaseModel):
    """POST /me/avatar/upload-url — 앱이 Storage에 직접 업로드할 서명 URL."""

    upload_url: str = Field(..., description="이 URL로 이미지 바이트를 PUT (Content-Type 필수).")
    public_url: str = Field(
        ..., description="업로드 후 이 URL을 PATCH /me/profile의 avatar_url로 (캐시 무효화용 ?v= 권장)."
    )
    max_bytes: int = Field(..., description="버킷 상한 (초과 시 Storage가 거부).")
    allowed_types: list[str] = Field(..., description="허용 Content-Type.")


# --- User settings -------------------------------------------------------------
# 기본값의 단일 소스 = 이 모델들의 필드 기본값. GET은 저장분을 여기에 머지해
# 완전한 객체로 반환. extra='forbid'라 화이트리스트 밖 키는 422로 거부됨.


class RunSettings(BaseModel):
    """러닝 동작 토글 4종."""

    model_config = ConfigDict(extra="forbid")

    auto_pause: bool = True
    voice_cue: bool = True
    haptics: bool = True
    keep_screen_on: bool = False


class AiCourseSettings(BaseModel):
    """AI 코스 생성 기본값 (후속: 생성 파이프라인이 참조 예정)."""

    model_config = ConfigDict(extra="forbid")

    terrain: Literal["flat", "mixed", "hill"] = "mixed"
    # 상한 32.2 = 마일 모드 UI 상한 20mi(32.19km) 수용 (km 모드 UI는 30km)
    default_distance_km: float = Field(5.0, ge=1.0, le=32.2)
    scenic: bool = True
    avoid_hills: bool = False
    prefer_loop: bool = True
    surface: Literal["any", "paved", "trail"] = "any"


class AudioCoachSettings(BaseModel):
    """AI 오디오 코치 (시안 5항목 그대로 — 프리미엄 기능이지만 저장은 무료).

    서버 스크립트 생성은 cue_interval_km만 참조. voice/rate/announce_*는
    프론트 TTS 파라미터의 기기 간 동기화용.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    voice: Literal["joy", "david"] = "joy"
    rate: float = Field(1.0, ge=0.6, le=1.6)
    cue_interval_km: float = Field(1.0, ge=0.5, le=3.0)
    announce_distance: bool = True
    announce_pace: bool = True
    announce_calories: bool = False


class WeatherSettings(BaseModel):
    """날씨 회피 조건 (시안 슬라이더 범위 그대로)."""

    model_config = ConfigDict(extra="forbid")

    avoid_dust: bool = True
    dust_level_pm10: int = Field(80, ge=30, le=150)
    avoid_heat: bool = True
    heat_temp_c: int = Field(28, ge=20, le=38)
    avoid_rain: bool = False


class FeedSettings(BaseModel):
    """피드 설정 (시안 프로필 설정 — 서버 강제). 기존 유저는 전부 기본값 True라
    breaking 0. auto_publish OFF는 POST /runs 미지정 시 기본 visibility=private."""

    model_config = ConfigDict(extra="forbid")

    auto_publish: bool = True
    allow_likes: bool = True
    allow_comments: bool = True


class NotifSettings(BaseModel):
    """푸시 알림 설정 (시안 FrNotifSettings — 프론트 키 그대로 camelCase).

    기본 전부 True(marketing만 False) → 기존 유저는 미설정=기본 발송(breaking 0).
    게이트 대상은 **푸시만** — 인앱 알림은 이 설정과 무관하게 항상 생성.
    runReminder·weekly·pb는 서버 발송 주체가 아직 없음(키만 보관, 향후 각 기능
    사이클에서 게이트 연결). marketing도 발송 기능 없음. → docs API_GUIDE 표.
    """

    model_config = ConfigDict(extra="forbid")

    master: bool = True          # 마스터 스위치 — OFF면 전 카테고리 푸시 스킵
    crewChallenge: bool = True   # challenge_completed
    crewNotice: bool = True      # crew_announcement
    crewChat: bool = True        # crew_chat (선등록 — 발송은 채팅 v2)
    crewJoin: bool = True         # crew_joined, join_requested, join_approved, crew_invited(선등록)
    likes: bool = True            # route_liked, run_kudoed
    comments: bool = True         # route_commented, run_commented
    followers: bool = True        # user_followed, follow_requested, follow_request_approved
    runReminder: bool = True      # (발송 주체 없음 — 향후)
    weekly: bool = True           # (발송 주체 없음 — 향후)
    pb: bool = True               # (발송 주체 없음 — PB 저장 시 감지 가능, 백로그)
    marketing: bool = False       # (발송 기능 없음 — 기본 OFF)


class UserSettings(BaseModel):
    """GET /me/settings 응답 — 항상 완전한 객체 (기본값 머지됨)."""

    model_config = ConfigDict(extra="forbid")

    run: RunSettings = Field(default_factory=RunSettings)
    units: Literal["km", "mi"] = "km"
    theme: Literal["light", "dark"] = "light"
    lang: Literal["ko", "en"] = "ko"
    ai_course: AiCourseSettings = Field(default_factory=AiCourseSettings)
    weather: WeatherSettings = Field(default_factory=WeatherSettings)
    audio_coach: AudioCoachSettings = Field(default_factory=AudioCoachSettings)
    feed: FeedSettings = Field(default_factory=FeedSettings)
    notif: NotifSettings = Field(default_factory=NotifSettings)


class RunSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_pause: Optional[bool] = None
    voice_cue: Optional[bool] = None
    haptics: Optional[bool] = None
    keep_screen_on: Optional[bool] = None


class AiCourseSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terrain: Optional[Literal["flat", "mixed", "hill"]] = None
    default_distance_km: Optional[float] = Field(None, ge=1.0, le=32.2)
    scenic: Optional[bool] = None
    avoid_hills: Optional[bool] = None
    prefer_loop: Optional[bool] = None
    surface: Optional[Literal["any", "paved", "trail"]] = None


class WeatherSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    avoid_dust: Optional[bool] = None
    dust_level_pm10: Optional[int] = Field(None, ge=30, le=150)
    avoid_heat: Optional[bool] = None
    heat_temp_c: Optional[int] = Field(None, ge=20, le=38)
    avoid_rain: Optional[bool] = None


class AudioCoachSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: Optional[bool] = None
    voice: Optional[Literal["joy", "david"]] = None
    rate: Optional[float] = Field(None, ge=0.6, le=1.6)
    cue_interval_km: Optional[float] = Field(None, ge=0.5, le=3.0)
    announce_distance: Optional[bool] = None
    announce_pace: Optional[bool] = None
    announce_calories: Optional[bool] = None


class FeedSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_publish: Optional[bool] = None
    allow_likes: Optional[bool] = None
    allow_comments: Optional[bool] = None


class NotifSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    master: Optional[bool] = None
    crewChallenge: Optional[bool] = None
    crewNotice: Optional[bool] = None
    crewChat: Optional[bool] = None
    crewJoin: Optional[bool] = None
    likes: Optional[bool] = None
    comments: Optional[bool] = None
    followers: Optional[bool] = None
    runReminder: Optional[bool] = None
    weekly: Optional[bool] = None
    pb: Optional[bool] = None
    marketing: Optional[bool] = None


class SettingsPatch(BaseModel):
    """PATCH /me/settings 입력 — 보낸 키만 deep merge. 허용 외 키/값은 422."""

    model_config = ConfigDict(extra="forbid")

    run: Optional[RunSettingsPatch] = None
    units: Optional[Literal["km", "mi"]] = None
    theme: Optional[Literal["light", "dark"]] = None
    lang: Optional[Literal["ko", "en"]] = None
    ai_course: Optional[AiCourseSettingsPatch] = None
    weather: Optional[WeatherSettingsPatch] = None
    audio_coach: Optional[AudioCoachSettingsPatch] = None
    feed: Optional[FeedSettingsPatch] = None
    notif: Optional[NotifSettingsPatch] = None


# --- Weather ------------------------------------------------------------------


class PmReading(BaseModel):
    """One particulate-matter reading with the 환경부 grade."""

    value: float = Field(..., description="µg/m³")
    grade: str = Field(..., description="좋음 / 보통 / 나쁨 / 매우나쁨")


class UvReading(BaseModel):
    """자외선 지수 + 기상청 단계."""

    value: float = Field(..., description="UV index (OpenWeather uvi).")
    grade: str = Field(..., description="낮음 / 보통 / 높음 / 매우높음 / 위험")


class RunningIndex(BaseModel):
    """Rule-based '오늘 뛰기 좋은 날' score (no LLM call)."""

    score: int = Field(..., ge=0, le=100)
    label: str = Field(..., description="최고 / 좋음 / 보통 / 주의 / 비추천")
    comment: str = Field(..., description="한줄 코멘트 (최대 감점 요인 기준)")
    personalized: bool = Field(
        False,
        description="True면 comment가 유저의 weather 설정 기준으로 개인화됨 (score/label은 공용).",
    )


class WeatherResponse(BaseModel):
    """Current weather + air quality + running index for a location."""

    area: Optional[str] = Field(None, description="OpenWeather가 준 지역명 (동네).")
    temp_c: float
    feels_like_c: float
    condition: str = Field(..., description="하늘 상태 (한글, e.g. '맑음').")
    condition_code: int = Field(..., description="OpenWeather condition id.")
    humidity_pct: int
    wind_ms: float
    rain_1h_mm: Optional[float] = Field(None, description="최근 1시간 강수량(mm).")
    pm25: Optional[PmReading] = Field(None, description="미세먼지 API 실패 시 null.")
    pm10: Optional[PmReading] = None
    uv: Optional[UvReading] = Field(
        None, description="오늘 최고 자외선(solar-noon 최대 — /2.5/uvi 시맨틱, "
        "'현재'가 아님). API 실패 시 null (타일 숨김)."
    )
    is_day: bool = Field(
        True, description="일출~일몰 사이 여부 — 프론트 자체 아이콘 셋의 주/야 "
        "분기용 (10분 격자 캐시라 경계에서 최대 10분 지연)."
    )
    running_index: RunningIndex
    fetched_at: str = Field(..., description="원본 데이터 조회 시각 (캐시 공유됨).")


# --- IAP (Apple 인앱 구독) ------------------------------------------------------


class MockIapTransaction(BaseModel):
    """mock 모드 전용 페이로드 — 서명 검증만 스킵, 구조 검증은 실거래와 동일."""

    model_config = ConfigDict(extra="forbid")

    original_transaction_id: str = Field(..., min_length=1)
    product_id: str = Field(..., min_length=1)
    expires_at: str = Field(..., description="구독 만료 시각 (ISO 8601).")


class IapVerifyRequest(BaseModel):
    """POST /iap/verify 입력.

    apple 모드: StoreKit 2 구매 완료 후 받은 signedTransaction(JWS)을 jws로.
    mock 모드: mock 객체로 (개발/테스트 전용).
    """

    model_config = ConfigDict(extra="forbid")

    jws: Optional[str] = None
    mock: Optional[MockIapTransaction] = None


class IapVerifyResponse(BaseModel):
    """검증 성공 응답 — tier는 즉시 premium으로 전환된 상태."""

    tier: str
    product_id: str
    expires_at: str
    environment: str = Field(..., description="sandbox / production / mock")


# --- Tier / quota -------------------------------------------------------------


class AiGenerationQuota(BaseModel):
    """Weekly AI course-generation quota state (KST week, Monday reset)."""

    used: int = Field(..., description="Generations used since Monday 00:00 KST.")
    limit: Optional[int] = Field(None, description="Weekly cap; null for premium.")
    remaining: Optional[int] = Field(None, description="Left this week; null for premium.")
    reset_at: Optional[str] = Field(
        None, description="Next Monday 00:00 KST (ISO); null for premium."
    )
    unlimited: bool = Field(False, description="True for premium users.")


class QuotaResponse(BaseModel):
    """The caller's tier and quota state (GET /me/quota)."""

    tier: str
    ai_generation: AiGenerationQuota


# --- Social: follows ---------------------------------------------------------


class FollowUserItem(BaseModel):
    """One entry in a followers/following list."""

    user_id: str
    nickname: Optional[str] = Field(
        None, description="Display name; null if the user has no profile yet."
    )
    avatar_url: Optional[str] = None
    followed_at: str = Field(..., description="When the follow happened (ISO 8601).")
    is_following: bool = Field(
        False, description="True if the caller follows this listed user."
    )


class PublicProfileResponse(BaseModel):
    """Another user's public profile with follow stats. Never includes email."""

    user_id: str
    nickname: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    tier: str = Field("free", description="'free' or 'premium' (프리미엄 배지용).")
    created_at: str
    follower_count: int = Field(0, description="Number of users following this user.")
    following_count: int = Field(0, description="Number of users this user follows.")
    is_following: bool = Field(..., description="True if the caller follows this user.")
    is_followed_by: bool = Field(
        ..., description="True if this user follows the caller (맞팔 표시용)."
    )
    public_run_count: int = Field(
        0, description="이 유저가 '전체 공개'로 게시한 러닝 수 (시안 '게시한 러닝 · 공개 N')."
    )
    visibility: str = Field("public", description="계정 공개범위 (잠금 화면 판단용).")
    locked: bool = Field(
        False, description="True면 비공개 계정을 볼 권한 없음 — 🔒 화면. "
        "이때 follower/following/run count·bio는 0/null(미노출), 닉네임·아바타만."
    )
    # 피드 설정 렌더 힌트 (2026-07-13 additive) — 소유자 설정값 그대로. **잠금
    # 응답(locked=true)엔 null**(affordance 자체가 없어 무의미). false면 프론트가
    # 좋아요/댓글 버튼 렌더 생략(403은 레이스 폴백).
    allow_likes: Optional[bool] = Field(None, description="이 유저에게 좋아요 가능? (잠금 시 null)")
    allow_comments: Optional[bool] = Field(None, description="이 유저에게 댓글 가능? (잠금 시 null)")


class UserSearchItem(BaseModel):
    """GET /users/search 결과 1건 — 통합 검색 화면용(닉네임·아바타·한줄)."""

    user_id: str
    nickname: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = Field(
        None, description="한 줄 소개. **잠금(볼 수 없는 비공개) 계정은 null** — "
        "닉네임·아바타만. 프로필 진입 시 🔒 화면."
    )


class FollowDecisionRequest(BaseModel):
    """PATCH /me/follow-requests/{requester_id} — 승인/거절."""

    approve: bool = Field(..., description="True=승인(follows 생성) / False=거절.")


class RouteRequest(BaseModel):
    """Input from the client to generate a running route."""

    start: Coordinate = Field(..., description="Starting point")
    end: Optional[Coordinate] = Field(
        None,
        description="End point. If omitted, a loop back to start is assumed.",
    )
    target_distance_km: Optional[float] = Field(
        None,
        gt=0,
        # 32.2 = 마일 모드 UI 상한 20mi(32.19km) 수용 (km 모드 UI는 30km).
        # 서버는 단위 무관 km만 받는 안전망 — UI 상한은 프론트 몫.
        le=32.2,
        description=(
            "Desired total running distance in kilometers (최대 32.2). If "
            "omitted, the caller's settings.ai_course.default_distance_km is used."
        ),
    )
    # AI 코스 선호 — None(미지정)이면 유저의 settings.ai_course 값으로 폴백.
    # 우선순위: body 명시값 > 유저 설정 > 서버 기본값.
    terrain: Optional[Literal["flat", "mixed", "hill"]] = None
    scenic: Optional[bool] = None
    avoid_hills: Optional[bool] = None
    prefer_loop: Optional[bool] = None
    surface: Optional[Literal["any", "paved", "trail"]] = None
    pitstop_keyword: Optional[str] = Field(
        None,
        max_length=50,  # LLM 프롬프트 유입 — 보수적
        description="Optional waypoint keyword, e.g. '편의점' (convenience store), '공원', 'cafe'.",
    )
    notes: Optional[str] = Field(
        None,
        max_length=500,  # LLM 프롬프트 유입 — 보수적
        description="Free-form preferences, e.g. 'avoid hills', 'riverside'.",
    )
    avoid_from_route_id: Optional[str] = Field(
        None,
        description=(
            "Optional id of a past route to learn from directly. If set, that "
            "route's negative feedback is added to the location-based avoidance."
        ),
    )


class Waypoint(BaseModel):
    """A single ordered point along the generated route."""

    name: str = Field(..., description="Human-readable label for this waypoint.")
    coordinate: Coordinate
    is_pitstop: bool = Field(
        False, description="True if this waypoint matches the requested pitstop keyword."
    )
    description: Optional[str] = Field(
        None, description="Why this point was chosen / what's here."
    )


class RouteResponse(BaseModel):
    """Structured running route returned to the client."""

    summary: str = Field(..., description="Short human-readable description of the route.")
    total_distance_km: float = Field(..., description="Estimated total distance.")
    estimated_duration_min: Optional[float] = Field(
        None, description="Estimated jogging duration in minutes."
    )
    waypoints: list[Waypoint] = Field(
        default_factory=list, description="Ordered waypoints from start to finish."
    )
    polyline: Optional[list[Coordinate]] = Field(
        None,
        description="Decoded path geometry (from the Map API) for drawing on a map.",
    )
    # 동적 탐색 반경 (생성 파이프라인이 채움 — 기본값 있어 하위 호환)
    search_radius_km: Optional[float] = Field(
        None, description="이 코스를 찾은 탐색 반경(km, 출발지 기준 직선거리)."
    )
    radius_expanded: bool = Field(
        False,
        description="True면 초기 반경으로 실패해 반경을 넓혀 찾은 결과 — "
        "프론트가 '반경을 넓혀 찾았어요' 안내 가능.",
    )


class CoachCue(BaseModel):
    """오디오 코치 멘트 하나 — 프론트 TTS가 트리거 시점에 낭독.

    at 의미: distance_km → 누적 킬로미터(float), waypoint → waypoints 배열
    인덱스(해당 좌표 ~50m 근접 시 재생), start/finish → null.
    """

    trigger: Literal["start", "distance_km", "waypoint", "finish"]
    at: Optional[float] = None
    text: str = Field(..., min_length=1, max_length=300)


class CoachScriptResponse(BaseModel):
    """POST /routes/{id}/coach-script 응답 — route당 1회 생성 후 캐시."""

    route_id: str
    cues: list[CoachCue]
    from_cache: bool = Field(False, description="True면 저장된 스크립트 재반환 (Gemini 미호출).")
    created_at: str


class PedestrianRoute(BaseModel):
    """Normalized result returned by the Map service routing functions."""

    distance_m: float = Field(..., description="Total walking distance in meters.")
    duration_s: float = Field(..., description="Estimated walking duration in seconds.")
    path: list[Coordinate] = Field(
        default_factory=list, description="Ordered coordinates of the walking path."
    )
    provider: str = Field(..., description="'kakao' or 'naver'.")


class Place(BaseModel):
    """A point of interest returned by a keyword/place search."""

    name: str
    coordinate: Coordinate
    category: Optional[str] = None
    address: Optional[str] = None


class StoredRoute(BaseModel):
    """A saved route row returned to the client (mirrors the `routes` table)."""

    id: str
    created_at: str = Field(..., description="When the route was generated/saved.")
    user_id: Optional[str] = Field(None, description="Owner; NULL until auth is added.")
    # Original request inputs
    target_distance_km: Optional[float] = None
    pitstop_keyword: Optional[str] = None
    notes: Optional[str] = None
    # Generated result
    summary: str
    total_distance_km: float
    estimated_duration_min: Optional[float] = None
    waypoints: list[Waypoint] = Field(default_factory=list)
    polyline: Optional[list[Coordinate]] = None
    # Sharing
    is_public: bool = Field(False, description="Whether this route is in the public feed.")
    copied_from: Optional[str] = Field(
        None, description="Source route id if this route was copied from another."
    )


class PublicRouteResponse(BaseModel):
    """A public-feed view of a route. Omits the owner's private fields (notes)."""

    id: str
    created_at: str
    owner_id: Optional[str] = None
    summary: str
    total_distance_km: float
    estimated_duration_min: Optional[float] = None
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None
    waypoints: list[Waypoint] = Field(default_factory=list)
    polyline: Optional[list[Coordinate]] = None
    is_mine: bool = Field(..., description="True if the caller owns this route.")
    owner_nickname: Optional[str] = Field(
        None, description="Owner's nickname; null if they have no profile yet."
    )
    owner_avatar_url: Optional[str] = Field(
        None, description="코스 주인 아바타 (없으면 null → 이니셜 폴백)."
    )
    copy_count: int = Field(0, description="Number of times this route has been copied ('이 코스 달리기').")
    like_count: int = Field(0, description="Number of likes on this route.")
    is_liked: bool = Field(False, description="True if the caller has liked this route.")
    comment_count: int = Field(0, description="Number of comments on this route.")


class PeriodStats(BaseModel):
    """Running statistics for one time period."""

    total_distance_km: float
    run_count: int
    total_duration_sec: int
    avg_pace_sec_per_km: Optional[int] = None
    longest_run_km: Optional[float] = None
    delta_distance_km: Optional[float] = None


class RecordEntry(BaseModel):
    """하나의 개인 최고 기록(PB)과 그것을 달성한 run.

    value의 단위는 종류별: best_pace → sec/km, best_5k·longest_duration → sec,
    longest_distance → km.
    """

    value: float
    run_id: str
    ran_at: str = Field(..., description="달성 run의 시각 (표기용, e.g. '5월 28일').")
    distance_km: float = Field(..., description="달성 run의 거리 (표기용).")


class RecordsBlock(BaseModel):
    """전 기간 개인 최고 기록 4종 — 자격 run이 없으면 항목별 null."""

    best_pace: Optional[RecordEntry] = Field(
        None, description="최고 페이스 (sec/km). 1km 이상 run만 자격."
    )
    best_5k: Optional[RecordEntry] = Field(
        None, description="최고 5K (sec, 평균 페이스 환산). 5km 이상 run만 자격."
    )
    longest_distance: Optional[RecordEntry] = Field(None, description="최장 거리 (km).")
    longest_duration: Optional[RecordEntry] = Field(None, description="최장 시간 (sec).")


class NewRecord(BaseModel):
    """run 저장으로 경신된 PB 하나 (축하 모달용 이전/현재/향상률)."""

    type: Literal["best_pace", "best_5k", "longest_distance", "longest_duration"]
    previous: float = Field(..., description="종전 기록 (단위는 type별, RecordEntry 참고).")
    current: float = Field(..., description="이번 run의 기록.")
    improvement_pct: float = Field(..., description="향상률 % (시안 '4.5% 향상' 칩용).")


class StatsResponse(BaseModel):
    """Personal running statistics: this week, this month, all time."""

    week: PeriodStats
    month: PeriodStats
    all_time: PeriodStats
    records: RecordsBlock = Field(
        default_factory=RecordsBlock, description="전 기간 개인 최고 기록 (PB) 4종."
    )


class DailyRunStat(BaseModel):
    """One calendar day's running total (KST date) — 기록 탭 캘린더 점 찍기용."""

    date: str = Field(..., description="KST date, YYYY-MM-DD.")
    distance_km: float
    run_count: int


class MonthlyStatsResponse(BaseModel):
    """Stats for one selected KST month, with a per-day breakdown."""

    year: int
    month: int
    stats: PeriodStats = Field(
        ..., description="Month totals; delta_distance_km compares to the previous month."
    )
    days: list[DailyRunStat] = Field(
        default_factory=list, description="Days with runs only, ascending by date."
    )


class WeekStat(BaseModel):
    """월 내 한 주(KST 월요일 시작 캘린더 주)의 러닝 합계."""

    index: int = Field(..., description="월 내 주차 (1부터, 캘린더 그리드 기준).")
    distance_km: float
    run_count: int
    avg_pace_sec_per_km: Optional[int] = None


class MonthRecordEntry(BaseModel):
    """해당 월의 종목별 최고 기록 (시안 '이번 달 개인 기록' 카드)."""

    type: Literal["best_pace", "best_5k", "longest_distance", "longest_duration"]
    value: float = Field(..., description="단위는 type별 (RecordEntry와 동일).")
    ran_at: str
    distance_km: float
    all_time_best: bool = Field(
        ..., description="True면 이 달에 올타임 기록을 경신 (시안 up 화살표)."
    )


class MonthRankEntry(BaseModel):
    """이번 달 가장 최근 러닝의 종목별 순위 (시안 '이번 달 N번째로 빠른 …' 타일).

    4개 기록 차원(best_pace·best_5k 환산·longest_distance·longest_duration) 중
    가장 인상적인 1개를 서버가 선정. verified run만 대상. 프론트 조립:
    rank==1이면 "가장 빠른/긴", 아니면 "{rank}번째로 빠른/긴". 총 {total}회 중.
    """

    type: Literal["best_pace", "best_5k", "longest_distance", "longest_duration"]
    rank: int = Field(..., description="이번 run의 순위(1=최고). 빠름(pace·5k)은 낮을수록·거리·시간은 클수록 상위.")
    total: int = Field(..., description="이 차원의 이번 달 verified 러닝 수(≥2 — 1회뿐이면 타일 미생성).")
    value: float = Field(..., description="이 run의 해당 지표 값(단위는 type별).")
    ran_at: str = Field(..., description="랭크 대상 run(가장 최근)의 시각.")
    distance_km: float = Field(..., description="랭크 대상 run의 거리.")
    run_id: str


class InsightPattern(BaseModel):
    """러닝 패턴 (시안 '러닝 패턴' 카드) — 전부 KST 기준."""

    weekday_counts: list[int] = Field(..., description="월~일 7개, run 수.")
    time_of_day: Optional[Literal["dawn", "morning", "day", "evening", "night"]] = Field(
        None, description="최빈 시간대 (새벽 4-6 / 아침 6-9 / 낮 9-17 / 저녁 17-21 / 밤 21-4)."
    )
    time_of_day_pct: Optional[int] = Field(None, description="최빈 시간대 비율 %.")
    longest_streak_days: int = Field(0, description="월 내 최장 연속 러닝 일수.")
    run_days: int = Field(0, description="월 내 러닝한 날 수 (꾸준함 지표).")


class InsightPlanItem(BaseModel):
    """다음 달 추천 플랜 한 슬롯 — slot 고정 3종 (프론트 아이콘 매핑용)."""

    slot: Literal["goal", "focus", "challenge"]
    title: str
    body: str


class PaceTrendPoint(BaseModel):
    """페이스 추이 한 달 치 (시안 라인 차트) — stats.avg_pace와 동일 기준."""

    year: int
    month: int
    avg_pace_sec_per_km: Optional[int] = Field(
        None, description="그 달 평균 페이스(거리 가중). run 없으면 null(결측)."
    )


class InsightAi(BaseModel):
    """Gemini 생성 블록 — monthly_insights에 캐시됨."""

    coaching: str = Field(..., description="AI 코칭 요약 (3~5문장).")
    plan: list[InsightPlanItem]
    generated_at: str
    from_cache: bool = False


class MonthlyInsightResponse(BaseModel):
    """GET /me/insights/monthly — 프리미엄 월간 리포트.

    수치 블록은 매 요청 계산(항상 최신), ai 블록만 캐시.
    해당 월 run이 0회면 ai는 null (Gemini 미호출).
    """

    year: int
    month: int
    stats: PeriodStats
    weeks: list[WeekStat]
    records: list[MonthRecordEntry]
    pattern: InsightPattern
    pace_trend: list[PaceTrendPoint] = Field(
        default_factory=list,
        description="조회 월 포함 최근 3개월 평균 페이스 (오래된 달부터).",
    )
    month_rank: Optional[MonthRankEntry] = Field(
        None,
        description="이번 달 가장 최근 러닝의 종목별 순위(가장 인상적 1개). 랭크할 "
                    "차원이 없으면(각 차원 verified 러닝 <2회 등) null → 타일 미표시.",
    )
    ai: Optional[InsightAi] = None


class PushTokenRequest(BaseModel):
    """POST/DELETE /me/push-token — Expo 기기 토큰 등록/해제."""

    token: str = Field(..., max_length=200, description="Expo push token.")
    platform: Literal["ios", "android"] = Field(
        "ios", description="등록 시 사용 (해제 시 무시)."
    )

    @field_validator("token")
    @classmethod
    def _expo_format(cls, v: str) -> str:
        if not (v.startswith("ExponentPushToken[") and v.endswith("]")):
            raise ValueError("token must look like ExponentPushToken[...]")
        return v


class NotificationResponse(BaseModel):
    """One notification row returned to the caller."""

    id: str
    type: str
    actor_id: str
    actor_nickname: Optional[str] = None
    actor_avatar_url: Optional[str] = Field(
        None, description="행위자 아바타 (없으면 null → 이니셜 폴백)."
    )
    target_id: str
    target_type: str
    payload: Optional[dict] = Field(
        None,
        description="딥링크 보조 데이터. crew_announcement는 {\"crew_id\":...}. "
        "이 기능 이전에 발송된 알림은 null일 수 있음(소급 불가).",
    )
    is_read: bool
    created_at: str


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500, description="댓글 내용 (1~500자)")


class CommentResponse(BaseModel):
    id: str
    route_id: str
    user_id: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = Field(
        None, description="작성자 아바타 (없으면 null → 이니셜 폴백)."
    )
    content: str
    created_at: str


class RunCommentResponse(BaseModel):
    """run 댓글 (route 댓글과 동형, route_id 대신 run_id)."""

    id: str
    run_id: str
    user_id: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = Field(
        None, description="작성자 아바타 (없으면 null → 이니셜 폴백)."
    )
    content: str
    created_at: str


class PublishRequest(BaseModel):
    """Toggle a route's public visibility."""

    is_public: bool


class GpsPoint(BaseModel):
    """gps_track 한 포인트 — 좌표는 느슨하게 받고(서비스 bbox 밖은 파이프라인이
    조용히 제거) 검증은 서버 파이프라인의 몫."""

    # 오타/미지 키는 422 — 값(bbox)은 느슨하되 **키는 엄격**. 중첩 gps_track 원소의
    # 오타(latitide 등)로 좌표가 조용히 누락되던 갭 봉쇄(RunRequest forbid와 짝).
    model_config = ConfigDict(extra="forbid")

    lat: float
    lng: float
    t: int = Field(..., description="epoch milliseconds")
    acc: Optional[float] = Field(None, description="horizontalAccuracy(m) — 강력 권장.")
    alt: Optional[float] = Field(None, description="altitude(m) — 고도 차트용.")


class RunSplit(BaseModel):
    """km별 랩 — 시안 '페이스 & 고도 분석' 차트용."""

    km: float = Field(..., description="정수 랩(1,2,…) / 마지막 partial은 총거리.")
    sec: int = Field(..., description="랩 소요 시간 (elapsed).")
    elev_gain_m: Optional[int] = Field(None, description="랩 내 고도 상승 (alt 없으면 null).")
    partial: bool = False


class RunRequest(BaseModel):
    """Input from the client to log an actual run."""

    # 오타/미지 키는 422 — M-7 확장(코어 패스라 지연됐던 최고위험 모델). visibilty
    # 오타로 private 의도가 public(기본)으로 저장되던 프라이버시 갭 봉쇄. RunUpdate·
    # ProfileUpdate·Crew*와 정합. 중첩 gps_track 원소(GpsPoint)도 forbid.
    model_config = ConfigDict(extra="forbid")

    route_id: Optional[str] = Field(
        None,
        description="ID of the route that was run. Omit for a free (route-less) run.",
    )
    # 상한 350km = 세계 최장 울트라(현실 초장거리) 여유. 상한 없으면 9999km
    # 1회 전송으로 랭킹·챌린지·PB·통계 오염 가능 (unverified도 집계 포함).
    # ge=0.01: gt=0이면 1e-308 같은 값이 통과해 round 후 0.00km가 됨 — 하한 명시(L8)
    distance_km: float = Field(..., ge=0.01, le=350, description="Actual distance run, in km.")
    duration_sec: int = Field(
        ..., gt=0, le=7 * 24 * 3600, description="Elapsed time, in seconds (≤7일)."
    )
    avg_pace_sec_per_km: Optional[int] = Field(
        None, gt=0, description="Average pace in seconds per km (optional)."
    )
    # 저장 화면의 '메모' = notes (개인 메모 — 피드·크루·공개 프로필에 절대 미노출)
    notes: Optional[str] = Field(None, max_length=2000, description="개인 메모 (본인만).")
    area: Optional[str] = Field(
        None, max_length=50,
        description="지역명 (예: '성수동') — 프론트가 Kakao SDK 역지오코딩으로 "
        "변환해 전송, 서버는 저장·서빙만 (크루 area와 동일 분업).",
    )
    title: Optional[str] = Field(
        None, max_length=60,
        description="러닝 제목 (예: '야간 러닝'). 프론트가 시간대 기본값 생성해 보냄. optional.",
    )
    visibility: Literal["public", "followers", "private"] = Field(
        "public",
        description="공개 범위: public(전체)/followers(팔로워만)/private(비공개). 기본 public.",
    )
    gps_track: Optional[list[GpsPoint]] = Field(
        None,
        max_length=5000,
        description=(
            "러닝 종료 시 일괄 전송하는 GPS 궤적 (3~5초 또는 10m 간격 권장, "
            "최대 5000pt). 있으면 서버가 검증·스플릿·경로를 계산한다. optional."
        ),
    )
    # 크루 러닝 세션 태깅 L1 (2026-07-13) — "이 러닝은 OO크루 정기런"
    crew_id: Optional[str] = Field(
        None, description="크루 정기런 태그 — '크루 러닝 시작'으로 진입 시 동봉. "
        "서버가 caller 멤버십 검증(비멤버 400). 없으면 일반 러닝.",
    )
    announcement_id: Optional[str] = Field(
        None, description="집결 공지 연결(선택) — 있으면 session_key가 그 공지 "
        "기준(정밀 세션), 없으면 크루+날짜 버킷.",
    )

    @model_validator(mode="after")
    def _pace_sanity(self) -> "RunRequest":
        # duration/distance 평균 페이스가 인간 하한(1'30"/km ≈ 세계기록 미만)보다
        # 빠르면 물리적으로 불가능한 자기신고 → 거부. GPS suspect 판정과 별개로
        # 트랙 없는 자율신고 run의 최소 방어선.
        if self.distance_km > 0 and self.duration_sec / self.distance_km < 90:
            raise ValueError(
                "duration_sec 대비 distance_km가 물리적으로 불가능한 페이스입니다 "
                "(평균 1'30\"/km 미만)."
            )
        return self


class RunUpdate(BaseModel):
    """저장 후 편집 (제목·공개 범위·메모·사진). 보낸 필드만 수정, 거리·시간은 불변."""

    # 오타/미지 키 422 — visibility(프라이버시) silent swallow 봉쇄(감사 3차 M-7).
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, max_length=60)
    visibility: Optional[Literal["public", "followers", "private"]] = None
    notes: Optional[str] = Field(None, max_length=2000)
    area: Optional[str] = Field(None, max_length=50, description="지역명 (예: '성수동').")
    photos: Optional[list[str]] = Field(
        None, max_length=3,
        description="사진 경로 배열 (업로드 3-step의 path 그대로, ≤3, 중복 불가). "
        "빠진 기존 경로는 Storage에서 삭제됨. []로 전체 삭제.",
    )

    @field_validator("photos")
    @classmethod
    def _photos_unique(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None and len(v) != len(set(v)):
            raise ValueError("photos must not contain duplicate paths")
        return v


class RunPhotoUploadUrlRequest(BaseModel):
    """POST /runs/{id}/photos/upload-url — 슬롯별 서명 업로드 URL 발급."""

    slot: int = Field(..., ge=1, le=3, description="사진 슬롯 (1~3).")
    content_type: Literal["image/jpeg", "image/png", "image/webp"]


class RunPhotoUploadUrlResponse(BaseModel):
    """서명 업로드 URL — avatar 3-step과 동형 (run-photos private 버킷)."""

    upload_url: str
    path: str = Field(..., description="업로드 후 PATCH /runs/{id}의 photos에 넣을 경로.")
    max_bytes: int
    allowed_types: list[str]


class RunResponse(BaseModel):
    """A stored run record returned to the client (mirrors the `runs` table)."""

    id: str
    created_at: str = Field(..., description="When the record was saved.")
    user_id: Optional[str] = Field(None, description="Owner; NULL until auth is added.")
    route_id: Optional[str] = Field(None, description="Linked route, if any.")
    ran_at: str = Field(..., description="When the run actually happened.")
    distance_km: float
    duration_sec: int
    avg_pace_sec_per_km: Optional[int] = None
    notes: Optional[str] = None
    title: Optional[str] = None
    area: Optional[str] = Field(
        None, description="지역명 (프론트 역지오코딩 저장값). 과거 run은 null — 라인 숨김."
    )
    visibility: Optional[str] = Field(
        "public", description="public/followers/private. 타인이 보는 상세에선 null."
    )
    # 완료 화면 비교 rows (POST /runs 응답에서만 — 최근 30일 평균 대비)
    recent_avg_pace_sec_per_km: Optional[int] = Field(
        None, description="최근 30일 평균 페이스 (이번 run 제외). 히스토리 없으면 null.",
    )
    pace_delta_sec: Optional[int] = Field(
        None, description="이번 run 페이스 − 최근 평균 (음수=평소보다 빠름). null이면 비교 불가.",
    )
    # Feedback loop (NULL/empty until the user submits feedback)
    liked: Optional[bool] = Field(None, description="True=좋았어요, False=별로예요.")
    feedback_tags: list[str] = Field(default_factory=list)
    feedback_at: Optional[str] = Field(None, description="When feedback was submitted.")
    # PB 경신 (POST /runs 응답에서만 채워짐 — 비어있지 않으면 축하 모달 대상)
    new_records: list[NewRecord] = Field(
        default_factory=list,
        description="이번 저장으로 경신된 PB 목록. 첫 run(이전 기록 없음)은 항상 [].",
    )
    # GPS 서버 검증 (기본값 있는 추가 필드 — 하위 호환)
    verification: str = Field(
        "unverified",
        description="unverified(GPS 없음/판정 보류) / verified / suspect(부정 의심 — PB·랭킹·챌린지 제외)",
    )
    is_flagged: bool = Field(
        False,
        description="True면 서버가 조정·의심 표시 — 거리 대체(verified+distance_km_reported) 또는 suspect.",
    )
    distance_km_reported: Optional[float] = Field(
        None, description="거리 괴리로 서버 값이 대체됐을 때 앱이 신고했던 원본 거리."
    )
    has_track: bool = Field(False, description="True면 GET /runs/{id}/track 조회 가능.")
    splits: Optional[list[RunSplit]] = Field(
        None, description="km별 랩 (GPS 없는 run은 null)."
    )
    kudos_count: int = Field(
        0, description="이 run이 받은 kudos 수 (기록 카드 ♥ 표시용)."
    )
    my_kudos: bool = Field(
        False,
        description="조회자가 이 run에 kudos를 눌렀는지 (상세 ♥ 초기 상태 — "
        "피드 my_kudos와 동일 계산. 본인 run은 kudos 불가라 항상 false).",
    )
    comment_count: int = Field(0, description="이 run이 받은 댓글 수 (카드 💬 표시용).")
    photos: list[str] = Field(
        default_factory=list,
        description="사진 서명 URL(만료 1h) — 상세(GET /runs/{id})에서만 채움, 목록은 photo_thumb.",
    )
    photo_thumb: Optional[str] = Field(
        None, description="첫 사진 서명 URL(만료 1h) — 목록 카드 썸네일용."
    )
    polyline_thumb: Optional[list[Coordinate]] = Field(
        None, description="카드 지도용 축약 폴리라인(≤36pt, 좌표 5자리). "
        "트랙 없는 run은 null — 지도 자리 숨김/일러스트 폴백."
    )
    # 피드 설정 렌더 힌트 (2026-07-13 additive) — run 소유자 설정값. 타인 상세에서
    # "좋아요/댓글 버튼 렌더 여부" 판단(false면 생략, 403은 레이스 폴백). 본인 상세도 참값.
    allow_likes: Optional[bool] = Field(None, description="소유자에게 kudos 가능?")
    allow_comments: Optional[bool] = Field(None, description="소유자에게 댓글 가능?")


class RunTrackResponse(BaseModel):
    """GET /runs/{run_id}/track — 상세 화면 전용 (경로 지도)."""

    polyline: list[Coordinate] = Field(..., description="간축된 경로 (≤1000pt).")
    server_distance_km: float
    elev_gain_m: Optional[int] = None
    point_count_raw: int
    point_count_kept: int


class FeedbackRequest(BaseModel):
    """Input to submit feedback for a logged run (2단계 피드백 루프)."""

    liked: bool = Field(..., description="좋았어요(true) / 별로예요(false).")
    tags: list[FeedbackTag] = Field(
        default_factory=list,
        max_length=20,  # 허용 태그 수 이내 — 무제한 배열 방어(L8)
        description="Detail tags (multi-select). Must be from the allowed list.",
    )

    @field_validator("tags")
    @classmethod
    def _dedupe_tags(cls, v: list) -> list:
        # 순서 보존 중복 제거 (같은 태그 반복 전송 방어)
        seen: set = set()
        return [t for t in v if not (t in seen or seen.add(t))]


# --- Community: crews --------------------------------------------------------


class CrewLevel(str, Enum):
    """Allowed crew difficulty levels."""

    ANY = "무관"
    BEGINNER = "입문"
    INTERMEDIATE = "중급"
    ADVANCED = "고급"


# 시·도 17개 광역 표준 명칭 (DB CHECK·프론트 정적 목록과 동일 기준). sigungu는
# 250개 관리 부담 회피 위해 자유 문자열(길이 제한만) — 프론트 표준 목록 신뢰.
Sido = Literal[
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시",
    "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도",
    "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도",
    "경상남도", "제주특별자치도",
]

# 크루 카드 태그 — 서버 정의 고정 어휘 (자유입력 아님). 카드엔 최대 2개 노출,
# 저장은 최대 5개. 시간대/지형/분위기 3분류 13종.
CrewTag = Literal[
    "새벽", "아침", "저녁", "야간", "주말",          # 시간대
    "평지", "트레일", "언덕",                          # 지형
    "입문환영", "기록도전", "친목", "여성전용", "페이스그룹",  # 분위기
]


def _short_day_items(value: Optional[list[str]]) -> Optional[list[str]]:
    """active_days 각 항목 길이 제한 (요일 라벨은 짧음 — 거대 문자열 방어)."""
    if value is None:
        return value
    for item in value:
        if len(item) > 10:
            raise ValueError("active_days 항목은 10자 이하여야 합니다.")
    return value


class CrewCreate(BaseModel):
    """Input to create a crew. owner_id comes from the token, not the body."""

    # 오타/미지 키는 422 — is_public·join_policy 같은 보안 필드가 오타로 silent
    # swallow(200)되던 갭 봉쇄(M-7 확장, 크루 계열 정합). ProfileUpdate 선례.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=50, description="크루 이름")
    description: Optional[str] = Field(None, max_length=500, description="한 줄 소개")
    area: Optional[str] = Field(None, max_length=50, description="활동 지역")
    radius_km: Optional[float] = Field(None, gt=0, le=20, description="활동 반경(km, 시안 확정 상한 20)")
    sport: Optional[str] = Field(None, max_length=30, description="종목")
    level: CrewLevel = Field(CrewLevel.ANY, description="레벨")
    max_members: Optional[int] = Field(None, gt=0, le=100, description="최대 인원(없으면 무제한, 시안 확정 상한 100)")
    is_public: bool = Field(True, description="공개여부")
    join_policy: Literal["open", "approval"] = Field(
        "open", description="가입 방식: open=즉시 가입, approval=승인제"
    )
    active_days: list[str] = Field(
        default_factory=list, max_length=7, description="활동 요일 (예: ['월','수'])"
    )
    active_time: Optional[str] = Field(None, max_length=50, description="활동 시간")
    color: Optional[str] = Field(None, max_length=20, description="색상 (예: #FF8800)")
    # 둘러보기(당근식) — 프론트가 위치 선택 UI에서 해석해 전송 (서버 지오코딩 안 함)
    sido: Optional[Sido] = Field(None, description="시·도 (17개 광역 표준명).")
    sigungu: Optional[str] = Field(None, max_length=30, description="시군구명 (예: 성동구).")
    lat: Optional[float] = Field(None, ge=33.0, le=39.0, description="대표 좌표 위도.")
    lng: Optional[float] = Field(None, ge=124.0, le=132.0, description="대표 좌표 경도.")
    tags: list[CrewTag] = Field(
        default_factory=list, max_length=5,
        description="카드 태그 (서버 정의 어휘, 최대 5개 저장·카드엔 2개 노출).",
    )
    # 상설 집결지 (CREW_MEET_PLACE_DESIGN) — 공지의 일회성 place_*와 독립.
    # 길이·bbox는 공지 place_* 규칙 복제(≤100자·한국 bbox, 앱 검증만).
    meet_place_name: Optional[str] = Field(None, max_length=100, description="상설 집결지 표시명.")
    meet_lat: Optional[float] = Field(None, ge=33.0, le=39.0, description="집결 좌표 위도.")
    meet_lng: Optional[float] = Field(None, ge=124.0, le=132.0, description="집결 좌표 경도.")

    _days = field_validator("active_days")(staticmethod(_short_day_items))


class TransferRequest(BaseModel):
    """Input to transfer crew ownership to another member."""

    new_owner_id: str = Field(..., description="user_id of the member to promote.")
    leave_after: bool = Field(
        False,
        description="If true, the old owner also leaves the crew after handing over.",
    )


class CrewResponse(BaseModel):
    """A crew row returned to the client (mirrors `crews` + member_count)."""

    id: str
    created_at: str
    owner_id: str
    name: str
    description: Optional[str] = None
    area: Optional[str] = None
    radius_km: Optional[float] = None
    sport: Optional[str] = None
    level: str
    max_members: Optional[int] = None
    is_public: bool
    join_policy: str = Field("open", description="'open' 또는 'approval'.")
    active_days: list[str] = Field(default_factory=list)
    active_time: Optional[str] = None
    color: Optional[str] = None
    member_count: int = Field(..., description="Current number of members.")
    owner_nickname: Optional[str] = Field(
        None, description="Owner's nickname; null if they have no profile yet."
    )
    # 둘러보기 필드
    sido: Optional[str] = None
    sigungu: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    tags: list[str] = Field(default_factory=list)
    distance_km: Optional[float] = Field(
        None,
        description="요청에 lat/lng가 있고 크루에 좌표가 있으면 계산된 거리(km, 1자리). "
        "그 외 null.",
    )
    # 크루 이미지 (2026-07-13 additive) — 없으면 null → 프론트 기본 그라데이션/아이콘.
    cover_url: Optional[str] = Field(None, description="커버 이미지 URL(둘러보기 카드·상세 헤더).")
    icon_url: Optional[str] = Field(None, description="크루 아이콘 URL(원형 뱃지).")
    admin_count: Optional[int] = Field(
        None, description="운영진(role=admin) 수 — 크루 상세(GET /crews/{id})에서만 채움"
                         "(관리 화면 통계). 목록/기타 응답은 null.",
    )
    # 상설 집결지 (2026-07-14 additive, CREW_MEET_PLACE_DESIGN) — 카드 장소 라인.
    # 셋 다 null이면 프론트가 장소 라인 숨김. _to_response의 **crew 스프레드로
    # 10개 소비 경로(browse·mine·상세·preview·join 등)에 자동 노출.
    meet_place_name: Optional[str] = Field(None, description="상설 집결지 표시명 — null이면 카드 장소 라인 숨김.")
    meet_lat: Optional[float] = Field(None, description="집결 좌표 위도 (지도 진입용).")
    meet_lng: Optional[float] = Field(None, description="집결 좌표 경도.")


class CrewMemberResponse(BaseModel):
    """One entry in the crew member roster."""

    user_id: str
    nickname: Optional[str] = Field(
        None, description="Display name; null if the member has no profile yet."
    )
    role: str = Field(..., description='"owner" / "admin"(운영진) / "member".')
    avatar_url: Optional[str] = Field(
        None, description="멤버 아바타 (없으면 null → 이니셜 폴백)."
    )
    joined_at: str = Field(..., description="When the user joined the crew (ISO 8601).")
    challenge_km: Optional[float] = Field(
        None,
        description="현재 진행 챌린지에서 이 멤버의 기여 거리(km, verified run 합). "
                    "진행 중 챌린지가 없으면 null. **주간 랭킹 km와 별개** — 랭킹은 "
                    "이번 주 월요일 KST 기준, 이 값은 챌린지 기간(starts~ends) 기준.",
    )
    permissions: Optional[dict] = Field(
        None,
        description="세부 권한 5키 bool (v2). **owner는 전부 true 합성**, admin은 "
                    "부여된 값, member는 null. 키: announcements·challenges·edit_crew·"
                    "kick_members·manage_admins. 행동 가능 판별용(role은 표시·정렬용).",
    )


class CrewPermissionsPatch(BaseModel):
    """PATCH /crews/{id}/members/{uid}/permissions — 보낸 키만 갱신(v2).

    owner 또는 manage_admins admin. 대상은 admin이어야. 비owner는 자기 보유 키만
    grant + 주의 2키(kick_members·manage_admins)는 owner만(§3 위임 사슬).
    """

    model_config = ConfigDict(extra="forbid")

    announcements: Optional[bool] = None
    challenges: Optional[bool] = None
    edit_crew: Optional[bool] = None
    kick_members: Optional[bool] = None
    manage_admins: Optional[bool] = None


class CrewPermissionsResponse(BaseModel):
    """permissions 조정 결과 — 머지 후 5키 전체."""

    user_id: str
    permissions: dict = Field(..., description="머지 후 5키 bool.")


class CrewRoleUpdate(BaseModel):
    """PATCH /crews/{id}/members/{user_id}/role — owner 또는 manage_admins admin, admin↔member."""

    role: Literal["admin", "member"] = Field(
        ..., description="owner로의 변경은 불가 — 위임은 PATCH /crews/{id}/transfer."
    )


class CrewRoleResponse(BaseModel):
    """role 전환 결과."""

    user_id: str
    role: str


# ── 크루 채팅 (docs/CREW_CHAT_DESIGN.md) ──────────────────────────────────────

CHAT_EMOJIS = ("👍", "🔥", "👏", "💪")   # 고정 4종 (단일 소스)


class ChatMessageCreate(BaseModel):
    """POST /crews/{id}/chat/messages — v1은 text만 (system/run_share는 v1.5)."""

    content: str = Field(..., min_length=1, max_length=2000)


class ChatShareRunRequest(BaseModel):
    """POST /crews/{id}/chat/share-run — 본인 run을 채팅에 카드로 공유 (v1.5)."""

    run_id: str = Field(..., description="공유할 run (본인 것만, private 불가).")
    caption: Optional[str] = Field(None, max_length=2000, description="카드에 붙일 한마디(선택).")


class ChatReactRequest(BaseModel):
    """POST/DELETE /crews/{id}/chat/messages/{mid}/react."""

    emoji: Literal["👍", "🔥", "👏", "💪"]


class ChatMuteRequest(BaseModel):
    muted: bool


class ChatMessageResponse(BaseModel):
    """채팅 메시지 1건 — 발신자 프로필·반응 집계 포함."""

    id: str
    crew_id: str
    sender_id: Optional[str] = Field(None, description="탈퇴 작성자는 null(익명화).")
    sender_nickname: Optional[str] = None
    sender_avatar_url: Optional[str] = None
    type: str = Field("text", description="text / system / run_share.")
    content: Optional[str] = Field(None, description="삭제된 메시지는 null.")
    payload: Optional[dict] = None
    created_at: str
    reactions: dict[str, int] = Field(
        default_factory=dict, description="이모지별 카운트 (0인 이모지는 생략)."
    )
    my_reactions: list[str] = Field(
        default_factory=list, description="조회자가 누른 이모지 목록."
    )
    deleted: bool = Field(False, description="soft 삭제 여부 (content=null).")
    blocked: bool = Field(
        False,
        description="차단 관계 발신자의 메시지 (v3.5). true면 서버가 content·"
        "payload를 null로 보냄 — 프론트는 '가려진 메시지' 플레이스홀더 렌더. "
        "반응 집계(reactions)는 유지(카운트 왜곡 방지), 새 반응 추가는 404.",
    )


class ChatUnreadResponse(BaseModel):
    unread_count: int
    muted: bool = Field(False, description="이 방 채팅 mute 상태.")


class CrewRankingEntry(BaseModel):
    """One entry in the crew weekly distance ranking."""

    rank: int = Field(..., description="1-based rank; tied members share the same rank.")
    user_id: str
    nickname: Optional[str] = Field(
        None, description="Display name; null if the member has no profile yet."
    )
    distance_km: float = Field(..., description="Total distance run this week (KST Monday 00:00 onwards).")
    avatar_url: Optional[str] = Field(
        None, description="멤버 아바타 (없으면 null → 이니셜 폴백)."
    )
    me: bool = Field(..., description="True면 호출자 본인 행 (본인 하이라이트용).")


class CrewUpdate(BaseModel):
    """Partial-update input for a crew. Only provided (non-None) fields are written."""

    # 오타/미지 키는 422 — is_public·join_policy 같은 보안 필드가 오타로 silent
    # swallow(200)되던 갭 봉쇄(M-7 확장). CrewCreate와 정합. 명시 null=삭제
    # (sido/sigungu/lat/lng·cover/icon)는 update_crew가 model_fields_set으로 구분.
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=50, description="크루 이름")
    description: Optional[str] = Field(None, max_length=500, description="한 줄 소개")
    area: Optional[str] = Field(None, max_length=50, description="활동 지역")
    radius_km: Optional[float] = Field(None, gt=0, le=20, description="활동 반경(km, 시안 확정 상한 20)")
    sport: Optional[str] = Field(None, max_length=30, description="종목")
    level: Optional[CrewLevel] = Field(None, description="레벨")
    max_members: Optional[int] = Field(None, gt=0, le=100, description="최대 인원(시안 확정 상한 100)")
    is_public: Optional[bool] = Field(None, description="공개 여부")
    join_policy: Optional[Literal["open", "approval"]] = Field(
        None, description="가입 방식 변경 (크루장만)"
    )
    active_days: Optional[list[str]] = Field(None, max_length=7, description="활동 요일")
    active_time: Optional[str] = Field(None, max_length=50, description="활동 시간")
    color: Optional[str] = Field(None, max_length=20, description="색상 (예: #FF8800)")
    sido: Optional[Sido] = Field(None, description="시·도 (17개 광역 표준명).")
    sigungu: Optional[str] = Field(None, max_length=30, description="시군구명.")
    lat: Optional[float] = Field(None, ge=33.0, le=39.0)
    lng: Optional[float] = Field(None, ge=124.0, le=132.0)
    tags: Optional[list[CrewTag]] = Field(None, max_length=5)
    # 상설 집결지 (CREW_MEET_PLACE_DESIGN) — 명시 null=삭제(_NULL_DELETABLE),
    # 생략=유지, 값=설정. 검증은 공지 place_* 규칙 복제(≤100자·한국 bbox).
    meet_place_name: Optional[str] = Field(None, max_length=100, description="상설 집결지 표시명. 명시 null=삭제.")
    meet_lat: Optional[float] = Field(None, ge=33.0, le=39.0, description="집결 좌표 위도. 명시 null=삭제.")
    meet_lng: Optional[float] = Field(None, ge=124.0, le=132.0, description="집결 좌표 경도. 명시 null=삭제.")
    # 크루 이미지 — 업로드(3-step) 후 public_url을 여기에 저장. 명시 null=삭제
    # (Storage 파일도 정리 — update_crew가 model_fields_set으로 구분). ""는 422.
    cover_url: Optional[str] = Field(None, min_length=1, max_length=500, description="커버 URL. 명시 null=삭제.")
    icon_url: Optional[str] = Field(None, min_length=1, max_length=500, description="아이콘 URL. 명시 null=삭제.")

    _days = field_validator("active_days")(staticmethod(_short_day_items))


class CrewRunItem(BaseModel):
    """One run in the crew activity feed.

    Deliberately excludes personal fields (notes, liked, feedback_tags) —
    crew members see stats, not private notes/feedback.
    """

    run_id: str
    user_id: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    ran_at: str
    title: Optional[str] = None
    distance_km: float
    duration_sec: int
    avg_pace_sec_per_km: Optional[int] = None
    route_id: Optional[str] = None
    area: Optional[str] = Field(None, description="지역명 (카드 지역 라인 — null이면 숨김).")
    photo_thumb: Optional[str] = Field(
        None, description="첫 사진 서명 URL(만료 1h) — 카드 썸네일. 없으면 null."
    )
    polyline_thumb: Optional[list[Coordinate]] = Field(
        None, description="카드 지도용 축약 폴리라인(≤36pt). 트랙 없으면 null."
    )
    route_summary: Optional[str] = Field(
        None, description="연결된 코스 요약 — 공개 코스일 때만, 비공개면 null."
    )
    comment_count: int = Field(0, description="run 댓글 수 (카드 💬).")
    # 피드 설정 렌더 힌트 (2026-07-13 additive) — run 소유자 설정값. false면 프론트가
    # 좋아요/댓글 버튼 렌더 생략(403은 레이스 폴백). ActivityFeedItem에 자동 전파.
    allow_likes: Optional[bool] = Field(None, description="소유자에게 kudos 가능?")
    allow_comments: Optional[bool] = Field(None, description="소유자에게 댓글 가능?")
    # 크루 러닝 세션 태깅 L1 (2026-07-13) — 이 크루의 정기런이면 배지+참여자 수.
    is_crew_session: bool = Field(
        False, description="이 run이 **이 크루의 정기런** 태그면 true → '정기런' 배지.",
    )
    session_participant_count: Optional[int] = Field(
        None, description="같은 정기런 세션 참여자 수(distinct, private 제외·차단 전역). "
        "정기런 아니면 null.",
    )


class ActivityFeedItem(CrewRunItem):
    """One run in the following activity feed (GET /feed/activities).

    Inherits CrewRunItem's privacy guarantees (no notes/feedback fields,
    route_summary only for public courses). comment_count now included
    (run comments shipped 2026-07-08).
    """

    is_mine: bool = Field(False, description="내 run이면 true (kudos 버튼 비활성용).")
    kudos_count: int = 0
    my_kudos: bool = Field(False, description="내가 이 run에 kudos를 눌렀는지.")
    visibility: Optional[str] = Field(
        None, description="공개 범위 (본인 프로필 뱃지용). 활동 피드/크루 피드에선 생략(null)."
    )


class KudosUserItem(BaseModel):
    """One user in a run's kudos list."""

    user_id: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: str


class InviteCodeResponse(BaseModel):
    """A crew's invite code (owner only)."""

    code: str = Field(..., description="8자 초대 코드 (I/O/0/1 제외 대문자+숫자).")


class CrewInviteRequest(BaseModel):
    """POST /crews/{id}/invitations — 크루원이 비크루원을 인앱 초대."""

    user_id: str = Field(..., description="초대할 대상 user_id (비크루원·비차단).")


class JoinByCodeRequest(BaseModel):
    """Join a crew by invite code. Normalized server-side (strip + upper)."""

    code: str = Field(..., min_length=6, max_length=12)


class JoinRequestResponse(BaseModel):
    """One join request (returned to the requester; 202 body on approval crews)."""

    id: str
    crew_id: str
    user_id: str
    nickname: Optional[str] = None
    status: str = Field(..., description="pending / approved / rejected")
    created_at: str
    decided_at: Optional[str] = None


class MyJoinRequestItem(BaseModel):
    """GET /me/join-requests 한 건 — 둘러보기 '신청됨' 뱃지용.

    전체 상태 포함 (pending/approved/rejected) — 프론트가 필터해서 사용.
    """

    crew_id: str
    crew_name: Optional[str] = Field(None, description="크루 이름 (표시용).")
    status: str = Field(..., description="pending / approved / rejected")
    created_at: str
    decided_at: Optional[str] = None


class JoinRequestItem(BaseModel):
    """One entry in the owner's pending-request list."""

    id: str
    user_id: str
    nickname: Optional[str] = None
    created_at: str


def _require_aware_iso(value: Optional[str]) -> Optional[str]:
    """ISO 8601 + 타임존 필수 검증. naive 입력은 서버가 UTC로 오해석해 KST 의도가
    9시간 시프트되므로(감사 M2) 아예 거부한다. None은 통과(선택 필드)."""
    if value is None:
        return value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("ISO 8601 형식이 아닙니다 (예: 2026-07-07T20:00:00+09:00).") from exc
    if parsed.tzinfo is None:
        raise ValueError(
            "타임존이 필요합니다 — ISO 8601 with timezone offset "
            "(예: 2026-07-07T20:00:00+09:00 또는 ...Z)."
        )
    return value


class AnnouncementCreate(BaseModel):
    """Input to create a crew announcement. author comes from the token."""

    title: str = Field(..., min_length=1, max_length=100, description="공지 제목")
    body: str = Field(..., min_length=1, max_length=2000, description="공지 본문")
    run_at: Optional[str] = Field(None, description="러닝 일시 (ISO 8601 + 타임존). 있어야 RSVP 가능.")
    place_name: Optional[str] = Field(None, max_length=100, description="장소명(표시용)")
    # 집결 좌표 — 미니맵·"지도 앱에서 보기"용. 한국 bbox(Coordinate와 동일 범위,
    # run.area/좌표 분업 선례처럼 서버는 저장·서빙만). place_name(표시명)과 병존.
    place_lat: Optional[float] = Field(None, ge=33.0, le=39.0, description="집결 좌표 위도")
    place_lng: Optional[float] = Field(None, ge=124.0, le=132.0, description="집결 좌표 경도")
    rsvp_closes_at: Optional[str] = Field(
        None, description="참석 투표 마감 (ISO 8601 + 타임존, run_at 이전). 없으면 run_at이 마감."
    )

    _tz = field_validator("run_at", "rsvp_closes_at")(
        staticmethod(_require_aware_iso)
    )


class AnnouncementUpdate(BaseModel):
    """Partial-update input. Only provided fields are written; no notification."""

    title: Optional[str] = Field(None, min_length=1, max_length=100)
    body: Optional[str] = Field(None, min_length=1, max_length=2000)
    run_at: Optional[str] = None
    place_name: Optional[str] = Field(None, max_length=100)
    place_lat: Optional[float] = Field(None, ge=33.0, le=39.0)
    place_lng: Optional[float] = Field(None, ge=124.0, le=132.0)
    rsvp_closes_at: Optional[str] = None

    _tz = field_validator("run_at", "rsvp_closes_at")(
        staticmethod(_require_aware_iso)
    )


class RsvpRequest(BaseModel):
    """One member's attendance vote (re-voting overwrites)."""

    status: Literal["going", "not_going", "maybe"] = Field(
        ..., description="참석 / 불참 / 미정"
    )


class RsvpTally(BaseModel):
    """Aggregated RSVP counts for one announcement (current members only)."""

    going: int = 0
    not_going: int = 0
    maybe: int = 0


class RsvpMember(BaseModel):
    """One attendee in the 참석자 명단."""

    user_id: str
    nickname: Optional[str] = None


class AnnouncementResponse(BaseModel):
    """A crew announcement with RSVP tallies and the caller's vote."""

    id: str
    crew_id: str
    author_id: Optional[str] = Field(None, description="작성자. 탈퇴 시 null.")
    author_nickname: Optional[str] = None
    author_avatar_url: Optional[str] = Field(
        None, description="작성자 아바타 (탈퇴 작성자·미설정은 null → 이니셜 폴백)."
    )
    title: str
    body: str
    run_at: Optional[str] = None
    place_name: Optional[str] = None
    place_lat: Optional[float] = None
    place_lng: Optional[float] = None
    rsvp_closes_at: Optional[str] = None
    rsvp_open: bool = Field(
        False, description="run_at이 있고 마감(coalesce(rsvp_closes_at, run_at)) 전이면 true."
    )
    rsvp: RsvpTally = Field(default_factory=RsvpTally)
    my_rsvp: Optional[str] = Field(None, description="내 투표 상태; 안 했으면 null.")
    created_at: str
    updated_at: str


class AnnouncementDetailResponse(AnnouncementResponse):
    """Announcement detail — adds the attendee roster."""

    going_members: list[RsvpMember] = Field(default_factory=list)


class ChallengeCreate(BaseModel):
    """Input to create a crew challenge. crew_id and created_by come from the URL/token."""

    title: str = Field(..., min_length=1, max_length=100, description="챌린지 제목 (예: '이번 주 100km 달성!')")
    goal_km: float = Field(..., gt=0, le=100, description="목표 거리(km, 시안 확정 상한 100)")
    starts_at: str = Field(..., description="시작 시각 (ISO 8601 + 타임존, 예: 2026-07-07T00:00:00+09:00)")
    ends_at: str = Field(..., description="종료 시각 (ISO 8601 + 타임존, 예: 2026-07-13T23:59:59+09:00)")

    _tz = field_validator("starts_at", "ends_at")(staticmethod(_require_aware_iso))


class ChallengeResponse(BaseModel):
    """A crew challenge row plus real-time progress fields."""

    id: str
    crew_id: str
    title: str
    goal_km: float
    starts_at: str
    ends_at: str
    created_by: Optional[str] = Field(
        None, description="생성자. 크루 위임 후 계정 삭제 시 null (H2 정책)."
    )
    created_at: str
    # real-time computed fields
    achieved_km: float = Field(..., description="기간 내 크루 누적 거리(km)")
    progress_pct: float = Field(..., description="달성률 0~100 (소수점 1자리)")
    is_completed: bool = Field(..., description="achieved_km >= goal_km")
    is_active: bool = Field(..., description="현재 시각이 starts_at~ends_at 사이인지")


# ── 신고 (docs/REPORT_DESIGN.md) ──────────────────────────────────────────────


class ReportCreate(BaseModel):
    """POST /reports 입력. v1은 target_type='user'만 오픈(Literal이 나머지 422)."""

    # 오타/미지 키 422 — reason·target_type 같은 필드가 오타로 silent 무시되면
    # 신고가 조용히 누락된다(M-7 계열, 신규 모델은 forbid 기본).
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["user"] = Field(
        ..., description="v1은 'user'만. run/댓글 등은 스키마(DB CHECK 6종)만 선반영 — API 확장 시 Literal만 넓힘."
    )
    target_id: str = Field(..., description="신고 대상 user_id.")
    reason: Literal["spam", "abuse", "inappropriate", "impersonation", "other"] = Field(
        ..., description="사유(영문 서버 키 — 한글 라벨은 프론트 몫)."
    )
    detail: Optional[str] = Field(
        None, max_length=500, description="자유 서술(선택, ≤500자 — 'other' 보완용)."
    )


class ReportUserBrief(BaseModel):
    """신고 목록의 reporter/target 프로필 요약."""

    user_id: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None


class ReportItem(BaseModel):
    """GET /admin/reports 한 항목 (운영 전용 — 일반 응답에 노출 금지)."""

    id: str
    reporter: ReportUserBrief
    target_type: str
    target_id: str
    target: Optional[ReportUserBrief] = Field(
        None, description="target_type='user'일 때만 프로필 요약(그 외 null)."
    )
    reason: str
    detail: Optional[str] = None
    status: str
    created_at: str
    reviewed_at: Optional[str] = None


class ReportDecision(BaseModel):
    """PATCH /admin/reports/{id} 입력 — 단방향(pending 되돌리기는 Literal 밖 422)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["reviewed", "dismissed"]
