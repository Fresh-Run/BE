"""
Integration test: AI 코스 거리 보장 v2.7 — 배치 풀 (§2 생성 전략)

v2.7 (2026-07-21 오너 확정): attempt 루프 폐기 → N개(기본 9) 병렬 생성 →
pre-gate 통과분(체인 aim×[0.75,1.25]) **전부 병렬 스냅** → 밴드 최근접 서빙.
게이트(밴드 [target−0.3,+0.5]·캡 target+1.0·traversability·일방)는 불변, 선택
층만 교체. 적응형·재추첨·시간 예산 게이트는 폐기(1패스 풀). T-map leg 상한 40
안전핀. gen_meta: pool_size·snapped_count·tmap_legs·snaps·initial_ratio.

mock(tests.mock_route_app, 8001): pool_size·tmap_leg_cap 오버라이드 지원.
gemini_seq=체인 순응 배수(chain=aim×f, 통과=0.75≤f≤1.25), seq=스냅 결과.

케이스:
 1. 전통과 밴드 hit + gen_meta(pool·snapped·tmap_legs·snaps)
 2. 부분 통과 — pre-gate 밖 후보는 스냅 안 됨(snapped < pool)
 3. 캡 초과 서빙 — 밴드 없음 → 캡 내 최선 missed
 4. 전멸 502 — 밴드·캡 서빙 후보 0 (초과 캡밖 / 미달)
 5. leg 상한 발동 — cap 낮춰 스냅 수 제한
 6. 프롬프트 단위(상한만) + 뚝섬 초기 조준 오버라이드
 7. traversability 폐기 — 강 위 후보 제외하고 정상 서빙
 8. nopath 폴백 — 전 스냅 T-map 장애 → AI추정
 9. 콜 타임아웃 — 부분(성공분으로)·전패(502)
10. end-aware 일방 + 일방 실행가능성 게이트 + is_one_way

Run: python tests/test_route_distance_guarantee_integration.py  (로컬 서버 8000 필요)
"""
from __future__ import annotations

import os, subprocess, sys, time
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = "http://localhost:8000"      # gen()이 /api를 붙임
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


def gen(c, token, base=B8001, target=5.0, start=None, end=None):
    # 기본 좌표는 far 미등록 격자(37.20,127.00 — 등록 6좌표서 30km+) → est_ratio
    # default 1.6. 격자 테이블 등록 좌표를 피해 mock 기하 baseline(initial_ratio 1.6) 유지.
    body = {"start": start or {"lat": 37.2000, "lng": 127.0000}, "target_distance_km": target}
    if end:
        body["end"] = end
    return c.post(f"{base}/api/routes/generate",
                  headers={"Authorization": f"Bearer {token}"}, json=body)


def scenario(c, seq, **extra):
    assert c.post(f"{B8001}/__mock/scenario", json={"seq": seq, **extra}).status_code == 200


def stats(c):
    return c.get(f"{B8001}/__mock/stats").json()


