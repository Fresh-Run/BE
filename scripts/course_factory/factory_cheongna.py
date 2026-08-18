"""그래프 캐노니컬 공장 — 청라 파일럿 (2026-08-19, 4안 오프라인 실증).

완전 오프라인: 서빙 코드·DB·배포 무접촉. osmnx walk 그래프(사전 추출
cheongna_walk.graphml) 위에서 round-trip 순환 후보를 배치 생성하고, 기존
스크리닝(screen_seed_candidates.screen_track — §8.19 기계 지표)을 그대로 통과.

알고리즘(선택 근거): GraphHopper round_trip 동형 — 시작점에서 방위 θ로
원(둘레≈목표 L)을 그려 원주 위 가상 포인트 3개를 잡고, 가중 최단경로 4레그를
잇되 **사용 엣지 가중 ×4 페널티**로 비중첩 유도(문헌 표준 대비 구현 단순·의존
0 — 파일럿 목적에 충분). 차도 회피는 highway 클래스 가중(§8.19 ③ 프록시):
footway/path/pedestrian/living ×1.0 · service ×1.6 · residential ×1.8 ·
unclassified ×2.2 · tertiary ×3 · secondary+ ×5.
녹지 폴리곤 30m 버퍼 가중(v1)은 **제외** — 판단 플래그: 공수 대비 파일럿 판정에
불필요(차도 클래스 가중이 1차 갈음), 공장 승격 시 v2로.

Run: .venv/bin/python scripts/course_factory/factory_cheongna.py
출력: out/cheongna_candidates.json + 콘솔 결과표.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import networkx as nx  # noqa: E402
import osmnx as ox  # noqa: E402

from scripts.screen_seed_candidates import screen_track  # noqa: E402 — §8.19 단일 소스

HERE = os.path.dirname(os.path.abspath(__file__))
GRAPHML = os.path.join(HERE, "cheongna_walk.graphml")
OUT = os.path.join(HERE, "out")

# 차도 회피 가중(§8.19 ③ 프록시)
ROAD_PENALTY = {"footway": 1.0, "path": 1.0, "pedestrian": 1.0, "living_street": 1.0,
                "steps": 2.0, "service": 1.6, "residential": 1.8, "unclassified": 2.2,
                "tertiary": 3.0, "tertiary_link": 3.0, "secondary": 5.0,
                "secondary_link": 5.0, "primary": 6.0, "primary_link": 6.0}

# 시작점 후보 — 청라 공공 지점(세션 기지 실좌표: 공원·수변, Kakao/등재 전례)
STARTS = {
    "청라호수공원 북": (37.5333, 126.6285),
    "청라호수공원 남": (37.5262, 126.6300),
    "커낼웨이 중앙": (37.5238, 126.6315),
    "솔빛공원권": (37.5244, 126.6264),
    "심곡천 수변": (37.5365, 126.6420),
    "가정중앙시장역권": (37.5205, 126.6450),
    "로봇랜드권 서": (37.5410, 126.6180),
}
TARGETS_KM = (3.0, 5.0, 7.0)
BEARINGS = (0, 90, 180, 270)

# 기존 청라 캐노니컬 근사 중심(세션 기지 — DB 무접촉 제약, 확정은 오너 게이트)
KNOWN_CANON = {"솔빛 블록": (37.5240, 126.6290), "청라호수공원": (37.5300, 126.6290)}


def offset(lat, lng, bearing_deg, dist_m):
    R = 6371000.0
    b = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    d = dist_m / R
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(b))
    lng2 = math.radians(lng) + math.atan2(
        math.sin(b) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lng2)


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    G = ox.load_graphml(GRAPHML)
    for u, v, k, d in G.edges(keys=True, data=True):
        h = d.get("highway")
        if isinstance(h, list):
            h = h[0]
        d["w"] = float(d.get("length", 1.0)) * ROAD_PENALTY.get(h, 2.5)
    UG = nx.Graph()  # 무향 단순화(보행 양방향) — 최단경로용
    for u, v, d in G.edges(data=True):
        w = d["w"]
        if not UG.has_edge(u, v) or UG[u][v]["w"] > w:
            UG.add_edge(u, v, w=w, length=float(d.get("length", 1.0)))
    pos = {n: (G.nodes[n]["y"], G.nodes[n]["x"]) for n in G.nodes}

    def nearest(lat, lng):
        return ox.distance.nearest_nodes(G, lng, lat)

    results = []
    attempts = 0
    reject_hist = {}
    for sname, (slat, slng) in STARTS.items():
        s = nearest(slat, slng)
        for L in TARGETS_KM:
            r = L * 1000 / (2 * math.pi)
            for th in BEARINGS:
                attempts += 1
                clat, clng = offset(slat, slng, th, r)
                vias = []
                bad = False
                for ang in (90, 180, 270):
                    vlat, vlng = offset(clat, clng, (th + 180 + ang) % 360, r)
                    try:
                        vias.append(nearest(vlat, vlng))
                    except Exception:
                        bad = True
                        break
                if bad:
                    reject_hist["via 스냅 실패"] = reject_hist.get("via 스냅 실패", 0) + 1
                    continue
                seq = [s, *vias, s]
                used = set()
                path_nodes = []
                ok = True
                for a, b in zip(seq, seq[1:]):
                    H = UG.copy()
                    for (eu, ev) in used:
                        if H.has_edge(eu, ev):
                            H[eu][ev]["w"] *= 4.0   # 비중첩 유도
                    try:
                        p = nx.shortest_path(H, a, b, weight="w")
                    except Exception:
                        ok = False
                        break
                    for eu, ev in zip(p, p[1:]):
                        used.add((eu, ev) if eu < ev else (ev, eu))
                    path_nodes.extend(p if not path_nodes else p[1:])
                if not ok:
                    reject_hist["경로 없음"] = reject_hist.get("경로 없음", 0) + 1
                    continue
                pts = [pos[n] for n in path_nodes]
                verdict = screen_track(pts)
                if "reject" in verdict:
                    key = verdict["reject"].split("(")[0]
                    reject_hist[key] = reject_hist.get(key, 0) + 1
                    continue
                dup = [n for n, c in KNOWN_CANON.items()
                       if min(math.dist((p[0], p[1]), c) for p in pts[::5]) < 0.004]
                results.append({"start": sname, "target_km": L, "bearing": th,
                                "pts": pts, **{k: v for k, v in verdict.items()},
                                "dup_approx": dup})
    el = time.time() - t0
    results.sort(key=lambda r: (r["tier"] != "clean", r["dbl_pct"],
                                r["longest_retrace_m"]))
    print(f"\n생성 {attempts}시도 → §8.19 통과 {len(results)} ({el:.0f}s)")
    print("탈락 분포:", reject_hist)
    for r in results[:12]:
        print(f"  [{r['tier']:9}] {r['start']} {r['target_km']}km방위{r['bearing']} → "
              f"{r['km']}km 폐합{r['closure']}m 이중{r['dbl_pct']}% 둘레비{r['bbox_ratio']} "
              f"회랑{r['longest_retrace_m']}m mwy{r['motorway_m']} trunk{r['trunk_m']}"
              + (f" ⚠근사중복:{r['dup_approx']}" if r["dup_approx"] else ""))
    json.dump(results, open(os.path.join(OUT, "cheongna_candidates.json"), "w"),
              ensure_ascii=False)
    print(f"saved → out/cheongna_candidates.json · 총 소요 {el:.0f}s")


if __name__ == "__main__":
    main()
