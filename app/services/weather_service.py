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
import urllib.parse

from app.core.config import settings
from app.models.schemas import (
    PmReading,
    RunningIndex,
    UvReading,
    WeatherResponse,
    WeatherSettings,
)

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)

# ── OpenWeather 일일 콜 카운터 (T-map 동형, 2026-08-06 — One Call 전환 대비) ──
# KST 일 단위, 임계(기본 800 = cap 1,000의 80%) 초과 시 WARNING 1회+100콜마다.
# 차단 없음(관측 additive). atexit에 프로세스 합계 1줄.
_daily_ow = {"day": None, "n": 0, "warned_at": 0}
_process_ow_total = {"n": 0}


def ow_process_total() -> int:
    return _process_ow_total["n"]


def _ow_tick() -> None:
    from datetime import datetime, timedelta, timezone as _tz
    _process_ow_total["n"] += 1
    day = datetime.now(_tz(timedelta(hours=9))).date().isoformat()
    if _daily_ow["day"] != day:
        _daily_ow.update(day=day, n=0, warned_at=0)
    _daily_ow["n"] += 1
    thr = settings.openweather_daily_warn_calls
    if not thr or _daily_ow["n"] < thr:
        return
    if (_daily_ow["warned_at"] == 0
            or _daily_ow["n"] - _daily_ow["warned_at"] >= 100):
        _daily_ow["warned_at"] = _daily_ow["n"]
        logger.warning("OpenWeather 일일 콜 %d — 소프트 임계 %d 초과(KST %s, "
                       "One Call cap 1,000 대비). 차단 아님.",
                       _daily_ow["n"], thr, day)


def _log_ow_total() -> None:
    if _process_ow_total["n"]:
        logger.info("OpenWeather HTTP 시도 프로세스 합계: %d콜", _process_ow_total["n"])


import atexit as _atexit

_atexit.register(_log_ow_total)

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
# {(lat2, lng2): (expires_at_monotonic, response, (sunrise, sunset) epoch|None)}
# sun은 UV 야간 0 처리(AIR_QUALITY_SOURCE_DESIGN §3 ⓐ)의 응답 시점 판정용 —
# 와이어 비노출(응답 스키마 불변).
_cache: dict[tuple[float, float],
             tuple[float, WeatherResponse, tuple[float, float] | None]] = {}


def _cache_key(lat: float, lng: float) -> tuple[float, float]:
    """~1.1km grid: users in the same neighbourhood share one entry."""
    return (round(lat, 2), round(lng, 2))


def _cache_get(
    key: tuple[float, float],
) -> tuple[WeatherResponse, tuple[float, float] | None] | None:
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1], hit[2]
    return None


def _cache_put(key: tuple[float, float], value: WeatherResponse,
               sun: tuple[float, float] | None = None) -> None:
    # Lazy cleanup on insert; hard cap protects memory. A concurrent miss on
    # the same key may fetch twice (no lock) — rare and harmless.
    now = time.monotonic()
    if len(_cache) >= _CACHE_MAX:
        for k in [k for k, (exp, *_r) in _cache.items() if exp <= now]:
            _cache.pop(k, None)
        while len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
    _cache[key] = (now + _CACHE_TTL_SEC, value, sun)


# ── 환경부 PM grades ──────────────────────────────────────────────────────────

_PM25_BOUNDS = (15.0, 35.0, 75.0)   # 좋음 / 보통 / 나쁨 upper bounds
_PM10_BOUNDS = (30.0, 80.0, 150.0)
_GRADE_ORDER = ["좋음", "보통", "나쁨", "매우나쁨"]

_UV_BOUNDS = (2.0, 5.0, 7.0, 10.0)  # 기상청 단계: 낮음/보통/높음/매우높음 upper bounds


