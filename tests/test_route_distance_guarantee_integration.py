"""
Integration test: AI 코스 목표 거리 ±500m 보장 (ROUTE_DISTANCE_GUARANTEE_DESIGN)

게이트: _SHORT_RATIO=0.6(하한만) → |actual−target| ≤ 0.5km 양방향 일원화.
4회 전패 시 |오차| 최소 후보 + target_missed=true. 프롬프트는 체인 목표
(target/1.45) 명시 + "avoid overshooting" 삭제.

mock 6케이스 (tests.mock_route_app을 8001에 기동 — Gemini·T-map 실호출 0):
 1. 1시도 합격: [4.2] → 채택·missed=false·gemini 1회
 2. 미달 재시도 합격: [2.5, 3.7] → 3.7 채택·false·gemini 2회
 3. 초과 재시도(신규 행동): [4.8, 4.3] → 4.8 반려·4.3 채택 (구 게이트는 4.8 통과)
 4. 4회 전패: [2.5, 2.7, 5.2, 3.2] → 3.2 채택·target_missed=true·gemini 4회
 5. NO_PATH 폴백 회귀: 전부 no_path → AI 추정 유지·폴백 동작 불변
 6. 프롬프트 단위: "avoid overshooting" 부재 + "about 2.8 km"(=4.0/1.45) 포함

+ E2E 실호출 1건(비용 ~2원): |total−4| ≤ 0.5 OR target_missed=true 계약 검증.

Run: python tests/test_route_distance_guarantee_integration.py  (로컬 서버 8000 필요)
"""
from __future__ import annotations

import os, subprocess, sys, time
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # app 임포트용

BASE = "http://localhost:8000"      # gen()이 /api를 붙임 — 중복 금지
B8001 = "http://localhost:8001"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
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


def ok(m):         print(f"  ✓ {m}")
def fail(m, d=""):  print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):       print(f"\n[{t}]")


def sb_user(c, email):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": "test1234", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]


def sb_login(c, email):
    return c.post(f"{_SB}/auth/v1/token?grant_type=password",
                  headers={"apikey": _ANON, "Content-Type": "application/json"},
                  json={"email": email, "password": "test1234"}).json()["access_token"]


def gen(c, token, base=B8001, target=4.0):
    return c.post(f"{base}/api/routes/generate",
                  headers={"Authorization": f"Bearer {token}"},
                  json={"start": {"lat": 37.5445, "lng": 127.0374},
                        "target_distance_km": target})


def scenario(c, seq):
    assert c.post(f"{B8001}/__mock/scenario", json={"seq": seq}).status_code == 200


def stats(c):
    return c.get(f"{B8001}/__mock/stats").json()


