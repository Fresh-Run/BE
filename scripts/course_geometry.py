"""코스 지오메트리 유도 — 시더·백필 공유 단일 소스 (2026-07-15).

배경: 시드 코스는 `sb_insert_route`가 `waypoints:[]`+polyline 미설정으로 만들어
지오메트리가 비어 있었다(프론트 코스 카드가 "네온 폴백"으로 렌더). 트랙 없는
run과 형제 케이스. 실제 앱 저장 경로(route_service.persist_route, :357~381)와
**동일 포맷**으로 채운다:
  polyline : [{"lat":.., "lng":..}, ...]                       (Coordinate[])
  waypoints: [{"name", "coordinate":{lat,lng}, "is_pitstop", "description"}, ...]

유도 방식: §19 실 GPS 트랙 라이브러리(seed_real_tracks.json, 5종)에서 코스 시작
좌표에 **가장 가까운 실 트랙**을 골라, 그 트랙의 자연스러운 도로 모양을 코스
시작점으로 **평행이동(translate)** → 실제 러닝 경로 형태를 재사용(기하학적 원이
아니라 실도로 궤적). run 트랙에서 코스를 유도하라는 지침 그대로.
"""
from __future__ import annotations

import json
import math
import os

_TRACKS_PATH = os.path.join(os.path.dirname(__file__), "seed_real_tracks.json")


def load_tracks(path: str = _TRACKS_PATH) -> list[dict]:
    """seed_real_tracks.json → [{name, area, points:[(lat,lng)...]}]."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for name, t in data["tracks"].items():
        pts = [(p["lat"], p["lng"]) for p in t["points"]]
        out.append({"name": name, "area": t.get("area"), "points": pts})
    return out


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """두 좌표 간 거리(km)."""
    (la1, lo1), (la2, lo2) = a, b
    r = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dphi = math.radians(la2 - la1)
    dl = math.radians(lo2 - lo1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _nearest_track(start: tuple[float, float], tracks: list[dict]) -> dict:
    return min(tracks, key=lambda t: _haversine(start, t["points"][0]))


def _densify(pts: list[tuple[float, float]], target: int = 48) -> list[tuple[float, float]]:
    """세그먼트 균등 분할로 target 근처까지 점 채움(부드러운 렌더용)."""
    segs = len(pts) - 1
    if segs <= 0 or len(pts) >= target:
        return pts
    per = max(1, round(target / segs))
    out: list[tuple[float, float]] = []
    for i in range(segs):
        a, b = pts[i], pts[i + 1]
        for k in range(per):
            f = k / per
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    out.append(pts[-1])
    return out


def derive_geometry(
    start_lat: float, start_lng: float, summary: str, tracks: list[dict]
) -> tuple[list[dict], list[dict]]:
    """(polyline, waypoints) — 실제 앱 저장 포맷(Coordinate[] / Waypoint[]).

    코스 시작점에 가장 가까운 실 트랙을 시작점으로 평행이동해 재사용.
    좌표는 6자리 반올림(≈0.1m — 카드 렌더 충분, Coordinate 범위 [33-39,124-132] 내).
    """
    start = (start_lat, start_lng)
    tr = _nearest_track(start, tracks)
    base = tr["points"]
    dlat = start_lat - base[0][0]
    dlng = start_lng - base[0][1]
    moved = [(la + dlat, lo + dlng) for la, lo in base]
    dense = _densify(moved, 48)

    polyline = [{"lat": round(la, 6), "lng": round(lo, 6)} for la, lo in dense]

    label = (summary or "코스").split()[0]
    n = len(dense)
    picks = [(0, f"{label} 출발"), (n // 3, "중간 지점"),
             (2 * n // 3, "반환점"), (n - 1, "도착")]
    waypoints = []
    for ix, nm in picks:
        la, lo = dense[ix]
        waypoints.append({
            "name": nm,
            "coordinate": {"lat": round(la, 6), "lng": round(lo, 6)},
            "is_pitstop": False,
            "description": None,
        })
    return polyline, waypoints
