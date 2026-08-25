"""OSM 보행:도로 태깅비 프로브 — 공장 타겟 필터(청라 3.4 우수 / 팽성 0.25 불성립).

각 후보 지역 중심에서 walk 그래프를 받아 highway 클래스별 길이 합을 내고,
보행(footway·path·pedestrian·living_street·steps) : 도로(residential·service·
unclassified·tertiary·secondary·primary) 길이비를 계산. 필터 ≥1.5(청라 기준).
완전 오프라인 산출물(서버·DB 무접촉). Run: .venv/bin/python scripts/course_factory/tagging_probe.py
"""
from __future__ import annotations
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import osmnx as ox  # noqa: E402

WALK = {"footway", "path", "pedestrian", "living_street", "steps", "track"}
ROAD = {"residential", "service", "unclassified", "tertiary", "tertiary_link",
        "secondary", "secondary_link", "primary", "primary_link", "trunk", "motorway"}

# NEW territory(캐노니컬 0) + 러닝 수요 높은 계획도시/공원/수변 후보
CANDIDATES = {
    "세종 호수공원": (36.4800, 127.2590),
    "수원 광교호수공원": (37.2860, 127.0640),
    "인천 송도 센트럴파크": (37.3920, 126.6390),
    "성남 분당 율동공원": (37.3520, 127.1300),
    "고양 일산 호수공원": (37.6580, 126.7690),
    "대전 엑스포/갑천": (36.3720, 127.3880),
    "광주 풍암호수공원": (35.1330, 126.8760),
    "서울 뚝섬한강공원": (37.5300, 127.0700),
}
DIST = 1100  # 프록시 샘플 반경(m) — 빠른 필터용(생성은 target 반경으로 별도)


def ratio_for(center, dist=DIST):
    G = ox.graph_from_point(center, dist=dist, network_type="walk")
    walk_m = road_m = 0.0
    hist: dict[str, float] = {}
    for _u, _v, d in G.edges(data=True):
        h = d.get("highway")
        if isinstance(h, list):
            h = h[0]
        L = float(d.get("length", 0.0))
        hist[h] = hist.get(h, 0.0) + L
        if h in WALK:
            walk_m += L
        elif h in ROAD:
            road_m += L
    ratio = walk_m / road_m if road_m > 0 else float("inf")
    return ratio, walk_m, road_m, G.number_of_nodes(), hist


def main():
    out = []
    for name, c in CANDIDATES.items():
        t = time.time()
        try:
            r, wm, rm, n, hist = ratio_for(c)
            verdict = "PASS(≥1.5)" if r >= 1.5 else ("경계(1.0~1.5)" if r >= 1.0 else "제외(<1.0)")
            top = sorted(hist.items(), key=lambda x: -x[1])[:4]
            print(f"{name:20} ratio={r:5.2f} [{verdict:12}] walk={wm/1000:.1f}km "
                  f"road={rm/1000:.1f}km nodes={n} ({time.time()-t:.0f}s) top={[ (k,round(v)) for k,v in top]}")
            out.append({"region": name, "center": c, "ratio": round(r, 2),
                        "walk_km": round(wm/1000, 2), "road_km": round(rm/1000, 2),
                        "nodes": n, "verdict": verdict})
        except Exception as e:
            print(f"{name:20} FAIL {type(e).__name__}: {str(e)[:80]}")
            out.append({"region": name, "center": c, "error": str(e)[:120]})
    os.makedirs(os.path.join(os.path.dirname(__file__), "out"), exist_ok=True)
    json.dump(out, open(os.path.join(os.path.dirname(__file__), "out", "tagging_probe.json"), "w"),
              ensure_ascii=False, indent=1)
    print("\nsaved → out/tagging_probe.json")


if __name__ == "__main__":
    main()
