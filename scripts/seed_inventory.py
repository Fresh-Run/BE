"""run 궤적 → 캐노니컬 시드 재고 조사 (읽기 전용, 재사용 — 2026-07-29 v1).

실유저 run 전수에서 "시드 재료급"을 뽑는다: verified + acc ≤10m + 거리 ≥2km +
기존 캐노니컬 중첩 <50%. 루프/구간 판별·같은 격자 반복 주행(다유저 동일 회랑)
신호 포함. 천곡·습지 레시피(실유저 궤적 시드)의 입구 계기판.

자동화 착수 트리거(2026-07-30 재설정): **다유저 동일회랑 3건+ 또는 미처리 재료급
동시 5건+** — 1회랑·2명 규모는 수동 레시피가 더 쌈(제주 이호테우 건으로 실증,
배치7 수동 등재). 평택(36.95,127.04) 격자는 부대 내부 전례(§8.19 ⑤)로 재제외.

Run: python scripts/seed_inventory.py
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from supabase import create_client  # noqa: E402

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

# 스키마 자가검증 대상 — 이 스크립트가 참조하는 (테이블, 컬럼) 전목록.
# 드리프트 시 조용히 빈 값 대신 시끄럽게 죽는다(§B). select문 수정 시 여기도 갱신.
_SCHEMA_REFS = {
    "profiles": ["user_id", "nickname"],
    "runs": ["id", "user_id", "ran_at", "distance_km", "verification", "title",
             "start_lat", "start_lng", "route_id"],
    "run_tracks": ["run_id", "points", "avg_accuracy_m",
                   "raw_point_count", "kept_point_count"],
    "canonical_courses": ["name", "polyline"],
}


def verify_schema():
    """PostgREST 루트 OpenAPI(실카탈로그에서 생성)로 (테이블,컬럼) 일괄 대조."""
    import httpx
    k = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    spec = httpx.get(os.environ["SUPABASE_URL"] + "/rest/v1/",
                     headers={"apikey": k, "Authorization": f"Bearer {k}"},
                     timeout=30).json()
    defs = spec.get("definitions", {})
    missing = []
    for table, cols in _SCHEMA_REFS.items():
        actual = set(defs.get(table, {}).get("properties", {}))
        if not actual:
            missing.append(f"{table} (테이블 없음)")
            continue
        missing += [f"{table}.{c}" for c in cols if c not in actual]
    if missing:
        sys.exit("[스키마 드리프트] DB에 없는 참조: " + ", ".join(missing))


# 데모·운영·테스트 계정(시드 재료 제외) — DEMO_ACCOUNTS.md 기준
_EXCLUDED_EMAIL_HINTS = ("@freshrun.com", "freshrun0609", "ascreview")
# 닉네임이 아니라 user_id로 제외(2026-07-30 — '이준'→'이반' 닉변으로 dev 6런 혼입 전례)
_EXCLUDED_USER_IDS = {"1c6e6330-fb15-480c-abac-8656033812ea"}  # Ivan(프론트 개발)


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*6371000*math.asin(math.sqrt(h))


def resample(pts, step=20):
    out = [tuple(pts[0])]
    for i in range(len(pts)-1):
        d = hav(tuple(pts[i]), tuple(pts[i+1]))
        n = max(1, int(d // step))
        for k in range(1, n+1):
            t = k/n
            out.append((pts[i][0]+(pts[i+1][0]-pts[i][0])*t,
                        pts[i][1]+(pts[i+1][1]-pts[i][1])*t))
    return out


def coverage(a_pts, b_pts, near=40):
    """a 점 중 b 40m 이내 비율(%) — 리샘플 기반."""
    b = resample(b_pts)[::2]
    a = resample(a_pts)[::2]
    hit = sum(1 for p in a if min(hav(p, q) for q in b) <= near)
    return 100*hit/len(a)


def _load_qa_verdicts() -> tuple[dict, dict]:
    """오너 QA 기각 원장 로드 — ({run_id: 사유}, {(lat2, lng2): 사유}).
    run 기각·grid 재제외 모두 ★ 후보에서 제외하고 '기각됨' 표기(재발굴 방지)."""
    import json
    path = os.path.join(os.path.dirname(__file__), "seed_qa_verdicts.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}, {}
    runs_r, grids_r = {}, {}
    for v in data.get("verdicts", []):
        if v.get("verdict") != "rejected":
            continue
        if v.get("type", "run") == "grid":
            grids_r[tuple(v["grid"])] = v["reason"]
        else:
            runs_r[v["run_id"]] = v["reason"]
    return runs_r, grids_r


def _is_rejected(run_id: str, grid, runs_r: dict, grids_r: dict) -> str | None:
    """기각 사유 반환(미기각이면 None) — run 개별 우선, 다음 격자."""
    if run_id in runs_r:
        return runs_r[run_id]
    if grid is not None and tuple(grid) in grids_r:
        return grids_r[tuple(grid)]
    return None


def main():
    import httpx
    verify_schema()
    k = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    users, page = [], 1
    while True:
        b = httpx.get(os.environ["SUPABASE_URL"]+f"/auth/v1/admin/users?per_page=100&page={page}",
                      headers={"apikey": k, "Authorization": f"Bearer {k}"}, timeout=30).json()["users"]
        users += b
        if len(b) < 100:
            break
        page += 1
    email = {u["id"]: (u.get("email") or "") for u in users}
    nick = {p["user_id"]: p["nickname"] for p in
            sb.table("profiles").select("user_id,nickname").execute().data}

    def is_real(uid):
        e = email.get(uid, "")
        if any(h in e for h in _EXCLUDED_EMAIL_HINTS):
            return False
        return uid not in _EXCLUDED_USER_IDS

    runs = sb.table("runs").select(
        "id,user_id,ran_at,distance_km,verification,title,start_lat,start_lng,route_id"
    ).execute().data
    tracks = {t["run_id"]: t for t in sb.table("run_tracks").select("*").execute().data}
    canon = sb.table("canonical_courses").select("name,polyline").execute().data
    cpolys = [( c["name"], [(p[0], p[1]) if isinstance(p, list) else (p["lat"], p["lng"])
                            for p in c["polyline"]]) for c in canon]

    qa_runs, qa_grids = _load_qa_verdicts()
    real = [r for r in runs if is_real(r["user_id"])]
    print(f"실유저 run: {len(real)}건 (전체 {len(runs)}건, 제외 계정분 {len(runs)-len(real)})")
    rows, seedable = [], []
    for r in real:
        t = tracks.get(r["id"])
        if not t or not t.get("points"):
            rows.append((r, None, None, None, "트랙 없음"))
            continue
        pts = [(p["lat"], p["lng"]) if isinstance(p, dict) else (p[0], p[1])
               for p in t["points"]]
        best_cov, best_name = 0.0, "-"
        for name, cp in cpolys:
            if hav(pts[0], cp[0]) > 30000:   # 30km 밖 코스는 스킵(비용)
                continue
            c = coverage(pts, cp)
            if c > best_cov:
                best_cov, best_name = c, name
        closure = hav(pts[0], pts[-1])
        kind = "루프" if closure < 150 else ("구간(왕복)" if best_cov < 200 else "?")
        grid = (round(r["start_lat"], 2), round(r["start_lng"], 2)) if r.get("start_lat") else None
        ok_seed = (r["verification"] == "verified" and (t.get("avg_accuracy_m") or 99) <= 10
                   and (r["distance_km"] or 0) >= 2.0 and best_cov < 50)
        rows.append((r, t, best_cov, best_name, kind))
        _rej = _is_rejected(r["id"], grid, qa_runs, qa_grids) if ok_seed else None
        if ok_seed and _rej:
            print(f"  [기각됨] {nick.get(r['user_id'],'?')} {r['distance_km']}km "
                  f"{grid} — {_rej[:60]}")
        elif ok_seed:
            seedable.append((r, t, best_cov, best_name, kind, grid, pts))
        print(f"  {nick.get(r['user_id'],'?'):10} | {grid} | {r['distance_km']}km {r['verification']} "
              f"| acc {t.get('avg_accuracy_m')}m {t.get('raw_point_count')}→{t.get('kept_point_count')} "
              f"| route_id {'유' if r.get('route_id') else '무'} | 캐노니컬 최대중첩 {best_cov:.0f}%({best_name[:12]}) "
              f"| {kind} 폐합{closure:.0f}m | '{r.get('title')}'")

    print(f"\n=== 시드 재료급(verified·acc≤10·≥2km·캐노니컬 중첩<50%): {len(seedable)}건 ===")
    print("⚠️ 접근성(§8.19 ⑤ — 군부대·사유지·통제구역)은 자동 판별 불가 — 오너 확인 필수"
          " (전례: 평택 건 만점 지표였으나 부대 내부)")
    # 다유저 동일 회랑(히트맵 씨앗): 재료급 + 전체 실유저 트랙 간 pairwise
    all_tracks = [(r, [(p["lat"], p["lng"]) if isinstance(p, dict) else (p[0], p[1])
                       for p in tracks[r["id"]]["points"]])
                  for r in real if r["id"] in tracks and tracks[r["id"]].get("points")]
    for s in seedable:
        r, t, cov_, name, kind, grid, pts = s
        mates = []
        for r2, pts2 in all_tracks:
            if r2["id"] == r["id"] or r2["user_id"] == r["user_id"]:
                continue
            if hav(pts[0], pts2[0]) > 5000:
                continue
            c = coverage(pts2, pts)
            if c >= 60:
                mates.append((nick.get(r2["user_id"], "?"), round(c)))
        print(f"  ★ {nick.get(r['user_id'],'?')} {grid} {r['distance_km']}km {kind} "
              f"중첩{cov_:.0f}% — 동일회랑 타유저: {mates or '없음'}")


if __name__ == "__main__":
    main()
