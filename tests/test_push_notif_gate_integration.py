"""
Integration test: 푸시 알림 설정 게이트 (시안 FrNotifSettings v1)

send_for_notification을 직접 await하며 Expo POST를 mock — 발송/스킵을 호출
횟수로 검증. master OFF 전체 스킵 / 카테고리 OFF 해당만 스킵 / 미설정 유저
기본 발송 / 인앱은 게이트 무관 항상 생성.

in-process 테스트(app import) — 로컬 서버 불필요. .venv/bin/python으로 실행.
Run: python tests/test_push_notif_gate_integration.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import notification_service, profile_service, push_service  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402


def _keys():
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):              anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}
TS = int(time.time())


def ok(m):        print(f"  ✓ {m}")
def step(t):      print(f"\n[{t}]")


# --- Expo POST mock -----------------------------------------------------------
_posts: list[dict] = []


class _FakeResp:
    status_code = 200
    def json(self):  # Expo 성공 티켓
        return {"data": [{"status": "ok"}]}


async def _fake_post(self, url, **kw):
    _posts.append({"url": url, "json": kw.get("json")})
    return _FakeResp()


def run():
    c = httpx.Client(timeout=30)
    sb = get_supabase_admin()
    recipient = actor = None
    orig_post = httpx.AsyncClient.post
    httpx.AsyncClient.post = _fake_post  # Expo 왕복 차단
    try:
        step("0. 수신자(토큰 등록) + 발신자")
        recipient = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                           json={"email": f"png-r-{TS}@test.com", "password": "test1234",
                                 "email_confirm": True}).json()["id"]
        actor = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                       json={"email": f"png-a-{TS}@test.com", "password": "test1234",
                             "email_confirm": True}).json()["id"]
        # 프로필 행(설정 저장 전제) + 토큰
        for uid, nick in ((recipient, f"PNGR{TS}"), (actor, f"PNGA{TS}")):
            c.post(f"{_SB}/rest/v1/profiles", headers=_ADM, json={"user_id": uid, "nickname": nick})
        asyncio.run(push_service.register_token(recipient, f"ExponentPushToken[png{TS}]", "ios"))
        ok("수신자 프로필+토큰, 발신자 준비")

        def set_notif(**kw):
            # profiles.settings.notif 부분 갱신 (직접 REST)
            cur = c.get(f"{_SB}/rest/v1/profiles", headers=_ADM,
                        params={"user_id": f"eq.{recipient}", "select": "settings"}).json()[0]["settings"] or {}
            notif = {**cur.get("notif", {}), **kw}
            merged = {**cur, "notif": notif}
            c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM,
                    params={"user_id": f"eq.{recipient}"}, json={"settings": merged})

        def send(type_):
            _posts.clear()
            asyncio.run(push_service.send_for_notification(
                recipient, actor, type_, "tgt-id", "run", None))
            return len(_posts)

        step("1. 미설정 유저 — 기본 발송 (route_liked → 1 POST)")
        assert send("route_liked") == 1, "미설정=기본 발송"
        ok("미설정 유저 기본 발송")

        step("2. master OFF — 전체 스킵")
        set_notif(master=False)
        assert send("route_liked") == 0, "master OFF → 스킵"
        assert send("crew_announcement") == 0, "master OFF → 크루공지도 스킵"
        assert send("challenge_completed") == 0, "master OFF → 챌린지도 스킵"
        ok("master OFF 전 카테고리 스킵")

        step("3. 카테고리별 OFF — 해당만 스킵, 나머지 발송")
        set_notif(master=True, likes=False)
        assert send("route_liked") == 0, "likes OFF → route_liked 스킵"
        assert send("run_kudoed") == 0, "likes OFF → run_kudoed(같은 계열) 스킵"
        assert send("route_commented") == 1, "comments ON → 발송"
        assert send("user_followed") == 1, "followers ON → 발송"
        set_notif(likes=True, followers=False)
        assert send("user_followed") == 0, "followers OFF → user_followed 스킵"
        assert send("follow_requested") == 0, "followers OFF → 승인제 요청도 스킵(followers 계열)"
        assert send("follow_request_approved") == 0, "followers OFF → 승인 수락도 스킵"
        assert send("route_liked") == 1, "likes 복구 → 발송"
        set_notif(followers=True, crewJoin=False)
        assert send("crew_joined") == 0, "crewJoin OFF → crew_joined 스킵"
        assert send("join_requested") == 0 and send("join_approved") == 0, "crewJoin 계열 스킵"
        assert send("crew_announcement") == 1, "crewNotice ON → 발송"
        ok("카테고리별 OFF 해당 계열만 스킵")

        step("4. 인앱은 게이트 무관 — 항상 생성 (푸시만 master로 제어)")

        async def _create_and_settle(target_id):
            # fire-and-forget 푸시 태스크가 같은 루프에서 실행되도록 create 후 대기
            _posts.clear()
            await notification_service.create_notification(
                recipient, actor, "route_liked", target_id, "run")
            await asyncio.sleep(0.3)

        def inapp_rows(target_id):
            return c.get(f"{_SB}/rest/v1/notifications", headers=_ADM,
                         params={"user_id": f"eq.{recipient}", "type": "eq.route_liked",
                                 "target_id": f"eq.{target_id}", "select": "id"}).json()

        import uuid
        tgt_on, tgt_off = str(uuid.uuid4()), str(uuid.uuid4())  # notifications.target_id=uuid
        # positive control: master ON → 인앱 생성 + 푸시 발송(태스크가 실제 실행됨을 증명)
        set_notif(master=True, likes=True)
        asyncio.run(_create_and_settle(tgt_on))
        assert len(inapp_rows(tgt_on)) == 1, "인앱 생성(master ON)"
        assert len(_posts) == 1, f"master ON → 푸시 발송(태스크 실행 증명), got {len(_posts)}"

        # master OFF → 인앱은 여전히 생성, 푸시만 스킵
        set_notif(master=False)
        asyncio.run(_create_and_settle(tgt_off))
        assert len(inapp_rows(tgt_off)) == 1, "인앱은 master OFF여도 생성"
        assert len(_posts) == 0, f"master OFF → 푸시 스킵, got {len(_posts)}"
        ok("인앱 항상 생성 + 푸시만 master 게이트(ON 발송·OFF 스킵)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        httpx.AsyncClient.post = orig_post
        step("Cleanup")
        try:
            sb.table("push_tokens").delete().eq("user_id", recipient).execute()
            sb.table("notifications").delete().eq("user_id", recipient).execute()
        except Exception:  # noqa: BLE001
            pass
        for uid in (recipient, actor):
            if uid:
                c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run()