def _uv_grade(value: float) -> str:
    low, moderate, high, very_high = _UV_BOUNDS
    if value <= low:
        return "낮음"
    if value <= moderate:
        return "보통"
    if value <= high:
        return "높음"
    if value <= very_high:
        return "매우높음"
    return "위험"


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
        return 35, "무더위예요 — 오늘은 실내 러닝을 추천해요"
    if f > 28:
        return 20, "많이 더워요 — 한낮을 피해 아침·저녁에 뛰세요"
    if f > 24:
        return 10, "더위 주의 — 페이스를 늦추고 수분을 챙기세요"
    if f > 22:
        return 5, "살짝 더울 수 있어요 — 가볍게 뛰기 좋아요"
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
        return 35, "미세먼지 매우 나쁨 — 야외 러닝은 피하세요"
    if worst == "나쁨":
        return 15, "미세먼지가 나빠요 — 실내 러닝을 추천해요"
    if worst == "보통":
        return 0, "미세먼지 보통 — 민감하다면 마스크를 챙기세요"
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


# ── i18n (캐시 밖 조립, 2026-07-29 Ivan) ─────────────────────────────────────
# 캐시는 공용 원데이터(ko 텍스트+condition_code)만 저장 — en 텍스트는 응답 시점에
# deep copy로 조립(07/05 공유 캐시 오염 전례와 같은 축: 캐시 원본 무수정·키 무변).
# comment는 deduction 고정 문구 전수의 exact-match 사전(미스면 ko 유지 — fail-open),
# condition은 OpenWeather lang=kr description 대신 condition_code 자체 매핑(콜 증가 0).

_COMMENT_EN: dict[str, str] = {
    "무더위예요 — 오늘은 실내 러닝을 추천해요": "Extreme heat — indoor running recommended today",
    "많이 더워요 — 한낮을 피해 아침·저녁에 뛰세요": "Very hot — run in the morning or evening, not midday",
    "더위 주의 — 페이스를 늦추고 수분을 챙기세요": "Heat caution — slow your pace and stay hydrated",
    "살짝 더울 수 있어요 — 가볍게 뛰기 좋아요": "Slightly warm — good for an easy run",
    "조금 쌀쌀해요 — 워밍업을 충분히 하세요": "A bit chilly — warm up thoroughly",
    "추워요 — 보온에 신경 쓰고 워밍업을 길게 하세요": "Cold — layer up and take a longer warm-up",
    "강추위예요 — 오늘은 실내 러닝을 추천해요": "Freezing — indoor running recommended today",
    "뇌우가 있어요 — 야외 러닝은 피하세요": "Thunderstorms — avoid running outdoors",
    "가벼운 비가 와요 — 미끄럼에 주의하세요": "Light rain — watch for slippery spots",
    "비가 와요 — 실내 러닝을 추천해요": "Rainy — indoor running recommended",
    "눈이 와요 — 미끄럼 주의, 실내 러닝도 좋아요": "Snowy — watch your footing, indoor running works too",
    "시야가 흐려요 — 밝은 옷을 입고 뛰세요": "Low visibility — wear bright clothing",
    "바람이 매우 강해요 — 실내 러닝을 추천해요": "Very strong wind — indoor running recommended",
    "바람이 강해요 — 맞바람 구간을 짧게 잡으세요": "Strong wind — keep headwind stretches short",
    "미세먼지 매우 나쁨 — 야외 러닝은 피하세요": "Air quality very poor — avoid running outdoors",
    "미세먼지가 나빠요 — 실내 러닝을 추천해요": "Poor air quality — indoor running recommended",
    "미세먼지 보통 — 민감하다면 마스크를 챙기세요": "Moderate air quality — bring a mask if sensitive",
    "습도가 높아요 — 페이스를 평소보다 늦추세요": "High humidity — run slower than usual",
    "뛰기 딱 좋은 날씨예요!": "Perfect running weather!",
}


def _condition_en(code: int) -> str:
    if 200 <= code < 300:
        return "Thunderstorm"
    if 300 <= code < 400:
        return "Drizzle"
    if code == 500:
        return "Light rain"
    if 500 < code < 600:
        return "Rain"
    if 600 <= code < 700:
        return "Snow"
    if 700 <= code < 800:
        return "Hazy"
    if code == 800:
        return "Clear"
    if code in (801, 802):
        return "Partly cloudy"
    return "Cloudy"  # 803·804·미지 코드


