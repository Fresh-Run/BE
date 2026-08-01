"""GPS 트랙 처리 파이프라인 — 러닝 기록의 서버 검증 (설계 2026-07-06 확정).

전부 순수 계산 (DB·외부 API 없음): 필터 → 스무딩 → 거리/스플릿/고도 → 간축.
저장·검증 판정 결합은 run_service의 몫.

임계값 근거:
- MAX_ACCURACY_M 30: 도심 스마트폰 GPS는 5~15m — 30m 초과는 터널·실내 픽스.
- MAX_SPEED_MS 8.3 (=2'00"/km): 5000m 세계기록 페이스(~8.0m/s)조차 일반 유저가
  지속 불가. GPS 점프는 보통 수십 m/s라 여유 있게 걸러진다.
- PAUSE_GAP_S 60: 일시정지(신호등·휴식) 중 이동을 거리로 산입하지 않는다.
  시간은 elapsed 기준 유지 (앱 duration_sec와 일관 — moving time은 후속).
- ELEV_HYSTERESIS_M 3: 기압계 없는 GPS 고도는 ±5m 노이즈 — 문턱 없이 합치면
  평지에서도 수십 m 상승이 잡힌다.
- 스무딩은 3점 이동평균 1패스: GPS 지그재그의 haversine 과대측정(+3~7%)을
  절반 이상 상쇄. 사후 일괄 처리라 칼만 필터는 복잡도 대비 이득 없음.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

MAX_TRACK_POINTS = 5000   # ≈ 4초 간격 5.5시간 (풀마라톤 커버)
MIN_TRACK_POINTS = 10
MAX_ACCURACY_M = 30.0
MAX_SPEED_MS = 8.3
PAUSE_GAP_S = 60.0
# 이동시간(moving) 판정 속도 하한 (Ivan 배치 ①, 2026-07-23): 구간 순간속도가
# 이 값 미만이면 정지로 보고 moving_sec서 제외(Strava식). 0.5m/s≈1.8km/h(느린 걷기
# 이하) — 신호등·휴식은 elapsed엔 남고 moving엔 빠진다. PAUSE_GAP_S(거리 미산입)와
# 별개 축: 60s gap은 seg=0으로 자연히 speed<0.5라 moving서도 제외(정합).
MOVING_SPEED_MS = 0.5
ELEV_HYSTERESIS_M = 3.0
LOW_CONFIDENCE_DROP_RATIO = 0.20  # 필터 제거율이 이걸 넘으면 검증 보류
MIN_PARTIAL_KM = 0.2              # 마지막 부분 킬로 스플릿 포함 최소 거리
DP_EPSILON_M = 5.0                # Douglas-Peucker 간축 허용 오차
MAX_POLYLINE_POINTS = 1000

# 검증 판정 (run_service가 사용)
DISTANCE_MISMATCH_RATIO = 0.10    # 앱신고 vs 서버 괴리 — 초과 시 서버 값으로 대체
SUSPECT_AVG_PACE_S = 150          # 평균 < 2'30"/km → 자전거/차량 의심
SUSPECT_SPLIT_PACE_S = 160        # 최속 1km 스플릿 < 2'40" → 의심

# 좌표 정합성 3겹 (2026-07-30 국제화 — 한국 bbox 폐지, 호바트 테스터 실피해):
# ① 세계 유효 범위 ② null island(0,0 반경 ~1km — GPS 미수신 쓰레기의 고전)
# ③ 시작점 앵커 창 — 첫 유효 포인트 반경 100km 밖 드롭. 100km 근거: 단일 러닝
# 세션의 시작점 직선 변위 상한(울트라 100km+도 루프·왕복형이라 직선반경은 그
# 미만이 일반) — 취지는 도시 간·대륙 점프 GPS 글리치(수백 km+) 차단, 실주행 전부
# 통과. accuracy 컷·속도 이상치·suspect 안티치트는 무변경("유효 좌표" 정의만 교체).
_NULL_ISLAND_M = 1000.0
_ANCHOR_RADIUS_M = 100_000.0


def _coarse_dist_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """equirectangular 근사(정합성 필터용 — km 스케일 판정에 충분)."""
    kx = 111320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat1 - lat2) * 111320.0, (lng1 - lng2) * kx)


@dataclass
class TrackPoint:
    lat: float
    lng: float
    t_ms: int
    acc: float | None = None
    alt: float | None = None


@dataclass
class Split:
    km: float                 # 1, 2, … 정수 랩 / 마지막 partial은 총거리 (예: 5.18)
    sec: int                  # 랩 소요 시간 (elapsed — 일시정지 포함)
    elev_gain_m: int | None   # alt 없으면 None
    partial: bool = False
    moving_sec: int = 0       # 랩 이동 시간 (정지 제외, speed≥MOVING_SPEED_MS) — Ivan ①


@dataclass
class ProcessedTrack:
    polyline: list[dict]      # [{"lat":…,"lng":…}] 간축 결과
    splits: list[Split]
    server_distance_km: float
    elev_gain_m: int | None
    elapsed_s: float          # 트랙 자체의 경과 시간 (검증 페이스 계산용)
    moving_s: float           # 트랙 총 이동 시간 (정지 제외) — Ivan ②(run·track moving_sec 총합)
    point_count_raw: int
    point_count_kept: int
    low_confidence: bool = False
    fastest_km_pace_s: int | None = None   # 정수 km 랩 중 최속 (suspect 판정용)
    raw_pace_s_per_km: float | None = None  # 속도 필터 전 평균 페이스 (부정 판정용)
    max_speed_kmh: float | None = None      # 필터 전 최고 구간 속도 (관측용 저장)
    avg_accuracy_m: float | None = None     # 수신 포인트 평균 accuracy (관측용)
    _kept: list[TrackPoint] = field(default_factory=list, repr=False)


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _basic_filter(points: list[TrackPoint]) -> list[TrackPoint]:
    """① 구조 정리(정렬·중복 t 제거) + ② accuracy/좌표 정합성 3겹 필터(글로벌)."""
    pts = sorted(points, key=lambda p: p.t_ms)
    seen: set[int] = set()
    base: list[TrackPoint] = []
    anchor: TrackPoint | None = None
    for p in pts:
        if p.t_ms in seen:
            continue
        seen.add(p.t_ms)
        if not (-90.0 <= p.lat <= 90.0 and -180.0 <= p.lng <= 180.0):
            continue                                    # ① 세계 유효 범위
        if _coarse_dist_m(p.lat, p.lng, 0.0, 0.0) < _NULL_ISLAND_M:
            continue                                    # ② null island
        if p.acc is not None and p.acc > MAX_ACCURACY_M:
            continue
        if anchor is None:
            anchor = p                                  # 첫 유효 포인트 = 세션 앵커
        elif _coarse_dist_m(p.lat, p.lng, anchor.lat, anchor.lng) > _ANCHOR_RADIUS_M:
            continue                                    # ③ 시작점 앵커 창(대륙 점프 차단)
        base.append(p)
    return base


def _speed_filter(base: list[TrackPoint]) -> list[TrackPoint]:
    """③ 속도 이상치(순간이동) 필터 — 마지막 정상 포인트 기준 재연결."""
    if not base:
        return []
    kept = [base[0]]
    for p in base[1:]:
        dt = (p.t_ms - kept[-1].t_ms) / 1000.0
        if dt <= 0:
            continue
        v = _haversine_m(kept[-1].lat, kept[-1].lng, p.lat, p.lng) / dt
        if v > MAX_SPEED_MS:
            continue  # 순간이동 — 마지막 정상 포인트 기준으로 재연결
        kept.append(p)
    return kept


def _raw_pace_s_per_km(base: list[TrackPoint]) -> float | None:
    """속도 필터 '이전' 궤적의 평균 페이스 — 부정 판정용.

    자전거/차량은 속도 필터에 스스로 걸려 필터 후 거리가 깎이므로, 필터 후
    지표만 보면 suspect를 회피할 수 있다. raw 거리는 실제 이동을 반영해
    지속적인 초인 속도를 그대로 드러낸다.
    """
    if len(base) < 2:
        return None
    dist = sum(
        _haversine_m(base[i - 1].lat, base[i - 1].lng, base[i].lat, base[i].lng)
        for i in range(1, len(base))
    )
    elapsed = (base[-1].t_ms - base[0].t_ms) / 1000.0
    if dist <= 0 or elapsed <= 0:
        return None
    return elapsed / (dist / 1000.0)


def _smooth(pts: list[TrackPoint]) -> list[TrackPoint]:
    """⑤ 3점 이동평균 (좌표만 — t/alt는 중앙 포인트 값 유지)."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        out.append(TrackPoint(
            lat=(pts[i - 1].lat + pts[i].lat + pts[i + 1].lat) / 3,
            lng=(pts[i - 1].lng + pts[i].lng + pts[i + 1].lng) / 3,
            t_ms=pts[i].t_ms, acc=pts[i].acc, alt=pts[i].alt,
        ))
    out.append(pts[-1])
    return out


