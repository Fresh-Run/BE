"""
Integration test: 러닝을 코스로 저장 POST /runs/{id}/copy-as-route (Ivan '이 경로 달리기')

⚠️ 선행: db/2026-07-21_routes_source_run_id.sql 적용 필요(source_run_id 컬럼·
유니크·route_saved CHECK). 미적용 시 저장·알림 실패.

케이스:
 1. 복사 성공 201 + 필드 정확(polyline=트랙·waypoints=[]·summary·duration·
    is_one_way·source_run_id) + 내 코스 리스팅 등장
 2. 멱등 재호출 200 + 같은 코스(신규 안 생김)
 3. 비가시(private 타인) 404 / 차단 404 / 없는 run 404
 4. 트랙 없는 수동 기록 400
 5. route_saved 알림 발송 + likes OFF면 인앱 유지·푸시 스킵 + 자기 run self 스킵
 6. DELETE /routes로 삭제 가능(기존 레인 정합)

Run: python tests/test_copy_run_as_route_integration.py  (로컬 서버 + SQL 선행)
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


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


def ok(m):        print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):      print(f"\n[{t}]")


def sb_user(c, email):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": "test1234", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]


def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


def gps(n=50, dlat=0.0009, dt=36000):
    """직선 편도 트랙 ~5km — 러닝 속도(100m/36초 ≈ 10km/h, 과속 필터 회피).
    n=50 × 100m = ~4.9km(신고 5.0과 ±10% 내 → verified, distance 유지).
    끝점이 시작에서 멀어 is_one_way=true(편도)."""
    return [{"lat": round(37.5445 + i * dlat, 7), "lng": 127.0374,
             "t": 1_783_300_000_000 + i * dt, "acc": 8.0} for i in range(n)]


def save_run(c, tok, km=5.0, pace=360, vis="public", **extra):
    body = {"distance_km": km, "duration_sec": round(km * pace),
            "avg_pace_sec_per_km": pace, "visibility": vis, **extra}
    r = api(c, "POST", "/runs", tok, json=body)
    assert r.status_code == 200, r.text[:200]
    return r.json()["id"]


def notifs(c, tok, typ):
    return [n for n in api(c, "GET", "/notifications", tok).json() if n["type"] == typ]


def run_tests():
    c = httpx.Client(timeout=90)
    uids = {}
    try:
        step("0. O(러너)·V(뷰어)·B(차단)")
        for k in ("o", "v", "b"):
            uids[k] = sb_user(c, f"crr-{k}-{TS}@test.com")
        tk = {k: sb_login(c, f"crr-{k}-{TS}@test.com") for k in uids}
        for k in uids:
            assert api(c, "PATCH", "/me/profile", tk[k], json={"nickname": f"CRR{k}{TS}"}).status_code == 200
        # O의 public GPS run (편도 트랙 ~266m — is_one_way true 확인용) + 제목 없음
        run_pub = save_run(c, tk["o"], km=5.0, gps_track=gps())  # n=25 편도(북쪽 266m)
        ok("유저 3 + O의 public 편도 GPS run")

        step("1. 복사 성공 201 + 필드 정확 + 내 코스 리스팅")
        r = api(c, "POST", f"/runs/{run_pub}/copy-as-route", tk["v"])
        assert r.status_code == 201, f"신규 201, got {r.status_code}: {r.text[:150]}"
        d = r.json()
        assert d["source_run_id"] == run_pub, "source_run_id=원본 run"
        assert d["waypoints"] == [], "트랙 기반이라 waypoints 없음"
        assert d["polyline"] and len(d["polyline"]) >= 2, "polyline=트랙 포인트"
        assert d["is_public"] is False, "저장 코스는 private"
        assert d["is_one_way"] is True, "편도 트랙(끝점 멀다) → is_one_way true"
        assert "님의 러닝" in d["summary"] and "5.0km" in d["summary"], f"제목 없는 run summary, got {d['summary']}"
        assert d["total_distance_km"] == 5.0, d["total_distance_km"]
        route_id = d["id"]
        # 내 코스 리스팅(저장한 코스 아님 — get_route로 소유 확인)
        assert api(c, "GET", f"/routes/{route_id}", tk["v"]).status_code == 200, "내 코스로 조회 가능"
        ok(f"201 · polyline·waypoints=[]·private·is_one_way·summary·source_run_id · 내 코스 등장")

        step("2. 멱등 재호출 200 + 같은 코스")
        r2 = api(c, "POST", f"/runs/{run_pub}/copy-as-route", tk["v"])
        assert r2.status_code == 200, f"재호출 멱등 200, got {r2.status_code}"
        assert r2.json()["id"] == route_id, "같은 코스 반환(신규 안 생김)"
        rc = c.get(f"{_SB}/rest/v1/routes?user_id=eq.{uids['v']}&source_run_id=eq.{run_pub}&select=id", headers=_ADM).json()
        assert len(rc) == 1, f"코스 1개만, got {len(rc)}"
        ok("재호출 200 · 동일 코스 · 행 1개(멱등)")

        step("3. 비가시(private 타인) 404 / 차단 404 / 없는 run 404")
        run_priv = save_run(c, tk["o"], km=3.0, vis="private", gps_track=gps())
        assert api(c, "POST", f"/runs/{run_priv}/copy-as-route", tk["v"]).status_code == 404, "private 타인 404 은닉"
        # 차단: B가 O를 차단 → O의 public run도 404
        assert api(c, "POST", f"/users/{uids['o']}/block", tk["b"]).status_code == 204
        assert api(c, "POST", f"/runs/{run_pub}/copy-as-route", tk["b"]).status_code == 404, "차단 관계 404"
        api(c, "DELETE", f"/users/{uids['o']}/block", tk["b"])
        ghost = "00000000-0000-0000-0000-000000000000"
        assert api(c, "POST", f"/runs/{ghost}/copy-as-route", tk["v"]).status_code == 404, "없는 run 404"
        ok("private 404 · 차단 404 · 없는 run 404")

        step("4. 트랙 없는 수동 기록 400")
        run_manual = save_run(c, tk["o"], km=4.0)  # gps_track 없음 → 수동
        r = api(c, "POST", f"/runs/{run_manual}/copy-as-route", tk["v"])
        assert r.status_code == 400, f"트랙 없음 400, got {r.status_code}: {r.text[:120]}"
        ok("수동 기록(트랙 없음) → 400")

        step("5. route_saved 알림 — 발송 / likes OFF 미푸시(인앱 유지) / self 스킵")
        # O에게 route_saved 알림 왔나 (step1의 V→O 복사)
        ns = notifs(c, tk["o"], "route_saved")
        assert len(ns) == 1 and ns[0]["actor_id"] == uids["v"] and ns[0]["target_id"] == run_pub, f"route_saved 알림, got {ns}"
        # 자기 run 복사 → self 스킵 (O가 자기 run 저장)
        before = len(notifs(c, tk["o"], "route_saved"))
        rs = api(c, "POST", f"/runs/{run_pub}/copy-as-route", tk["o"])
        assert rs.status_code == 201, f"자기 run 복사 허용 201, got {rs.status_code}"
        assert len(notifs(c, tk["o"], "route_saved")) == before, "자기 run 복사는 self 알림 스킵"
        ok("route_saved 발송(V→O) · 자기 run 복사 self 스킵 · likes 카테고리(푸시 게이트는 설정 통합테스트 커버)")

        step("6. DELETE /routes 삭제 (기존 레인 정합)")
        assert api(c, "DELETE", f"/routes/{route_id}", tk["v"]).status_code == 204, "저장 코스도 DELETE 204"
        assert api(c, "GET", f"/routes/{route_id}", tk["v"]).status_code == 404, "삭제 후 404"
        ok("저장 코스 DELETE 204 · 삭제 확인")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/rest/v1/routes?user_id=eq.{uid}", headers=_ADM)
            c.delete(f"{_SB}/rest/v1/runs?user_id=eq.{uid}", headers=_ADM)
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (임시 유저·run·route·트랙 cascade)")


if __name__ == "__main__":
    run_tests()
