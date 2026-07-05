"""Pydantic schemas shared across the API and services.

Coordinate convention: South Korea uses WGS84 lat/lng. Note that Kakao's
REST API expects coordinates as `x=longitude, y=latitude`.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    """A user's public profile (mirrors the `profiles` table)."""

    user_id: str
    nickname: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    tier: str = Field("free", description="'free' or 'premium'. Admin/IAP-managed.")
    created_at: str
    updated_at: str


class ProfileUpdate(BaseModel):
    """Input to create/update the caller's profile. user_id comes from the token."""

    nickname: str = Field(..., min_length=2, max_length=20, description="Display name.")
    avatar_url: Optional[str] = Field(None, description="Avatar image URL.")
    bio: Optional[str] = Field(None, description="Short bio.")


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
    default_distance_km: float = Field(5.0, ge=1.0, le=20.0)
    scenic: bool = True
    avoid_hills: bool = False
    prefer_loop: bool = True
    surface: Literal["any", "paved", "trail"] = "any"


class WeatherSettings(BaseModel):
    """날씨 회피 조건 (시안 슬라이더 범위 그대로)."""

    model_config = ConfigDict(extra="forbid")

    avoid_dust: bool = True
    dust_level_pm10: int = Field(80, ge=30, le=150)
    avoid_heat: bool = True
    heat_temp_c: int = Field(28, ge=20, le=38)
    avoid_rain: bool = False


class UserSettings(BaseModel):
    """GET /me/settings 응답 — 항상 완전한 객체 (기본값 머지됨)."""

    model_config = ConfigDict(extra="forbid")

    run: RunSettings = Field(default_factory=RunSettings)
    units: Literal["km", "mi"] = "km"
    theme: Literal["light", "dark"] = "light"
    lang: Literal["ko", "en"] = "ko"
    ai_course: AiCourseSettings = Field(default_factory=AiCourseSettings)
    weather: WeatherSettings = Field(default_factory=WeatherSettings)


class RunSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_pause: Optional[bool] = None
    voice_cue: Optional[bool] = None
    haptics: Optional[bool] = None
    keep_screen_on: Optional[bool] = None


class AiCourseSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terrain: Optional[Literal["flat", "mixed", "hill"]] = None
    default_distance_km: Optional[float] = Field(None, ge=1.0, le=20.0)
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


class SettingsPatch(BaseModel):
    """PATCH /me/settings 입력 — 보낸 키만 deep merge. 허용 외 키/값은 422."""

    model_config = ConfigDict(extra="forbid")

    run: Optional[RunSettingsPatch] = None
    units: Optional[Literal["km", "mi"]] = None
    theme: Optional[Literal["light", "dark"]] = None
    lang: Optional[Literal["ko", "en"]] = None
    ai_course: Optional[AiCourseSettingsPatch] = None
    weather: Optional[WeatherSettingsPatch] = None


# --- Weather ------------------------------------------------------------------


class PmReading(BaseModel):
    """One particulate-matter reading with the 환경부 grade."""

    value: float = Field(..., description="µg/m³")
    grade: str = Field(..., description="좋음 / 보통 / 나쁨 / 매우나쁨")


class RunningIndex(BaseModel):
    """Rule-based '오늘 뛰기 좋은 날' score (no LLM call)."""

    score: int = Field(..., ge=0, le=100)
    label: str = Field(..., description="최고 / 좋음 / 보통 / 주의 / 비추천")
    comment: str = Field(..., description="한줄 코멘트 (최대 감점 요인 기준)")


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
    running_index: RunningIndex
    fetched_at: str = Field(..., description="원본 데이터 조회 시각 (캐시 공유됨).")


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


class RouteRequest(BaseModel):
    """Input from the client to generate a running route."""

    start: Coordinate = Field(..., description="Starting point")
    end: Optional[Coordinate] = Field(
        None,
        description="End point. If omitted, a loop back to start is assumed.",
    )
    target_distance_km: float = Field(
        ...,
        gt=0,
        le=100,
        description="Desired total running distance in kilometers.",
    )
    pitstop_keyword: Optional[str] = Field(
        None,
        description="Optional waypoint keyword, e.g. '편의점' (convenience store), '공원', 'cafe'.",
    )
    notes: Optional[str] = Field(
        None, description="Free-form preferences, e.g. 'avoid hills', 'riverside'."
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


class StatsResponse(BaseModel):
    """Personal running statistics: this week, this month, all time."""

    week: PeriodStats
    month: PeriodStats
    all_time: PeriodStats


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


class NotificationResponse(BaseModel):
    """One notification row returned to the caller."""

    id: str
    type: str
    actor_id: str
    actor_nickname: Optional[str] = None
    target_id: str
    target_type: str
    is_read: bool
    created_at: str


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500, description="댓글 내용 (1~500자)")


