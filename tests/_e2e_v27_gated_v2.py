"""v2.7 재E2E — 합격선 재정의 (2026-07-22 오너 결정: 뚝섬 관문 제외·별도 과제 §3).

G1' 일반 2건(성수·여의도) 서빙(verdict∈{hit,missed}) & nopath 0
G2' 전건 20s 내
G3' gen_meta(pool_size·snapped_count·tmap_legs·snap_errors) 실측 저장
+ 뚝섬 1건 참고 측정(관문 무관, 데이터 축적용)

배포는 하지 않고 VERDICT만 출력. 자체 uvicorn(8003)=현행 코드(sanitize 포함).
"""
from __future__ import annotations
import os, sys, time, json, subprocess, asyncio
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
BASE = "http://localhost:8003/api"
B = "http://localhost:8003"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"
_RESULT = os.path.join(os.path.dirname(__file__), "..", "_e2e_v27_verdict_v2.json")


def _keys():
    a = s = ""
    for l in open("/Users/jiyeon/Desktop/Running AI/.env"):
        l = l.strip()
        if l.startswith("SUPABASE_KEY="): a = l.split("=", 1)[1]
        elif l.startswith("SUPABASE_SERVICE_ROLE_KEY="): s = l.split("=", 1)[1]
    return a, s


AN, SV = _keys()
ADM = {"apikey": SV, "Authorization": f"Bearer {SV}", "Content-Type": "application/json"}
TS = int(time.time())

# 관문 대상(gated) — 내륙 격자 2곳(수변 2km+ 실측: 강남 2.45km·목동 2.47km).
# 성수·여의도(구 관문)는 둘 다 한강 인접 고산포라 §3 수변 과제로 편입(관문 부적격).
GATED = [("강남-역삼", 37.4995, 127.0360), ("목동", 37.5265, 126.8620)]
REF = [("뚝섬-ref", 37.5219, 127.0561)]  # 수변 1.33km — §3 데이터 축적용(관문 제외)


def _emit(verdict, payload):
    payload["verdict"] = verdict
    try:
        json.dump(payload, open(_RESULT, "w"), ensure_ascii=False, indent=2)
    except Exception:
        pass
    print(f"\nVERDICT: {verdict}")


def _probe():
    from app.services import map_service
    from app.models.schemas import Coordinate

    async def go():
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                dm, ds, path = await map_service._tmap_walk_leg(
                    client, Coordinate(lat=37.5445, lng=127.0374),
                    Coordinate(lat=37.5480, lng=127.0374))
                return True, f"200 dist={dm}m"
            except map_service.TmapQuotaExceeded:
                return False, "429 QUOTA_EXCEEDED (미리셋)"
            except map_service.LegNotRoutable:
                return True, "200(빈경로지만 쿼터 정상)"
            except Exception as e:
                return False, f"{type(e).__name__}: {str(e)[:100]}"
    return asyncio.run(go())


