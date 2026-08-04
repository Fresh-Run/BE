"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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
def init_sentry() -> bool:
    """DSN 게이트 sentry_sdk.init — 부팅 시 1회. 테스트가 동일 구성을 그대로
    밟을 수 있게 함수로 분리(단일 소스). 활성 시 True."""
    if not settings.sentry_dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0,  # 에러 트래킹만 — APM은 후속
        # SDK 기본 "medium"은 에러 요청의 JSON body(GPS 궤적·신체정보 포함
        # 가능)를 US Sentry로 첨부 — 개인정보 축소 (PRIVACY_DATA_MAP §7-2)
        max_request_body_size="never",
        # 스택 지역변수에 req 좌표·유저 이메일 노출 관찰(운영 관측 07-09) —
        # App Privacy "충돌 데이터 신원 미연결" 신고와 일치시키기 위해 차단
        include_local_variables=False,
        # 외부 발신에 추적 헤더(sentry-trace/baggage) 전면 미주입 — 에어코리아
        # 게이트웨이가 sentry 추적 헤더 실린 요청을 400(reason 10)으로 반려
        # (2026-08-04 프로브 3면 비교 실측). traces_sample_rate=0이라 분산
        # 추적 전파의 실익이 0 → 빈 리스트(전면 미전파)가 최단 안전. APM을
        # 켜는 날 자사 오리진 한정으로 재설계.
        trace_propagation_targets=[],
    )
    logging.getLogger(__name__).info("Sentry 활성화 (environment=%s)", settings.environment)
    return True


init_sentry()

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

# ── error_code 계약 (2026-07-30, additive) ───────────────────────────────────
# 모든 4xx/5xx body 최상위에 error_code 동봉 — detail은 바이트 불변(§D 에러 계약,
# 고정 문자열 무접촉). 클라 분기·i18n 조회 키는 error_code만(와이어 값 — pm/uv
# grade 전례와 동일 패턴). 개별 엔드포인트 수정 0 — 이 중앙 핸들러가 전량 커버.
# 매핑: dict detail의 "error" 키 승격(기존 구조화 코드 21종) → 문자열 큐레이션 표
# → status 제네릭 폴백(코드 없는 에러 응답 0 보장).

_ERROR_CODE_BY_DETAIL = {
    "Crew not found": "crew_not_found",
    "Run not found": "run_not_found",
    "User not found": "user_not_found",
    "Route not found": "route_not_found",
    "Route not found or not public": "route_not_found",
    "Members only": "members_only",
    "User is not a member of this crew": "not_crew_member",
    "Invalid invite code": "invalid_invite_code",
    "Crew is full": "crew_full",
    "Already a member": "already_member",
    "Not found": "not_found",
    "Not authenticated": "unauthorized",
}
_ERROR_CODE_BY_STATUS = {400: "bad_request", 401: "unauthorized", 403: "forbidden",
                         404: "not_found", 409: "conflict", 422: "bad_request",
                         429: "rate_limited"}


def _resolve_error_code(status_code: int, detail) -> str:
    if isinstance(detail, dict) and detail.get("error"):
        return str(detail["error"])
    if isinstance(detail, str) and detail in _ERROR_CODE_BY_DETAIL:
        return _ERROR_CODE_BY_DETAIL[detail]
    if status_code >= 500:
        return "server_error"
    return _ERROR_CODE_BY_STATUS.get(status_code, "bad_request")


@app.exception_handler(StarletteHTTPException)
async def _http_exception_with_code(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(
            {"detail": exc.detail,
             "error_code": _resolve_error_code(exc.status_code, exc.detail)}),
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def _validation_with_code(request: Request, exc: RequestValidationError):
    # input 에코백 제거(2026-07-31 오너 결정, 프라이버시) — 검증 실패 시 클라
    # 전송 body 원문(notes·GPS 좌표 등)이 detail[].input으로 반사되던 것 차단.
    # type·loc·msg는 유지 — 클라 분기·i18n 키는 type+loc 조합(§5 소비 규칙).
    errors = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({"detail": errors,
                                  "error_code": "validation_error"}),
    )


@app.exception_handler(Exception)
async def _unhandled_with_code(request: Request, exc: Exception):
    # 미처리 예외 500 JSON화(2026-07-31, 에러 감사 ⑤ 공백) — 기존 Starlette
    # 기본은 text/plain "Internal Server Error"(JSON도 error_code도 없음).
    # 내부 상세는 응답에 싣지 않는다(고정 문자열) — 전문은 로그·Sentry로만.
    # 명시 캡처: 등록 핸들러 경유 시 자동 캡처에만 의존하지 않는다(재raise 여부가
    # 스택 구성에 의존) — Dedupe 기본 통합이 이중 캡처를 자연 방지.
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    logging.getLogger(__name__).error("미처리 예외 → 500 JSON 응답", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "일시적인 서버 오류입니다. 잠시 후 다시 시도해 주세요.",
                 "error_code": "server_error"},
    )


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    """Welcome endpoint."""
    return {"app": settings.app_name, "docs": "/docs"}