def _dp_simplify(pts: list[TrackPoint], epsilon_m: float) -> list[TrackPoint]:
    """⑦ Douglas-Peucker (반복형) — 위경도를 로컬 미터 평면으로 근사."""
    if len(pts) < 3:
        return pts
    lat0 = math.radians(pts[0].lat)
    kx = 111320.0 * math.cos(lat0)  # 경도 1° ≈ m
    ky = 110540.0

    def xy(p: TrackPoint) -> tuple[float, float]:
        return (p.lng * kx, p.lat * ky)

    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        s, e = stack.pop()
        if e - s < 2:
            continue
        x1, y1 = xy(pts[s])
        x2, y2 = xy(pts[e])
        seg_len = math.hypot(x2 - x1, y2 - y1)
        best_d, best_i = -1.0, -1
        for i in range(s + 1, e):
            x0, y0 = xy(pts[i])
            if seg_len == 0:
                d = math.hypot(x0 - x1, y0 - y1)
            else:
                d = abs((x2 - x1) * (y1 - y0) - (x1 - x0) * (y2 - y1)) / seg_len
            if d > best_d:
                best_d, best_i = d, i
        if best_d > epsilon_m:
            keep[best_i] = True
            stack.append((s, best_i))
            stack.append((best_i, e))
    out = [p for p, k in zip(pts, keep) if k]
    if len(out) > MAX_POLYLINE_POINTS:  # 안전망: 균등 다운샘플
        step = len(out) / MAX_POLYLINE_POINTS
        out = [out[int(i * step)] for i in range(MAX_POLYLINE_POINTS - 1)] + [out[-1]]
    return out


