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
