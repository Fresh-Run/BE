# TEMP — 에어코리아 서빙 프로세스 400 미스터리 진단: 셸 측 짝 프로브 (2026-08-04).
# 제거 트리거: 미스터리 해소 시 /admin/diag/airkorea-probe·weather_service 프로브
# 블록·이 모듈·테스트 일괄 삭제.
# app/ 안에 있는 이유: 배포 이미지는 COPY app/뿐 + .dockerignore가 scripts/ 제외
# (2026-08-04 실전 1차 셸 프로브 불발 원인) — app 패키지 편입이 이미지 포함 보장.
"""fly ssh console에서 실행 — 서빙 프로브와 나란히 diff하기 위한 셸 측 관측.

서빙 엔드포인트(/admin/diag/airkorea-probe)와 **문자 그대로 같은 함수**
(weather_service.airkorea_probe)를 셸 프로세스에서 실행한다 — 코드·클라이언트
구성·요청·마스킹·출력 필드가 전부 동일하므로, 두 출력의 diff는 순수하게
"프로세스 문맥 차이"만 남는다(이 실험의 목적).

키는 env(AIRKOREA_API_KEY → settings)에서 읽고, 출력은 전부 ****+뒤4자 마스킹.
출력은 sort_keys JSON — 서빙 측은 `| jq -S .`로 받아 diff.

Run (fly ssh console 안에서): python /app/app/diag_airkorea_shell.py
외부 콜: 에어코리아 정확히 1회. DB 무접촉·부수효과 0.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import weather_service as ws  # noqa: E402


def main() -> int:
    obs = asyncio.run(ws.airkorea_probe())
    print(json.dumps(obs, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if obs.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
