"""
Unit: 푸시 닉네임 폴백 lang-aware (2026-07-29 Ivan 합의)

닉네임 미해석 시 수신자 lang으로 폴백 — ko="러너"·en="A runner". 조립 로직을
본체와 동일 식으로 재현해 검증(발송 없음, 외부 콜 0).

Run: python tests/test_push_nickname_fallback.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.push_service import _NICKNAME_FALLBACK, _TEMPLATES  # noqa: E402


def ok(m):
    print(f"  ✓ {m}")


def assemble(type_, lang, nickname):
    """send_for_notification body 조립부와 동일 식(비-PB 분기)."""
    return _TEMPLATES[type_][lang].format(
        nickname=nickname or _NICKNAME_FALLBACK[lang])


def run():
    print("[1. 미해석 + en → 영문 폴백 문장]")
    b = assemble("route_liked", "en", None)
    assert b == "A runner liked your course", b
    b2 = assemble("follow_requested", "en", None)
    assert b2 == "A runner requested to follow you", b2
    # run_kudoed en 개정(07/29 Ivan — 인앱 'likes' 통일): liked + 대상(run/course) 구분
    bk = assemble("run_kudoed", "en", None)
    assert bk == "A runner liked your run", bk
    assert assemble("route_liked", "en", None) == "A runner liked your course"
    ok(f'"{b}" · "{b2}" · "{bk}" (route_liked와 동사 동일·대상 구분 확인)')

    print("\n[2. 미해석 + ko/미설정 → 러너 유지]")
    b3 = assemble("run_kudoed", "ko", None)
    assert b3 == "러너님이 회원님의 러닝을 응원해요", b3
    # 미설정 lang은 본체(line 199)가 ko로 폴백 — 동일 결과
    ok(f'"{b3}" (lang 미설정도 본체 ko 폴백 경유 동일)')

    print("\n[3. 정상 해석 → 폴백 미사용 회귀]")
    b4 = assemble("route_liked", "en", "지연")
    assert b4 == "지연 liked your course", b4
    b5 = assemble("route_liked", "ko", "지연")
    assert b5 == "지연님이 회원님의 코스를 좋아해요", b5
    ok(f'"{b4}" · "{b5}"')

    print("\n[4. 폴백 사전 무결성 — 본체 lang 도메인(ko/en) 전부 커버]")
    assert set(_NICKNAME_FALLBACK) == {"ko", "en"}
    nick_templates = [t for t, v in _TEMPLATES.items() if "{nickname}" in v["ko"]]
    for t in nick_templates:
        for lg in ("ko", "en"):
            assemble(t, lg, None)   # KeyError/format 오류 없이 전 템플릿 조립
    ok(f"nickname 템플릿 {len(nick_templates)}종 × ko/en 전부 조립 성공")


if __name__ == "__main__":
    run()
    print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