_LABEL_EN: dict[str, str] = {   # 러닝지수 등급 라벨 5종 (_label 전수, 2026-07-29 Ivan)
    # 2026-08-06 en 3종 축약(Ivan — 375pt 칩 오버플로우): Excellent→Great,
    # Caution→Risky, Not recommended→Avoid. 표시 전용 문자열(클라 분기 키는
    # grade — 라벨 분기 금지 계약)·ko 와이어 값·판정 임계 무변경.
    "최고": "Great", "좋음": "Good", "보통": "Fair",
    "주의": "Risky", "비추천": "Avoid",
}


def localize_weather(response: WeatherResponse, lang: str) -> WeatherResponse:
    """en 유저용 텍스트 조립 — ko/미설정은 원본 그대로(복사 0, 현행 동일).

    personalized comment는 personalize_index가 이미 lang으로 조립하므로 스킵.
    ⚠️ pm25/pm10.grade·uv.grade(및 유사 grade 필드)는 **localize 금지** — 클라가
    색상 매핑 조회 키(와이어 값)로 사용 중이라 번역하면 클라가 깨진다(Ivan 계약
    2026-07-29). '마저 번역' 금지 — 표시 텍스트가 아니라 enum 값이다."""
    if lang != "en":
        return response
    out = response.model_copy(deep=True)   # 공유 캐시 원본 무수정(전례 축)
    out.condition = _condition_en(out.condition_code)
    out.running_index.label = _LABEL_EN.get(
        out.running_index.label, out.running_index.label)  # 미스=ko 유지
    if not out.running_index.personalized:
        out.running_index.comment = _COMMENT_EN.get(
            out.running_index.comment, out.running_index.comment)  # 미스=ko 유지
    return out


# ── personalization (캐시 밖) ─────────────────────────────────────────────────


def _is_raining(response: WeatherResponse) -> bool:
    """뇌우(2xx)·이슬비(3xx)·비(5xx) 또는 최근 1시간 강수량이 있으면 True (눈 제외)."""
    code = response.condition_code
    if 200 <= code < 600:
        return True
    return (response.rain_1h_mm or 0) > 0


def personalize_index(
    response: WeatherResponse, ws: WeatherSettings, lang: str = "ko"
) -> WeatherResponse:
    """유저 weather 설정 기준을 넘긴 요인이 있으면 코멘트만 개인화한 복사본 반환.

    캐시가 WeatherResponse 객체 참조를 그대로 돌려주므로 원본은 절대 수정하지
    않는다 — deep copy 필수 (running_index가 중첩 모델이라 얕은 복사도 오염).
    score/label은 공용 기준 유지, comment + personalized 플래그만 바뀐다.
    복수 트리거 시 우선순위: 미세먼지 > 더위 > 비 (건강 위해도 순).
    """
    en = lang == "en"   # 동적 문구라 exact-match 사전 불가 — 생성 시점 lang 분기
    comment = None
    if (
        ws.avoid_dust
        and response.pm10 is not None
        and response.pm10.value >= ws.dust_level_pm10
    ):
        comment = (
            f"Above the recommended threshold (PM10 {ws.dust_level_pm10}) — "
            "indoor running recommended" if en else
            f"권장 기준(PM10 {ws.dust_level_pm10})을 넘었어요 — "
            "실내 러닝을 추천해요"
        )
    elif ws.avoid_heat and response.temp_c >= ws.heat_temp_c:
        comment = (
            f"Above the recommended threshold ({ws.heat_temp_c}°C) — "
            "try a morning or evening run" if en else
            f"권장 기준({ws.heat_temp_c}°C)을 넘었어요 — "
            "아침·저녁 러닝을 추천해요"
        )
    elif ws.avoid_rain and _is_raining(response):
        comment = ("Matches your rain-avoidance setting — indoor running recommended"
                   if en else "설정하신 비 회피 조건에 해당해요 — 실내 러닝을 추천해요")

    if comment is None:
        return response

    out = response.model_copy(deep=True)
    out.running_index.comment = comment
    out.running_index.personalized = True
    return out


