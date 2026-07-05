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
# logs are silently dropped. stdout 라인 로그 — 호스팅(fly logs 등) 뷰어가
# 그대로 수집한다 (구조화 JSON은 트래픽 생긴 뒤 후속).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# httpx logs every request URL at INFO — that would write secrets embedded in
# query strings (crew invite codes, the OpenWeather appid) into server logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Sentry — SENTRY_DSN이 설정된 경우에만 활성 (미설정 = no-op, 로컬 기본).
if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0,  # 에러 트래킹만 — APM은 후속
    )
    logging.getLogger(__name__).info("Sentry 활성화 (environment=%s)", settings.environment)

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

# CORS — 네이티브(Expo) 앱은 CORS 무관. '*'는 개발 중 브라우저(Swagger 등)
# 접근용이며, credentials=False가 정합('*'+credentials 조합은 브라우저 표준상
# 무효 — 우리는 쿠키 없이 Bearer 토큰만 쓰므로 불필요). 웹 클라이언트가
# 생기면 그때 allow_origins를 도메인 목록으로 좁힌다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
