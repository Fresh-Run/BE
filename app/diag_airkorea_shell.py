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

모드 (센트리 가설 결정 실험, 2026-08-04):
  기본           — 무센트리 프로세스(기존 셸 조건 그대로).
  --with-sentry  — 앱과 **문자 그대로 동일한** 초기화 경로(import app.main —
                   sentry_sdk.init 포함, 단일 소스)를 먼저 밟은 뒤 프로브 1회.
                   DSN은 env(SENTRY_DSN → settings)에서만 읽고 화면 출력 0.
                   셸 400 재현 = 센트리 헤더 주입 가설 확정 재료.

Run (fly ssh console 안에서):
  python /app/app/diag_airkorea_shell.py
  python /app/app/diag_airkorea_shell.py --with-sentry
외부 콜: 에어코리아 정확히 1회. DB 무접촉·부수효과 0.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import weather_service as ws  # noqa: E402


def main(argv: list[str]) -> int:
    if "--with-sentry" in argv:
        # 별도 init 복제 금지 — 앱 부팅과 동일 코드가 실행되게 import로 밟는다
        # (드리프트 0). DSN 미설정이면 앱과 동일하게 no-op — active로 판별.
        import app.main  # noqa: F401
        import sentry_sdk
        active = sentry_sdk.get_client().is_active()
        print(f"# mode=with-sentry active={active}", file=sys.stderr)
        if not active:
            print("# 경고: SENTRY_DSN 미설정 — 무센트리와 동일 조건", file=sys.stderr)
    else:
        print("# mode=plain (무센트리)", file=sys.stderr)
    obs = asyncio.run(ws.airkorea_probe())
    print(json.dumps(obs, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if obs.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
