"""E2E: 중립 라벨 실전 검증 (§3 축 B, 2026-07-22) — 실 Gemini+T-map, 로컬 8003.

강남·목동(내륙)+청라(라벨 hallucination 재현 지역) 3건 생성 → 서빙 응답의
웨이포인트 라벨이 중립(출발/지점 N/복귀·도착)인지, pitstop만 Kakao 실명인지,
제목이 중립 템플릿인지, 창작 지명이 0인지 검증. 케이스 간 5s.

관문: 강남·목동 서빙(무회귀) + 전 서빙 응답에 창작 지명 0 + 라벨 중립.
"""
from __future__ import annotations
import os, sys, time, json, subprocess, asyncio
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
BASE = "http://localhost:8003/api"; B = "http://localhost:8003"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"
_RESULT = os.path.join(os.path.dirname(__file__), "..", "_e2e_neutral_verdict.json")


def _keys():
    a = s = ""
    for l in open("/Users/jiyeon/Desktop/Running AI/.env"):
        l = l.strip()
        if l.startswith("SUPABASE_KEY="): a = l.split("=", 1)[1]
        elif l.startswith("SUPABASE_SERVICE_ROLE_KEY="): s = l.split("=", 1)[1]
    return a, s


AN, SV = _keys(); ADM = {"apikey": SV, "Authorization": f"Bearer {SV}", "Content-Type": "application/json"}
TS = int(time.time())
# (이름, lat, lng, pitstop) — 청라는 실사용 재현 위해 pitstop "공원" 포함
CASES = [("강남", 37.4995, 127.0360, None), ("목동", 37.5265, 126.8620, None),
         ("청라", 37.5242, 126.6303, "공원")]
_NEUTRAL_PREFIX = ("출발", "복귀", "도착")
# 창작 의심 토큰 — 서버 중립 라벨엔 절대 없어야(pitstop=Kakao 실명은 예외 취급)
_HALLU = ("경기장", "공촌", "연희", "아시아드", "대교", "초등", "아파트")


def _emit(v, p):
    p["verdict"] = v
    try: json.dump(p, open(_RESULT, "w"), ensure_ascii=False, indent=2)
    except Exception: pass
    print(f"\nVERDICT: {v}")


def _probe():
    from app.services import map_service
    from app.models.schemas import Coordinate
    async def go():
        async with httpx.AsyncClient(timeout=10) as c:
            try:
                dm, _, _ = await map_service._tmap_walk_leg(c, Coordinate(lat=37.5445, lng=127.0374), Coordinate(lat=37.5460, lng=127.0374))
                return True, f"200 {dm}m"
            except Exception as e: return False, f"{type(e).__name__}: {str(e)[:80]}"
    return asyncio.run(go())


def _label_ok(name, is_pitstop):
    if is_pitstop:
        return True  # pitstop = Kakao 실명 허용
    return name in _NEUTRAL_PREFIX or name.startswith("지점 ")


def run():
    ok, why = _probe()
    print(f"[G0 프로브] {why}")
    if not ok:
        _emit("PROBE_FAIL", {"probe": why}); return
    c = httpx.Client(timeout=60); uid = None; proc = None; rows = []
    try:
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8003", "--log-level", "warning"],
                                cwd=os.path.join(os.path.dirname(__file__), ".."))
        for _ in range(60):
            try:
                if c.get(f"{B}/health").status_code == 200: break
            except Exception: pass
            time.sleep(0.5)
        else:
            _emit("FAIL", {"error": "서버 기동 실패"}); return
        uid = c.post(f"{_SB}/auth/v1/admin/users", headers=ADM, json={"email": f"nl-{TS}@test.com", "password": "test1234", "email_confirm": True}).json()["id"]
        tok = c.post(f"{_SB}/auth/v1/token?grant_type=password", headers={"apikey": AN, "Content-Type": "application/json"}, json={"email": f"nl-{TS}@test.com", "password": "test1234"}).json()["access_token"]
        c.request("PATCH", f"{BASE}/me/profile", headers={"Authorization": f"Bearer {tok}"}, json={"nickname": f"NL{TS}"})
        c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{uid}", headers=ADM, json={"tier": "premium"})

        for ci, (name, lat, lng, pit) in enumerate(CASES):
            if ci: time.sleep(5)
            body = {"start": {"lat": lat, "lng": lng}, "target_distance_km": 5.0}
            if pit: body["pitstop_keyword"] = pit
            t0 = time.time()
            r = c.post(f"{BASE}/routes/generate", headers={"Authorization": f"Bearer {tok}"}, json=body)
            el = round(time.time() - t0, 1)
            row = {"name": name, "status": r.status_code, "elapsed": el}
            if r.status_code == 200:
                d = r.json()
                wps = [(w["name"], w.get("is_pitstop", False)) for w in d.get("waypoints", [])]
                row["summary"] = d.get("summary"); row["dist"] = d.get("total_distance_km")
                row["labels"] = wps
                # 라벨 중립성 + 창작 지명 검사
                bad_label = [nm for nm, isp in wps if not _label_ok(nm, isp)]
                # 창작 토큰(비-pitstop 라벨·summary에)
                non_pit_text = d.get("summary", "") + " " + " ".join(nm for nm, isp in wps if not isp)
                hallu = [h for h in _HALLU if h in non_pit_text]
                summ_ok = d.get("summary", "").endswith(("순환 코스", "편도 코스"))
                row["bad_label"] = bad_label; row["hallu"] = hallu; row["summ_ok"] = summ_ok
            else:
                row["detail"] = r.text[:100]
            rows.append(row)

        print("\n[결과]")
        for r in rows:
            if r["status"] == 200:
                print(f"  {r['name']:5s} 200 dist={r['dist']} '{r['summary']}' labels={r['labels']} "
                      f"bad={r['bad_label']} hallu={r['hallu']}")
            else:
                print(f"  {r['name']:5s} {r['status']} {r.get('detail','')}")

        served = [r for r in rows if r["status"] == 200]
        # 관문: 강남·목동 서빙 무회귀
        inland_served = all(r["status"] == 200 for r in rows if r["name"] in ("강남", "목동"))
        # 전 서빙 응답: 라벨 중립 + 창작 지명 0 + 제목 중립
        labels_clean = all(not r["bad_label"] and not r["hallu"] and r["summ_ok"] for r in served)
        gates = {"내륙_서빙무회귀": inland_served, "라벨중립_창작지명0": labels_clean,
                 "서빙건_존재": len(served) > 0}
        print("\n[관문]")
        for k, v in gates.items(): print(f"  {'✓' if v else '✗'} {k}: {v}")
        cheongna = next((r for r in rows if r["name"] == "청라"), {})
        print(f"  [참고] 청라 status={cheongna.get('status')} labels={cheongna.get('labels','(미서빙)')}")
        passed = all(gates.values())
        _emit("PASS" if passed else "FAIL", {"probe": why, "rows": rows, "gates": gates})
    finally:
        if proc: proc.terminate()
        if uid:
            c.delete(f"{_SB}/rest/v1/routes?user_id=eq.{uid}", headers=ADM)
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=ADM)
        print("  정리 완료")


if __name__ == "__main__":
    run()