class CommentResponse(BaseModel):
    id: str
    route_id: str
    user_id: str
    nickname: Optional[str] = None
    content: str
    created_at: str


class PublishRequest(BaseModel):
    """Toggle a route's public visibility."""

    is_public: bool


class RunRequest(BaseModel):
    """Input from the client to log an actual run."""

    route_id: Optional[str] = Field(
        None,
        description="ID of the route that was run. Omit for a free (route-less) run.",
    )
    distance_km: float = Field(..., gt=0, description="Actual distance run, in km.")
    duration_sec: int = Field(..., gt=0, description="Elapsed time, in seconds.")
    avg_pace_sec_per_km: Optional[int] = Field(
        None, gt=0, description="Average pace in seconds per km (optional)."
    )
    notes: Optional[str] = Field(None, description="Free-form notes about the run.")


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
    # Feedback loop (NULL/empty until the user submits feedback)
    liked: Optional[bool] = Field(None, description="True=좋았어요, False=별로예요.")
    feedback_tags: list[str] = Field(default_factory=list)
    feedback_at: Optional[str] = Field(None, description="When feedback was submitted.")


class FeedbackRequest(BaseModel):
    """Input to submit feedback for a logged run (2단계 피드백 루프)."""

    liked: bool = Field(..., description="좋았어요(true) / 별로예요(false).")
    tags: list[FeedbackTag] = Field(
        default_factory=list,
        description="Detail tags (multi-select). Must be from the allowed list.",
    )


# --- Community: crews --------------------------------------------------------


class CrewLevel(str, Enum):
    """Allowed crew difficulty levels."""

    ANY = "무관"
    BEGINNER = "입문"
    INTERMEDIATE = "중급"
    ADVANCED = "고급"


class CrewCreate(BaseModel):
    """Input to create a crew. owner_id comes from the token, not the body."""

    name: str = Field(..., min_length=1, description="크루 이름")
    description: Optional[str] = Field(None, description="한 줄 소개")
    area: Optional[str] = Field(None, description="활동 지역")
    radius_km: Optional[float] = Field(None, gt=0, description="활동 반경(km)")
    sport: Optional[str] = Field(None, description="종목")
    level: CrewLevel = Field(CrewLevel.ANY, description="레벨")
    max_members: Optional[int] = Field(None, gt=0, description="최대 인원(없으면 무제한)")
    is_public: bool = Field(True, description="공개여부")
    join_policy: Literal["open", "approval"] = Field(
        "open", description="가입 방식: open=즉시 가입, approval=승인제"
    )
    active_days: list[str] = Field(default_factory=list, description="활동 요일 (예: ['월','수'])")
    active_time: Optional[str] = Field(None, description="활동 시간")
    color: Optional[str] = Field(None, description="색상 (예: #FF8800)")


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


class CrewMemberResponse(BaseModel):
    """One entry in the crew member roster."""

    user_id: str
    nickname: Optional[str] = Field(
        None, description="Display name; null if the member has no profile yet."
    )
    role: str = Field(..., description='"owner" or "member".')
    joined_at: str = Field(..., description="When the user joined the crew (ISO 8601).")


class CrewRankingEntry(BaseModel):
    """One entry in the crew weekly distance ranking."""

    rank: int = Field(..., description="1-based rank; tied members share the same rank.")
    user_id: str
    nickname: Optional[str] = Field(
        None, description="Display name; null if the member has no profile yet."
    )
    distance_km: float = Field(..., description="Total distance run this week (KST Monday 00:00 onwards).")


