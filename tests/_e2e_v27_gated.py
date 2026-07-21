"""v2.7 E2E 자동 관문 러너 (2026-07-22 자정 리셋 후 무인 실행 — 오너 완전 자동 승인).

⚠️ 로컬 E2E 하네스(underscore 접두 = 로컬 전용). 실 Gemini + 실 T-map 호출.
자족: 자체 uvicorn(8003) 기동 → T-map 리셋 프로브 1콜 → E2E 5건 → 기계 판정 →
정리. 배포는 이 스크립트가 하지 않는다(호출한 에이전트가 VERDICT 읽고 fly deploy).

관문(오너 명문화 2026-07-21, 애매=불합격):
 G0 프로브: T-map 1콜 200 확인. 429/기타 → STOP(전체 중단, E2E 미진입).
 G1 뚝섬 3건 중 서빙(verdict∈{hit,missed}) ≥ 2.
 G2 verdict=nopath 0건 (전 5건).
 G3 일반 2건(성수·여의도) 서빙.
 G4 전건 20s 내.
 G5 gen_meta(pool_size·snapped_count·tmap_legs·snap_errors) 실측 저장(서빙분).
 하나라도 미달/애매 → FAIL(배포 보류). 전부 충족 → PASS.

출력: 마지막 줄 `VERDICT: PASS|FAIL|PROBE_FAIL` + 표 + JSON(파일).
Run: python tests/_e2e_v27_gated.py
"""
from __future__ import annotations
import os, sys, time, json, subprocess, asyncio
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = "http://localhost:8003/api"
B = "http://localhost:8003"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"
_RESULT = os.path.join(os.path.dirname(__file__), "..", "_e2e_v27_verdict.json")


def _keys():
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):              anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}
TS = int(time.time())

CASES = [
    ("뚝섬-1", 37.5219, 127.0561), ("뚝섬-2", 37.5219, 127.0561),
    ("뚝섬-3", 37.5219, 127.0561), ("성수", 37.5445, 127.0374),
    ("여의도", 37.5285, 126.9328),
]


def _emit(verdict: str, payload: dict):
    payload["verdict"] = verdict
    try:
        json.dump(payload, open(_RESULT, "w"), ensure_ascii=False, indent=2)
    except Exception:
        pass
    print(f"\nVERDICT: {verdict}")


def _probe() -> tuple[bool, str]:
    """T-map 리셋 확인 — 육상 leg 1콜. 200이면 (True), 429/기타면 (False, 사유)."""
    from app.services import map_service
    from app.models.schemas import Coordinate

    async def go():
        o = Coordinate(lat=37.5445, lng=127.0374)
        d = Coordinate(lat=37.5480, lng=127.0374)
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                dm, ds, path = await map_service._tmap_walk_leg(client, o, d)
                return True, f"200 dist={dm}m"
            except map_service.TmapQuotaExceeded:
                return False, "429 QUOTA_EXCEEDED (아직 미리셋)"
            except map_service.LegNotRoutable:
                return True, "200(빈경로지만 쿼터 정상 — 리셋 확인)"
            except Exception as e:
                return False, f"{type(e).__name__}: {str(e)[:100]}"

    return asyncio.run(go())


