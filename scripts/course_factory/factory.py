"""그래프 캐노니컬 공장 — 일반화(청라 파일럿 factory_cheongna.py 알고리즘 재사용).

지역별 config(center, target 반경)로 osmnx walk 그래프를 받아 round-trip 순환
후보를 배치 생성하고 screen_seed_candidates.screen_track(§8.19)으로 스크리닝한다.
시작점은 지역 중심 링에서 자동 유도(공원/수변 코어 가정). 완전 오프라인 —
서버·DB·배포 무접촉. 산출: out/<slug>_candidates.json.

Run: .venv/bin/python scripts/course_factory/factory.py <slug>
"""
from __future__ import annotations
import json, math, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import networkx as nx  # noqa: E402
import osmnx as ox  # noqa: E402
from scripts.screen_seed_candidates import screen_track  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
ROAD_PENALTY = {"footway": 1.0, "path": 1.0, "pedestrian": 1.0, "living_street": 1.0,
                "track": 1.2, "steps": 2.0, "service": 1.6, "residential": 1.8,
                "unclassified": 2.2, "tertiary": 3.0, "tertiary_link": 3.0,
                "secondary": 5.0, "secondary_link": 5.0, "primary": 6.0,
                "primary_link": 6.0, "trunk": 8.0, "motorway": 12.0}
TARGETS_KM = (3.0, 5.0, 7.0)
BEARINGS = (0, 90, 180, 270)

# slug -> (표시명, center(lat,lng), 태깅비). NEW territory(캐노니컬 0) 확정 타겟만.
REGIONS = {
    "gwanggyo": ("수원 광교호수공원", (37.2860, 127.0640)),
    "ilsan":    ("고양 일산호수공원", (37.6580, 126.7690)),
    "daejeon":  ("대전 엑스포/갑천", (36.3720, 127.3880)),
}


def offset(lat, lng, bearing_deg, dist_m):
    R = 6371000.0
    b = math.radians(bearing_deg); lat1 = math.radians(lat); d = dist_m / R
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(b))
    lng2 = math.radians(lng) + math.atan2(math.sin(b) * math.sin(d) * math.cos(lat1),
                                          math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lng2)


def build_starts(center):
    """중심 + 4방위 ~600m 오프셋(공원/수변 코어 산포). 스냅은 main에서."""
    lat, lng = center
    s = {"코어": center}
    for name, brg in (("북", 0), ("동", 90), ("남", 180), ("서", 270)):
        s[name] = offset(lat, lng, brg, 600)
    return s


def run(slug, name, center):
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    # 7km 루프 반경 ~1114m + 시작 산포 600m + 여유 → dist 2600m
    G = ox.graph_from_point(center, dist=2600, network_type="walk")
    for u, v, k, d in G.edges(keys=True, data=True):
        h = d.get("highway")
        if isinstance(h, list):
            h = h[0]
        d["w"] = float(d.get("length", 1.0)) * ROAD_PENALTY.get(h, 2.5)
    UG = nx.Graph()
    for u, v, d in G.edges(data=True):
        w = d["w"]
        if not UG.has_edge(u, v) or UG[u][v]["w"] > w:
            UG.add_edge(u, v, w=w, length=float(d.get("length", 1.0)))
    pos = {n: (G.nodes[n]["y"], G.nodes[n]["x"]) for n in G.nodes}

    def nearest(lat, lng):
        return ox.distance.nearest_nodes(G, lng, lat)

    starts = build_starts(center)
    results, attempts, reject_hist = [], 0, {}
    for sname, (slat, slng) in starts.items():
        try:
            s = nearest(slat, slng)
        except Exception:
            continue
        for L in TARGETS_KM:
            r = L * 1000 / (2 * math.pi)
            for th in BEARINGS:
                attempts += 1
                clat, clng = offset(slat, slng, th, r)
                vias, bad = [], False
                for ang in (90, 180, 270):
                    vlat, vlng = offset(clat, clng, (th + 180 + ang) % 360, r)
                    try:
                        vias.append(nearest(vlat, vlng))
                    except Exception:
                        bad = True; break
                if bad:
                    reject_hist["via 스냅 실패"] = reject_hist.get("via 스냅 실패", 0) + 1
                    continue
                seq = [s, *vias, s]; used = set(); path_nodes = []; ok = True
                for a, b in zip(seq, seq[1:]):
                    H = UG.copy()
                    for (eu, ev) in used:
                        if H.has_edge(eu, ev):
                            H[eu][ev]["w"] *= 4.0
                    try:
                        p = nx.shortest_path(H, a, b, weight="w")
                    except Exception:
                        ok = False; break
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
                results.append({"region": name, "start": sname, "target_km": L,
                                "bearing": th, "pts": pts, **verdict})
    el = time.time() - t0
    results.sort(key=lambda r: (r["tier"] != "clean", r["dbl_pct"], r["longest_retrace_m"]))
    print(f"\n[{name}] 생성 {attempts}시도 → §8.19 통과 {len(results)} ({el:.0f}s)")
    print("  탈락 분포:", reject_hist)
    for r in results[:8]:
        print(f"  [{r['tier']:9}] {r['start']} {r['target_km']}km방위{r['bearing']} → "
              f"{r['km']}km 폐합{r['closure']}m 이중{r['dbl_pct']}% 둘레비{r['bbox_ratio']} "
              f"회랑{r['longest_retrace_m']}m")
    json.dump(results, open(os.path.join(OUT, f"{slug}_candidates.json"), "w"), ensure_ascii=False)
    print(f"  saved → out/{slug}_candidates.json")
    return {"region": name, "attempts": attempts, "passed": len(results),
            "clean": sum(1 for r in results if r["tier"] == "clean"), "sec": round(el)}


def main():
    slugs = sys.argv[1:] or list(REGIONS)
    summary = []
    for slug in slugs:
        name, center = REGIONS[slug]
        summary.append({"slug": slug, **run(slug, name, center)})
    json.dump(summary, open(os.path.join(OUT, "factory_summary.json"), "w"), ensure_ascii=False, indent=1)
    print("\n=== 지역별 요약 ===")
    for s in summary:
        print(f"  {s['region']:20} 시도 {s['attempts']} → 통과 {s['passed']} (clean {s['clean']}) {s['sec']}s")


if __name__ == "__main__":
    main()
