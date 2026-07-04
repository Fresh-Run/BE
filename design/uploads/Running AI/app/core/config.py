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
    environment: str = "development"
    debug: bool = True

    # OpenAI (or any OpenAI-compatible endpoint, e.g. Google Gemini)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    # Base URL for the OpenAI-compatible API. Point this at Gemini's
    # OpenAI-compatible endpoint to route requests to Google Gemini:
    #   https://generativelanguage.googleapis.com/v1beta/openai/
    openai_base_url: str = "https://api.openai.com/v1"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # Map APIs (South Korea)
    kakao_rest_api_key: str = ""
    naver_map_client_id: str = ""
    naver_map_client_secret: str = ""
    # T-map (SK Telecom) — sidewalk-accurate pedestrian routing.
    tmap_app_key: str = ""
    map_provider: Literal["kakao", "naver", "tmap"] = "kakao"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read once per process)."""
    return Settings()


settings = get_settings()