def process_track(raw: list[TrackPoint]) -> ProcessedTrack | None:
    """전체 파이프라인. 유효 트랙이 못 되면 None (run은 unverified로 저장)."""
    raw_n = len(raw)
    if raw_n < MIN_TRACK_POINTS:
        return None
    base = _basic_filter(raw)
    kept = _speed_filter(base)
    if len(kept) < MIN_TRACK_POINTS:
        return None
    low_confidence = (1 - len(kept) / raw_n) > LOW_CONFIDENCE_DROP_RATIO
    raw_pace = _raw_pace_s_per_km(base)

    # 관측 지표 (run_tracks에 저장 — 필터 동작·부정 패턴 추적용)
    max_v_ms = 0.0
    for i in range(1, len(base)):
        dt = (base[i].t_ms - base[i - 1].t_ms) / 1000.0
        if dt > 0:
            v = _haversine_m(base[i - 1].lat, base[i - 1].lng,
                             base[i].lat, base[i].lng) / dt
            max_v_ms = max(max_v_ms, v)
    accs = [p.acc for p in raw if p.acc is not None]
    avg_acc = round(sum(accs) / len(accs), 1) if accs else None

    sm = _smooth(kept)

    # ④⑥ 거리 누적 (gap 구간 미산입) + 스플릿 (km 경계 선형 보간)
    has_alt = all(p.alt is not None for p in sm[:5]) and sm[0].alt is not None
    total_m = 0.0
    splits: list[Split] = []
    lap_start_t = sm[0].t_ms
    lap_gain = 0.0
    lap_moving = 0.0          # 현재 랩 이동시간 누적 (정지 제외)
    total_gain = 0.0
    total_moving = 0.0        # 트랙 전체 이동시간 (= Σ split.moving_sec)
    elev_ref = sm[0].alt if has_alt else None
    next_km = 1

    for i in range(1, len(sm)):
        a, b = sm[i - 1], sm[i]
        dt = (b.t_ms - a.t_ms) / 1000.0
        seg = _haversine_m(a.lat, a.lng, b.lat, b.lng)
        if dt > PAUSE_GAP_S:
            seg = 0.0  # 일시정지 중 이동 — 거리 미산입 (시간은 elapsed 유지)

        # 이동시간(moving): 구간 순간속도 ≥ MOVING_SPEED_MS면 그 dt를 이동으로 산입.
        # seg가 0(60s gap)이면 speed 0 → 자연 제외. elapsed(sec)와 달리 정지 시간 뺌.
        speed = seg / dt if dt > 0 else 0.0
        seg_moving = dt if speed >= MOVING_SPEED_MS else 0.0
        total_moving += seg_moving

        # 고도 hysteresis (상승만, 3m 문턱)
        if has_alt and b.alt is not None and elev_ref is not None:
            if b.alt >= elev_ref + ELEV_HYSTERESIS_M:
                lap_gain += b.alt - elev_ref
                total_gain += b.alt - elev_ref
                elev_ref = b.alt
            elif b.alt < elev_ref:
                elev_ref = b.alt

        # km 경계 통과 (한 세그먼트에서 여러 경계 가능). moving은 elapsed와 동일한
        # frac로 랩에 안분(구간 내 등속 가정 — 경계 앞뒤 랩에 비례 배분).
        seg_frac_prev = 0.0
        while seg > 0 and total_m + seg >= next_km * 1000.0:
            frac = (next_km * 1000.0 - total_m) / seg
            cross_t = a.t_ms + (b.t_ms - a.t_ms) * frac
            lap_moving += seg_moving * (frac - seg_frac_prev)
            splits.append(Split(
                km=float(next_km),
                sec=round((cross_t - lap_start_t) / 1000.0),
                elev_gain_m=round(lap_gain) if has_alt else None,
                moving_sec=round(lap_moving),
            ))
            lap_start_t = cross_t
            lap_gain = 0.0
            lap_moving = 0.0
            seg_frac_prev = frac
            next_km += 1
        lap_moving += seg_moving * (1.0 - seg_frac_prev)  # 경계 뒤 잔여(또는 전량)
        total_m += seg

    total_km = total_m / 1000.0
    remainder = total_km - (next_km - 1)
    if remainder >= MIN_PARTIAL_KM:
        splits.append(Split(
            km=round(total_km, 2),
            sec=round((sm[-1].t_ms - lap_start_t) / 1000.0),
            elev_gain_m=round(lap_gain) if has_alt else None,
            partial=True,
            moving_sec=round(lap_moving),
        ))

    full_laps = [s for s in splits if not s.partial and s.sec > 0]
    fastest = min((s.sec for s in full_laps), default=None)

    simplified = _dp_simplify(sm, DP_EPSILON_M)
    return ProcessedTrack(
        # alt 보존(2026-08-01, Ivan 계약 — 고도 차트+avoid_hills 실효 측정 소스).
        # 미전송 포인트는 키 생략(구클라·구트랙 무영향). 수평 거리·필터 판정에는
        # 유입되지 않는다(하버사인은 lat/lng만 — 테스트로 박제).
        polyline=[{"lat": round(p.lat, 6), "lng": round(p.lng, 6),
                   **({"alt": round(p.alt, 1)} if p.alt is not None else {})}
                  for p in simplified],
        splits=splits,
        server_distance_km=round(total_km, 2),
        elev_gain_m=round(total_gain) if has_alt else None,
        elapsed_s=(sm[-1].t_ms - sm[0].t_ms) / 1000.0,
        moving_s=total_moving,
        point_count_raw=raw_n,
        point_count_kept=len(kept),
        low_confidence=low_confidence,
        fastest_km_pace_s=fastest,
        raw_pace_s_per_km=raw_pace,
        max_speed_kmh=round(max_v_ms * 3.6, 1),
        avg_accuracy_m=avg_acc,
        _kept=kept,
    )


