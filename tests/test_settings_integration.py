"""
Integration test: user settings (GET/PATCH /me/settings)
Run: python tests/test_settings_integration.py
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"

def _keys() -> tuple[str, str]:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):             anon = line.split("=",1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=",1)[1]
    return anon, svc

_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}

def ok(m):   print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")

def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200,201): fail("create user", r.text[:200])
    return r.json()["id"]

def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type":"application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]

def sb_del_user(c, uid): c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)

def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer":"return=minimal"},
             params={col: f"in.({',' .join(vals)})"})

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

DEFAULTS = {
    "run": {"auto_pause": True, "voice_cue": True, "haptics": True, "keep_screen_on": False},
    "units": "km", "theme": "light", "lang": "ko",
    "ai_course": {"terrain": "mixed", "default_distance_km": 5.0, "scenic": True,
                  "avoid_hills": False, "prefer_loop": True, "surface": "any"},
    "weather": {"avoid_dust": True, "dust_level_pm10": 80, "avoid_heat": True,
                "heat_temp_c": 28, "avoid_rain": False},
    "audio_coach": {"enabled": True, "voice": "joy", "rate": 1.0,
                    "cue_interval_km": 1.0, "announce_distance": True,
                    "announce_pace": True, "announce_calories": False},
    "feed": {"auto_publish": True, "allow_likes": True, "allow_comments": True},
    "notif": {"master": True, "crewChallenge": True, "crewNotice": True, "crewChat": True,
              "crewJoin": True, "likes": True, "comments": True, "followers": True,
              "runReminder": True, "weekly": True, "pb": True, "marketing": False},
}


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"st-u{i}-{ts}@t.l" for i in range(1,3)]
    uids: list[str] = []
    toks: list[str] = []

    with httpx.Client(timeout=20) as c:
        try:
            step("1. 유저 2명 (u1 프로필 O, u2 프로필 X)")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2 = uids; tok1, tok2 = toks
            assert api(c, "PATCH", "/me/profile", tok1,
                       json={"nickname": f"설정u1-{ts%100000}"}).status_code == 200
            ok("u1 프로필 생성, u2는 미생성")

            step("2. 미설정 유저 GET → 기본값 완전 객체")
            r = api(c, "GET", "/me/settings", tok1)
            assert r.status_code == 200 and r.json() == DEFAULTS, \
                f"기본값 표와 정확히 일치해야 함"
            ok("기본값 완전 객체 ✓ (run/units/theme/lang/ai_course/weather)")

            step("3. PATCH 한 키만 → deep merge (나머지 유지)")
            r = api(c, "PATCH", "/me/settings", tok1, json={"run": {"haptics": False}})
            assert r.status_code == 200, r.text[:300]
            d = r.json()
            assert d["run"]["haptics"] is False
            assert d["run"]["auto_pause"] is True, "같은 그룹의 다른 키 유지"
            assert d["units"] == "km" and d["theme"] == "light", "다른 그룹 유지"
            ok("haptics만 변경, 나머지 전부 유지 ✓")

            step("4. 그룹 2개 + theme/lang 동시 PATCH + 멱등")
            body = {"theme": "dark", "lang": "en", "units": "mi",
                    "weather": {"dust_level_pm10": 100},
                    "ai_course": {"terrain": "hill", "default_distance_km": 8.5}}
            d1 = api(c, "PATCH", "/me/settings", tok1, json=body).json()
            d2 = api(c, "PATCH", "/me/settings", tok1, json=body).json()  # 재PATCH
            assert d1 == d2, "멱등이어야 함"
            assert d1["theme"] == "dark" and d1["lang"] == "en" and d1["units"] == "mi"
            assert d1["weather"]["dust_level_pm10"] == 100
            assert d1["weather"]["avoid_dust"] is True, "weather 나머지 유지"
            assert d1["ai_course"]["terrain"] == "hill"
            assert d1["ai_course"]["default_distance_km"] == 8.5
            assert d1["run"]["haptics"] is False, "이전 PATCH 유지"
            r = api(c, "GET", "/me/settings", tok1)
            assert r.json() == d1, "GET도 동일"
            ok("다중 그룹 merge ✓ theme=dark·lang=en 유지 ✓ 멱등 ✓")

            step("5. 잘못된 키/값 → 422 + 저장 안 됨")
            bad_bodies = [
                {"theme": "system"},                      # 허용 외 값
                {"units": "yard"},
                {"weather": {"dust_level_pm10": 500}},    # 범위 밖
                {"ai_course": {"default_distance_km": 0.5}},
                {"run": {"hapitcs": True}},               # 오타 키 (extra forbid)
                {"volume": 10},                           # 미지 그룹
            ]
            for b in bad_bodies:
                r = api(c, "PATCH", "/me/settings", tok1, json=b)
                assert r.status_code == 422, f"{b} → 422여야 함, got {r.status_code}"
            assert api(c, "GET", "/me/settings", tok1).json() == d1, \
                "실패한 PATCH가 아무것도 저장하면 안 됨"
            ok("허용 외 값·범위 밖·오타 키·미지 그룹 전부 422 ✓ 저장 무변화 ✓")

            step("6. 유저 격리 + 프로필 미생성 유저")
            r = api(c, "GET", "/me/settings", tok2)
            assert r.status_code == 200 and r.json() == DEFAULTS, \
                "프로필 없어도 GET은 기본값"
            r = api(c, "PATCH", "/me/settings", tok2, json={"units": "mi"})
            assert r.status_code == 404, f"프로필 미생성 PATCH → 404, got {r.status_code}"
            assert api(c, "GET", "/me/settings", tok1).json()["units"] == "mi", \
                "u1 설정은 u2와 무관"
            ok("미생성 GET 기본값 ✓ PATCH 404 ✓ 격리 ✓")

            step("7. /me/profile 회귀 (settings 컬럼 추가 영향 없음)")
            r = api(c, "GET", "/me/profile", tok1)
            assert r.status_code == 200
            p = r.json()
            assert p["nickname"] == f"설정u1-{ts%100000}" and p["tier"] == "free"
            assert "settings" not in p, "프로필 응답에 settings가 새면 안 됨"
            r = api(c, "PATCH", "/me/profile", tok1,
                    json={"nickname": f"설정u1-{ts%100000}", "bio": "회귀"})
            assert r.status_code == 200
            assert api(c, "GET", "/me/settings", tok1).json()["units"] == "mi", \
                "프로필 upsert가 settings를 지우면 안 됨"
            ok("프로필 응답 정상 ✓ settings 미노출 ✓ upsert 후 설정 보존 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
