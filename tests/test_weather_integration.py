"""
Integration test: weather proxy (GET /weather)
1) 순수 함수 (러닝지수·PM등급·캐시키) — 직접 import
2) mock OpenWeather 서버 + 별도 uvicorn(8001) — 파싱·캐시·에러 경로
3) 실제 OpenWeather 1회 (본 서버 8000) — 401이면 "키 활성화 대기" 스킵
Run: python tests/test_weather_integration.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

_SB = "https://jlmmqnpddkokyintlawd.supabase.co"

def _keys() -> tuple[str, str]:
    anon = svc = ""
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):             anon = line.split("=",1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=",1)[1]
    return anon, svc

_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}

def ok(m):   print(f"  ✓ {m}")
def warn(m): print(f"  ⚠ {m}")
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


# ═══ Phase 1: 순수 함수 ════════════════════════════════════════════════════════

def phase1():
    from app.core.config import settings
    from app.services import weather_service as ws

    step("1-1. 러닝지수 규칙")
    # 좋은 날: 체감 18°C 맑음 → 100 최고
    good = ws._running_index(18.0, 800, 2.0, 10.0, 25.0, 50)
    assert (good.score, good.label) == (100, "최고"), (good.score, good.label)
    assert good.comment == "뛰기 딱 좋은 날씨예요!"
    # 이상 구간 확장 확인: 22°C → 0 감점, 23°C → -10
    assert ws._running_index(22.0, 800, 2.0, 10.0, 25.0, 50).score == 100
    assert ws._running_index(23.0, 800, 2.0, 10.0, 25.0, 50).score == 90
    # 더운 날: 체감 30°C → -40
    hot = ws._running_index(30.0, 800, 2.0, 10.0, 25.0, 60)
    assert (hot.score, hot.label) == (60, "보통"), (hot.score, hot.label)
    assert "더워요" in hot.comment
    # 미세먼지 나쁨: PM2.5 60 → -25
    dust = ws._running_index(18.0, 800, 2.0, 60.0, 25.0, 50)
    assert (dust.score, dust.label) == (75, "좋음")
    assert "미세먼지" in dust.comment
    # 매우나쁨 PM10 200 → -50
    dust2 = ws._running_index(18.0, 800, 2.0, 10.0, 200.0, 50)
    assert dust2.score == 50 and "매우 나쁨" in dust2.comment
    # 비(501) -35 + 강풍(9) -15 → 50, 코멘트는 최대 감점(비)
    rainy = ws._running_index(18.0, 501, 9.0, 10.0, 25.0, 50)
    assert rainy.score == 50 and "비가 와요" in rainy.comment
    # 클램프: 뇌우 -60 + 무더위 33°C -60 + 매우나쁨 -50 → 0 비추천
    worst = ws._running_index(33.0, 211, 2.0, 80.0, 25.0, 50)
    assert (worst.score, worst.label) == (0, "비추천")
    # 습도 90% -10, 이슬비(300) -20
    assert ws._running_index(18.0, 800, 2.0, 10.0, 25.0, 90).score == 90
    assert ws._running_index(18.0, 300, 2.0, 10.0, 25.0, 50).score == 80
    ok("좋은날 100 ✓ 22°C 확장 ✓ 더위 60 ✓ 먼지 75/50 ✓ 비+바람 50 ✓ 클램프 0 ✓")

    step("1-2. PM 등급 (환경부 기준)")
    assert ws._pm_grade(15.0, ws._PM25_BOUNDS) == "좋음"
    assert ws._pm_grade(16.0, ws._PM25_BOUNDS) == "보통"
    assert ws._pm_grade(36.0, ws._PM25_BOUNDS) == "나쁨"
    assert ws._pm_grade(76.0, ws._PM25_BOUNDS) == "매우나쁨"
    assert ws._pm_grade(30.0, ws._PM10_BOUNDS) == "좋음"
    assert ws._pm_grade(81.0, ws._PM10_BOUNDS) == "나쁨"
    ok("PM2.5·PM10 경계값 ✓")

    step("1-2b. UV 등급 (기상청 단계)")
    for v, g in ((0.0, "낮음"), (2.0, "낮음"), (2.1, "보통"), (5.0, "보통"),
                 (5.1, "높음"), (7.0, "높음"), (7.1, "매우높음"), (10.0, "매우높음"),
                 (10.1, "위험")):
        assert ws._uv_grade(v) == g, (v, g, ws._uv_grade(v))
    ok("UV 5단계 경계값 ✓")

    step("1-3. 캐시 키 반올림 (~1.1km 격자)")
    assert ws._cache_key(37.5445, 127.0374) == ws._cache_key(37.5449, 127.0351)
    assert ws._cache_key(37.5445, 127.0374) != ws._cache_key(37.60, 127.0374)
    ok("같은 동네 공유 ✓ 다른 동네 분리 ✓")

    step("1-4. 키 미설정 → WeatherNotConfigured")
    orig = settings.openweather_api_key
    settings.openweather_api_key = ""
    try:
        try:
            asyncio.run(ws.get_weather(37.5, 127.0))
            fail("키 없이 호출이 성공하면 안 됨")
        except ws.WeatherNotConfigured:
            ok("WeatherNotConfigured ✓")
    finally:
        settings.openweather_api_key = orig

    # 요약용 예시 3개 출력
    print("\n  ── 러닝지수 예시 ──")
    for name, idx in [("좋은 날(18°C 맑음, PM좋음)", good),
                      ("더운 날(체감 30°C)", hot),
                      ("미세먼지 나쁨(PM2.5 60)", dust)]:
        print(f"  {name}: {idx.score}점 [{idx.label}] — {idx.comment}")


# ═══ Phase 2: mock 서버 ═══════════════════════════════════════════════════════

WEATHER_JSON = {
    "name": "성수동",
    "main": {"temp": 21.3, "feels_like": 20.8, "humidity": 55},
    "wind": {"speed": 2.1},
    "weather": [{"id": 800, "main": "Clear", "description": "맑음", "icon": "01d"}],
}
NIGHT_JSON = {**WEATHER_JSON,
              "weather": [{"id": 800, "main": "Clear", "description": "맑음", "icon": "01n"}]}
AIR_JSON = {"list": [{"components": {"pm2_5": 12.0, "pm10": 28.0}}]}
UVI_JSON = {"value": 6.23}


class MockOW(BaseHTTPRequestHandler):
    counts = {"weather": 0, "air": 0, "uv": 0}

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        lat = float(parse_qs(parsed.query).get("lat", ["0"])[0])
        if parsed.path == "/data/2.5/weather":
            MockOW.counts["weather"] += 1
            if lat == 11.0:
                self._send(401, {"cod": 401, "message": "Invalid API key"})
            elif lat == 14.0:
                self._send(200, NIGHT_JSON)
            else:
                self._send(200, WEATHER_JSON)
        elif parsed.path == "/data/2.5/air_pollution":
            MockOW.counts["air"] += 1
            if lat == 12.0:
                self._send(500, {"error": "boom"})
            else:
                self._send(200, AIR_JSON)
        elif parsed.path == "/data/2.5/uvi":
            MockOW.counts["uv"] += 1
            if lat == 13.0:
                self._send(500, {"error": "boom"})
            else:
                self._send(200, UVI_JSON)
        else:
            self._send(404, {})

    def log_message(self, *a):  # silence
        pass


def phase2(c, tok):
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

        def w(lat, lng, token=tok):
            return c.get(f"{B}/weather", params={"lat": lat, "lng": lng},
                         headers={"Authorization": f"Bearer {token}"})

        step("2-1. 정상 응답 파싱 + 러닝지수")
        r = w(37.5445, 127.0374)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["area"] == "성수동" and d["temp_c"] == 21.3
        assert d["feels_like_c"] == 20.8 and d["condition"] == "맑음"
        assert d["condition_code"] == 800 and d["humidity_pct"] == 55
        assert d["wind_ms"] == 2.1 and d["rain_1h_mm"] is None
        assert d["pm25"] == {"value": 12.0, "grade": "좋음"}
        assert d["pm10"] == {"value": 28.0, "grade": "좋음"}
        assert d["running_index"]["score"] == 100
        assert d["running_index"]["label"] == "최고"
        assert d["uv"] == {"value": 6.2, "grade": "높음"}, d.get("uv")
        assert d["is_day"] is True, "icon 01d → 낮"
        assert d["fetched_at"]
        ok("전체 필드 파싱 ✓ PM 등급 ✓ UV 6.2 높음 ✓ 러닝지수 100 ✓")

        step("2-2. 캐시: 같은 격자 재요청 → 외부 호출 없음")
        n0 = MockOW.counts["weather"]
        assert n0 == 1, f"첫 요청 후 외부 호출 1회여야 함, got {n0}"
        w(37.5445, 127.0374)                 # 완전 동일
        w(37.5449, 127.0351)                 # 같은 격자 (반올림 동일)
        assert MockOW.counts["weather"] == 1, "캐시 히트면 외부 호출이 늘면 안 됨"
        r = w(37.60, 127.0374)               # 다른 격자
        assert r.status_code == 200
        assert MockOW.counts["weather"] == 2, "다른 격자는 새로 호출"
        ok("동일·근접 좌표 캐시 공유 ✓ 다른 격자 분리 ✓")

        step("2-3. 인증 없음 → 401")
        r = c.get(f"{B}/weather", params={"lat": 37.5, "lng": 127.0})
        assert r.status_code == 401, f"인증 필수, got {r.status_code}"
        ok("무인증 401 ✓")

        step("2-4. OpenWeather 401 → 503 friendly (키 활성화 대기)")
        r = w(11.0, 127.0)
        assert r.status_code == 503, f"503이어야 함, got {r.status_code}"
        d = r.json()["detail"]
        assert d["error"] == "weather_key_inactive" and "활성화" in d["message"]
        assert "test-key" not in r.text, "응답에 키가 노출되면 안 됨"
        ok("503 weather_key_inactive ✓ 키 미노출 ✓")

        step("2-5. 미세먼지 API만 실패 → 200 + pm null")
        r = w(12.0, 127.0)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["pm25"] is None and d["pm10"] is None
        assert d["running_index"]["score"] == 100, "먼지 없이 지수 계산돼야 함"
        ok("부분 실패 격리 ✓ (200 + pm null + 지수 유지)")

        step("2-6. 자외선 API만 실패 → 200 + uv null (타일 숨김)")
        r = w(13.0, 127.0)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["uv"] is None and d["pm25"] is not None
        assert d["running_index"]["score"] == 100
        ok("uv만 null ✓ 나머지 정상 ✓")

        step("2-7. is_day — 밤 아이콘(01n) → false")
        r = w(14.0, 127.0)
        assert r.status_code == 200 and r.json()["is_day"] is False, r.json().get("is_day")
        ok("밤 케이스 false ✓ (낮은 2-1에서 검증)")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        httpd.shutdown()
        httpd.server_close()
        ok("mock 서버·uvicorn(8001) 정리 완료")


# ═══ Phase 3: 실제 OpenWeather 1회 ════════════════════════════════════════════

def phase3(c, tok):
    step("3. 실제 OpenWeather 호출 1회 (본 서버 8000)")
    r = c.get("http://localhost:8000/api/weather",
              params={"lat": 37.5445, "lng": 127.0374},
              headers={"Authorization": f"Bearer {tok}"}, timeout=20)
    if r.status_code == 200:
        d = r.json()
        assert isinstance(d["temp_c"], (int, float))
        assert 0 <= d["running_index"]["score"] <= 100
        assert d["running_index"]["comment"]
        # UV: deprecated 엔드포인트 실확인 — 끊기면 null(무해)이라 warn만
        if d.get("uv") is not None:
            assert d["uv"]["value"] >= 0 and d["uv"]["grade"] in (
                "낮음", "보통", "높음", "매우높음", "위험")
            uv_txt = f"UV {d['uv']['value']} [{d['uv']['grade']}]"
        else:
            warn("실호출 uv=null — /2.5/uvi 서비스 종료 가능성, 전환 검토 신호")
            uv_txt = "UV null"
        ok(f"실호출 200 ✓ {d.get('area')}: {d['temp_c']}°C, {uv_txt}, "
           f"지수 {d['running_index']['score']}점 [{d['running_index']['label']}]")
    elif r.status_code == 503 and r.json().get("detail", {}).get("error") == "weather_key_inactive":
        warn("키 활성화 대기 — 스킵 (활성화 후 이 테스트만 다시 돌리면 됨)")
    else:
        fail("실호출 예상 밖 응답", f"{r.status_code} {r.text[:200]}")


def run():
    ts = int(time.time()); pw = "TestPass123!"
    uid = None
    with httpx.Client(timeout=20) as c:
        try:
            phase1()

            step("공용: 테스트 유저 1명 생성")
            uid = sb_user(c, f"wt-u1-{ts}@t.l", pw)
            tok = sb_login(c, f"wt-u1-{ts}@t.l", pw)
            ok(f"u1={uid[:8]}…")

            phase2(c, tok)
            phase3(c, tok)

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)
        finally:
            step("Cleanup")
            if uid:
                sb_del_user(c, uid)
            ok("auth user 삭제")


if __name__ == "__main__":
    run()
