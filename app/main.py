"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.core.config import settings

# Surface our INFO-level logs (avoidance hints, save confirmations) in the
# server console. Without this, the default root level is WARNING and these
# logs are silently dropped.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# httpx logs every request URL at INFO — that would write secrets embedded in
# query strings (crew invite codes, the OpenWeather appid) into server logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

# IAP mock 모드 프로덕션 사고 방지 (안전장치 ① 부팅 거부 — ②③은 iap_service).
if settings.iap_mode == "mock" and settings.environment == "production":
    raise RuntimeError(
        "IAP_MODE=mock은 production에서 금지입니다. "
        "ENVIRONMENT 또는 IAP_MODE 설정을 확인하세요."
    )

app = FastAPI(
    title=settings.app_name,
    description="South Korea-based running route AI generator.",
    version="0.1.0",
)

# CORS — tighten allow_origins for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    """Welcome endpoint."""
    return {"app": settings.app_name, "docs": "/docs"}
