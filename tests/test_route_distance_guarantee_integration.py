"""
Integration test: AI 코스 목표 거리 보장 v2 — 비대칭 밴드 (ROUTE_DISTANCE_GUARANTEE_DESIGN)

게이트 v2 (2026-07-20, TF 낙산 5km→3.0km 사례 계기): **target ≤ actual ≤ target+0.3**
만 합격 — 미달 무조건 불합격(−허용 0), 초과 +300m. 구 ±0.5 대칭 밴드 대체.
전패 시 초과 후보 우선(목표 최근접), 없으면 미달 최장 + target_missed=true.
프롬프트 조준점은 밴드 중앙 (target+0.15)/1.45.

mock 7케이스 (tests.mock_route_app을 8001에 기동 — Gemini·T-map 실호출 0):
 1. 1시도 합격: [4.2] → 채택(밴드 [4.0,4.3] 내)·missed=false·gemini 1회
 2. ★근소 미달 반려(신규): [3.7, 4.1] → 3.7 반려(구 게이트는 통과)·4.1 채택·gemini 2회
 3. 초과 재시도: [4.8, 4.3] → 4.8 반려·4.3 채택(상한 경계)
 4. 4회 전패(초과 존재): [2.5, 2.7, 5.2, 3.2] → ★5.2 채택(초과 우선 — 구 로직은
    |오차| 최소 3.2)·target_missed=true·gemini 4회
 4b. 4회 전패(전부 미달): [2.5, 2.7, 3.0, 3.2] → 미달 최장 3.2·missed=true
 5. NO_PATH 폴백 회귀: 전부 no_path → AI 추정(=target, 밴드 내) 유지·missed=false
 6. 프롬프트 단위: "about 2.9 km"((4.0+0.15)/1.45) + "err slightly longer" 포함

+ E2E 실호출 1건(비용 ~2원): (4.0 ≤ total ≤ 4.3) OR target_missed=true 계약 검증.

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

        step("1. 1시도 합격 — [4.2] → 채택(밴드 [4.0,4.3] 내)·missed=false·gemini 1회")
        scenario(c, [{"snap_km": 4.2}])
        r = gen(c, tok)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d["total_distance_km"] == 4.2 and d["target_missed"] is False, d
        assert stats(c)["gemini_calls"] == 1, stats(c)
        ok("4.2 채택 · target_missed=false · gemini 1회")

        step("2. ★근소 미달 반려(v2 신규) — [3.7, 4.1] → 3.7 반려·4.1 채택")
        scenario(c, [{"snap_km": 3.7}, {"snap_km": 4.1}])
        d = gen(c, tok).json()
        assert d["total_distance_km"] == 4.1 and d["target_missed"] is False, d
        assert d["radius_expanded"] is True, "2시도 = 반경 확장 플래그"
        assert stats(c)["gemini_calls"] == 2, \
            "3.7(−0.3)이 반려됐다는 증거 — 구 ±0.5 게이트는 1회에 통과"
        ok("3.7(−0.3, 구게이트 합격값) 반려 → 4.1 채택 · gemini 2회")

        step("3. 초과 재시도 — [4.8, 4.3] → 4.8 반려·4.3 채택(상한 경계)")
        scenario(c, [{"snap_km": 4.8}, {"snap_km": 4.3}])
        d = gen(c, tok).json()
        assert d["total_distance_km"] == 4.3 and d["target_missed"] is False, d
        assert stats(c)["gemini_calls"] == 2, "4.8이 반려됐다는 증거"
        ok("4.8(+0.8) 반려 → 4.3(+0.3 경계) 채택")

        step("4. 4회 전패(초과 존재) — [2.5, 2.7, 5.2, 3.2] → ★5.2 채택(초과 우선)")
        scenario(c, [{"snap_km": 2.5}, {"snap_km": 2.7}, {"snap_km": 5.2}, {"snap_km": 3.2}])
        d = gen(c, tok).json()
        assert d["total_distance_km"] == 5.2, \
            f"초과 우선(미달 3.2가 |오차| 최소여도 후순위), got {d['total_distance_km']}"
        assert d["target_missed"] is True, "전패 플래그"
        assert stats(c)["gemini_calls"] == 4, "cap 4 유지"
        ok("전패 → 초과 후보 5.2 채택 · target_missed=true · gemini 4회(cap)")

        step("4b. 4회 전패(전부 미달) — [2.5, 2.7, 3.0, 3.2] → 미달 최장 3.2")
        scenario(c, [{"snap_km": 2.5}, {"snap_km": 2.7}, {"snap_km": 3.0}, {"snap_km": 3.2}])
        d = gen(c, tok).json()
        assert d["total_distance_km"] == 3.2 and d["target_missed"] is True, d
        ok("전패(전부 미달) → 최장 3.2 채택 · target_missed=true "
           "(⚠️ 미달 최선 시 실패 반환 여부는 오너 결정 대기)")

        step("5. NO_PATH 폴백 회귀 — 전부 no_path → AI 추정 유지")
        scenario(c, [{"no_path": True}] * 4)
        d = gen(c, tok).json()
        assert d["total_distance_km"] == 4.0, "AI 추정(=target mock) 폴백 유지"
        assert d["target_missed"] is False, "4.0 ∈ [4.0, 4.3] → 플래그 없음"
        assert d.get("polyline") in (None, []), "폴백은 폴리라인 없음(기존 동작)"
        ok("NO_PATH 4연속 → AI 추정 폴백 · 기존 동작 불변")

        step("6. 프롬프트 단위 검증 (호출 0회)")
        from app.services.openai_service import _build_prompt, _SNAP_INFLATION, _BAND_AIM_KM
        from app.models.schemas import Coordinate
        assert _SNAP_INFLATION == 1.45 and _BAND_AIM_KM == 0.15
        p = _build_prompt(4.0, Coordinate(lat=37.5445, lng=127.0374), None, None, None,
                          radius_km=1.0)
        assert "avoid overshooting" not in p, "과소 기하 유도 문구 삭제"
        assert "about 2.9 km" in p, f"체인 목표((4.0+0.15)/1.45=2.9) 명시, got: {p[:200]}"
        assert "1.3-1.7x" in p, "팽창 맥락 안내"
        assert "about 4.0 km" in p, "최종 목표 거리도 유지"
        assert "err slightly longer" in p, "오버슈트 바이어스 문구(미달 불합격 세트)"
        ok("프롬프트: 체인 2.9km(밴드 중앙 조준) · err slightly longer · 1.3-1.7x")

        print("\n" + "=" * 50 + "\n  MOCK 6케이스 PASSED — E2E는 메인 서버로\n" + "=" * 50)

        step("E2E. 실호출 1건 (메인 8000, 비용 ~2원) — v2 계약 검증")
        r = gen(c, tok, base=BASE)
        assert r.status_code == 200, r.text[:250]
        d = r.json()
        total = d["total_distance_km"]
        in_band = 4.0 - 1e-9 <= total <= 4.3 + 1e-9
        assert in_band or d["target_missed"] is True, \
            f"계약 위반: {total} ∉ [4.0, 4.3]인데 missed={d['target_missed']}"
        print(f"    실측: total={total}km (오차 {total-4.0:+.2f}) "
              f"target_missed={d['target_missed']} radius_expanded={d['radius_expanded']}")
        ok(f"E2E 계약 준수: [target, target+0.3] 이내 또는 플래그 (실제 {total}km)")

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
