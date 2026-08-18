"""실주 트랙 → 캐노니컬 등재 후보 스크리닝 (2026-08-18 레포 승격 — 세션 스크립트 박제).

§8.19 기계 지표 전수(실기능 함수 단일 소스) + 이 스크리닝만의 보조 지표:
- **bbox 둘레비**(2026-08-18 신설 — 제주 911a674f 갭 실증): 궤적 총길이 ÷ bbox
  볼록 둘레 상한(2×(w+h)). **>1.5 = 동방향 자기중첩 의심**(트랙 반복 주행) —
  역방향 전용인 이중주행 지표가 동방향 랩을 못 잡는 갭을 막는다.
- **longest_retrace_m**(_spur_metrics): 왕복 회랑 내재 검출(여수 67416687 전례 —
  폐합 재량 통과였어도 420m 왕복 팔로 부적격). 300m+ = 의심 플래그.

원장(seed_qa_verdicts.json) run·grid 양형 제외, 기등재 캐노니컬 중복 표기.
읽기 전용 — DB 쓰기 0. Run: python scripts/screen_seed_candidates.py
"""
from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.schemas import Coordinate  # noqa: E402
from app.services import route_service as rs  # noqa: E402

BAND_M = (3000, 16000)
CLEAN_CLOSURE_M = 50
CONNECTOR_CLOSURE_M = 500
BBOX_RATIO_SUSPECT = 1.5
RETRACE_CORRIDOR_SUSPECT_M = 300
DBL_MAX = 0.20


def _dm(a, b):
    return rs._dist_km(Coordinate(lat=a[0], lng=a[1]),
                       Coordinate(lat=b[0], lng=b[1])) * 1000


def _resample(pts, step=15.0):
    out = [pts[0]]
    acc = 0.0
    for i in range(1, len(pts)):
        acc += _dm(pts[i - 1], pts[i])
        if acc >= step:
            out.append(pts[i])
            acc = 0.0
    return out


def double_run_ratio(pts, near=20.0):
    """역방향 재밟기 비율(§8.19 ① — 왕복 팔). 동방향 랩은 bbox_ratio가 담당."""
    p = _resample(pts)
    n = len(p) - 1
    if n < 3:
        return 0.0
    seg = [_dm(p[i], p[i + 1]) for i in range(n)]
    tot = sum(seg)
    mk = 0.0
    for j in range(n):
        for i in range(j - 1):
            if _dm(p[j], p[i + 1]) <= near and _dm(p[j + 1], p[i]) <= near:
                mk += seg[j]
                break
    return mk / tot if tot else 0.0


def bbox_ratio(pts):
    """총길이 ÷ bbox 볼록 둘레 상한 — >1.5면 동방향 자기중첩 의심(제주 실증 4.5)."""
    lats = [p[0] for p in pts]
    lngs = [p[1] for p in pts]
    w = _dm((min(lats), min(lngs)), (min(lats), max(lngs)))
    h = _dm((min(lats), min(lngs)), (max(lats), min(lngs)))
    total = sum(_dm(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    return total / max(1.0, 2 * (w + h))


def screen_track(pts):
    """트랙 1건 판정 — dict(탈락 사유 or 후보 지표)."""
    if len(pts) < 10:
        return {"reject": f"포인트 부족({len(pts)}pt)"}
    total = sum(_dm(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    if not (BAND_M[0] <= total <= BAND_M[1]):
        return {"reject": f"거리 밴드 밖({total/1000:.2f}km)"}
    closure = _dm(pts[0], pts[-1])
    if closure > CONNECTOR_CLOSURE_M:
        return {"reject": f"개방 궤적(폐합 {closure:.0f}m)"}
    br = bbox_ratio(pts)
    if br > BBOX_RATIO_SUSPECT:
        return {"reject": f"동방향 자기중첩 의심(둘레비 {br:.2f} > {BBOX_RATIO_SUSPECT})"}
    dr = double_run_ratio(pts)
    if dr > DBL_MAX:
        return {"reject": f"이중주행 {dr*100:.0f}%(기준 {DBL_MAX*100:.0f}%)"}
    coords = [Coordinate(lat=p[0], lng=p[1]) for p in pts]
    spur = rs._spur_metrics(coords)
    hard, _ = rs._road_hit_m(list(pts), "hard")
    _, trunk = rs._road_hit_m(list(pts), "obs")
    out = {"km": round(total / 1000, 2), "closure": round(closure),
           "tier": "clean" if closure <= CLEAN_CLOSURE_M else "connector",
           "dbl_pct": round(dr * 100), "bbox_ratio": round(br, 2),
           "longest_retrace_m": spur["longest_retrace_m"],
           "motorway_m": round(hard), "trunk_m": round(trunk)}
    if spur["longest_retrace_m"] >= RETRACE_CORRIDOR_SUSPECT_M:
        out["flag"] = f"왕복 회랑 {spur['longest_retrace_m']}m — §8.19 ① 의심(여수 전례)"
    if hard >= 100:
        out["flag"] = f"motorway 연속 {hard:.0f}m"
    return out


def main():
    from app.core.supabase_client import get_supabase_admin
    sb = get_supabase_admin()
    verd = json.load(open(os.path.join(os.path.dirname(__file__), "seed_qa_verdicts.json")))["verdicts"]
    ex_runs = {v["run_id"] for v in verd if v.get("type") == "run"}
    ex_grids = {tuple(v["grid"]) for v in verd if v.get("type") == "grid"}
    canon = sb.table("canonical_courses").select("name,polyline").execute().data
    canon_g = {}
    for c in canon:
        canon_g[c["name"]] = {(round(p[0] if isinstance(p, list) else p["lat"], 2),
                               round(p[1] if isinstance(p, list) else p["lng"], 2))
                              for p in c["polyline"]}
    tracks = sb.table("run_tracks").select("run_id,points").limit(2000).execute().data
    runs = {r["id"]: r for r in sb.table("runs").select("id,user_id").limit(2000).execute().data}
    profs = {p["user_id"]: p["nickname"] for p in
             sb.table("profiles").select("user_id,nickname").limit(2000).execute().data}
    n_pass = 0
    for t in tracks:
        pts = [(p["lat"], p["lng"]) for p in (t["points"] or []) if "lat" in p]
        if not pts:
            continue
        if t["run_id"] in ex_runs:
            print(f"제외(원장 run) {t['run_id'][:8]}")
            continue
        grids = {(round(a, 2), round(b, 2)) for a, b in pts}
        hit_grid = grids & ex_grids
        if hit_grid:
            print(f"제외(원장 격자 {sorted(hit_grid)[0]}) {t['run_id'][:8]}")
            continue
        r = screen_track(pts)
        if "reject" in r:
            continue
        nick = profs.get((runs.get(t["run_id"]) or {}).get("user_id"), "?")
        dup = [n for n, gs in canon_g.items() if len(grids & gs) >= max(1, len(grids) // 2)]
        n_pass += 1
        flag = f" ⚑{r['flag']}" if r.get("flag") else ""
        dups = f" ⚠중복:{dup[0]}" if dup else ""
        print(f"[{r['tier']:9}] {t['run_id'][:8]} {nick[:10]:10} {r['km']}km 폐합{r['closure']}m "
              f"이중{r['dbl_pct']}% 둘레비{r['bbox_ratio']} 회랑{r['longest_retrace_m']}m"
              f"{flag}{dups}")
    print(f"\n후보 {n_pass}건 (원장 제외·거리·개방·자기중첩·이중주행 통과분)")


if __name__ == "__main__":
    main()
