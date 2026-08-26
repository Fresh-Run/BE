"""Map API integration for South Korea (Kakao / Naver).

This module provides boilerplate functions for:
  - keyword place search (to resolve pitstops like convenience stores)
  - pedestrian / walking routing between points

Both Kakao and Naver are stubbed with the correct endpoints, headers, and
request shapes. Fill in response parsing and error handling as needed.

For runners, T-map provides true sidewalk-level pedestrian routing and is the
recommended provider (MAP_PROVIDER=tmap). Kakao/Naver are driving-oriented.

API references:
  - Kakao Local (keyword search):
    https://developers.kakao.com/docs/latest/ko/local/dev-guide
  - Kakao Mobility (directions): https://developers.kakao.com/docs/latest/ko/kakaonavi/dev-guide
  - Naver Maps Directions (NCP):
    https://api.ncloud-docs.com/docs/ai-naver-mapsdirections
  - T-map Pedestrian (보행자 경로안내):
    https://tmapapi.sktelecom.com/main.html#webservice/docs/tmapRouteForPedestrian
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.core.json_util import loads_lenient
from app.models.schemas import Coordinate, PedestrianRoute, Place

# --- Endpoints ---------------------------------------------------------------

KAKAO_KEYWORD_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_COORD2ADDRESS_URL = "https://dapi.kakao.com/v2/local/geo/coord2address.json"
# 아파트/사유지 단지 + 접근 제한 구역 building_name/주소 신호(백로그 #6 관측).
# 브랜드 아파트·단지 + 군사·반환부지·예약제 구역(용산 부검 §8.14) — 관측 전용(필터 아님).
_APT_SIGNAL = re.compile(
    r"아파트|단지|자이|e편한|편한세상|푸르지오|롯데캐슬|힐스테이트|래미안|더샵|"
    r"아이파크|주공|캐슬|위브|SK뷰|sk뷰|해모로|스위첸|리슈빌|데시앙|우방|한신|"
    r"반환부지|기지|군부대|부대|military|훈련장|주둔지|위수지역")


def _is_apartment_name(building_name: str | None) -> bool:
    """건물명이 아파트/단지 신호면 True — 관측 분류(필터 아님)."""
    return bool(building_name and _APT_SIGNAL.search(building_name))


async def count_apartment_signal(coords: list[Coordinate]) -> tuple[int, int]:
    """좌표들을 역지오코딩해 아파트 단지 building_name 신호 수 반환 (hits, checked).

    관측 전용(백로그 #6, 2026-07-23) — 선택 route의 waypoint 실발생률 축적으로 접근성
    필터 착수 여부를 데이터로 재판정. best-effort: 개별 실패는 checked에 미포함, 키
    없거나 좌표 없으면 (0,0). 병렬 발사로 latency ~1콜.
    ⚠️ building_name은 인접 도로점에도 근접 단지명을 반환(edge-adjacency) — 절대
    관통 판정 아니고 근접 신호. 비율 추세용."""
    if not settings.kakao_rest_api_key or not coords:
        return 0, 0
    headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}

    async def _one(co: Coordinate) -> tuple[int, int]:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(KAKAO_COORD2ADDRESS_URL, headers=headers,
                                        params={"x": co.lng, "y": co.lat})
                resp.raise_for_status()
                docs = loads_lenient(resp.text, context="kakao coord2address").get("documents", [])
            # building_name(도로명 건물) + address_name(지번/도로명) 둘 다 검사 —
            # 반환부지·기지 신호는 건물명 없이 주소에만 있을 수 있음(같은 응답, 추가 콜 0).
            d0 = docs[0] if docs else {}
            bn = (d0.get("road_address") or {}).get("building_name") or ""
            addr = ((d0.get("road_address") or {}).get("address_name")
                    or (d0.get("address") or {}).get("address_name") or "")
            return (1 if _is_apartment_name(bn + " " + addr) else 0, 1)
        except Exception:  # noqa: BLE001 — 관측이라 개별 실패 무시
            return (0, 0)

    results = await asyncio.gather(*[_one(c) for c in coords])
    return sum(r[0] for r in results), sum(r[1] for r in results)
KAKAO_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"

NAVER_GEOCODE_URL = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"
NAVER_DRIVING_URL = "https://maps.apigw.ntruss.com/map-direction/v1/driving"

# T-map pedestrian routing (POST, JSON body). Coordinates are lng/lat.
TMAP_PEDESTRIAN_URL = (
    "https://apis.openapi.sk.com/tmap/routes/pedestrian?version=1&format=json"
)

# Default request timeout for all outbound Map API calls.
_TIMEOUT = httpx.Timeout(10.0)

logger = logging.getLogger(__name__)

# ── T-map 실 HTTP 콜 카운터 (관측 additive, 2026-08-05 청구 회계) ─────────────
# 요청 스코프: create_running_route가 begin으로 가변 박스를 심고, _tmap_walk_leg가
# POST **시도마다** +1(실패 leg도 청구될 수 있어 시도 기준 상한 집계). ContextVar에
# 가변 dict를 담는 이유 — asyncio.gather 자식 태스크는 컨텍스트를 복사하지만 박스
# 객체는 공유라 증가가 부모에 보인다. begin 없이 호출(스크립트 등)이면 no-op.
import contextvars as _contextvars

_tmap_counter: "_contextvars.ContextVar[dict | None]" = _contextvars.ContextVar(
    "tmap_counter", default=None)


def begin_tmap_count() -> dict:
    """요청 시작 시 호출 — 새 카운터 박스를 심고 반환."""
    box = {"n": 0, "hit": 0}
    _tmap_counter.set(box)
    return box


def tmap_call_count() -> int | None:
    """현 요청의 T-map HTTP 시도 수. begin 전이면 None(비생성 문맥)."""
    box = _tmap_counter.get()
    return box["n"] if box is not None else None


def tmap_cache_hits() -> int | None:
    """현 요청의 leg 캐시 적중 수(관측 — 절감 실측의 분자)."""
    box = _tmap_counter.get()
    return box.get("hit") if box is not None else None


# 프로세스 합계(오프라인 캠페인 회계, 2026-08-05 청구 포렌식) — 스크립트·E2E가
# map_service를 경유하는 한 무조건 집계, 종료 시 합계 1줄. T-map 10원/콜(2026-08
# 실측 — 244,000원/2.44만콜)이라 캠페인 예산 선계산의 자. 서버 프로세스도 종료 시
# 1줄 남지만 무해(관측 로그).
_process_tmap_total = {"n": 0}


def tmap_process_total() -> int:
    return _process_tmap_total["n"]


class TmapBudgetExceeded(Exception):
    """프로세스 콜 예산(TMAP_BUDGET_CALLS) 소진 — 오프라인 캠페인 하드캡.

    서빙은 미설정(0)=무제한이라 발생하지 않는다. 캠페인 스크립트에서 발생 시
    즉시 중단이 정답(예산 재승인 후 재개)."""


def _log_tmap_total() -> None:
    n = _process_tmap_total["n"]
    if n:
        budget = settings.tmap_budget_calls
        logger.info(
            "T-map HTTP 시도 프로세스 합계: %d콜 (≈%d원 — 10원/콜 2026-08 실측)%s",
            n, n * 10, f" | 예산 {budget}콜" if budget else "")


import atexit as _atexit

_atexit.register(_log_tmap_total)


# ── leg 캐시 (예산 1단계 ②, 2026-08-05) — 좌표쌍 라운딩 키 + TTL 메모리 캐시 ──
# 정밀도 5자리(≈1.1m): T-map이 어차피 시작·끝을 보행 네트워크에 스냅하는 반경
# (수십 m)보다 두 자릿수 작아 경로 정확도 무영향 — 4자리(≈11m)는 길 건너편
# 오스냅 가능성이 있어 기각. 단일 워커 상주 dict(무Redis — 오버엔지니어링 경계),
# TTL 기본 600s(재생성 리트라이 창 커버·도로망 변화 무관 수준), 상한 초과 시
# 만료분 청소 후 최고령 축출(weather _cache 관례).
_LEG_CACHE_MAX = 2000
_leg_cache: dict[tuple, tuple[float, object]] = {}   # key → (expires_at, result)


def _leg_key(o: Coordinate, d: Coordinate) -> tuple:
    return (round(o.lat, 5), round(o.lng, 5), round(d.lat, 5), round(d.lng, 5))


def clear_tmap_leg_cache() -> None:
    """테스트·캠페인 격리용."""
    _leg_cache.clear()


def _leg_cache_get(key: tuple):
    hit = _leg_cache.get(key)
    if hit is None:
        return None
    if hit[0] <= time.monotonic():
        _leg_cache.pop(key, None)
        return None
    return hit[1]


def _leg_cache_put(key: tuple, result) -> None:
    ttl = settings.tmap_leg_cache_ttl_s
    if ttl <= 0:
        return
    now = time.monotonic()
    if len(_leg_cache) >= _LEG_CACHE_MAX:
        for k in [k for k, (exp, _r) in _leg_cache.items() if exp <= now]:
            _leg_cache.pop(k, None)
        while len(_leg_cache) >= _LEG_CACHE_MAX:
            _leg_cache.pop(next(iter(_leg_cache)))
    _leg_cache[key] = (now + ttl, result)


# ── 일일 소프트 임계 (예산 1단계 ③) — KST 일 콜 카운트, 초과 WARNING(차단 없음) ──
_daily_tmap = {"day": None, "n": 0, "warned_at": 0}


def _daily_tmap_tick() -> None:
    from datetime import datetime, timedelta, timezone as _tz
    day = datetime.now(_tz(timedelta(hours=9))).date().isoformat()
    if _daily_tmap["day"] != day:
        _daily_tmap.update(day=day, n=0, warned_at=0)
    _daily_tmap["n"] += 1
    thr = settings.tmap_daily_warn_calls
    if not thr or _daily_tmap["n"] < thr:
        return
    # 첫 초과 시 1회 + 이후 100콜마다(로그 폭주 방지) — 차단은 하지 않는다
    # (차단 도입 여부는 오너 별도 결정 사항).
    if (_daily_tmap["warned_at"] == 0
            or _daily_tmap["n"] - _daily_tmap["warned_at"] >= 100):
        _daily_tmap["warned_at"] = _daily_tmap["n"]
        logger.warning(
            "T-map 일일 콜 %d — 소프트 임계 %d 초과(KST %s, ≈%d원). 차단 아님.",
            _daily_tmap["n"], thr, day, _daily_tmap["n"] * 10)


# --- Place search ------------------------------------------------------------


async def search_places(
    keyword: str,
    near: Coordinate | None = None,
    radius_m: int = 2000,
    limit: int = 5,
    sort: str = "distance",
) -> list[Place]:
    """Search for places (e.g. '편의점') near a coordinate, or nationwide.

    near=None이면 전국 정확도순(출발지 검색) — 카카오가 좌표 없는 keyword
    검색을 네이티브 지원하며, 그때 distance 정렬·radius는 불가(400)라
    파라미터를 통째로 뺀다. 좌표가 있으면 현행 거리순 그대로.
    Place (keyword) search always uses Kakao, independent of MAP_PROVIDER
    (which only selects the *routing* provider, e.g. T-map for walking).
    """
    return await _kakao_search_places(keyword, near, radius_m, limit, sort)


async def _kakao_search_places(
    keyword: str, near: Coordinate | None, radius_m: int, limit: int,
    sort: str = "distance",
) -> list[Place]:
    """Kakao Local keyword search. Kakao expects x=lng, y=lat.

    sort='distance'(기본, 근접) / 'accuracy'(관련도). 랜드마크형 pitstop은
    accuracy가 실제 공원을 상위로 올림(distance는 근접 상호가 실제 공원을 묻음 —
    청라 실측: distance는 밴드 내 공원 0, accuracy는 청라호수공원 포함 9개)."""
    if not settings.kakao_rest_api_key:
        raise RuntimeError(
            "Kakao place search is not configured. Set KAKAO_REST_API_KEY "
            "in your environment (see .env.example)."
        )

    headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}
    params = {"query": keyword, "size": limit}
    if near is not None:
        params.update({"x": near.lng, "y": near.lat,
                       "radius": radius_m, "sort": sort})
    else:
        params["sort"] = "accuracy"  # 좌표 없이 sort=distance는 카카오 400
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(KAKAO_KEYWORD_SEARCH_URL, headers=headers, params=params)
        resp.raise_for_status()
        data = loads_lenient(resp.text, context="kakao search")  # 제어문자 방어

    places: list[Place] = []
    for doc in data.get("documents", []):
        try:
            coordinate = Coordinate(lat=float(doc["y"]), lng=float(doc["x"]))
        except (KeyError, ValueError, ValidationError):
            # Skip results with missing/unparseable or out-of-range (non-Korea)
            # coordinates so one bad row doesn't fail the whole search.
            logger.debug("Skipping Kakao result with bad coordinate: %s", doc)
            continue
        places.append(
            Place(
                name=doc.get("place_name", keyword),
                coordinate=coordinate,
                category=doc.get("category_group_name") or None,
                category_code=doc.get("category_group_code") or None,
                address=doc.get("road_address_name") or doc.get("address_name"),
            )
        )
    return places


# ── pitstop 의도 존중 재랭킹 (2026-07-22, 백로그 (b)) ─────────────────────────
# 실사용 부검: pitstop "공원"이 category 무필터 텍스트+거리순이라 "…청라호수공원점"
# 상호를 가진 음식점이 실제 공원을 밀어냄. 랜드마크형 키워드는 상업 카테고리를
# 제외하고 적합도로 재랭킹, 상업형 키워드는 그 카테고리만, 미분류는 현행 유지.
_COMMERCIAL_CODES = {"FD6", "CE7", "CS2", "HP8", "PM9", "BK9", "OL7", "AD5"}  # 음식점·카페·편의점·병원·약국·은행·주유소·숙박
# 상업형 키워드 → include-only 코드(필터 반전)
_COMMERCIAL_KEYWORD_CODES = {"카페": "CE7", "커피": "CE7", "편의점": "CS2",
                             "음식점": "FD6", "식당": "FD6", "맛집": "FD6"}
# 랜드마크형 토큰(이 중 하나라도 키워드에 있으면 랜드마크 의도)
_LANDMARK_TOKENS = ("공원", "호수", "산", "천", "강변", "하천", "놀이터", "숲",
                    "해변", "저수지", "수목원", "둘레길", "생태")


def _keyword_intent(keyword: str) -> tuple[str, str | None]:
    """키워드→의도: (commercial, 코드) / (landmark, 토큰) / (unknown, None). 소규모
    매핑 — 미분류는 현행 무필터(과설계 금지)."""
    k = (keyword or "").strip()
    for kw, code in _COMMERCIAL_KEYWORD_CODES.items():
        if kw in k:
            return "commercial", code
    for t in _LANDMARK_TOKENS:
        if t in k:
            return "landmark", t
    return "unknown", None


def _adequacy(name: str, token: str) -> int:
    """이름 적합도 — 상호 차용(…공원점/캠퍼스) 최하, 실제 명칭(…공원) 우대."""
    if any(f"{token}{s}" in name for s in ("점", "캠퍼스", "지점", "타운")):
        return 0  # 랜드마크 상호 차용 — 실제 그곳이 아님
    if name.endswith(token):
        return 2  # 실제 명칭(예: 모래성공원)
    if token in name:
        return 1
    return 0


# 위치 밴드(루프 자연 지점, 2026-07-22 (b)): pitstop이 시작점 코앞(84m)이면 5km
# 루프 기하가 핀치돼 overshoot→502(청라 실사용 검증). 상한은 target×0.5, **하한은 절대
# 200m**(2026-07-22 좌표민감도 부검: target×0.15=750m 하한이 랜드마크 근접 출발점에서
# 대표 park(청라호수공원 354m)를 잘라내 소공원이 뽑히던 것 교정. 핀치는 target 무관 절대
# 기하라 절대 하한이 맞다 — 200m 미만만 핀치 보호로 제외). 밴드 내 0이면 적합도·최근접 폴백.
_POS_BAND_LO_M = 200.0          # 절대 하한(핀치 보호) — 200m 미만만 제외
_POS_BAND_HI_FACTOR = 0.50      # 상한은 target 비례 유지


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 great-circle 거리(m) — pitstop 위치 밴드용."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(x))


def _in_position_band(start: Coordinate, place: Place, target_km: float) -> bool:
    """pitstop이 루프 자연 지점(시작 거리 [절대 200m, target×0.5]) 안인가.
    하한 절대 200m: 핀치(코앞 pitstop→overshoot)만 제외, 300~700m 대표 park는 통과."""
    d_m = _haversine_m(start.lat, start.lng, place.coordinate.lat, place.coordinate.lng)
    return _POS_BAND_LO_M <= d_m <= target_km * _POS_BAND_HI_FACTOR * 1000.0


_ROTATE_TOP_K = 5  # pitstop 로테이션 창(P3, 2026-08-26) — 밴드 내 상위 K 안에서만 회전


def _rotate_pitstop(ordered: list[Place], recent: list[str] | None,
                    top_k: int = _ROTATE_TOP_K) -> list[Place]:
    """P3 로테이션(2026-08-26 오너 1차) — "항상 스타벅스" 해소. 밴드/거리로 이미
    정렬된 pitstop 후보에서, **상위 top_k 안에서만** 최근 채택(recent)에 안 든 최선을
    맨 앞으로 올린다. 품질 보존: top_k 밖 후보는 절대 승격 안 함(먼 카페로 안 튐).

    - recent: 유저 최근 채택 pitstop명(최신 우선). avoid는 그중 서로 다른
      top_k-1개까지만 — ≥K개 서로 다른 후보가 있으면 항상 fresh 하나가 남아
      rank[0] 고착(무한 스타벅스)이 풀린다.
    - 결정론: 같은 (ordered, recent) → 같은 결과(랜덤 아님, 재현성 유지).
    - recent 없음/후보<2/상위 K 전부 최근이면 → 종전 순서(rank[0]) 무교란(하위호환)."""
    if not recent or len(ordered) < 2:
        return ordered
    seen: set = set()
    avoid: set = set()
    for nm in recent:  # 최신순 — 서로 다른 top_k-1개만 회피 집합에
        if nm and nm not in seen:
            seen.add(nm)
            avoid.add(nm)
            if len(avoid) >= top_k - 1:
                break
    head = ordered[:top_k]
    for i, p in enumerate(head):
        if p.name not in avoid:
            if i == 0:
                return ordered  # rank[0] 이미 fresh — 바이트 무교란
            return [head[i], *head[:i], *head[i + 1:], *ordered[top_k:]]
    return ordered  # 상위 K 전부 최근 채택 → 종전(rank[0], 회피 불가)


def rank_places_for_keyword(
    keyword: str, places: list[Place],
    start: Coordinate | None = None, target_km: float | None = None,
    recent_pitstops: list[str] | None = None,
) -> list[Place]:
    """pitstop 의도 존중 재랭킹/필터. 통과 후보 리스트(빈 리스트면 상위가 폴백).

    - unknown 의도: 원본(거리순) 그대로 — 현행 동작 보존.
    - commercial 의도: 그 카테고리 코드만 남김(거리순 유지) + **밴드 내 상위 K
      로테이션**(P3, recent_pitstops로 연속 동일 회피 — 품질 보존, 먼 후보 승격 없음).
    - landmark 의도: 상업 카테고리 제외 후 [적합도 desc, **위치밴드 desc**, **대표성**,
      시작거리 asc] 안정 정렬. **대표성 = Kakao accuracy 순위**(places는 accuracy 정렬로
      들어옴 → 원 인덱스가 순위, 작을수록 대표). ★밴드 내에서만 대표성 tiebreak(오너 C) —
      밴드 밖은 기존 거리순. 청라 실측: accuracy가 청라호수공원을 밴드 내 #1로 올림.
      (로테이션 미적용 — 랜드마크는 대표성=최적 공원 선택이 의도라 회전 시 품질 강등.)
    """
    intent, param = _keyword_intent(keyword)
    if intent == "unknown":
        return places
    if intent == "commercial":
        # 그 카테고리 코드만 남김. 위치 밴드 우대(2026-07-23 오너 승격) — 편의점 등도
        # pitstop 목적이 "중간 보급"이라 시작 코앞(밴드 밖)보다 밴드 내(루프 중간) 우선.
        # 밴드 내 후보 0이면 자연히 최근접 폴백(전부 out-band → 거리순 → 최근접).
        # 채택이 밴드 밖이면 pitstop_obs.in_band=false가 그 폴백을 신호한다.
        cat = [p for p in places if p.category_code == param]
        if start is None or target_km is None:
            return cat  # 밴드 정보 없으면 현행(거리순 원본 — 하위호환)

        def _d(p):
            return _haversine_m(start.lat, start.lng, p.coordinate.lat, p.coordinate.lng)
        # P3: **밴드 내에서만** 상위 K 회전(먼 카페 승격 금지 — 품질 보존). 밴드 밖은
        # 종전대로 뒤에 거리순(밴드 내 0이면 out_band 최근접이 자연 폴백).
        in_band = sorted([p for p in cat if _in_position_band(start, p, target_km)], key=_d)
        out_band = sorted([p for p in cat if not _in_position_band(start, p, target_km)], key=_d)
        return _rotate_pitstop(in_band, recent_pitstops) + out_band
    kept = [p for p in places if p.category_code not in _COMMERCIAL_CODES]
    if not kept:
        return []
    has_band = start is not None and target_km is not None
    acc_rank = {id(p): i for i, p in enumerate(places)}  # accuracy 정렬 원 순위

    def _key(p: Place):
        adeq = _adequacy(p.name, param)
        if has_band:
            d = _haversine_m(start.lat, start.lng,
                             p.coordinate.lat, p.coordinate.lng) / 1000.0
            in_band = _in_position_band(start, p, target_km)
        else:
            d, in_band = 0.0, False
        # 적합도 → 위치밴드 → (밴드 내면 accuracy 순위=대표성, 밴드 밖이면 거리 상수)
        # → 최종 거리. 밴드 내에서만 대표성이 거리를 이긴다(오너 C).
        rep = acc_rank[id(p)] if in_band else 10 ** 9
        return (-adeq, -int(in_band), rep, d)

    return sorted(kept, key=_key)


async def _naver_search_places(
    keyword: str, near: Coordinate, radius_m: int, limit: int
) -> list[Place]:
    """Naver place search stub.

    Naver's place/local search lives behind the NAVER Search API (separate
    credentials from Maps). Implement against your chosen endpoint here.
    """
    raise NotImplementedError(
        "Naver place search is not implemented. Use MAP_PROVIDER=kakao, "
        "or wire up the NAVER Search (Local) API here."
    )


# --- Pedestrian routing ------------------------------------------------------


class LegNotRoutable(Exception):
    """T-map이 이 leg(두 점 사이)의 실보행 경로를 못 찾음 — 200이지만 빈 경로.

    강 위·철로 등 보행 불가 구간의 양안 웨이포인트를 이을 때 발생. HTTP/네트워크
    장애(raise_for_status)와 구분해 상위(route_service)가 이 후보를 traversability
    실패로 폐기하게 한다 — 그냥 두면 그 leg가 폴리라인에서 누락돼 렌더 시 인접
    구간이 물 위를 직선 횡단하게 보인다(Ivan 리포트 A). 좌표 미기록(프라이버시)."""


class TmapQuotaExceeded(Exception):
    """T-map 무료 쿼터 소진 — HTTP 429 QUOTA_EXCEEDED (일시적 인프라 한계).

    LegNotRoutable(지오 문제, 후보 자체 결함)과 **반드시 구분**한다: 이건 후보가
    아니라 우리 쪽 일일 콜 예산이 바닥난 것 — 상위(route_service)가 AI추정 nopath
    폴백(폴리라인 없는 가짜 코스)을 서빙하는 대신 503으로 정직하게 실패하게 한다
    ("앱은 거짓말하지 않는다", 2026-07-21 E2E 실증: 429 전패가 5/5 nopath 200 서빙).
    무료 티어는 자정(KST) 리셋. 좌표 미기록(프라이버시)."""


async def get_pedestrian_route(
    origin: Coordinate,
    destination: Coordinate,
    waypoints: list[Coordinate] | None = None,
) -> PedestrianRoute:
    """Fetch a walking/pedestrian route between two points (optionally via waypoints).

    Returns a normalized PedestrianRoute. Uses the configured MAP_PROVIDER.

    Note: Kakao Mobility and Naver Directions are primarily *driving* APIs.
    For true sidewalk-accurate pedestrian routing in Korea, prefer the T-map
    Pedestrian API (MAP_PROVIDER=tmap).
    """
    if settings.map_provider == "tmap":
        return await _tmap_pedestrian_route(origin, destination, waypoints)
    if settings.map_provider == "kakao":
        return await _kakao_route(origin, destination, waypoints)
    return await _naver_route(origin, destination, waypoints)


async def _kakao_route(
    origin: Coordinate,
    destination: Coordinate,
    waypoints: list[Coordinate] | None,
) -> PedestrianRoute:
    """Kakao Mobility directions. Coordinates are "lng,lat" strings."""
    headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}
    params: dict[str, str] = {
        "origin": f"{origin.lng},{origin.lat}",
        "destination": f"{destination.lng},{destination.lat}",
        "priority": "RECOMMEND",
    }
    if waypoints:
        params["waypoints"] = "|".join(f"{w.lng},{w.lat}" for w in waypoints)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(KAKAO_DIRECTIONS_URL, headers=headers, params=params)
        resp.raise_for_status()
        data = loads_lenient(resp.text, context="kakao directions")  # 제어문자 방어

    # Parse the first route's summary + geometry.
    route = data["routes"][0]
    summary = route["summary"]
    path: list[Coordinate] = []
    for section in route.get("sections", []):
        for road in section.get("roads", []):
            verts = road.get("vertexes", [])
            # vertexes are a flat [lng, lat, lng, lat, ...] array.
            for i in range(0, len(verts) - 1, 2):
                path.append(Coordinate(lat=verts[i + 1], lng=verts[i]))

    return PedestrianRoute(
        distance_m=float(summary["distance"]),
        duration_s=float(summary["duration"]),
        path=path,
        provider="kakao",
    )


async def _naver_route(
    origin: Coordinate,
    destination: Coordinate,
    waypoints: list[Coordinate] | None,
) -> PedestrianRoute:
    """Naver Directions (NCP). Coordinates are "lng,lat" strings."""
    headers = {
        "x-ncp-apigw-api-key-id": settings.naver_map_client_id,
        "x-ncp-apigw-api-key": settings.naver_map_client_secret,
    }
    params: dict[str, str] = {
        "start": f"{origin.lng},{origin.lat}",
        "goal": f"{destination.lng},{destination.lat}",
    }
    if waypoints:
        params["waypoints"] = "|".join(f"{w.lng},{w.lat}" for w in waypoints)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(NAVER_DRIVING_URL, headers=headers, params=params)
        resp.raise_for_status()
        data = loads_lenient(resp.text, context="naver driving")  # 제어문자 방어

    route = data["route"]["traoptimal"][0]
    summary = route["summary"]
    path = [Coordinate(lat=pt[1], lng=pt[0]) for pt in route.get("path", [])]

    return PedestrianRoute(
        distance_m=float(summary["distance"]),
        duration_s=float(summary["duration"]) / 1000.0,  # naver returns ms
        path=path,
        provider="naver",
    )


async def _tmap_pedestrian_route(
    origin: Coordinate,
    destination: Coordinate,
    waypoints: list[Coordinate] | None,
) -> PedestrianRoute:
    """T-map Pedestrian routing — sidewalk-accurate walking paths.

    The T-map *pedestrian* API only routes between a single start and end
    point (its `passList` waypoint support is unreliable for walking). To
    follow an arbitrary number of AI-generated waypoints in order, we split
    the ordered point list into adjacent pairs, route each leg separately,
    then stitch the legs back into one continuous path and sum the totals.

    This removes the old 5-waypoint cap: every point is honored.
    """
    # Full ordered itinerary: start -> each waypoint -> end.
    points: list[Coordinate] = [origin, *(waypoints or []), destination]

    total_distance_m = 0.0
    total_duration_s = 0.0
    path: list[Coordinate] = []
    road_segments: list = []
    crossing_total: int | None = 0   # 관측 — leg 하나라도 파싱 None이면 전체 None

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for leg_index in range(len(points) - 1):
            leg_start = points[leg_index]
            leg_end = points[leg_index + 1]
            distance_m, duration_s, leg_path, leg_roads, leg_cross = await _tmap_walk_leg(
                client, leg_start, leg_end
            )
            total_distance_m += distance_m
            total_duration_s += duration_s
            road_segments.extend(leg_roads)
            crossing_total = (None if leg_cross is None or crossing_total is None
                              else crossing_total + leg_cross)

            # Drop the first coordinate of every leg after the first so the
            # shared point between consecutive legs isn't duplicated.
            if path and leg_path:
                leg_path = leg_path[1:]
            path.extend(leg_path)

    return PedestrianRoute(
        distance_m=total_distance_m,
        duration_s=total_duration_s,
        path=path,
        provider="tmap",
        road_segments=road_segments,
        crossing_count=crossing_total,
    )


def _count_crossings(features) -> int | None:
    """횡단보도 수(관측 전용, 2026-07-31) — Point turnType 211 카운트, 0이면
    LineString facilityType '15' 폴백(실프로브 확인 shape). 어떤 파싱 이상도
    None으로 삼킨다 — 관측 실패가 경로 생성 실패로 전이되지 않는다."""
    try:
        pts = sum(1 for f in features
                  if f.get("geometry", {}).get("type") == "Point"
                  and f.get("properties", {}).get("turnType") == 211)
        if pts:
            return pts
        return sum(1 for f in features
                   if f.get("geometry", {}).get("type") != "Point"
                   and str(f.get("properties", {}).get("facilityType")) == "15")
    except Exception:  # noqa: BLE001 — 관측은 부가, 무해화
        return None


async def _tmap_walk_leg(
    client: httpx.AsyncClient,
    origin: Coordinate,
    destination: Coordinate,
) -> tuple[float, float, list[Coordinate]]:
    """Route a single start->end pedestrian leg via the T-map API.

    T-map is a POST with a JSON body and returns a GeoJSON FeatureCollection.
    Coordinates are WGS84 lng/lat. Returns (distance_m, duration_s, path).
    """
    # leg 캐시(예산 1단계 ②) — 적중이면 HTTP 0(카운터·예산·일일 임계 전부 무소모).
    # 리스트는 얕은 복사로 반환 — 호출측 변형이 캐시 원본을 오염하지 않게.
    _ck = _leg_key(origin, destination)
    if settings.tmap_leg_cache_ttl_s > 0:
        _cached = _leg_cache_get(_ck)
        if _cached is not None:
            _b = _tmap_counter.get()
            if _b is not None:
                _b["hit"] = _b.get("hit", 0) + 1
            d, s, p, rs, cc = _cached
            return d, s, list(p), list(rs), cc
    # 하드캡(예산 1단계 ①) — 서빙은 미설정(0)=무제한. 캐시 미스의 실호출만 소모.
    _budget = settings.tmap_budget_calls
    if _budget and _process_tmap_total["n"] >= _budget:
        raise TmapBudgetExceeded(
            f"TMAP_BUDGET_CALLS={_budget} 소진(시도 {_process_tmap_total['n']}) — "
            f"캠페인 중단, 예산 재승인 후 재개")
    headers = {
        "appKey": settings.tmap_app_key,
        "Content-Type": "application/json",
    }
    body: dict[str, object] = {
        "startX": origin.lng,
        "startY": origin.lat,
        "endX": destination.lng,
        "endY": destination.lat,
        "startName": "start",
        "endName": "end",
        "reqCoordType": "WGS84GEO",  # input coordinate system
        "resCoordType": "WGS84GEO",  # response coordinate system
        "searchOption": "0",  # 0=recommended, 4=shortest distance
    }

    _box = _tmap_counter.get()
    if _box is not None:            # 관측 additive — 청구 대조용 시도 카운트
        _box["n"] += 1
    _process_tmap_total["n"] += 1   # 프로세스 합계(오프라인 캠페인 회계) — 무조건
    _daily_tmap_tick()              # 일일 소프트 임계(예산 1단계 ③ — WARNING만)
    resp = await client.post(TMAP_PEDESTRIAN_URL, headers=headers, json=body)
    # T-map 무료 쿼터 소진은 429 QUOTA_EXCEEDED — 일반 HTTP 장애와 구분해 전용
    # 예외로 승격(상위가 nopath 폴백 금지·503 정직화). 다른 4xx/5xx는 그대로 전파.
    if resp.status_code == 429:
        raise TmapQuotaExceeded()
    resp.raise_for_status()
    # T-map GeoJSON 응답의 도로/POI명에 간헐적 미이스케이프 제어문자 → E2E 성수
    # nopath의 실블로커(2026-07-22). 표준 resp.json() 대신 제어문자 방어 파싱.
    data = loads_lenient(resp.text, context="tmap pedestrian")

    # Totals live on the first (Point) feature's properties; the geometry is
    # the concatenation of all LineString features.
    distance_m = 0.0
    duration_s = 0.0
    path: list[Coordinate] = []

    road_segments: list = []   # (roadType, name, distance_m) — §8.20 T-map 관측 축
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        if "totalDistance" in props:
            distance_m = float(props["totalDistance"])
        if "totalTime" in props:
            duration_s = float(props["totalTime"])

        geometry = feature.get("geometry", {})
        if geometry.get("type") == "LineString":
            for lng, lat in geometry.get("coordinates", []):
                path.append(Coordinate(lat=lat, lng=lng))
            road_segments.append((props.get("roadType"), props.get("name") or "",
                                  float(props.get("distance") or 0)))

    # T-map은 보행 불가 구간에 200 + 빈/무의미 응답을 준다(에러코드가 아님).
    # 유효 경로(거리>0·점 존재) 없으면 이 leg는 실보행 불가 — 조용히 distance=0,
    # path=[]로 통과시키면 폴리라인에 구멍이 나 물 위 직선 횡단이 생긴다(리포트 A).
    if not path or distance_m <= 0:
        raise LegNotRoutable()

    _cross = _count_crossings(data.get("features", []))
    _leg_cache_put(_ck, (distance_m, duration_s, list(path), list(road_segments),
                         _cross))
    return distance_m, duration_s, path, road_segments, _cross
