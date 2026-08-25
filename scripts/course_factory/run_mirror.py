"""Overpass 미러 순회 후 첫 성공 엔드포인트로 factory 실행(일산·대전). 3엔드포인트
차단이면 중단(무한 재시도 금지)."""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import osmnx as ox  # noqa: E402
from scripts.course_factory.factory import run, REGIONS  # noqa: E402

EPS = ["https://overpass-api.de/api", "https://overpass.kumi.systems/api",
       "https://overpass.private.coffee/api"]
ox.settings.requests_timeout = 18


def pick_endpoint():
    for ep in EPS:
        ox.settings.overpass_url = ep
        t = time.time()
        try:
            ox.graph_from_point((37.6580, 126.7690), dist=150, network_type="walk")
            print(f"ENDPOINT_OK {ep} ({time.time()-t:.0f}s)", flush=True)
            return ep
        except Exception as e:
            print(f"ENDPOINT_FAIL {ep} {type(e).__name__} ({time.time()-t:.0f}s)", flush=True)
    return None


ep = pick_endpoint()
if not ep:
    print("ALL_BLOCKED — 3엔드포인트 차단, 중단(무한 재시도 금지)", flush=True)
    sys.exit(0)
ox.settings.overpass_url = ep
summary = []
for slug in ("ilsan", "daejeon"):
    name, center = REGIONS[slug]
    try:
        summary.append({"slug": slug, **run(slug, name, center)})
    except Exception as e:
        print(f"RUN_FAIL {slug} {type(e).__name__} {str(e)[:80]}", flush=True)
print("=== 요약 ===", flush=True)
for s in summary:
    print(f"  {s['region']:16} 시도 {s['attempts']} → 통과 {s['passed']} (clean {s['clean']}) {s['sec']}s", flush=True)
print("DONE", flush=True)