def run():
    # ── G0 프로브(서버 무관, 직접 T-map 1콜) ───────────────────────────────
    ok, why = _probe()
    print(f"[G0 프로브] T-map: {why}")
    if not ok:
        _emit("PROBE_FAIL", {"probe": why,
              "note": "리셋 미확인 — E2E 미진입, 전체 중단(추정 진행 금지)"})
        return

    c = httpx.Client(timeout=60)
    uid = None
    proc = None
    rows = []
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8003",
             "--log-level", "warning"],
            cwd=os.path.join(os.path.dirname(__file__), ".."))
        for _ in range(60):
            try:
                if c.get(f"{B}/health").status_code == 200: break
            except Exception: pass
            time.sleep(0.5)
        else:
            _emit("FAIL", {"probe": why, "error": "로컬 서버 8003 기동 실패"})
            return

        r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                   json={"email": f"e2eg-{TS}@test.com", "password": "test1234", "email_confirm": True})
        uid = r.json()["id"]
        tok = c.post(f"{_SB}/auth/v1/token?grant_type=password",
                     headers={"apikey": _ANON, "Content-Type": "application/json"},
                     json={"email": f"e2eg-{TS}@test.com", "password": "test1234"}).json()["access_token"]
        c.request("PATCH", f"{BASE}/me/profile", headers={"Authorization": f"Bearer {tok}"},
                  json={"nickname": f"E2EG{TS}"})
        c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{uid}", headers=_ADM, json={"tier": "premium"})

        for name, lat, lng in CASES:
            t0 = time.time()
            try:
                resp = c.post(f"{BASE}/routes/generate",
                              headers={"Authorization": f"Bearer {tok}"},
                              json={"start": {"lat": lat, "lng": lng}, "target_distance_km": 5.0})
                el = round(time.time() - t0, 1)
                st = resp.status_code
                dist = resp.json().get("total_distance_km") if st == 200 else None
                detail = "" if st == 200 else resp.text[:160]
            except Exception as e:
                el = round(time.time() - t0, 1); st = "ERR"; dist = None; detail = str(e)[:160]
            rows.append({"name": name, "status": st, "dist": dist, "elapsed": el, "detail": detail})

        # gen_meta 실측 조회 (created_at desc → 역순으로 CASES에 매핑)
        gm = c.get(f"{_SB}/rest/v1/routes?user_id=eq.{uid}"
                   f"&select=total_distance_km,gen_meta,created_at&order=created_at.asc",
                   headers=_ADM).json()
        # 서빙된 케이스만 routes 행이 생김(503/502는 미저장). created_at asc = 호출 순.
        metas = [g.get("gen_meta") or {} for g in gm]

        # 케이스별 verdict 매핑: 저장 순서(asc)가 CASES 순서와 일치(순차 호출).
        served_flags = []   # per case: 'served'(hit/missed) | 'nopath' | 'fail'
        mi = 0
        for row in rows:
            if row["status"] == 200 and mi < len(metas):
                v = metas[mi].get("verdict"); mi += 1
                if v in ("hit", "missed"):
                    served_flags.append("served"); row["verdict"] = v
                elif v == "nopath":
                    served_flags.append("nopath"); row["verdict"] = "nopath"
                else:
                    served_flags.append("fail"); row["verdict"] = v
            else:
                served_flags.append("fail"); row["verdict"] = None

        print("\n[E2E 5건]")
        for row, fl in zip(rows, served_flags):
            print(f"  {row['name']:8s} {str(row['status']):4s} {fl:7s} "
                  f"verdict={row.get('verdict')} dist={row['dist']} {row['elapsed']}s {row['detail']}")
        print("\n[gen_meta 실측]")
        for g in gm:
            m = g.get("gen_meta") or {}
            print(f"  dist={g['total_distance_km']} pool={m.get('pool_size')} "
                  f"snapped={m.get('snapped_count')} tmap_legs={m.get('tmap_legs')} "
                  f"snap_errors={m.get('snap_errors')} verdict={m.get('verdict')}")

        # ── 기계 판정 ──────────────────────────────────────────────────────
        ttuk = [f for r, f in zip(rows, served_flags) if r["name"].startswith("뚝섬")]
        norm = [f for r, f in zip(rows, served_flags) if not r["name"].startswith("뚝섬")]
        g1 = sum(1 for f in ttuk if f == "served") >= 2
        g2 = sum(1 for f in served_flags if f == "nopath") == 0
        g3 = all(f == "served" for f in norm)
        g4 = all(isinstance(r["elapsed"], (int, float)) and r["elapsed"] < 20 for r in rows)
        need = {"pool_size", "snapped_count", "tmap_legs", "snap_errors"}
        g5 = all(need <= set(m.keys()) for r, m in zip(
            [r for r in rows if r["status"] == 200], metas)) and len(metas) > 0
        gates = {"G1_뚝섬서빙≥2": g1, "G2_nopath0": g2, "G3_일반서빙": g3,
                 "G4_20s내": g4, "G5_gen_meta": g5}
        total_legs = sum((g.get("gen_meta") or {}).get("tmap_legs") or 0 for g in gm)
        print("\n[관문]")
        for k, v in gates.items():
            print(f"  {'✓' if v else '✗'} {k}: {v}")
        passed = all(gates.values())
        _emit("PASS" if passed else "FAIL",
              {"probe": why, "rows": rows, "served_flags": served_flags,
               "gates": gates, "gen_meta": [g.get("gen_meta") for g in gm],
               "e2e_tmap_legs": total_legs})
    finally:
        if proc: proc.terminate()
        if uid:
            c.delete(f"{_SB}/rest/v1/routes?user_id=eq.{uid}", headers=_ADM)
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (서버 종료·유저·코스 삭제)")


if __name__ == "__main__":
    run()