# ── OpenWeather fetch ─────────────────────────────────────────────────────────


async def _fetch_current(
    client: httpx.AsyncClient, lat: float, lng: float, key: str
) -> dict:
    """Current weather; raises the friendly errors. Never leaks the key."""
    try:
        _ow_tick()   # 벤더 콜 관측(2026-08-06)
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


async def _fetch_uv(
    client: httpx.AsyncClient, lat: float, lng: float, key: str
) -> float | None:
    """UV index — **현재 UV**(One Call 4.0 current, 2026-08-18 전환).

    Best-effort — any failure returns None (타일 숨김).

    구 /data/2.5/uvi(일 최고값 시맨틱)가 러닝 골든타임(아침·저녁) 판단을
    왜곡하던 것 교정(2026-08-05 파이프 추적 — 파이프 무왜곡·시맨틱 갭 확정).
    4.0 응답 shape는 3.0(current.uvi)과 다름: top에 data 배열 — **data[0].uvi**
    (2026-08-18 실검증·담당자 확인. 3.0 경로는 별도 구독이라 401). 계정 cap
    1,000/일 = 무료 한도 잠금(청구 0 구조), 카운터 임계 800 감시.
    """
    try:
        _ow_tick()   # 벤더 콜 관측(2026-08-06) — 4.0 전환에도 배선 유지
        res = await client.get(
            f"{settings.openweather_base_url}/data/4.0/onecall/current",
            params={"lat": lat, "lon": lng, "appid": key},
        )
        if res.status_code != 200:
            return None
        data = res.json().get("data") or []
        uvi = data[0].get("uvi") if data else None   # 구조 이상 방어 — None 폴백
        return float(uvi) if uvi is not None else None
    except Exception:  # noqa: BLE001 — partial failure must not break weather
        logger.warning("OpenWeather uvi(4.0 current) 호출 실패 (자외선 없이 응답)")
        return None


async def _fetch_air(
    client: httpx.AsyncClient, lat: float, lng: float, key: str
) -> dict | None:
    """Air pollution components; best-effort — any failure returns None."""
    try:
        _ow_tick()   # 벤더 콜 관측(2026-08-06)
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


def _uv_at_response_time(
    response: WeatherResponse, sun: tuple[float, float] | None
) -> WeatherResponse:
    """UV 야간 0 처리(AIR_QUALITY_SOURCE_DESIGN §3 ⓐ, 오너 승인 2026-07-31).

    daily-max UV(구 /2.5/uvi)가 밤에도 노출되던 것(실측: 20:53 KST "매우높음 9.3")
    교정. 2026-08-18 4.0 current(실시간) 전환 후에도 유지 — 실시간 UV는 밤에
    자연히 ~0이지만, 캐시 TTL 10분 경계(일몰 직전 적재값이 직후 히트)를 이
    응답 시점 가드가 계속 막는다(무수정 호환).
    판정은 **응답 시점**(캐시 적재 시점 아님): 낮에 적재된 캐시가 일몰 직후
    히트돼도 밤엔 0 — lang 응답 시점 조립 함정과 동형. 비교는 epoch(UTC) 초라
    KST 경계 계산 불요. sun 결손 시 적재 시점 is_day 폴백(best-effort).
    grade 어휘는 기존 "낮음" 재사용 — 스키마·와이어 값 집합 불변.
    """
    if response.uv is None:
        return response
    if sun and sun[0] and sun[1]:
        night = not (sun[0] <= time.time() <= sun[1])
    else:
        night = not response.is_day
    if not night:
        return response
    out = response.model_copy(deep=True)   # 공유 캐시 원본 무수정(07/05 전례 축)
    out.uv = UvReading(value=0.0, grade=_uv_grade(0.0))
    return out


