"""
Integration test: 설정 → 실동작 연결
1) 결정론 순수 함수 — effective-prefs 머지 6케이스, avoid_tags 충돌 필터,
   personalize_index (트리거·우선순위·캐시 원본 불변)
2) mock OpenWeather + 별도 uvicorn(8001) — A/B 유저 개인화 + 캐시 비오염
3) 실제 Gemini 2회 (본 서버 8000) — 설정 기반 생성 + body 덮어쓰기(회귀 겸용)
Run: python tests/test_settings_apply_integration.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
    anon = svc = ""
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                svc = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(m):
    print(f"  ✓ {m}")


def fail(m, d=""):
    print(f"  ✗ {m}" + (f": {d}" if d else ""))
    sys.exit(1)


def step(t):
    print(f"\n[{t}]")


def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201):
        fail("create user", r.text[:200])
    return r.json()["id"]


def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200:
        fail("login", r.text[:200])
    return r.json()["access_token"]


def sb_del_user(c, uid):
    c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)


def sb_del_in(c, table, col, vals):
    if not vals:
        return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})


# ═══ Phase 1: 결정론 순수 함수 ════════════════════════════════════════════════

def phase1():
    from app.models.schemas import (
        AiCourseSettings,
        Coordinate,
        PmReading,
        RouteRequest,
        RunningIndex,
        WeatherResponse,
        WeatherSettings,
    )
    from app.services import openai_service as oai
    from app.services import route_service as rs
    from app.services import weather_service as ws

    START = {"start": {"lat": 37.5445, "lng": 127.0374}}
    SAVED = AiCourseSettings(terrain="flat", default_distance_km=3.0, scenic=False,
                             avoid_hills=True, prefer_loop=False, surface="paved")

    step("1-1. effective-prefs 머지 (body > 설정 > 기본값)")
    # ① body 전부 지정 → 설정 완전 무시
    req = RouteRequest(**START, target_distance_km=7, terrain="hill", scenic=True,
                       avoid_hills=False, prefer_loop=True, surface="trail")
    km, p = rs._resolve_course_prefs(req, SAVED)
    assert km == 7 and (p.terrain, p.scenic, p.avoid_hills, p.prefer_loop, p.surface) == \
        ("hill", True, False, True, "trail"), p
    # ② body 비움 → 설정값 전부 주입 + 거리 폴백
    km, p = rs._resolve_course_prefs(RouteRequest(**START), SAVED)
    assert km == 3.0 and (p.terrain, p.scenic, p.avoid_hills, p.prefer_loop, p.surface) == \
        ("flat", False, True, False, "paved"), p
    # ③ 부분 지정 (terrain만 body) → 필드별 독립 머지
    km, p = rs._resolve_course_prefs(RouteRequest(**START, terrain="mixed"), SAVED)
    assert p.terrain == "mixed" and p.surface == "paved" and p.avoid_hills is True
    # ④ 서버 기본값 (설정 없는 유저 = AiCourseSettings())
    km, p = rs._resolve_course_prefs(RouteRequest(**START), AiCourseSettings())
    assert km == 5.0 and p.terrain == "mixed" and p.scenic is True and p.prefer_loop is True
    # ⑤ 모순: avoid_hills=True + terrain='hill' → avoid_hills 승 (terrain=mixed)
    km, p = rs._resolve_course_prefs(
        RouteRequest(**START, terrain="hill", avoid_hills=True), SAVED)
    assert p.terrain == "mixed" and p.avoid_hills is True
    # ⑥ body false로 설정 덮어쓰기 (None과 구분되는지)
    km, p = rs._resolve_course_prefs(
        RouteRequest(**START, scenic=False, avoid_hills=False),
        AiCourseSettings(scenic=True, avoid_hills=True))
    assert p.scenic is False and p.avoid_hills is False
    ok("전부지정 ✓ 폴백 ✓ 부분머지 ✓ 서버기본 ✓ 모순해소 ✓ false 덮어쓰기 ✓")

    step("1-2. avoid_tags 충돌 필터 (명시 선호 > 커뮤니티 힌트)")
    tags = ["오르막많음", "노면나쁨", "사람많음"]
    kept = rs._filter_conflicting_avoid_tags(
        tags, AiCourseSettings(terrain="hill", surface="trail"))
    assert kept == ["사람많음"], kept
    kept = rs._filter_conflicting_avoid_tags(tags, AiCourseSettings(terrain="hill"))
    assert kept == ["노면나쁨", "사람많음"], kept
    kept = rs._filter_conflicting_avoid_tags(tags, AiCourseSettings())
    assert kept == tags, kept
    ok("hill→오르막 제거 ✓ trail→노면 제거 ✓ 기본은 유지 ✓")

    step("1-3. 프롬프트 주입 (_prefs_text / end_text)")
    start = Coordinate(lat=37.5445, lng=127.0374)
    t = oai._prefs_text(AiCourseSettings(terrain="flat", scenic=True, surface="paved"))
    assert "prefer flat terrain" in t and "scenic" in t and "well-paved" in t
    t = oai._prefs_text(AiCourseSettings(terrain="hill", scenic=False))
    assert "uphill" in t and "scenic" not in t
    # 모순 방어 2중화: prefs에 hill+avoid_hills가 그대로 와도 hill 문구 생략
    t = oai._prefs_text(AiCourseSettings(terrain="hill", avoid_hills=True))
    assert "uphill" not in t and "avoid steep hills" in t
    assert oai._prefs_text(AiCourseSettings(terrain="mixed", scenic=False)) == ""
    assert oai._prefs_text(None) == ""
    # prefer_loop 분기
    pr = oai._build_prompt(5, start, None, None, None,
                           prefs=AiCourseSettings(prefer_loop=False, scenic=False))
    assert "out-and-back" in pr and "loop route)" not in pr
    pr = oai._build_prompt(5, start, None, None, None,
                           prefs=AiCourseSettings(prefer_loop=True, scenic=False))
    assert "a loop route" in pr
    end = Coordinate(lat=37.55, lng=127.04)
    pr = oai._build_prompt(5, start, end, None, None,
                           prefs=AiCourseSettings(prefer_loop=False, scenic=False))
    assert "end at (37.55, 127.04)" in pr and "out-and-back" not in pr
    # 기존 문단(notes/avoid)과 공존
    pr = oai._build_prompt(5, start, None, None, "한강 근처",
                           avoid_tags=["사람많음"],
                           prefs=AiCourseSettings(terrain="flat", scenic=False))
    assert "prefer flat terrain" in pr and "한강 근처" in pr and "quieter" in pr
    ok("prefs 문구 ✓ 모순 방어 ✓ loop 분기 3종 ✓ notes·avoid 공존 ✓")

    step("1-4. personalize_index — 트리거·우선순위")

    def mk_weather(temp=20.0, pm10=None, code=800, rain=None):
        return WeatherResponse(
            area="성수동", temp_c=temp, feels_like_c=temp, condition="맑음",
            condition_code=code, humidity_pct=50, wind_ms=2.0, rain_1h_mm=rain,
            pm25=None,
            pm10=PmReading(value=pm10, grade="보통") if pm10 is not None else None,
            running_index=RunningIndex(score=80, label="좋음", comment="기본 코멘트"),
            fetched_at="2026-07-05T00:00:00+00:00",
        )

    # 미세먼지 트리거
    out = ws.personalize_index(mk_weather(pm10=70.0),
                               WeatherSettings(dust_level_pm10=50))
    assert out.running_index.personalized is True
    assert "PM10 50" in out.running_index.comment
    assert (out.running_index.score, out.running_index.label) == (80, "좋음"), "점수는 공용 유지"
    # 더위 트리거 (기준 이상, 경계 포함)
    out = ws.personalize_index(mk_weather(temp=28.0), WeatherSettings(heat_temp_c=28))
    assert out.running_index.personalized and "28°C" in out.running_index.comment
    # 비 트리거 — 강수 코드 / rain_1h_mm 각각
    wset_rain = WeatherSettings(avoid_dust=False, avoid_heat=False, avoid_rain=True)
    out = ws.personalize_index(mk_weather(code=501), wset_rain)
    assert out.running_index.personalized and "비 회피" in out.running_index.comment
    out = ws.personalize_index(mk_weather(code=800, rain=0.5), wset_rain)
    assert out.running_index.personalized and "비 회피" in out.running_index.comment
    # 우선순위: 먼지 > 더위 > 비 (전부 트리거 → 먼지 코멘트)
    all_bad = mk_weather(temp=35.0, pm10=100.0, code=501)
    out = ws.personalize_index(
        all_bad, WeatherSettings(dust_level_pm10=50, heat_temp_c=25, avoid_rain=True))
    assert "미세먼지" in out.running_index.comment
    # 먼지 미트리거 시 더위 > 비
    out = ws.personalize_index(
        mk_weather(temp=35.0, pm10=30.0, code=501),
        WeatherSettings(dust_level_pm10=50, heat_temp_c=25, avoid_rain=True))
    assert "더위 기준" in out.running_index.comment
    # 토글 꺼짐 / 기준 미달 / pm10 없음 → 원본 그대로 (같은 객체)
    w = mk_weather(temp=35.0, pm10=100.0, code=501)
    assert ws.personalize_index(
        w, WeatherSettings(avoid_dust=False, avoid_heat=False, avoid_rain=False)) is w
    w = mk_weather(temp=20.0, pm10=40.0)
    assert ws.personalize_index(w, WeatherSettings()) is w
    w = mk_weather(pm10=None, temp=20.0)
    assert ws.personalize_index(w, WeatherSettings(dust_level_pm10=30)) is w
    ok("먼지·더위(경계)·비(코드/강수량) ✓ 우선순위 ✓ 미트리거 원본 반환 ✓")

    step("1-5. 캐시 원본 불변 (핵심 안전망)")
    original = mk_weather(temp=30.0, pm10=90.0)
    key = ws._cache_key(35.001, 128.001)  # 실제 캐시에 넣고 확인
    ws._cache_put(key, original)
    out = ws.personalize_index(original, WeatherSettings(dust_level_pm10=50))
    assert out is not original and out.running_index is not original.running_index
    cached = ws._cache_get(key)
    assert cached is original, "캐시는 원본 객체를 그대로 보관"
    assert cached.running_index.comment == "기본 코멘트"
    assert cached.running_index.personalized is False
    ws._cache.pop(key, None)
    ok("deep copy ✓ 캐시 안 comment/personalized 불변 ✓")


# ═══ Phase 2: mock OpenWeather — A/B 유저 개인화 + 캐시 비오염 ═══════════════════

# temp 26 → 감점 25(더위 주의), PM10 70 → 보통 -5 ⇒ 공용 점수 70 [좋음]
# 기본 설정(B): dust 80·heat 28 → 미트리거. A(dust 50): 70≥50 → 개인화.
WEATHER_JSON = {
    "name": "성수동",
    "main": {"temp": 26.0, "feels_like": 26.0, "humidity": 50},
    "wind": {"speed": 2.0},
    "weather": [{"id": 800, "main": "Clear", "description": "맑음"}],
}
AIR_JSON = {"list": [{"components": {"pm2_5": 10.0, "pm10": 70.0}}]}


class MockOW(BaseHTTPRequestHandler):
    counts = {"weather": 0}

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/data/2.5/weather":
            MockOW.counts["weather"] += 1
            self._send(200, WEATHER_JSON)
        elif path == "/data/2.5/air_pollution":
            self._send(200, AIR_JSON)
        else:
            self._send(404, {})

    def log_message(self, *a):
        pass


def phase2(c, tok_a, tok_b):
    httpd = HTTPServer(("127.0.0.1", 0), MockOW)
    mock_port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    env = {**os.environ,
           "OPENWEATHER_BASE_URL": f"http://127.0.0.1:{mock_port}",
           "OPENWEATHER_API_KEY": "test-key-not-real"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--port", "8001", "--log-level", "warning"],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    B = "http://localhost:8001/api"
    try:
        for _ in range(30):
            try:
                if httpx.get("http://localhost:8001/docs", timeout=2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            fail("mock용 uvicorn(8001) 기동 실패")

        def w(token):
            return c.get(f"{B}/weather", params={"lat": 37.61, "lng": 127.03},
                         headers={"Authorization": f"Bearer {token}"})

        step("2-1. A 유저: 개인 기준(dust 50) 설정")
        r = c.patch(f"{B}/me/settings", headers={"Authorization": f"Bearer {tok_a}"},
                    json={"weather": {"dust_level_pm10": 50}})
        assert r.status_code == 200, r.text[:300]
        assert r.json()["weather"]["dust_level_pm10"] == 50
        ok("PATCH /me/settings 200 ✓")

        step("2-2. A(개인화) → B(기본) 순서로 호출: 캐시 공유 + 코멘트 분리")
        ra = w(tok_a)
        assert ra.status_code == 200, ra.text[:300]
        da = ra.json()
        assert da["running_index"]["personalized"] is True
        assert "PM10 50" in da["running_index"]["comment"], da["running_index"]
        assert da["running_index"]["score"] == 70 and da["running_index"]["label"] == "좋음"

        rb = w(tok_b)
        db = rb.json()
        assert db["running_index"]["personalized"] is False, "A의 개인화가 캐시를 오염시킴!"
        assert db["running_index"]["comment"] == "더위 주의 — 페이스를 늦추고 수분을 챙기세요", \
            db["running_index"]
        assert db["running_index"]["score"] == 70, "점수는 공용 기준으로 동일해야 함"
        ok("A 개인 코멘트 ✓ B 기본 코멘트 ✓ 점수 공용 70 동일 ✓")

        step("2-3. 캐시: 외부 호출 1회 유지 + 재호출에도 오염 없음")
        assert MockOW.counts["weather"] == 1, \
            f"두 유저가 같은 격자면 외부 호출 1회여야 함, got {MockOW.counts['weather']}"
        da2 = w(tok_a).json()
        db2 = w(tok_b).json()
        assert da2["running_index"]["personalized"] is True
        assert db2["running_index"]["personalized"] is False
        assert MockOW.counts["weather"] == 1, "재호출은 캐시 히트여야 함"
        ok("외부 호출 1회 ✓ 재호출 A/B 코멘트 유지 ✓ (캐시 원본 비오염)")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        httpd.shutdown()
        httpd.server_close()
        ok("mock 서버·uvicorn(8001) 정리 완료")


# ═══ Phase 3: 실제 Gemini 2회 (본 서버 8000) ═════════════════════════════════════

def phase3(c, tok):
    def api(method, path, **kw):
        return c.request(method, f"{BASE}{path}",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=90, **kw)

    step("3-1. 설정 기반 생성 — body에 거리·선호 없이 (설정 3km/flat/paved 폴백)")
    r = api("PATCH", "/me/settings", json={"ai_course": {
        "terrain": "flat", "surface": "paved", "scenic": True,
        "default_distance_km": 3.0}})
    assert r.status_code == 200, r.text[:300]
    r = api("POST", "/routes/generate",
            json={"start": {"lat": 37.5445, "lng": 127.0374}})
    assert r.status_code == 200, r.text[:400]
    d1 = r.json()
    assert d1["summary"] and len(d1["waypoints"]) >= 2
    assert 1.0 <= d1["total_distance_km"] <= 6.0, \
        f"설정 3km 기준인데 {d1['total_distance_km']}km"
    ok(f"200 ✓ {d1['total_distance_km']}km / waypoint {len(d1['waypoints'])}개 — {d1['summary'][:40]}…")

    step("3-2. body 덮어쓰기 (7km 명시, 레거시 전체 body — 회귀 겸용)")
    r = api("POST", "/routes/generate", json={
        "start": {"lat": 37.5445, "lng": 127.0374},
        "target_distance_km": 7, "notes": "한강 근처"})
    assert r.status_code == 200, r.text[:400]
    d2 = r.json()
    assert d2["summary"] and len(d2["waypoints"]) >= 2
    assert 3.5 <= d2["total_distance_km"] <= 11.0, \
        f"body 7km 기준인데 {d2['total_distance_km']}km"
    ok(f"200 ✓ {d2['total_distance_km']}km — body가 설정(3km)을 덮어씀")

    step("3-3. 저장된 target_distance_km = 최종 유효값 확인")
    r = api("GET", "/routes", params={"limit": 2})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    saved = sorted(row["target_distance_km"] for row in rows)
    assert saved == [3.0, 7.0], f"설정 폴백 3.0 + body 7.0이 저장돼야 함, got {saved}"
    ok("routes.target_distance_km = [3.0(설정 폴백), 7.0(body)] ✓")


def run():
    ts = int(time.time())
    pw = "TestPass123!"
    emails = [f"sa-u{i}-{ts}@t.l" for i in range(1, 4)]  # A(개인화), B(기본), G(Gemini)
    uids: list[str] = []
    with httpx.Client(timeout=30) as c:
        try:
            phase1()

            step("공용: 테스트 유저 3명 생성 (A/B 날씨, G 코스)")
            toks = []
            for i, e in enumerate(emails):
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
                r = c.patch(f"{BASE}/me/profile",
                            headers={"Authorization": f"Bearer {toks[-1]}"},
                            json={"nickname": f"적용u{i+1}-{ts % 100000}"})
                assert r.status_code == 200, r.text[:200]
            ok("유저 3명 + 프로필 생성")

            phase2(c, toks[0], toks[1])
            phase3(c, toks[2])

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            sb_del_in(c, "route_generations", "user_id", uids)
            sb_del_in(c, "routes", "user_id", uids)
            sb_del_in(c, "profiles", "user_id", uids)
            for uid in uids:
                sb_del_user(c, uid)
            ok(f"routes·quota·profiles·auth user {len(uids)}명 삭제")


if __name__ == "__main__":
    run()