class CrewUpdate(BaseModel):
    """Partial-update input for a crew. Only provided (non-None) fields are written."""

    name: Optional[str] = Field(None, min_length=1, description="크루 이름")
    description: Optional[str] = Field(None, description="한 줄 소개")
    area: Optional[str] = Field(None, description="활동 지역")
    radius_km: Optional[float] = Field(None, gt=0, description="활동 반경(km)")
    sport: Optional[str] = Field(None, description="종목")
    level: Optional[CrewLevel] = Field(None, description="레벨")
    max_members: Optional[int] = Field(None, gt=0, description="최대 인원")
    is_public: Optional[bool] = Field(None, description="공개 여부")
    join_policy: Optional[Literal["open", "approval"]] = Field(
        None, description="가입 방식 변경 (크루장만)"
    )
    active_days: Optional[list[str]] = Field(None, description="활동 요일")
    active_time: Optional[str] = Field(None, description="활동 시간")
    color: Optional[str] = Field(None, description="색상 (예: #FF8800)")


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
    distance_km: float
    duration_sec: int
    avg_pace_sec_per_km: Optional[int] = None
    route_id: Optional[str] = None
    route_summary: Optional[str] = Field(
        None, description="연결된 코스 요약 — 공개 코스일 때만, 비공개면 null."
    )


class ActivityFeedItem(CrewRunItem):
    """One run in the following activity feed (GET /feed/activities).

    Inherits CrewRunItem's privacy guarantees (no notes/feedback fields,
    route_summary only for public courses). comment_count is deliberately
    absent — added later (non-breaking) when run comments ship.
    """

    is_mine: bool = Field(False, description="내 run이면 true (kudos 버튼 비활성용).")
    kudos_count: int = 0
    my_kudos: bool = Field(False, description="내가 이 run에 kudos를 눌렀는지.")


class KudosUserItem(BaseModel):
    """One user in a run's kudos list."""

    user_id: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: str


class InviteCodeResponse(BaseModel):
    """A crew's invite code (owner only)."""

    code: str = Field(..., description="8자 초대 코드 (I/O/0/1 제외 대문자+숫자).")


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


class JoinRequestItem(BaseModel):
    """One entry in the owner's pending-request list."""

    id: str
    user_id: str
    nickname: Optional[str] = None
    created_at: str


class AnnouncementCreate(BaseModel):
    """Input to create a crew announcement. author comes from the token."""

    title: str = Field(..., min_length=1, max_length=100, description="공지 제목")
    body: str = Field(..., min_length=1, max_length=2000, description="공지 본문")
    run_at: Optional[str] = Field(None, description="러닝 일시 (ISO 8601). 있어야 RSVP 가능.")
    place_name: Optional[str] = Field(None, description="장소명")
    place_lat: Optional[float] = None
    place_lng: Optional[float] = None
    rsvp_closes_at: Optional[str] = Field(
        None, description="참석 투표 마감 (ISO 8601, run_at 이전이어야 함). 없으면 run_at이 마감."
    )


class AnnouncementUpdate(BaseModel):
    """Partial-update input. Only provided fields are written; no notification."""

    title: Optional[str] = Field(None, min_length=1, max_length=100)
    body: Optional[str] = Field(None, min_length=1, max_length=2000)
    run_at: Optional[str] = None
    place_name: Optional[str] = None
    place_lat: Optional[float] = None
    place_lng: Optional[float] = None
    rsvp_closes_at: Optional[str] = None


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

    title: str = Field(..., min_length=1, description="챌린지 제목 (예: '이번 주 100km 달성!')")
    goal_km: float = Field(..., gt=0, description="목표 거리(km)")
    starts_at: str = Field(..., description="시작 시각 (ISO 8601, 예: 2026-07-07T00:00:00+09:00)")
    ends_at: str = Field(..., description="종료 시각 (ISO 8601, 예: 2026-07-13T23:59:59+09:00)")


class ChallengeResponse(BaseModel):
    """A crew challenge row plus real-time progress fields."""

    id: str
    crew_id: str
    title: str
    goal_km: float
    starts_at: str
    ends_at: str
    created_by: str
    created_at: str
    # real-time computed fields
    achieved_km: float = Field(..., description="기간 내 크루 누적 거리(km)")
    progress_pct: float = Field(..., description="달성률 0~100 (소수점 1자리)")
    is_completed: bool = Field(..., description="achieved_km >= goal_km")
    is_active: bool = Field(..., description="현재 시각이 starts_at~ends_at 사이인지")
