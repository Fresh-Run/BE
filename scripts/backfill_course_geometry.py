"""코스 지오메트리 백필 — 시드 코스의 null polyline/waypoints 채우기 (2026-07-15).

배경: 시드 코스가 `waypoints:[]`+polyline null로 저장돼 프론트 코스 카드가
"네온 폴백"으로 렌더됐다(스테이징 routes 21/49 지오메트리 부재 — Ivan 진단).
`sb_insert_route`는 패치했으나(재시드 대비), 기존 스테이징 행은 리시드 없이
**핀포인트 PATCH**로 backfill(run·kudos·세션 등 나머지 세계 무접촉).

범위: **시드 계정(test1/test2/demo1~5) 소유 + polyline null** 행만. 비시드/실계정
코스는 건드리지 않음. 멱등: 이미 polyline 있으면 스킵.

포맷: `course_geometry.derive_geometry`(시더와 단일 소스) → 실제 앱 저장 경로와
동일한 Coordinate[]/Waypoint[].

실행: python scripts/backfill_course_geometry.py
"""
from __future__ import annotations

import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(__file__))
from course_geometry import derive_geometry, load_tracks

_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _svc_key() -> str:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    with open(env) as f:
        for line in f:
            if line.strip().startswith("SUPABASE_SERVICE_ROLE_KEY="):
                return line.strip().split("=", 1)[1]
    raise SystemExit("SERVICE_ROLE 키 없음")


def main() -> None:
    svc = _svc_key()
    adm = {"apikey": svc, "Authorization": f"Bearer {svc}"}
    c = httpx.Client(timeout=30)
    tracks = load_tracks()

    users = {u["id"]: u["email"].split("@")[0]
             for u in c.get(f"{_SB}/auth/v1/admin/users", headers=adm,
                            params={"per_page": "200"}).json()["users"]}
    seed = {uid for uid, e in users.items()
            if e in ("test1", "test2") or e.startswith("demo")}

    rows = c.get(f"{_SB}/rest/v1/routes", headers=adm,
                 params={"select": "id,summary,polyline,user_id,start_lat,start_lng",
                         "limit": "500"}).json()
    targets = [x for x in rows
               if not x.get("polyline")           # null 지오메트리만
               and x["user_id"] in seed            # 시드 소유만
               and x.get("start_lat") is not None]

    print(f"백필 대상: {len(targets)}행 (시드 소유 + polyline null + start 좌표 有)")
    skipped_no_start = [x for x in rows
                        if not x.get("polyline") and x["user_id"] in seed
                        and x.get("start_lat") is None]
    if skipped_no_start:
        print(f"⚠️ start 좌표 없어 스킵: {len(skipped_no_start)}행 (판단 플래그)")

    done = 0
    for x in targets:
        poly, wp = derive_geometry(x["start_lat"], x["start_lng"],
                                   x.get("summary") or "", tracks)
        r = c.patch(f"{_SB}/rest/v1/routes?id=eq.{x['id']}", headers=adm,
                    json={"polyline": poly, "waypoints": wp})
        status = "✓" if r.status_code in (200, 204) else f"✗{r.status_code}"
        print(f"  {status} {users[x['user_id']]:6} '{(x.get('summary') or '')[:26]}' "
              f"→ {len(poly)}pt")
        if r.status_code in (200, 204):
            done += 1

    # 검증: 시드 코스 전수 재조회
    rows2 = c.get(f"{_SB}/rest/v1/routes", headers=adm,
                  params={"select": "id,polyline,waypoints,user_id", "limit": "500"}).json()
    seed_rows = [x for x in rows2 if x["user_id"] in seed]
    have_geo = sum(1 for x in seed_rows if x.get("polyline") and x.get("waypoints"))
    print(f"\n백필 {done}건 완료.")
    print(f"검증: 시드 코스 {have_geo}/{len(seed_rows)} 지오메트리 보유")


if __name__ == "__main__":
    main()