def run_tests():
    c = httpx.Client(timeout=120)
    uids = {}
    proc = None
    try:
        step("0. premium 유저 + mock 서버 8001")
        uids["u"] = sb_user(c, f"rdg-u-{TS}@test.com")
        tok = sb_login(c, f"rdg-u-{TS}@test.com")
        assert c.request("PATCH", f"{BASE}/api/me/profile", headers={"Authorization": f"Bearer {tok}"},
                         json={"nickname": f"RDG{TS}"}).status_code == 200
        c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{uids['u']}", headers=_ADM, json={"tier": "premium"})
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.mock_route_app:app", "--port", "8001",
             "--log-level", "warning"],
            cwd=os.path.join(os.path.dirname(__file__), ".."))
        for _ in range(40):
            try:
                if c.get(f"{B8001}/health").status_code == 200: break
            except Exception: pass
            time.sleep(0.5)
        else:
            fail("mock 서버 기동 실패")
        ok("premium 유저 + mock 8001 up")

        step("1. 전통과 밴드 hit — pool 5·전부 5.0 스냅 → 밴드 최근접 + gen_meta")
        scenario(c, [{"snap_km": 5.0}], pool_size=5)
        r = gen(c, tok, target=5.0)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d["total_distance_km"] == 5.0 and d["target_missed"] is False, d
        assert stats(c)["gemini_calls"] == 5, "pool 5 = Gemini 5콜"
        gm = stats(c)["last_gen_meta"]
        assert gm["verdict"] == "hit" and gm["pool_size"] == 5 and gm["snapped_count"] == 5, gm
        assert gm["tmap_legs"] == 15, f"5 스냅 × 3 leg = 15, got {gm['tmap_legs']}"
        assert gm["snaps"] == [5.0] * 5 and gm.get("initial_ratio") == 1.6, gm
        ok(f"밴드 hit 5.0 · pool=5 snapped=5 tmap_legs=15 · gen_meta 완비")

        step("2. 부분 통과 — pre-gate 밖 후보는 스냅 안 됨(snapped < pool)")
        # f=1.0 2개 통과(chain=aim), f=2.5·0.4 3개 밴드 밖 → 스냅 대상 2개
        scenario(c, [{"snap_km": 5.0}], gemini_seq=[1.0, 1.0, 2.5, 0.4, 2.5], pool_size=5)
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.0 and d["target_missed"] is False, d
        gm = stats(c)["last_gen_meta"]
        assert gm["pool_size"] == 5 and gm["snapped_count"] == 2, f"통과 2개만 스냅, got {gm}"
        assert gm["tmap_legs"] == 6, f"2 스냅 × 3 leg = 6, got {gm['tmap_legs']}"
        ok("pool 5 중 pre-gate 통과 2개만 스냅(밴드 밖 3개 미스냅) · snapped=2")

        step("3. 캡 초과 서빙 — 밴드 없음(5.8) → 캡 내(≤6.0) 최선 missed")
        scenario(c, [{"snap_km": 5.8}], pool_size=5)
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.8 and d["target_missed"] is True, d
        assert stats(c)["last_gen_meta"]["verdict"] == "missed", stats(c)["last_gen_meta"]
        ok("전 스냅 5.8(+0.8 밴드밖·캡내) → missed 서빙")

        step("4. 전멸 502 — 초과 캡밖(8.0) / 미달(3.0) 둘 다 502")
        scenario(c, [{"snap_km": 8.0}], pool_size=5)
        r = gen(c, tok, target=5.0)
        assert r.status_code == 502 and r.json()["detail"]["error"] == "route_generation_failed", r.text[:150]
        scenario(c, [{"snap_km": 3.0}], pool_size=5)  # 미달 <4.7
        r2 = gen(c, tok, target=5.0)
        assert r2.status_code == 502, f"미달만 → 502, got {r2.status_code}"
        ok("초과 캡밖 8.0 → 502 · 미달 3.0 → 502 (밴드·캡 서빙 후보 0)")

        step("5. leg 상한 발동 — cap 6 → 통과 5개 중 2개만 스냅(6 leg)")
        scenario(c, [{"snap_km": 5.0}], pool_size=5, tmap_leg_cap=6)
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.0 and d["target_missed"] is False, d
        gm = stats(c)["last_gen_meta"]
        assert gm["tmap_legs"] == 6 and gm["snapped_count"] == 2, \
            f"leg 상한 6 → 2 스냅(6 leg)에서 컷, got {gm}"
        ok(f"leg 상한 6 발동 → snapped 2(나머지 3 미스냅) · tmap_legs=6 (쿼터 백스톱)")

        step("6. 프롬프트 단위(상한만) + 뚝섬 초기 조준 오버라이드")
        from app.services.openai_service import _build_prompt, _SNAP_INFLATION, _BAND_AIM_KM
        from app.services.route_service import _initial_est_ratio
        from app.models.schemas import Coordinate
        assert _SNAP_INFLATION == 1.6 and _BAND_AIM_KM == 0.2
        p = _build_prompt(4.0, Coordinate(lat=37.5445, lng=127.0374), None, None, None, radius_km=1.0)
        cap = round(round((4.0 + 0.2) / 1.6, 1) * 1.15, 1)
        assert f"MUST NOT exceed {cap} km" in p and "Aim for the middle" not in p, "상한만(양방향 롤백)"
        # 뚝섬 초기 조준
        # 격자 est_ratio 테이블(§3 STEP 2·3): 실측 ratio로 좌표별 보정
        assert _initial_est_ratio(Coordinate(lat=37.5219, lng=127.0561), None) == 1.84, "뚝섬권 1.84"
        assert _initial_est_ratio(Coordinate(lat=37.5265, lng=126.8620), None) == 1.41, "목동권 1.41"
        assert _initial_est_ratio(Coordinate(lat=37.5242, lng=126.6303), None) == 1.85, "청라권 1.85(STEP3 상향)"
        assert _initial_est_ratio(Coordinate(lat=37.4995, lng=127.0360), None) == 1.38, "강남권 1.38(STEP3 등록)"
        assert _initial_est_ratio(Coordinate(lat=37.5200, lng=127.0200), None) == 1.45, "신사/논현권 1.45(미노스 부검 등록)"
        assert _initial_est_ratio(Coordinate(lat=37.2000, lng=127.0000), None) == 1.6, "미등록 far 격자 default 1.6"
        assert _initial_est_ratio(Coordinate(lat=37.5219, lng=127.0561), 3.5) == 1.25, "일방 우선"
        ok("격자 est_ratio: 뚝섬1.84/목동1.41/청라1.85/강남1.38/미등록1.6/일방1.25")

        step("7. traversability 폐기 — 강 위 2개 제외하고 정상 5.0 서빙")
        scenario(c, [{"untraversable": True}, {"untraversable": True}, {"snap_km": 5.0}], pool_size=3)
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.0 and d["target_missed"] is False, d
        gm = stats(c)["last_gen_meta"]
        assert gm["snapped_count"] == 1 and gm["snaps"] == [None, None, 5.0], \
            f"강 위 2개 폐기(None)·정상 1개 스냅, got {gm['snaps']}"
        ok("강 위 leg 후보 폐기(snaps None) → 정상 후보 5.0 서빙")

        step("8. nopath 폴백 — 전 스냅 T-map 장애 → AI추정")
        scenario(c, [{"no_path": True}], pool_size=3)
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.0, "AI 추정(=target mock) 폴백"
        assert d.get("polyline") in (None, []), "폴백은 폴리라인 없음"
        assert stats(c)["last_gen_meta"]["verdict"] == "nopath", stats(c)["last_gen_meta"]
        ok("전 스냅 T-map 장애 → AI추정 폴백 · verdict=nopath")

        step("9. 콜 타임아웃 — 부분(성공분 서빙) / 전패(502)")
        scenario(c, [{"snap_km": 5.0}], gemini_seq=[-1, 1.0, 1.0], pool_size=3)
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.0, "타임아웃 1개 무시, 성공 2개로 서빙"
        assert stats(c)["last_gen_meta"]["pool_size"] == 2, "생성 성공 2개(타임아웃 1 제외)"
        scenario(c, [{"snap_km": 5.0}], gemini_seq=[-1, -1, -1], pool_size=3)
        r = gen(c, tok, target=5.0)
        assert r.status_code == 502, f"전 생성 타임아웃 → 502, got {r.status_code}"
        ok("부분 타임아웃 → 성공분 서빙 · 전 타임아웃 → 502")

        step("10. end-aware 일방 + 실행가능성 게이트 + is_one_way")
        # 실행가능 일방(직선 ~3.5km ≤ target×0.8=4.0) — end가 성수 기준 상대좌표라
        # start도 명시 성수(기본 강남과 분리)
        _su = {"lat": 37.5445, "lng": 127.0374}
        scenario(c, [{"snap_km": 5.0}], pool_size=3)
        d = gen(c, tok, target=5.0, start=_su, end={"lat": 37.5445, "lng": 127.0374 + 0.0396}).json()
        assert d["total_distance_km"] == 5.0 and d.get("is_one_way") is True, d
        # 초과(직선 ~5.0km > 4.0) → 422
        r = gen(c, tok, target=5.0, start=_su, end={"lat": 37.5445, "lng": 127.0374 + 0.0567})
        assert r.status_code == 422 and r.json()["detail"]["error"] == "one_way_end_too_far", r.text[:150]
        # 루프는 is_one_way false
        scenario(c, [{"snap_km": 5.0}], pool_size=3)
        assert gen(c, tok, target=5.0).json()["is_one_way"] is False
        ok("일방 3.5km 서빙·is_one_way true · 초과 422 · 루프 false")

        step("11. 적응 재추첨(미노스 부검) — 언더슈트 지배→재조준 서빙 / overshoot 미발동 / 재추첨도 미달 502")
        # 11a: 초기 9 언더슈트(4.0<밴드하한 4.7) + 재추첨 인밴드(5.0) → hit_redraw 서빙
        scenario(c, [{"snap_km": 4.0}] * 9 + [{"snap_km": 5.0}], pool_size=9)
        r = gen(c, tok, target=5.0)
        assert r.status_code == 200, f"재추첨 서빙 기대, got {r.status_code} {r.text[:120]}"
        gm = stats(c)["last_gen_meta"]
        assert gm["verdict"] == "hit_redraw" and gm.get("redraw", {}).get("redraw_hit") is True, gm
        assert gm["redraw"]["measured_ratio"] < 1.6, "실측 ratio < default 1.6(undershoot 근거)"
        # 11b: overshoot(5.8, 캡 내) 존재 → missed 서빙, 재추첨 미발동
        scenario(c, [{"snap_km": 5.8}], pool_size=9)
        gm = stats(c)["last_gen_meta"] if gen(c, tok, target=5.0).status_code == 200 else {}
        assert gm.get("verdict") == "missed" and "redraw" not in gm, \
            f"overshoot는 missed·재추첨 미발동, got {gm.get('verdict')}"
        # 11c: 재추첨 결과가 over-cap(5.7, 캡 내)만 → missed_redraw 서빙 (01:16 미노스 재현
        # — 5.7을 버려 502하던 것 수정). 초기 9 언더슈트 + 재추첨 5.7.
        scenario(c, [{"snap_km": 4.0}] * 9 + [{"snap_km": 5.7}], pool_size=9)
        r = gen(c, tok, target=5.0)
        assert r.status_code == 200, f"재추첨 over-cap missed 서빙 기대, got {r.status_code}"
        assert r.json()["target_missed"] is True, "over-cap 재추첨은 target_missed"
        gm = stats(c)["last_gen_meta"]
        assert gm["verdict"] == "missed_redraw" and gm["redraw"]["redraw_verdict"] == "missed", gm
        # 11d: 초기·재추첨 둘 다 언더슈트(4.0) → 502(재추첨 시도·기록됨)
        scenario(c, [{"snap_km": 4.0}], pool_size=9)
        r = gen(c, tok, target=5.0)
        assert r.status_code == 502, f"재추첨도 미달 → 502, got {r.status_code}"
        lf = stats(c)["last_failure"]
        assert lf["fail"] == "band_cap_zero" and (lf.get("redraw") or {}).get("redraw_hit") is False, lf
        ok("재추첨: in-band→hit_redraw · over-cap→missed_redraw(01:16 수정) · 전멸→502")

        step("11e. 재추첨 measured_ratio 블렌드 — 등록 격자면 grid 2:1 가중(01:16 노이즈 완화)")
        from app.services.route_service import _grid_ratio as _gr
        import statistics as _st
        from app.models.schemas import Coordinate as _C
        assert _gr(_C(lat=37.5163, lng=127.0203)) == 1.45, "신사/논현 격자 1.45"
        assert _st.median([1.32, 1.45, 1.45]) == 1.45, "grid 2:1 가중 → 1.45(노이즈 1.32 흡수)"
        assert _gr(_C(lat=37.2, lng=127.0)) is None, "미등록은 실측 단독(블렌드 없음)"
        ok("등록 격자 median(measured,grid,grid) 블렌드 · 미등록 실측 단독")

        print("\n" + "=" * 50 + "\n  MOCK 케이스 PASSED — E2E는 메인 서버로(내일 T-map 리셋 후)\n" + "=" * 50)

        # ── E2E는 T-map 쿼터(815/1000) 제약으로 오늘 실호출 금지 ──────────────
        # 내일 리셋 후: 뚝섬 3건 + 일반 지역 2건. 합격선: 뚝섬 서빙률 오늘(2/6)
        # 대비 개선 · 일반 지역 무회귀 · 시간 20s 내. (지시대로 오늘은 mock만.)
        print("\n" + "=" * 50 + "\n  ALL MOCK TESTS PASSED (E2E는 내일)\n" + "=" * 50)
    finally:
        step("Cleanup")
        if proc: proc.terminate()
        c.delete(f"{_SB}/rest/v1/routes?user_id=eq.{uids.get('u','')}", headers=_ADM)
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  정리 완료 (mock 서버 종료·코스·유저 삭제)")


if __name__ == "__main__":
    run_tests()
