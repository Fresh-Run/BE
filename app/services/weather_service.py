"""Weather proxy: OpenWeather current weather + air pollution + running index.

- Rule-based running index (no LLM call — free and instant).
- In-memory cache keyed by a ~1.1km grid (lat/lng rounded to 2 decimals),
  TTL 10 minutes, so nearby users share entries and the free-tier rate
  limit (60/min) is protected.
- The API key never appears in logs, errors, or responses.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.models.schemas import PmReading, RunningIndex, WeatherResponse

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)

# ── errors ────────────────────────────────────────────────────────────────────


class WeatherNotConfigured(Exception):
    """OPENWEATHER_API_KEY is not set."""


class WeatherKeyInactive(Exception):
    """OpenWeather returned 401 (fresh keys take up to a few hours to activate)."""


class WeatherUnavailable(Exception):
    """OpenWeather is down/unreachable (timeouts, 5xx, network errors)."""


# ── cache ─────────────────────────────────────────────────────────────────────

_CACHE_TTL_SEC = 600.0  # 10 minutes
_CACHE_MAX = 1000
# {(lat2, lng2): (expires_at_monotonic, response)}
_cache: dict[tuple[float, float], tuple[float, WeatherResponse]] = {}


def _cache_key(lat: float, lng: float) -> tuple[float, float]:
    """~1.1km grid: users in the same neighbourhood share one entry."""
    return (round(lat, 2), round(lng, 2))


def _cache_get(key: tuple[float, float]) -> WeatherResponse | None:
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    return None


def _cache_put(key: tuple[float, float], value: WeatherResponse) -> None:
    # Lazy cleanup on insert; hard cap protects memory. A concurrent miss on
    # the same key may fetch twice (no lock) — rare and harmless.
    now = time.monotonic()
    if len(_cache) >= _CACHE_MAX:
        for k in [k for k, (exp, _) in _cache.items() if exp <= now]:
            _cache.pop(k, None)
        while len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
    _cache[key] = (now + _CACHE_TTL_SEC, value)


# ── 환경부 PM grades ──────────────────────────────────────────────────────────

_PM25_BOUNDS = (15.0, 35.0, 75.0)   # 좋음 / 보통 / 나쁨 upper bounds
_PM10_BOUNDS = (30.0, 80.0, 150.0)
_GRADE_ORDER = ["좋음", "보통", "나쁨", "매우나쁨"]


def _pm_grade(value: float, bounds: tuple[float, float, float]) -> str:
    good, normal, bad = bounds
    if value <= good:
        return "좋음"
    if value <= normal:
        return "보통"
    if value <= bad:
        return "나쁨"
    return "매우나쁨"


# ── running index (rule-based) ────────────────────────────────────────────────


def _temp_deduction(feels_like_c: float) -> tuple[int, str]:
    f = feels_like_c
    if f > 32:
        return 60, "무더위예요 — 오늘은 실내 러닝을 추천해요"
    if f > 28:
        return 40, "많이 더워요 — 한낮을 피해 아침·저녁에 뛰세요"
    if f > 24:
        return 25, "더위 주의 — 페이스를 늦추고 수분을 챙기세요"
    if f > 22:
        return 10, "살짝 더울 수 있어요 — 가볍게 뛰기 좋아요"
    if f >= 5:
        return 0, ""  # 이상적 구간 (5~22°C)
    if f >= 0:
        return 5, "조금 쌀쌀해요 — 워밍업을 충분히 하세요"
    if f >= -5:
        return 20, "추워요 — 보온에 신경 쓰고 워밍업을 길게 하세요"
    return 35, "강추위예요 — 오늘은 실내 러닝을 추천해요"


def _condition_deduction(code: int) -> tuple[int, str]:
    if 200 <= code < 300:
        return 60, "뇌우가 있어요 — 야외 러닝은 피하세요"
    if 300 <= code < 400 or code == 500:
        return 20, "가벼운 비가 와요 — 미끄럼에 주의하세요"
    if 500 < code < 600:
        return 35, "비가 와요 — 실내 러닝을 추천해요"
    if 600 <= code < 700:
        return 35, "눈이 와요 — 미끄럼 주의, 실내 러닝도 좋아요"
    if 700 <= code < 800:
        return 10, "시야가 흐려요 — 밝은 옷을 입고 뛰세요"
    return 0, ""  # 800(맑음)·80x(구름)


def _wind_deduction(wind_ms: float) -> tuple[int, str]:
    if wind_ms >= 12:
        return 30, "바람이 매우 강해요 — 실내 러닝을 추천해요"
    if wind_ms >= 8:
        return 15, "바람이 강해요 — 맞바람 구간을 짧게 잡으세요"
    return 0, ""


def _dust_deduction(pm25: float | None, pm10: float | None) -> tuple[int, str]:
    grades = []
    if pm25 is not None:
        grades.append(_pm_grade(pm25, _PM25_BOUNDS))
    if pm10 is not None:
        grades.append(_pm_grade(pm10, _PM10_BOUNDS))
    if not grades:
        return 0, ""
    worst = max(grades, key=_GRADE_ORDER.index)
    if worst == "매우나쁨":
        return 50, "미세먼지 매우 나쁨 — 야외 러닝은 피하세요"
    if worst == "나쁨":
        return 25, "미세먼지가 나빠요 — 실내 러닝을 추천해요"
    if worst == "보통":
        return 5, "미세먼지 보통 — 민감하다면 마스크를 챙기세요"
    return 0, ""


def _humidity_deduction(humidity_pct: int) -> tuple[int, str]:
    if humidity_pct >= 85:
        return 10, "습도가 높아요 — 페이스를 평소보다 늦추세요"
    return 0, ""


def _label(score: int) -> str:
    if score >= 90:
        return "최고"
    if score >= 70:
        return "좋음"
    if score >= 50:
        return "보통"
    if score >= 30:
        return "주의"
    return "비추천"


def _running_index(
    feels_like_c: float,
    condition_code: int,
    wind_ms: float,
    pm25: float | None,
    pm10: float | None,
    humidity_pct: int,
) -> RunningIndex:
    """0~100 score, 100 minus rule-based deductions; comment = worst factor."""
    deductions = [
        _temp_deduction(feels_like_c),
        _condition_deduction(condition_code),
        _wind_deduction(wind_ms),
        _dust_deduction(pm25, pm10),
        _humidity_deduction(humidity_pct),
    ]
    score = max(0, min(100, 100 - sum(d for d, _ in deductions)))
    worst = max(deductions, key=lambda d: d[0])
    comment = worst[1] if worst[0] > 0 else "뛰기 딱 좋은 날씨예요!"
    return RunningIndex(score=score, label=_label(score), comment=comment)


# ── OpenWeather fetch ─────────────────────────────────────────────────────────


async def _fetch_current(
    client: httpx.AsyncClient, lat: float, lng: float, key: str
) -> dict:
    """Current weather; raises the friendly errors. Never leaks the key."""
    try:
        res = await client.get(
            f"{settings.openweather_base_url}/data/2.5/weather",
            params={"lat": lat, "lon": lng, "appid": key,
                    "units": "metric", "lang": "kr"},
        )
    except httpx.HTTPError:
        logger.warning("OpenWeather current-weather 호출 실패 (network)")
        raise WeatherUnavailable()
    if res.status_code == 401:
        raise WeatherKeyInactive()
    if res.status_code != 200:
        logger.warning("OpenWeather current-weather 응답 %s", res.status_code)
        raise WeatherUnavailable()
    return res.json()


async def _fetch_air(
    client: httpx.AsyncClient, lat: float, lng: float, key: str
) -> dict | None:
    """Air pollution components; best-effort — any failure returns None."""
    try:
        res = await client.get(
            f"{settings.openweather_base_url}/data/2.5/air_pollution",
            params={"lat": lat, "lon": lng, "appid": key},
        )
        if res.status_code != 200:
            return None
        return res.json()["list"][0]["components"]
    except Exception:  # noqa: BLE001 — partial failure must not break weather
        logger.warning("OpenWeather air-pollution 호출 실패 (미세먼지 없이 응답)")
        return None


async def get_weather(lat: float, lng: float) -> WeatherResponse:
    """Weather + PM + running index for (lat, lng), cached ~10min per grid cell."""
    if not settings.openweather_api_key:
        raise WeatherNotConfigured()

    key = _cache_key(lat, lng)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    api_key = settings.openweather_api_key
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        current, air = await asyncio.gather(
            _fetch_current(client, lat, lng, api_key),
            _fetch_air(client, lat, lng, api_key),
        )

    main = current.get("main", {})
    weather0 = (current.get("weather") or [{}])[0]
    pm25_v = air.get("pm2_5") if air else None
    pm10_v = air.get("pm10") if air else None
    feels = float(main.get("feels_like", main.get("temp", 15.0)))
    code = int(weather0.get("id", 800))
    wind = float(current.get("wind", {}).get("speed", 0.0))
    humidity = int(main.get("humidity", 50))

    response = WeatherResponse(
        area=current.get("name") or None,
        temp_c=float(main.get("temp", 0.0)),
        feels_like_c=feels,
        condition=weather0.get("description", ""),
        condition_code=code,
        humidity_pct=humidity,
        wind_ms=wind,
        rain_1h_mm=current.get("rain", {}).get("1h"),
        pm25=PmReading(value=pm25_v, grade=_pm_grade(pm25_v, _PM25_BOUNDS))
        if pm25_v is not None else None,
        pm10=PmReading(value=pm10_v, grade=_pm_grade(pm10_v, _PM10_BOUNDS))
        if pm10_v is not None else None,
        running_index=_running_index(feels, code, wind, pm25_v, pm10_v, humidity),
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    _cache_put(key, response)
    return response