def classify(processed: ProcessedTrack | None, app_distance_km: float) -> str:
    """검증 판정 — 'unverified' | 'suspect' | 'adjusted' | 'verified'.

    판정 순서가 중요:
    1) suspect를 low_confidence보다 먼저 — 자전거는 속도 필터에 스스로 걸려
       제거율이 높아지므로, low_confidence를 먼저 보면 부정이 unverified로
       빠져나간다. (집계는 이제 verified만 포함이라 랭킹 구멍은 아니지만,
       suspect는 is_flagged 표시·거리 정본 채택 방지에 여전히 필요.)
       그래서 필터 전 raw 페이스로 우선 판정.
    2) suspect가 adjusted보다 우선 — 부정 의심 거리를 정본으로 채택하지 않기
       위해 (거리 대체는 호출부에서 adjusted에만 적용).
    """
    if processed is None:
        return "unverified"
    if (processed.raw_pace_s_per_km is not None
            and processed.raw_pace_s_per_km < SUSPECT_AVG_PACE_S):
        return "suspect"
    if processed.server_distance_km <= 0 or processed.elapsed_s <= 0:
        return "unverified"
    if processed.elapsed_s / processed.server_distance_km < SUSPECT_AVG_PACE_S:
        return "suspect"
    if (processed.fastest_km_pace_s is not None
            and processed.fastest_km_pace_s < SUSPECT_SPLIT_PACE_S):
        return "suspect"
    if processed.low_confidence:
        return "unverified"
    mismatch = abs(app_distance_km - processed.server_distance_km) / processed.server_distance_km
    if mismatch > DISTANCE_MISMATCH_RATIO:
        return "adjusted"
    return "verified"


