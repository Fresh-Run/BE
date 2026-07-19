"""
Integration test: AI 코스 목표 거리 보장 v2.1 — 비대칭 밴드 [−0.1, +0.5]
(ROUTE_DISTANCE_GUARANTEE_DESIGN)

게이트 v2.1 (2026-07-20 최종 룰링, Ivan 절충안): **target−0.1 ≤ actual ≤
target+0.5**만 합격 (폭 0.6 — 명중률 확보). 전패 시 **미달 반환 금지** —
초과 최선만 target_missed=true, 초과 0이면 502 route_generation_failed
(기존 실패 계약 재사용, 쿼터 미소모). 프롬프트 조준점 (target+0.2)/1.45.

mock 케이스 (tests.mock_route_app을 8001에 기동 — Gemini·T-map 실호출 0, target=5.0):
 1. 하한 안쪽 합격: [4.95] → 채택·missed=false·gemini 1회
 2. 하한 밖 반려: [4.85, 4.95] → 4.85(−0.15) 반려 → 4.95 채택·gemini 2회
 3. 상한 안쪽 합격: [5.45] → 채택·1회
 3b. 상한 밖 반려: [5.55, 5.45] → 5.55(+0.55) 반려 → 5.45 채택·2회
 4. 전패(초과 존재): [4.0, 5.6, 5.8, 4.2] → 5.6 채택(초과 최선)·missed=true·4회
 4b. ★전패(미달만): [4.0, 4.2, 4.5, 4.7] → **502 route_generation_failed**
     (v2.1 신규 — 미달 서빙 금지)
 5. NO_PATH 폴백 회귀(target=4.0): 전부 no_path → AI 추정(4.0 ∈ [3.9,4.5])·missed=false
 6. 프롬프트 단위: "about 2.9 km"((4.0+0.2)/1.45) + "err slightly longer" 포함

+ E2E 실호출 1건(비용 ~2원): 200이면 (3.9 ≤ total ≤ 4.5) OR missed=true,
  또는 502 route_generation_failed(전패-미달만) — 둘 다 계약 준수.

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

        # 주의: 응답 total_distance_km는 표시용 0.1 반올림 — **게이트는 반올림 전
        # 원값**(v2.1). 그래서 4.95는 표시 5.0으로 합격, 5.55는 표시 5.5여도 반려.
        step("1. 하한 안쪽 합격 — [4.95] (target 5.0, 밴드 [4.9, 5.5])")
        scenario(c, [{"snap_km": 4.95}])
        r = gen(c, tok, target=5.0)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d["total_distance_km"] == round(4.95, 1) and d["target_missed"] is False, d
        assert stats(c)["gemini_calls"] == 1, stats(c)
        ok("4.95(−0.05) 합격 · missed=false · gemini 1회")

        step("2. 하한 밖 반려 — [4.85, 4.95] → 4.85 반려·4.95 채택")
        scenario(c, [{"snap_km": 4.85}, {"snap_km": 4.95}])
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == round(4.95, 1) and d["target_missed"] is False, d
        assert d["radius_expanded"] is True, "2시도 = 반경 확장 플래그"
        assert stats(c)["gemini_calls"] == 2, "4.85(−0.15)가 반려됐다는 증거"
        ok("4.85 반려 → 4.95 채택 · gemini 2회")

        step("3. 상한 안쪽 합격 — [5.45] 1시도")
        scenario(c, [{"snap_km": 5.45}])
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == round(5.45, 1) and d["target_missed"] is False, d
        assert stats(c)["gemini_calls"] == 1, stats(c)
        ok("5.45(+0.45) 합격 · 1회")

        step("3b. 상한 밖 반려 — [5.55, 5.45] → 5.55 반려·5.45 채택")
        scenario(c, [{"snap_km": 5.55}, {"snap_km": 5.45}])
        d = gen(c, tok, target=5.0).json()
        assert d["target_missed"] is False, d
        assert stats(c)["gemini_calls"] == 2, \
            "5.55(+0.55, 표시로는 5.5)가 원값 게이트에서 반려됐다는 증거 — 표시 반올림 우회 없음"
        ok("5.55 반려(원값 게이트) → 5.45 채택 · gemini 2회")

        step("4. 전패(초과 존재) — [4.0, 5.6, 5.8, 4.2] → 5.6 채택(초과 최선)")
        scenario(c, [{"snap_km": 4.0}, {"snap_km": 5.6}, {"snap_km": 5.8}, {"snap_km": 4.2}])
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.6, \
            f"초과 최선(5.6 < 5.8), 미달(4.0·4.2)은 반환 금지, got {d['total_distance_km']}"
        assert d["target_missed"] is True, "전패 플래그"
        assert stats(c)["gemini_calls"] == 4, "cap 4 유지"
        ok("전패 → 초과 최선 5.6 채택 · target_missed=true · gemini 4회(cap)")

        step("4b. ★전패(미달만) — [4.0, 4.2, 4.5, 4.7] → 502 실패 (v2.1 신규)")
        scenario(c, [{"snap_km": 4.0}, {"snap_km": 4.2}, {"snap_km": 4.5}, {"snap_km": 4.7}])
        r = gen(c, tok, target=5.0)
        assert r.status_code == 502, f"미달만 전패 → 502, got {r.status_code}: {r.text[:150]}"
        assert r.json()["detail"]["error"] == "route_generation_failed", r.text[:200]
        assert stats(c)["gemini_calls"] == 4, "4회 시도 후 실패"
        ok("전패(미달만) → 502 route_generation_failed — 미달 서빙 금지")

        step("5. NO_PATH 폴백 회귀 — 전부 no_path → AI 추정 유지 (target 4.0)")
        scenario(c, [{"no_path": True}] * 4)
        d = gen(c, tok).json()
        assert d["total_distance_km"] == 4.0, "AI 추정(=target mock) 폴백 유지"
        assert d["target_missed"] is False, "4.0 ∈ [3.9, 4.5] → 플래그 없음"
        assert d.get("polyline") in (None, []), "폴백은 폴리라인 없음(기존 동작)"
        ok("NO_PATH 4연속 → AI 추정 폴백 · 기존 동작 불변")

        step("6. 프롬프트 단위 검증 (호출 0회)")
        from app.services.openai_service import _build_prompt, _SNAP_INFLATION, _BAND_AIM_KM
        from app.models.schemas import Coordinate
        assert _SNAP_INFLATION == 1.45 and _BAND_AIM_KM == 0.2
        p = _build_prompt(4.0, Coordinate(lat=37.5445, lng=127.0374), None, None, None,
                          radius_km=1.0)
        assert "avoid overshooting" not in p, "과소 기하 유도 문구 삭제"
        assert "about 2.9 km" in p, f"체인 목표((4.0+0.2)/1.45=2.9) 명시, got: {p[:200]}"
        assert "1.3-1.7x" in p, "팽창 맥락 안내"
        assert "about 4.0 km" in p, "최종 목표 거리도 유지"
        assert "err slightly longer" in p, "오버슈트 바이어스 문구(미달 불합격 세트)"
        ok("프롬프트: 체인 2.9km(밴드 중심 +0.2 조준) · err slightly longer · 1.3-1.7x")

        print("\n" + "=" * 50 + "\n  MOCK 6케이스 PASSED — E2E는 메인 서버로\n" + "=" * 50)

        step("E2E. 실호출 1건 (비용 ~2원) — v2.1 계약 검증")
        r = gen(c, tok, base=BASE)
        if r.status_code == 502:
            assert r.json()["detail"]["error"] == "route_generation_failed", r.text[:200]
            ok("E2E: 전패(미달만) → 502 실패 계약 준수 (미달 서빙 금지)")
        else:
            assert r.status_code == 200, r.text[:250]
            d = r.json()
            total = d["total_distance_km"]
            in_band = 3.9 - 1e-9 <= total <= 4.5 + 1e-9
            assert in_band or d["target_missed"] is True, \
                f"계약 위반: {total} ∉ [3.9, 4.5]인데 missed={d['target_missed']}"
            print(f"    실측: total={total}km (오차 {total-4.0:+.2f}) "
                  f"target_missed={d['target_missed']} radius_expanded={d['radius_expanded']}")
            ok(f"E2E 계약 준수: [target−0.1, target+0.5] 이내 또는 초과+플래그 (실제 {total}km)")

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
