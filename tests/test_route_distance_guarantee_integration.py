"""
Integration test: AI 코스 목표 거리 보장 v2.1 — 비대칭 밴드 [−0.1, +0.5]
(ROUTE_DISTANCE_GUARANTEE_DESIGN)

게이트 v2.1 (2026-07-20 최종 룰링, Ivan 절충안): **target−0.1 ≤ actual ≤
target+0.5**만 합격 (폭 0.6 — 명중률 확보). 전패 시 **미달 반환 금지** —
초과 최선만 target_missed=true, 초과 0이면 502 route_generation_failed
(기존 실패 계약 재사용, 쿼터 미소모). 프롬프트 조준점 (target+0.2)/1.45.

v2.2 (같은 날 긴급 재보정 — 실전 명중률 0): ① 적응형 팽창비(직전 attempt 실측
ratio를 다음 체인 목표에 피드백, 관측 클램프 [1.1, 2.2], 초기 상수 1.45→1.6)
② 전패 초과 서빙 캡 +1.0km(초과 최선이 그 밖이면 502) ③ 예상 시간 러닝 환산
(거리 × 6'30"/km — T-map 도보 시간 폐기).

mock 케이스 (tests.mock_route_app을 8001에 기동 — Gemini·T-map 실호출 0, target=5.0):
 1. 하한 안쪽 합격: [4.95] → 채택·missed=false·gemini 1회 + duration=32(러닝 환산)
 2. 하한 밖 반려: [4.85, 4.95] → 4.85(−0.15) 반려 → 4.95 채택·gemini 2회
 3. 상한 안쪽 합격: [5.45] → 채택·1회
 3b. 상한 밖 반려: [5.55, 5.45] → 5.55(+0.55) 반려 → 5.45 채택·2회
 4. 전패(캡 내 초과 존재): [4.0, 5.6, 5.8, 4.2] → 5.6 채택(초과 최선 ≤ +1.0)·missed·4회
 4b. 전패(미달만): [4.0, 4.2, 4.5, 4.7] → 502 (미달 서빙 금지)
 4c. ★전패(초과가 전부 캡 밖): [6.1, 6.5, 7.0, 8.0] → **502** (v2.2 신규)
 4d. 캡 경계: [6.0, 6.5, 7.0, 8.0] → 6.0(+1.0 정확히) 채택·missed=true
 5. NO_PATH 폴백 회귀(target=4.0): 전부 no_path → AI 추정(4.0 ∈ [3.9,4.5])·missed=false
 6. 프롬프트 단위: 기본 체인 "about 2.6 km"((4.2)/1.6) + "err slightly longer"
 7. ★적응형 피드백: [5.6, 5.3] → attempt1 aim 3.2((5.2)/1.6) → ratio 관측(클램프
    2.2) → attempt2 aim 2.4((5.2)/2.2) → 5.3 합격. chain_targets 기록으로 검증

+ E2E 실호출 2건(비용 ~4원, target=5.0 서울): 각각 200이면 밴드 내 or
  missed(총거리 ≤ 6.0), 또는 502 — 계약 준수 + 명중률 방향 관찰(표본 적음 인지).

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


def gen(c, token, base=B8001, target=4.0, start=None, end=None):
    body = {"start": start or {"lat": 37.5445, "lng": 127.0374},
            "target_distance_km": target}
    if end:
        body["end"] = end
    return c.post(f"{base}/api/routes/generate",
                  headers={"Authorization": f"Bearer {token}"}, json=body)


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
        assert d["estimated_duration_min"] == round(round(4.95, 1) * 6.5), \
            f"러닝 환산(6'30\"/km) 기대, got {d['estimated_duration_min']}"
        assert stats(c)["gemini_calls"] == 1, stats(c)
        ok(f"4.95(−0.05) 합격 · missed=false · duration={d['estimated_duration_min']}분(러닝 환산) · gemini 1회")

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

        step("4. 전패(캡 내 초과 존재) — [4.0, 5.6, 5.8, 4.2] → 5.6 채택")
        scenario(c, [{"snap_km": 4.0}, {"snap_km": 5.6}, {"snap_km": 5.8}, {"snap_km": 4.2}])
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.6, \
            f"초과 최선(5.6 < 5.8, 둘 다 캡 6.0 내), 미달(4.0·4.2)은 반환 금지, got {d['total_distance_km']}"
        assert d["target_missed"] is True, "전패 플래그"
        assert stats(c)["gemini_calls"] == 4, "cap 4 유지"
        ok("전패 → 초과 최선 5.6 채택 · target_missed=true · gemini 4회(cap)")

        step("4b. 전패(미달만) — [4.0, 4.2, 4.5, 4.7] → 502 실패")
        scenario(c, [{"snap_km": 4.0}, {"snap_km": 4.2}, {"snap_km": 4.5}, {"snap_km": 4.7}])
        r = gen(c, tok, target=5.0)
        assert r.status_code == 502, f"미달만 전패 → 502, got {r.status_code}: {r.text[:150]}"
        assert r.json()["detail"]["error"] == "route_generation_failed", r.text[:200]
        assert stats(c)["gemini_calls"] == 4, "4회 시도 후 실패"
        ok("전패(미달만) → 502 route_generation_failed — 미달 서빙 금지")

        step("4c. ★전패(초과 전부 캡 밖) — [6.1, 6.5, 7.0, 8.0] → 502 (v2.2 신규)")
        scenario(c, [{"snap_km": 6.1}, {"snap_km": 6.5}, {"snap_km": 7.0}, {"snap_km": 8.0}])
        r = gen(c, tok, target=5.0)
        assert r.status_code == 502, \
            f"초과 최선 6.1(+1.1 > 캡 +1.0) → 502, got {r.status_code}: {r.text[:150]}"
        assert r.json()["detail"]["error"] == "route_generation_failed", r.text[:200]
        ok("초과 전부 캡(+1.0) 밖 → 502 — '6.3km는 5km의 답이 아니다' 반영")

        step("4d. 캡 경계 — [6.0, 6.5, 7.0, 8.0] → 6.0(+1.0 정확히) 채택+missed")
        scenario(c, [{"snap_km": 6.0}, {"snap_km": 6.5}, {"snap_km": 7.0}, {"snap_km": 8.0}])
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 6.0 and d["target_missed"] is True, d
        ok("캡 경계 +1.0 = 서빙 허용 · missed=true")

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
        assert _SNAP_INFLATION == 1.6 and _BAND_AIM_KM == 0.2, "v2.2 재보정 상수"
        p = _build_prompt(4.0, Coordinate(lat=37.5445, lng=127.0374), None, None, None,
                          radius_km=1.0)
        assert "avoid overshooting" not in p, "과소 기하 유도 문구 삭제"
        expect_chain = round((4.0 + 0.2) / 1.6, 1)
        assert f"about {expect_chain} km" in p, f"기본 체인 목표({expect_chain}) 명시, got: {p[:200]}"
        assert "err slightly longer" in p, "오버슈트 바이어스 문구"
        cap = round(expect_chain * 1.15, 1)
        assert f"MUST NOT exceed {cap} km" in p, "체인 상한 강제 문구(v2.3)"
        # 적응형 오버라이드 — chain_target_km이 오면 그 값이 프롬프트에 실림
        p2 = _build_prompt(4.0, Coordinate(lat=37.5445, lng=127.0374), None, None, None,
                           radius_km=1.0, chain_target_km=2.4)
        assert "about 2.4 km" in p2, "적응형 체인 목표 오버라이드"
        ok(f"프롬프트: 기본 체인 {expect_chain}km(1.6 재보정) · 오버라이드 2.4km · err slightly longer")

        step("7. ★적응형 피드백 — [5.6, 5.3] → aim 3.2 → ratio 1.75 관측 → aim 3.0 → 합격")
        scenario(c, [{"snap_km": 5.6}, {"snap_km": 5.3}])
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.3 and d["target_missed"] is False, d
        st = stats(c)
        assert st["gemini_calls"] == 2, st
        aims = st["chain_targets"]
        exp1 = round((5.0 + 0.2) / 1.6, 1)          # 3.2 — 초기 상수 조준
        ratio1 = 5.6 / exp1                          # ≈1.75 — mock은 aim에 순응(chain=aim)
        exp2 = round((5.0 + 0.2) / ratio1, 1)        # 3.0 — 관측 ratio 반영
        assert aims == [exp1, exp2], \
            f"적응형 조준 [초기 {exp1}, 피드백 {exp2}] 기대, got {aims}"
        ok(f"attempt1 aim {aims[0]} → ratio {ratio1:.2f} 관측 → attempt2 aim {aims[1]} → 5.3 합격")

        step("8. ★사전 게이트 재추첨 — gemini [×1.6, ×1.0] → 1롤 반려·2롤 통과 (v2.3)")
        assert c.post(f"{B8001}/__mock/scenario",
                      json={"seq": [{"snap_km": 5.2}], "gemini_seq": [1.6, 1.0]}
                      ).status_code == 200
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.2 and d["target_missed"] is False, d
        st = stats(c)
        assert st["gemini_calls"] == 2, f"재추첨 1회 = gemini 2, got {st}"
        assert st["tmap_calls"] == 1, f"반려 롤은 T-map 미호출, got {st}"
        ok("체인 ×1.6 반려(T-map 0) → 재추첨 순응 → 5.2 합격 · gemini 2/tmap 1")

        step("9. ★사전 게이트 소진 → salvage — gemini [×2.0 ×3] → 최근접 롤로 스냅 진행")
        assert c.post(f"{B8001}/__mock/scenario",
                      json={"seq": [{"snap_km": 5.2}],
                            "gemini_seq": [2.0, 2.0, 2.0]}).status_code == 200
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.2 and d["target_missed"] is False, d
        st = stats(c)
        assert st["gemini_calls"] == 3, f"롤 3회 소진(재추첨 상한), got {st}"
        assert st["tmap_calls"] == 1, f"salvage여도 attempt당 T-map 1회, got {st}"
        assert d["radius_expanded"] is False, "salvage로 attempt1에서 완결(원지시 pre_miss였으면 attempt2행)"
        ok("3롤 비순응 → 최근접 롤 salvage → 5.2 합격 · gemini 3/tmap 1 (attempt 미소실)")

        step("10. ★end-aware — |start−end|≈5km 일방: 반경 corridor + aim 물리 하한 (v2.3)")
        scenario(c, [{"snap_km": 5.2}])
        d = gen(c, tok, target=5.0,
                end={"lat": 37.5445, "lng": 127.0374 + 0.0567}).json()  # ~5km 동쪽
        assert d["total_distance_km"] == 5.2 and d["target_missed"] is False, d
        st = stats(c)
        r1 = st["radii"][0]
        assert r1 >= 3.4, \
            f"end-aware r0 = max(1.2, |s−e|/2+1.0) ≈ 3.5 기대(구식 1.2면 기하 모순), got {r1}"
        aim1 = st["chain_targets"][0]
        assert aim1 >= 5.0, \
            f"aim 물리 하한(직선거리×1.05 ≈ 5.3) 기대 — 하한 없으면 4.2로 전 롤 반려됨, got {aim1}"
        ok(f"일방 attempt1 radius={r1} · aim={aim1}(하한 적용) · 5.2 합격")

        print("\n" + "=" * 50 + "\n  MOCK 케이스 PASSED — E2E는 메인 서버로\n" + "=" * 50)

        step("E2E. 실호출 4건 (target=5.0) — 원점 복귀 3좌표 + 일방 1건 (v2.3)")
        e2e_cases = [
            ("성수 루프", {"lat": 37.5445, "lng": 127.0374}, None),
            ("여의도 루프", {"lat": 37.5285, "lng": 126.9328}, None),
            ("잠실 루프", {"lat": 37.5145, "lng": 127.1027}, None),
            ("일방 성수→건대너머(~5km)", {"lat": 37.5445, "lng": 127.0374},
             {"lat": 37.5445, "lng": 127.0941}),  # ~5km 동쪽
        ]
        for name, s, e in e2e_cases:
            r = gen(c, tok, base=BASE, target=5.0, start=s, end=e)
            if r.status_code == 502:
                assert r.json()["detail"]["error"] == "route_generation_failed", r.text[:200]
                print(f"    {name}: 502 (전패 — 정직 실패) — 계약 준수")
                continue
            assert r.status_code == 200, f"{name}: {r.text[:250]}"
            d = r.json()
            total = d["total_distance_km"]
            in_band = 4.9 - 1e-9 <= total <= 5.5 + 1e-9
            if in_band:
                assert d["target_missed"] is False, d["target_missed"]
            else:
                assert d["target_missed"] is True and total <= 6.0 + 1e-9, \
                    f"{name} 계약 위반: {total}, missed={d['target_missed']} (캡 6.0)"
            assert d["estimated_duration_min"] == round(total * 6.5), \
                f"러닝 환산 duration 기대, got {d['estimated_duration_min']}"
            print(f"    {name}: total={total}km (오차 {total-5.0:+.2f}) "
                  f"missed={d['target_missed']} radius={d['search_radius_km']}"
                  f"{' ★명중' if in_band else ''}")
        ok("E2E 4건 계약 준수 (실측값·명중 여부는 위 출력)")

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