# ── 에어코리아 실측 PM (AIR_QUALITY_SOURCE_DESIGN, 오너 승인 2026-07-31) ──
# 실채집 검증 완료(2026-08-03 광화문 실프로브): items 경로(response.body.items)·
# 필드명(stationName/pm10Value/pm25Value/*Flag — 정상 시 Flag는 null) 실물 일치.
# 결측 실물은 정상 시간대라 미채집 — "-"·음수·Flag 방어는 문서 기준 유지
# (실결측 관측 시 fixture 보강). 키는 Encoding/Decoding 양형 지원(_airkorea_key).

_AIRKOREA_BASE = "https://apis.data.go.kr/B552584"
_KOREA_BBOX = (33.0, 39.0, 124.0, 132.0)   # KoreaCoordinate와 동일 상수
_STATION_TTL_SEC = 24 * 3600.0
# {그리드: (expires_at_monotonic, stationName)} — 측정소는 사실상 불변이라 24h.
_station_cache: dict[tuple[float, float], tuple[float, str]] = {}


def _airkorea_key() -> str:
    """포털 키 양형 지원 — Encoding형(% 포함)이면 디코드해 httpx가 1회만
    인코딩하게(이중 인코딩 인증 실패 방지 — 2026-08-03 실채집 검증 방식)."""
    k = settings.airkorea_api_key
    return urllib.parse.unquote(k) if "%" in k else k


def _in_korea(lat: float, lng: float) -> bool:
    a, b, c, d = _KOREA_BBOX
    return a <= lat <= b and c <= lng <= d


def _parse_airkorea_value(raw, flag) -> float | None:
    """측정값 방어 파싱 — 결측이면 None(폴백 트리거).

    문서 기준 결측: 값 "-"(통신장애) · 음수(-999류) · *Flag 비어있지 않음
    ("점검및교정"/"장비점검"/"자료이상"/"통신장애"). 정상 시 Flag는 null(실채집).
    결측 실물은 미채집(정상 시간대) — 문서 기준 유지, 실결측 관측 시 보강.
    """
    if flag:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


_AIRKOREA_TIMEOUT = 3.0   # 전용 타임아웃 — 최악 지연 캡 = 3×2시도 = 6s


def _key_forms() -> set[str]:
    """serviceKey 등장 가능 3형 — 원문·디코드형·URL재인코드형(httpx가 URL에
    다시 인코딩한 표기). 마스킹 단일 소스(_mask_key·프로브 공용). 빈 키 가드."""
    raw = settings.airkorea_api_key
    if not raw:
        return set()
    dec = _airkorea_key()
    return {raw, dec, urllib.parse.quote(dec, safe="")}


def _mask_key(text: str) -> str:
    """로그 경로 마스킹 — 3형 전수(2026-08-04 백포트: 구현이 원문·디코드형만
    잡아 재인코드형 URL 표기가 새던 맹점 제거 — 재-ON 게이트 조건)."""
    for k in _key_forms():
        text = text.replace(k, "<key>")
    return text


def _airkorea_transport(url: str, params: dict) -> httpx.Response:
    """동기 전송 심(2026-08-03 승인 우회) — **콜마다 새 동기 클라이언트**로
    공유 풀·커넥션 상태를 원천 배제(uvicorn 서빙 프로세스 내 요청만 포털이
    400 거부하던 격리 결과 대응 — 동일 바이트 URL이 ssh에선 성공).
    to_thread로 호출된다(supabase-py 동형 관례). 테스트는 이 심을 패치.
    요청 관측: 전송 직전 실제 헤더·최종 URL(키 마스킹) — 원인 실체 기록용."""
    with httpx.Client(timeout=_AIRKOREA_TIMEOUT) as c:
        req = c.build_request("GET", url, params=params)
        logger.info("에어코리아 요청 관측 — url=%s headers=%s",
                    _mask_key(str(req.url)), dict(req.headers))
        return c.send(req)