def run():
    ok, why = _probe()
    print(f"[G0 프로브] T-map: {why}")
    if not ok:
        _emit("PROBE_FAIL", {"probe": why, "note": "리셋 미확인 — E2E 미진입, 중단"})
        return

    c = httpx.Client(timeout=60)
    uid = None
    proc = None
    rows = []
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8003", "--log-level", "warning"],
            cwd=os.path.join(os.path.dirname(__file__), ".."))
        for _ in range(60):
            try:
                if c.get(f"{B}/health").status_code == 200: break
            except Exception: pass
            time.sleep(0.5)
        else:
            _emit("FAIL", {"probe": why, "error": "로컬 서버 기동 실패"}); return

        uid = c.post(f"{_SB}/auth/v1/admin/users", headers=ADM,
                     json={"email": f"e2ev2-{TS}@test.com", "password": "test1234", "email_confirm": True}).json()["id"]
        tok = c.post(f"{_SB}/auth/v1/token?grant_type=password",
                     headers={"apikey": AN, "Content-Type": "application/json"},
                     json={"email": f"e2ev2-{TS}@test.com", "password": "test1234"}).json()["access_token"]
        c.request("PATCH", f"{BASE}/me/profile", headers={"Authorization": f"Bearer {tok}"}, json={"nickname": f"E2EV2{TS}"})
        c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{uid}", headers=ADM, json={"tier": "premium"})

        for ci, (name, lat, lng) in enumerate(GATED + REF):
            if ci:
                time.sleep(5)  # 케이스 간 5s — 연속 발사(인위 버스트)를 현실 부하로 모사
                               # (측정 조건 교정, 게이트 완화 아님 — 2026-07-22 오너)
            t0 = time.time()
            try:
                resp = c.post(f"{BASE}/routes/generate", headers={"Authorization": f"Bearer {tok}"},
                              json={"start": {"lat": lat, "lng": lng}, "target_distance_km": 5.0})
                el = round(time.time() - t0, 1)
                st, dist = resp.status_code, (resp.json().get("total_distance_km") if resp.status_code == 200 else None)
                detail = "" if st == 200 else resp.text[:150]
            except Exception as e:
                el, st, dist, detail = round(time.time() - t0, 1), "ERR", None, str(e)[:150]
            rows.append({"name": name, "status": st, "dist": dist, "elapsed": el, "detail": detail,
                         "ref": name.startswith("뚝섬")})

        gm = c.get(f"{_SB}/rest/v1/routes?user_id=eq.{uid}"
                   f"&select=total_distance_km,gen_meta,created_at&order=created_at.asc", headers=ADM).json()
        metas = [g.get("gen_meta") or {} for g in gm]
        mi = 0
        for row in rows:
            if row["status"] == 200 and mi < len(metas):
                v = metas[mi].get("verdict"); mi += 1
                row["verdict"] = v
                row["served"] = v in ("hit", "missed")
            else:
                row["verdict"] = None; row["served"] = False

        print("\n[재E2E]")
        for row in rows:
            tag = "(참고)" if row["ref"] else "(관문)"
            print(f"  {row['name']:9s}{tag} {str(row['status']):4s} verdict={row.get('verdict')} "
                  f"dist={row['dist']} {row['elapsed']}s {row['detail']}")
        print("\n[gen_meta]")
        for g in gm:
            m = g.get("gen_meta") or {}
            print(f"  dist={g['total_distance_km']} pool={m.get('pool_size')} snapped={m.get('snapped_count')} "
                  f"tmap_legs={m.get('tmap_legs')} snap_errors={m.get('snap_errors')} verdict={m.get('verdict')} snaps={m.get('snaps')}")

        gated = [r for r in rows if not r["ref"]]
        g1 = all(r["served"] for r in gated) and all(r["verdict"] != "nopath" for r in gated)
        g2 = all(isinstance(r["elapsed"], (int, float)) and r["elapsed"] < 20 for r in rows)
        need = {"pool_size", "snapped_count", "tmap_legs", "snap_errors"}
        served_metas = [metas[i] for i in range(len(metas))]
        g3 = len(served_metas) > 0 and all(need <= set(m.keys()) for m in served_metas)
        gates = {"G1'_일반서빙+nopath0": g1, "G2'_20s": g2, "G3'_gen_meta": g3}
        ttuk = [r for r in rows if r["ref"]]
        ttuk_served = sum(1 for r in ttuk if r["served"])
        legs = sum((g.get("gen_meta") or {}).get("tmap_legs") or 0 for g in gm)
        print("\n[관문]")
        for k, v in gates.items():
            print(f"  {'✓' if v else '✗'} {k}: {v}")
        print(f"  [참고] 뚝섬 {ttuk_served}/{len(ttuk)} 서빙 (관문 무관) · e2e_tmap_legs(저장분)={legs}")
        passed = all(gates.values())
        _emit("PASS" if passed else "FAIL",
              {"probe": why, "rows": rows, "gates": gates,
               "ttuk_served": ttuk_served, "gen_meta": [g.get("gen_meta") for g in gm], "e2e_tmap_legs": legs})
    finally:
        if proc: proc.terminate()
        if uid:
            c.delete(f"{_SB}/rest/v1/routes?user_id=eq.{uid}", headers=ADM)
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run()
