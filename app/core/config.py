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

    # IAP (Apple 인앱 구독 검증)
    # 'apple' = 실검증 (App Store Server API 크리덴셜 필요 — 출시기 구현),
    # 'mock'  = 개발/테스트 전용 (서명 검증 스킵, 페이로드 구조 검증만).
    # 기본값 apple: 미설정 환경에서는 verify가 503으로 안전하게 닫혀 있다.
    iap_mode: Literal["apple", "mock"] = "apple"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read once per process)."""
    return Settings()


settings = get_settings()