async def _airkorea_get(client: httpx.AsyncClient, url: str, params: dict,
                       label: str) -> httpx.Response:
    """에어코리아 호출 공통 — 비200·예외 즉시 재시도 1회(합계 2시도), 200이면
    재시도 없음(비용 방어). 전송은 _airkorea_transport(동기+새 클라이언트,
    to_thread) — client 인자는 Kakao 등 타 콜용으로 상위가 쥐고 있을 뿐
    여기선 미사용(우회 2026-08-03). 최종 실패는 관측 로그 후 예외 전파 →
    상위 폴백(OpenWeather) 체인 불변."""
    last_exc: Exception | None = None
    last_res: httpx.Response | None = None
    for attempt in (1, 2):
        try:
            res = await asyncio.to_thread(_airkorea_transport, url, params)
        except Exception as exc:  # noqa: BLE001 — 다음 시도/폴백
            logger.warning("에어코리아 %s 예외(시도 %d/2): %s",
                           label, attempt, type(exc).__name__)
            last_exc, last_res = exc, None
            continue
        if res.status_code == 200:
            return res
        body = _mask_key(res.text[:400])[:200]
        logger.warning("에어코리아 %s 비200(시도 %d/2) — status %s body %r",
                       label, attempt, res.status_code, body)
        last_exc, last_res = None, res
    if last_res is not None:
        last_res.raise_for_status()
    raise last_exc  # type: ignore[misc]


async def _resolve_station(client: httpx.AsyncClient, lat: float, lng: float) -> str | None:
    """그리드→근접 측정소명 (24h 캐시). Kakao transcoord(WGS84→TM, 기존 키)
    → 에어코리아 근접 측정소 목록. 실패 시 None(폴백) — 실패는 캐시하지 않음."""
    key = _cache_key(lat, lng)
    hit = _station_cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    # 1) WGS84 → TM (Kakao — 신규 의존 0)
    tc = await client.get(
        "https://dapi.kakao.com/v2/local/geo/transcoord.json",
        params={"x": lng, "y": lat, "input_coord": "WGS84", "output_coord": "TM"},
        headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
    )
    tc.raise_for_status()
    docs = tc.json().get("documents") or []
    if not docs:
        return None
    tm_x, tm_y = docs[0]["x"], docs[0]["y"]
    # 2) 근접 측정소 (거리순 1건)
    # 실채집 일치(2026-08-03): response.body.items[list]·stationName·tm(km) 확인.
    ns = await _airkorea_get(
        client, f"{_AIRKOREA_BASE}/MsrstnInfoInqireSvc/getNearbyMsrstnList",
        {"tmX": tm_x, "tmY": tm_y, "returnType": "json", "ver": "1.1",
         "serviceKey": _airkorea_key()}, "근접 측정소")
    items = (((ns.json().get("response") or {}).get("body") or {}).get("items")) or []
    name = items[0].get("stationName") if items else None
    if not name:
        return None
    _station_cache[key] = (time.monotonic() + _STATION_TTL_SEC, name)
    return name


async def _fetch_airkorea(
    client: httpx.AsyncClient, lat: float, lng: float
) -> tuple[float | None, float | None] | None:
    """에어코리아 실시간 측정값 (pm25, pm10) µg — best-effort, 실패는 None.

    grade는 khaiGrade를 쓰지 않고 상위에서 기존 breakpoint 표로 산출
    (매핑 단일 소스 — 설계 §8). 실채집 일치(2026-08-03): pm10Value/pm25Value
    문자열·정상 시 *Flag null(falsy라 파서 통과) 확인."""
    try:
        station = await _resolve_station(client, lat, lng)
        if not station:
            return None
        res = await _airkorea_get(
            client, f"{_AIRKOREA_BASE}/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty",
            {"stationName": station, "dataTerm": "DAILY", "pageNo": 1,
             "numOfRows": 1, "returnType": "json", "ver": "1.3",
             "serviceKey": _airkorea_key()}, "실시간 측정값")
        items = (((res.json().get("response") or {}).get("body") or {}).get("items")) or []
        if not items:
            return None
        it = items[0]
        pm25 = _parse_airkorea_value(it.get("pm25Value"), it.get("pm25Flag"))
        pm10 = _parse_airkorea_value(it.get("pm10Value"), it.get("pm10Flag"))
        return (pm25, pm10)
    except Exception:  # noqa: BLE001 — 실측 소스 장애가 날씨 응답을 막지 않는다
        logger.warning("에어코리아 조회 실패 — OpenWeather 폴백", exc_info=True)
        return None


