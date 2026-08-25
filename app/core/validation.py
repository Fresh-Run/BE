"""Path-parameter validation helpers.

`validate_uuid_or_404` 는 uuid path param(예: {crew_id}·{route_id}·{run_id}·
{comment_id}·{target_id}·{user_id})에 비uuid 문자열이 들어와 PostgREST가 22P02
(invalid input syntax for type uuid)를 던지고 그게 502 server_error로 노출되던
함정(§C '비uuid 22P02')을 근절하기 위한 공용 유틸이다.

정책: 비uuid = 존재할 수 없는 id → **404 은닉**(존재 숨김 표준, 권한 차단과 동일).
DB 쿼리 0(검증에서 차단). 기존 개별 교정(route DELETE·crews/{id})과 동작 동일.
"""
from __future__ import annotations

import uuid as _uuid

from fastapi import HTTPException, Request, status


def is_uuid(value: object) -> bool:
    """value가 UUID 형식으로 파싱되면 True (표준 형식 전부 허용)."""
    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def validate_uuid_or_404(value: str) -> str:
    """uuid path param 방어 — 유효하면 그대로 반환, 비uuid면 404 은닉.

    PostgREST 22P02 → 502 노출을 쿼리 이전에 차단(DB 무접촉). 404 detail은 고정
    문자열 "Not Found"(§D 에러 계약 — main.py가 error_code='not_found'로 매핑).
    """
    if not is_uuid(value):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return value


async def validate_uuid_path_params(request: Request) -> None:
    """라우터 전역 가드 — uuid 이름 path param(`id` 또는 `*_id`)에 비uuid 유입 시 404.

    이 앱의 모든 `id`/`*_id` path param은 uuid 리소스(crew_id·route_id·run_id·
    comment_id·target_id·report_id·requester_id·request_id·notification_id·
    message_id·announcement_id·user_id)이고 전부 PostgREST 필터에 유입된다 —
    비uuid면 22P02(→502)가 나므로 **쿼리 이전 단계에서 일괄 404 은닉**(§C '비uuid
    22P02' 근절). `id`/`*_id` 이름만 검사해 남발을 막고, 신규 uuid 엔드포인트도
    자동 커버(단일 소스). 고정 경로(/crews/mine·/routes/public 등)는 해당 param이
    없어 무동작. detail 고정 문자열 → error_code='not_found'(§D).
    """
    for name, value in request.path_params.items():
        if (name == "id" or name.endswith("_id")) and not is_uuid(value):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
