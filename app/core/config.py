"""Application configuration loaded from environment variables.

Uses pydantic-settings so values can be supplied via a `.env` file
(see `.env.example`) or real environment variables in production.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "Running Route AI"
    # dev/prod 분리 규칙 (배포 설계 2026-07-06):
    #   prod는 fly secrets로 ENVIRONMENT=production만 바꾸고,
    #   IAP_MODE·OPENWEATHER_BASE_URL 등 테스트 오버라이드는 "미설정"이 정답 —
    #   아래 기본값들이 전부 안전한 방향(닫힘/실서버)을 향한다.
    environment: str = "development"
    debug: bool = True

    # Sentry — DSN이 비어 있으면 연동 자체를 건너뛴다 (no-op).
    # 계정 생성 후 fly secrets set SENTRY_DSN=... 만 하면 켜진다.
    sentry_dsn: str = ""

    # Expo Push (원격 알림) — URL은 테스트 mock 치환용, 토큰은 EAS 푸시 보안
    # 활성화 시에만 필요 (기본 미사용)
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    expo_access_token: str = ""

    # OpenAI (or any OpenAI-compatible endpoint, e.g. Google Gemini)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    # Base URL for the OpenAI-compatible API. Point this at Gemini's
    # OpenAI-compatible endpoint to route requests to Google Gemini:
    #   https://generativelanguage.googleapis.com/v1beta/openai/
    openai_base_url: str = "https://api.openai.com/v1"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""  # anon (public) key — used for auth/token validation
    # service_role (secret) key — used for backend DATA access. Bypasses RLS,
    # so it must stay server-side only. Never expose to clients.
    supabase_service_role_key: str = ""

    # 앵커 혼합 풀 기여자 (ANCHOR_EPIC §9 부활, 2026-07-24) — 9-풀 중 앵커 롤 수.
    # 0=off(순수 v87, 즉시 롤백) / 스테이징 2~3. Gemini 0콜(규칙 기반 앵커 체인).
    anchor_pool_n: int = 0

    # in-band spur 구제(INBAND_SPUR_RESCUE_DESIGN, 오너 승인 2026-07-30) — v87
    # in-band hit의 longest_retrace_m > max_m 시 0원 대체→축소 재추첨→원 후보
    # 최후 서빙. enabled=False가 1차 롤백 경로(관측 필드는 플래그 무관 발효).
    spur_rescue_enabled: bool = False
    spur_rescue_max_m: float = 800.0
    spur_rescue_pool_n: int = 5

    # 베타 한정: 신규 가입 프로필 최초 생성 시 기본 tier=premium (방식 A 자동화,
    # 2026-07-27). 출시 전 OFF 원복(IAP_LAUNCH_CHECKLIST) — OFF 후 신규는 free
    # (컬럼 default), 기존 행 무영향(update 분기는 tier 불변).
    beta_default_premium: bool = False

    # 에어코리아 실측 PM(AIR_QUALITY_SOURCE_DESIGN, 오너 승인 2026-07-31) —
    # enabled=False가 롤백 경로(현행 OpenWeather 100% 복원). 공공데이터포털
    # 개편(—8/2)으로 키 미발급 — 문서 기반 구현 상태, fixture 실채집·ON은
    # 키 도착 후 별도 단계.
    airkorea_enabled: bool = False
    airkorea_api_key: str = ""

    # OpenWeather (current weather + air pollution proxy)
    openweather_api_key: str = ""
    # Overridable so tests can point the proxy at a local mock server.
    openweather_base_url: str = "https://api.openweathermap.org"

    # Map APIs (South Korea)
    kakao_rest_api_key: str = ""
    naver_map_client_id: str = ""
    naver_map_client_secret: str = ""
    # T-map (SK Telecom) — sidewalk-accurate pedestrian routing.
    tmap_app_key: str = ""
    map_provider: Literal["kakao", "naver", "tmap"] = "kakao"
    # T-map 콜 예산 1단계 (2026-08-05, 오너 확정 월 10만원=1만콜 하드 제약):
    # ①프로세스 하드캡 — 0=무제한(서빙 기본). **오프라인 캠페인 스크립트는 설정
    #   필수**(§C 콜 예산 선계산 — 초과 시 TmapBudgetExceeded로 중단).
    # ②leg 캐시 TTL초 — 0=캐시 OFF. ③KST 일일 소프트 임계 — 초과 시 WARNING만
    #   (차단 아님 — 차단 도입은 오너 별도 결정).
    tmap_budget_calls: int = 0
    tmap_leg_cache_ttl_s: float = 600.0
    tmap_daily_warn_calls: int = 300
    # OpenWeather 일일 소프트 임계(2026-08-06, One Call cap 1,000의 80%) —
    # 초과 시 WARNING만(차단 없음). 0=끔.
    openweather_daily_warn_calls: int = 800

    # IAP (Apple 인앱 구독 검증)
    # 'apple' = 실검증 (App Store Server API 크리덴셜 필요 — 출시기 구현),
    # 'mock'  = 개발/테스트 전용 (서명 검증 스킵, 페이로드 구조 검증만).
    # 기본값 apple: 미설정 환경에서는 verify가 503으로 안전하게 닫혀 있다.
    iap_mode: Literal["apple", "mock"] = "apple"

    # 운영진 화이트리스트 (docs/REPORT_DESIGN.md §4) — 콤마구분 UUID 문자열.
    # Fly secret ADMIN_USER_IDS로 주입. 미설정(빈 값)이면 admin 엔드포인트가
    # 전원 404 = fail-safe(의도된 안전 기본값). 값은 로그·화면에 출력 금지.
    admin_user_ids: str = ""


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read once per process)."""
    return Settings()


settings = get_settings()