# ── TEMP: 에어코리아 서빙 프로세스 400 미스터리 진단 프로브 (2026-08-04) ──
# 제거 트리거: 미스터리 해소 시(포털 회신 or TLS/커넥션 계층 원인 확정) 이 블록 +
# routes의 /admin/diag/airkorea-probe + app/diag_airkorea_shell.py +
# tests/test_airkorea_probe_integration.py 일괄 삭제.
# 관측 전용 — DB 쓰기 0·캐시 무접촉·airkorea_enabled 플래그와 무관하게 동작.

_PROBE_STATION = "종로구"   # 광화문 실채집(2026-08-03)과 동일 측정소


def _probe_mask(text: str) -> str:
    """serviceKey 원문 노출 금지 — 3형(_key_forms 단일 소스) 전부 ****+뒤4자."""
    raw = settings.airkorea_api_key
    for k in _key_forms():
        text = text.replace(k, "****" + raw[-4:])
    return text


# Authorization류는 값 전체 마스킹(관측 불요 — 존재 여부만 의미).
_PROBE_SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "cookie"}


def _probe_transport_observe(url: str, params: dict,
                             extra_headers: dict | None = None) -> dict:
    """_airkorea_transport와 동일 구성(새 httpx.Client(timeout=_AIRKOREA_TIMEOUT)
    + build_request→send) — 커넥션이 살아있는 컨텍스트 안에서 TLS·소켓 관측만 추가.
    재시도 0(원샷 관측). 테스트는 이 심을 패치.

    sent_headers: request 이벤트 훅으로 캡처한 **실발신 직전** 헤더 전체.
    훅은 원본 send 내부(전송 직전)에서 실행되므로 Sentry send 래퍼가 주입하는
    sentry-trace/baggage가 있으면 여기 잡힌다 — 조립 단계 로그(_airkorea_transport)
    가 못 보는 주입을 관측(센트리 가설 결정 실험, 2026-08-04). 훅은 순수 관측 —
    와이어 바이트 무접촉.

    extra_headers: 인과 증명용 수동 주입(--inject-headers) — Sentry 래퍼와 같은
    위치(send 진입 전 요청 변조)에 정적 헤더를 얹는다. None(기본)이면 무접촉."""
    started = time.monotonic()
    sent_headers: dict[str, str] = {}

    def _capture_sent(request: httpx.Request) -> None:
        for k, v in request.headers.items():
            sent_headers[k] = ("****" if k.lower() in _PROBE_SENSITIVE_HEADERS
                               else _probe_mask(v))

    with httpx.Client(timeout=_AIRKOREA_TIMEOUT,
                      event_hooks={"request": [_capture_sent]}) as c:
        req = c.build_request("GET", url, params=params)
        for k, v in (extra_headers or {}).items():
            req.headers[k] = v
        res = c.send(req)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        server_addr = client_addr = tls_version = tls_cipher = None
        stream = res.extensions.get("network_stream")
        if stream is not None:
            server_addr = stream.get_extra_info("server_addr")
            client_addr = stream.get_extra_info("client_addr")
            ssl_obj = stream.get_extra_info("ssl_object")
            if ssl_obj is not None:
                tls_version = ssl_obj.version()
                cipher = ssl_obj.cipher()
                tls_cipher = cipher[0] if cipher else None
        return {
            "url": _probe_mask(str(req.url)),
            "status": res.status_code,
            "http_version": res.http_version,
            "sent_headers": sent_headers,
            "headers": {k: _probe_mask(v) for k, v in res.headers.items()},
            "body_head": _probe_mask(res.text[:500]),
            "peer": list(server_addr) if server_addr else None,
            "local": list(client_addr) if client_addr else None,
            "tls_version": tls_version,
            "tls_cipher": tls_cipher,
            "elapsed_ms": elapsed_ms,
        }


