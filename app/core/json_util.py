"""제어문자 방어 JSON 파싱 — 외부 API 응답(Gemini tool_call·T-map/Kakao/Naver)
공용 단일 소스(CLAUDE.md '공유 로직 단일 소스').

배경: 외부 API가 간헐적으로 미이스케이프 제어문자(U+0000~U+001F)를 문자열 값에
담아 표준 json.loads가 'Invalid control character'로 깨진다. 2026-07-22 E2E 실측:
처음엔 Gemini 층으로 오진했으나 실제는 **T-map 응답**(도로/POI명)이 주 발생원
(map_service resp.json()). 보수적 방어로 두 층 모두 이 헬퍼로 일원화한다.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")


def loads_lenient(raw: str, *, context: str = "json") -> Any:
    """표준 파싱 우선(정상은 무변형) → 제어문자 파싱 실패에만 strip 후 1회 재시도.

    구조 whitespace(\\t\\n\\r) 제거는 JSON 무해(토큰은 구두점으로 구분)이고, 문자열
    내부 리터럴 제어문자(파싱 파괴 원인)만 실제로 사라진다. cleaned도 실패하면
    (문법 자체가 깨짐) JSONDecodeError를 그대로 전파 → 호출측 기존 실패 경로 유지
    (Gemini: 후보 탈락 / T-map: 스냅 실패 → nopath·503 판정).
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("%s JSON 제어문자 감지 — strip 후 재파싱 시도", context)
        return json.loads(_CONTROL_CHARS.sub("", raw))