def run_tests():
    c = httpx.Client(timeout=120)
    uids = {}
    proc = None
    made_routes = []
    try:
        step("0. 유저(premium — 쿼터 무제한) + mock 서버 8001 기동")
        uids["u"] = sb_user(c, f"rdg-u-{TS}@test.com")
        tok = sb_login(c, f"rdg-u-{TS}@test.com")
        assert c.request("PATCH", f"{BASE}/api/me/profile", headers={"Authorization": f"Bearer {tok}"},
                         json={"nickname": f"RDG{TS}"}).status_code == 200
        c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{uids['u']}", headers=_ADM, json={"tier": "premium"})
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.mock_route_app:app",
             "--port", "8001", "--log-level", "warning"],
            cwd=os.path.join(os.path.dirname(__file__), ".."))
        for _ in range(40):
            try:
                if c.get(f"{B8001}/health").status_code == 200: break
            except Exception: pass
            time.sleep(0.5)
        else:
            fail("mock 서버 기동 실패")
        ok("premium 유저 + mock 8001 up")

        step("1. 1시도 합격 — [4.2] → 채택·missed=false·gemini 1회")
        scenario(c, [{"snap_km": 4.2}])
        r = gen(c, tok)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d["total_distance_km"] == 4.2 and d["target_missed"] is False, d
        assert stats(c)["gemini_calls"] == 1, stats(c)
        ok("4.2 채택 · target_missed=false · gemini 1회")

        step("2. 미달 재시도 합격 — [2.5, 3.7] → 3.7 채택·gemini 2회")
        scenario(c, [{"snap_km": 2.5}, {"snap_km": 3.7}])
        d = gen(c, tok).json()
        assert d["total_distance_km"] == 3.7 and d["target_missed"] is False, d
        assert d["radius_expanded"] is True, "2시도 = 반경 확장 플래그"
        assert stats(c)["gemini_calls"] == 2, stats(c)
        ok("2.5 반려 → 3.7 채택 · gemini 2회 (비용 검증)")

        step("3. ★초과 재시도(신규 행동) — [4.8, 4.3] → 4.8 반려·4.3 채택")
        scenario(c, [{"snap_km": 4.8}, {"snap_km": 4.3}])
        d = gen(c, tok).json()
        assert d["total_distance_km"] == 4.3 and d["target_missed"] is False, d
        assert stats(c)["gemini_calls"] == 2, "4.8이 반려됐다는 증거(구 게이트는 1회에 통과)"
        ok("4.8(+0.8) 반려 → 4.3 채택 — 상한 게이트 작동 (구현 전엔 4.8 즉시 통과)")

        step("4. 4회 전패 — [2.5, 2.7, 5.2, 3.2] → 3.2 채택 + target_missed=true")
        scenario(c, [{"snap_km": 2.5}, {"snap_km": 2.7}, {"snap_km": 5.2}, {"snap_km": 3.2}])
        d = gen(c, tok).json()
        assert d["total_distance_km"] == 3.2, f"|오차| 최소 후보(3.2, −0.8) 채택, got {d['total_distance_km']}"
        assert d["target_missed"] is True, "전패 플래그"
        assert stats(c)["gemini_calls"] == 4, "cap 4 유지"
        ok("전패 → 최소오차 3.2 채택 · target_missed=true · gemini 4회(cap)")

        step("5. NO_PATH 폴백 회귀 — 전부 no_path → AI 추정 유지")
        scenario(c, [{"no_path": True}] * 4)
        d = gen(c, tok).json()
        assert d["total_distance_km"] == 4.0, "AI 추정(=target mock) 폴백 유지"
        assert d["target_missed"] is False, "|4.0−4.0|≤0.5 → 플래그 없음"
        assert d.get("polyline") in (None, []), "폴백은 폴리라인 없음(기존 동작)"
        ok("NO_PATH 4연속 → AI 추정 폴백 · 기존 동작 불변")

        step("6. 프롬프트 단위 검증 (호출 0회)")
        from app.services.openai_service import _build_prompt, _SNAP_INFLATION
        from app.models.schemas import Coordinate
        assert _SNAP_INFLATION == 1.45
        p = _build_prompt(4.0, Coordinate(lat=37.5445, lng=127.0374), None, None, None,
                          radius_km=1.0)
        assert "avoid overshooting" not in p, "과소 기하 유도 문구 삭제"
        assert "about 2.8 km" in p, f"체인 목표(4.0/1.45=2.8) 명시, got: {p[:200]}"
        assert "1.3-1.7x" in p, "팽창 맥락 안내"
        assert "about 4.0 km" in p, "최종 목표 거리도 유지"
        ok("프롬프트: overshooting 부재 · 체인 2.8km · 팽창 1.3-1.7x 안내")

        print("\n" + "=" * 50 + "\n  MOCK 6케이스 PASSED — E2E는 메인 서버로\n" + "=" * 50)

        step("E2E. 실호출 1건 (메인 8000, 비용 ~2원) — 계약 검증")
        r = gen(c, tok, base=BASE)
        assert r.status_code == 200, r.text[:250]
        d = r.json()
        dev = abs(d["total_distance_km"] - 4.0)
        assert dev <= 0.5 or d["target_missed"] is True, \
            f"계약 위반: |{d['total_distance_km']}−4.0|={dev:.2f} > 0.5인데 missed={d['target_missed']}"
        print(f"    실측: total={d['total_distance_km']}km (오차 {dev:+.2f}) "
              f"target_missed={d['target_missed']} radius_expanded={d['radius_expanded']}")
        ok(f"E2E 계약 준수: ±0.5 이내 또는 플래그 (실제 {d['total_distance_km']}km)")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup")
        if proc: proc.terminate()
        # E2E 생성 코스 삭제 (이 유저의 route 전부 — 임시 유저라 안전)
        c.delete(f"{_SB}/rest/v1/routes?user_id=eq.{uids.get('u','')}", headers=_ADM)
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (mock 서버 종료·코스·유저 삭제)")


if __name__ == "__main__":
    run_tests()