async def airkorea_probe(extra_headers: dict | None = None) -> dict:
    """에어코리아에 실기능 동일 경로(동기 클라이언트 + to_thread)로 정확히 1회
    요청하고 관측을 반환. 부수효과 0 — 측정소 캐시·응답 캐시 무접촉.
    extra_headers는 셸 --inject-headers 전용(서빙 엔드포인트는 항상 None)."""
    if not settings.airkorea_api_key:
        return {"ok": False, "error": "NotConfigured",
                "detail": "airkorea_api_key 미설정"}
    url = f"{_AIRKOREA_BASE}/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"
    params = {"stationName": _PROBE_STATION, "dataTerm": "DAILY", "pageNo": 1,
              "numOfRows": 1, "returnType": "json", "ver": "1.3",
              "serviceKey": _airkorea_key()}
    try:
        obs = await asyncio.to_thread(_probe_transport_observe, url, params,
                                      extra_headers)
    except Exception as exc:  # noqa: BLE001 — 관측 실패도 관측 결과다
        return {"ok": False, "error": type(exc).__name__,
                "detail": _probe_mask(str(exc))}
    return {"ok": True, **obs}


async def _fetch_pm(
    client: httpx.AsyncClient, lat: float, lng: float, ow_key: str
) -> tuple[float | None, float | None]:
    """PM 소스 오케스트레이터 — (pm25, pm10).

    한국 bbox + 플래그 ON + 키 존재 → 에어코리아 실측. 해외·장애·전항 결측 →
    OpenWeather(현행) 폴백. 부분 결측(한 항만 유효)은 실측 채택(있는 값만 —
    현행 결측 처리와 동형). 소스 구분은 와이어 비노출(설계 §2, 로그만)."""
    if (settings.airkorea_enabled and settings.airkorea_api_key
            and _in_korea(lat, lng)):
        got = await _fetch_airkorea(client, lat, lng)
        if got is not None and (got[0] is not None or got[1] is not None):
            logger.info("PM 소스: 에어코리아 실측 (%.2f, %.2f)", lat, lng)
            return got
    comp = await _fetch_air(client, lat, lng, ow_key)
    return ((comp.get("pm2_5") if comp else None),
            (comp.get("pm10") if comp else None))


async def get_weather(lat: float, lng: float) -> WeatherResponse:
    """Weather + PM + running index for (lat, lng), cached ~10min per grid cell."""
    if not settings.openweather_api_key:
        raise WeatherNotConfigured()

    key = _cache_key(lat, lng)
    cached = _cache_get(key)
    if cached is not None:
        return _uv_at_response_time(cached[0], cached[1])

    api_key = settings.openweather_api_key
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        current, (pm25_v, pm10_v), uv_v = await asyncio.gather(
            _fetch_current(client, lat, lng, api_key),
            _fetch_pm(client, lat, lng, api_key),
            _fetch_uv(client, lat, lng, api_key),
        )

    main = current.get("main", {})
    weather0 = (current.get("weather") or [{}])[0]
    # 주/야: icon suffix(d/n)가 1차 — OpenWeather가 sunrise/sunset에서 파생한
    # 값이라 동치(실확인: 23:55 KST에 "03n" = dt·일몰 비교와 일치). icon 결손
    # 시 sys 비교 폴백, 둘 다 없으면 낮. raw icon은 노출하지 않는다(아이콘
    # 체계 종속 방지 — 프론트는 is_day로 자체 셋 분기).
    icon = weather0.get("icon") or ""
    sys_d = current.get("sys") or {}
    _sr, _ss = sys_d.get("sunrise"), sys_d.get("sunset")
    _sun = (float(_sr), float(_ss)) if _sr and _ss else None  # UV 야간 판정용
    if icon:
        is_day = not icon.endswith("n")
    else:
        dt = current.get("dt")
        is_day = bool(_sr and _ss and dt and _sr < dt < _ss) if _sr else True
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
        uv=UvReading(value=round(uv_v, 1), grade=_uv_grade(uv_v))
        if uv_v is not None else None,
        is_day=is_day,
        running_index=_running_index(feels, code, wind, pm25_v, pm10_v, humidity),
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    _cache_put(key, response, _sun)
    return _uv_at_response_time(response, _sun)
