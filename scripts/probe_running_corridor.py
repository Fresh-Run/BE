"""러닝 회랑(한강·청계천) 조사 — 두 사례 재구성(DB 읽기) + T-map 하천변 경로 반환 확인(소량).

RUNNING_CORRIDOR_DESIGN 근거 수집용 1회성. DB는 select만(쓰기 0). T-map은 소량 유료 호출
(보행자 경로 반환 여부 확인 — 한강 리버사이드·청계천 산책로를 경로로 주는지).

실행:
  python scripts/probe_running_corridor.py            # 재구성 + T-map 프로브
  python scripts/probe_running_corridor.py --no-tmap  # 재구성만(유료 호출 0)
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import Coordinate  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.services import map_service, shape_metrics as sm  # noqa: E402

CASES = {
    "한남 8km(9304cba6)": "9304cba6",
    "청계 5km(9774e6db)": "9774e6db",
}

# T-map 프로브 레그 — 러닝 회랑 위 좌표(근사). 반환 경로가 회랑을 추종하는지 본다.
#  한강 북안(잠원/반포 리버사이드 보행로) 동서 1.x km · 청계천(광장~동쪽) 1.x km.
LEGS = {
    "한강 북안 리버사이드 동진(잠원)": (Coordinate(lat=37.5225, lng=127.0030),
                                        Coordinate(lat=37.5205, lng=127.0180)),
    "한남오거리→한강 진입(나들목)": (Coordinate(lat=37.5333, lng=127.0076),
                                     Coordinate(lat=37.5225, lng=127.0030)),
    "청계천 광장→동쪽(관수교 방면)": (Coordinate(lat=37.5693, lng=126.9779),
                                     Coordinate(lat=37.5690, lng=126.9905)),
    "청계천 동쪽→광장(역방향)": (Coordinate(lat=37.5690, lng=126.9905),
                                 Coordinate(lat=37.5693, lng=126.9779)),
}


def reconstruct():
    sb = get_supabase_admin()
    rows = sb.table("routes").select("id").gte("created_at", "2026-11-20") \
        .lte("created_at", "2026-11-21").execute().data
    pref = {x["id"][:8]: x["id"] for x in rows}
    print("=" * 60 + "\n[재구성] 두 사례 (DB 읽기 전용)\n" + "=" * 60)
    for label, p in CASES.items():
        if p not in pref:
            print(f"{label}: 미발견"); continue
        r = sb.table("routes").select(
            "target_distance_km,total_distance_km,gen_meta,waypoints,polyline"
        ).eq("id", pref[p]).execute().data[0]
        gm = r["gen_meta"] or {}
        so = sm.shape_obs(r["polyline"])
        rr, _tot, runs = sm._retrace_runs(sm._norm(r["polyline"]))
        print(f"\n### {label}  tgt={r['target_distance_km']} tot={r['total_distance_km']}")
        print(f"  verdict={gm.get('verdict')} engine={gm.get('engine')} anchor_n={gm.get('anchor_n')} "
              f"pool={gm.get('pool_size')} snapped={gm.get('snapped_count')} course_id={gm.get('course_id')}")
        print(f"  park_coverage={gm.get('park_coverage')} longest_retrace_m={gm.get('longest_retrace_m')} "
              f"retrace_ratio={so['retrace_ratio']} branch_count={so['branch_count']} "
              f"longest_run={round(max(runs, default=0))}m")
        print(f"  avoid_hills={gm.get('prefs', {}).get('avoid_hills')} "
              f"road_types={gm.get('tmap_road_types')}")
        print(f"  waypoints={[ (w.get('name'), round(w['coordinate']['lat'],4), round(w['coordinate']['lng'],4)) for w in (r['waypoints'] or []) ]}")


async def tmap_probe():
    print("\n" + "=" * 60 + "\n[T-map 프로브] 러닝 회랑 경로 반환 여부 (소량 유료 호출)\n" + "=" * 60)
    for name, (o, d) in LEGS.items():
        try:
            pr = await map_service.get_pedestrian_route(o, d)
        except Exception as e:  # noqa: BLE001
            print(f"\n### {name}: 호출 실패 {str(e)[:80]}"); continue
        path = pr.path or []
        lats = [c.lat for c in path]; lngs = [c.lng for c in path]
        straight = sm._hav((o.lat, o.lng), (d.lat, d.lng))
        detour = (pr.distance_m / straight) if straight else 0
        # 회랑 추종 근사: 경로가 직선(출발-도착) 회랑에서 벗어난 최대 수직거리
        maxoff = 0.0
        for c in path:
            maxoff = max(maxoff, sm._seg_pt_dist((c.lat, c.lng), (o.lat, o.lng), (d.lat, d.lng)))
        segs = pr.road_segments[:6]
        print(f"\n### {name}")
        print(f"  distance={round(pr.distance_m)}m 직선={round(straight)}m detour={detour:.2f}x "
              f"crossings={getattr(pr,'crossing_count',None)} pts={len(path)}")
        print(f"  회랑 이탈 최대={round(maxoff)}m (작을수록 회랑 추종) "
              f"lat범위={round((max(lats)-min(lats))*111000) if lats else 0}m")
        print(f"  road_segments(roadType,name,m) 상위: {segs}")


def main():
    reconstruct()
    if "--no-tmap" not in sys.argv:
        asyncio.run(tmap_probe())


if __name__ == "__main__":
    main()