# ── 카드 지도용 축약 폴리라인 (~30pt) ────────────────────────────────────────

THUMB_EPSILON_M = 25.0   # 실측: 실트랙 85pt → 33pt (설계 목표 ~30)
THUMB_MAX_POINTS = 36


def make_polyline_thumb(polyline: list[dict]) -> list[dict]:
    """저장 폴리라인을 카드 지도용으로 재단순화 — 상한 보장 + 좌표 5자리(~1m).

    eps 25m → 초과 시 50m → 그래도 초과 시 균등 추출 30pt. 목록은 고빈도
    경로라 저장 시 1회 계산해 run_tracks.polyline_thumb에 박제한다(전송량
    상한 고정 — 조회 시 재계산안은 트랙 길이 비례 전송이라 기각, 설계 문서).
    """
    pts = [TrackPoint(lat=p["lat"], lng=p["lng"], t_ms=0) for p in polyline]
    if len(pts) > THUMB_MAX_POINTS:
        out = _dp_simplify(pts, THUMB_EPSILON_M)
        if len(out) > THUMB_MAX_POINTS:
            out = _dp_simplify(pts, THUMB_EPSILON_M * 2)
        if len(out) > THUMB_MAX_POINTS:
            step = (len(out) - 1) / 29
            out = [out[round(i * step)] for i in range(30)]
        pts = out
    return [{"lat": round(p.lat, 5), "lng": round(p.lng, 5)} for p in pts]
