"""
Integration test: AI 코스 목표 거리 보장 v2.4 — 비대칭 밴드 [−0.3, +0.5]
(ROUTE_DISTANCE_GUARANTEE_DESIGN)

v2.4 (2026-07-20 오너 결정 — 하한 완화): 하한 −0.1→−0.3, 밴드 [target−0.3,
target+0.5] 폭 0.8. 계측 근거(v71): 4.84 같은 아깝게 미달 후보가 하한 밖으로
버려져 초과 서빙되던 편향(dev>0:dev<0=34:8) 완화. + gen_meta에 snaps 배열
(attempt별 스냅 — 버려진 후보 관측). 전패 처리는 새 하한 기준으로 불변.

v2.5 (2026-07-21 지연 통제): pre-gate 3롤 gather **병렬 발사** → attempt당
Gemini 콜 항상 3(=1+rerolls, 낭비 콜 포함) / T-map 1(채택만). ⚠️ 이 파일의
gemini_calls 기대치는 attempts×3. + 시간 예산 게이트 20s + 콜 타임아웃 8s +
gen_meta.elapsed_s. mock은 gather에서 gemini_seq를 리스트 순서로 소비.


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
        step("1. 하한 안쪽 합격 — [4.75] (target 5.0, 밴드 [4.7, 5.5])")
        scenario(c, [{"snap_km": 4.75}])
        r = gen(c, tok, target=5.0)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d["total_distance_km"] == round(4.75, 1) and d["target_missed"] is False, d
        assert d["estimated_duration_min"] == round(round(4.75, 1) * 6.5), \
            f"러닝 환산(6'30\"/km) 기대, got {d['estimated_duration_min']}"
        st = stats(c)
        assert st["gemini_calls"] == 3, st  # v2.5 병렬: 1 attempt × 3롤
        # 계측 영속화(리포트 B): 채택 attempt 메타 + snaps(v2.4)가 전달됐는지
        gm = st["last_gen_meta"]
        assert gm and gm["verdict"] == "hit", f"hit verdict 메타, got {gm}"
        assert gm["attempts"] == 1 and gm["ratio"] > 0 and "pre_rejects" in gm, gm
        assert gm["snaps"] == [round(4.75, 1)], f"snaps 배열 저장(v2.4), got {gm.get('snaps')}"
        assert gm.get("initial_ratio") == 1.6, f"initial_ratio 저장(v2.6 §4), got {gm.get('initial_ratio')}"
        ok(f"4.75 합격 · gen_meta verdict=hit snaps={gm['snaps']} initial_ratio={gm['initial_ratio']}")

        step("2. 하한 밖 반려 — [4.65, 4.75] → 4.65(−0.35) 반려·4.75 채택")
        scenario(c, [{"snap_km": 4.65}, {"snap_km": 4.75}])
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == round(4.75, 1) and d["target_missed"] is False, d
        assert d["radius_expanded"] is True, "2시도 = 반경 확장 플래그"
        st = stats(c)
        assert st["gemini_calls"] == 6, "2 attempt × 3롤 = 6 (병렬)"
        assert st["last_gen_meta"]["snaps"] == [round(4.65, 1), round(4.75, 1)], \
            f"attempt별 스냅: 버려진 4.65 + 채택 4.75(v2.4 관측), got {st['last_gen_meta']['snaps']}"
        ok("4.65(−0.35) attempt1 반려 → 4.75 attempt2 채택 · snaps=[4.6, 4.8]")

        step("3. 상한 안쪽 합격 — [5.45] 1시도")
        scenario(c, [{"snap_km": 5.45}])
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == round(5.45, 1) and d["target_missed"] is False, d
        assert stats(c)["gemini_calls"] == 3, stats(c)  # 1 attempt × 3롤
        ok("5.45(+0.45) 합격 · 1 attempt(gemini 3)")

        step("3b. 상한 밖 반려 — [5.55, 5.45] → 5.55 반려·5.45 채택")
        scenario(c, [{"snap_km": 5.55}, {"snap_km": 5.45}])
        d = gen(c, tok, target=5.0).json()
        assert d["target_missed"] is False, d
        assert stats(c)["gemini_calls"] == 6, \
            "2 attempt × 3롤 = 6. 5.55(+0.55)가 원값 게이트에서 반려(표시 반올림 우회 없음)"
        ok("5.55 반려(원값 게이트) → 5.45 채택 · 2 attempt")

        step("4. 전패(캡 내 초과 존재) — [4.0, 5.6, 5.8, 4.2] → 5.6 채택")
        scenario(c, [{"snap_km": 4.0}, {"snap_km": 5.6}, {"snap_km": 5.8}, {"snap_km": 4.2}])
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.6, \
            f"초과 최선(5.6 < 5.8, 둘 다 캡 6.0 내), 미달(4.0·4.2)은 반환 금지, got {d['total_distance_km']}"
        assert d["target_missed"] is True, "전패 플래그"
        st = stats(c)
        assert st["gemini_calls"] == 12, "4 attempt × 3롤 = 12 (cap 4 유지)"
        assert st["last_gen_meta"]["verdict"] == "missed", f"missed verdict, got {st['last_gen_meta']}"
        ok("전패 → 초과 최선 5.6 채택 · missed=true · verdict=missed · 4 attempt")

        step("4b. 전패(미달만) — [4.0, 4.2, 4.4, 4.5] 전부 <하한4.7 → 502 실패")
        scenario(c, [{"snap_km": 4.0}, {"snap_km": 4.2}, {"snap_km": 4.4}, {"snap_km": 4.5}])
        r = gen(c, tok, target=5.0)
        assert r.status_code == 502, f"미달만 전패 → 502, got {r.status_code}: {r.text[:150]}"
        assert r.json()["detail"]["error"] == "route_generation_failed", r.text[:200]
        assert stats(c)["gemini_calls"] == 12, "4 attempt × 3롤 = 12 후 실패"
        ok("전패(미달만 <4.7) → 502 route_generation_failed — 미달 서빙 금지")

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
        assert stats(c)["last_gen_meta"]["verdict"] == "nopath", "nopath verdict 메타"
        ok("NO_PATH 4연속 → AI 추정 폴백 · gen_meta verdict=nopath")

        step("6. 프롬프트 단위 검증 (호출 0회)")
        from app.services.openai_service import _build_prompt, _SNAP_INFLATION, _BAND_AIM_KM
        from app.models.schemas import Coordinate
        assert _SNAP_INFLATION == 1.6 and _BAND_AIM_KM == 0.2, "v2.2 재보정 상수"
        p = _build_prompt(4.0, Coordinate(lat=37.5445, lng=127.0374), None, None, None,
                          radius_km=1.0)
        assert "avoid overshooting" not in p, "과소 기하 유도 문구 삭제"
        expect_chain = round((4.0 + 0.2) / 1.6, 1)
        assert f"about {expect_chain} km" in p, f"기본 체인 목표({expect_chain}) 명시, got: {p[:200]}"
        # 상한만 (v2.6 양방향은 미달 유발로 롤백 — 오너 결정 2026-07-21)
        cap = round(expect_chain * 1.15, 1)
        assert f"MUST NOT exceed {cap} km" in p, "체인 상한 강제 문구"
        assert "err slightly longer" in p, "오버슈트 바이어스(하한 미명시 — 미달 방지)"
        assert "Aim for the middle" not in p, "양방향 middle 문구 롤백"
        # 적응형 오버라이드 — chain_target_km이 오면 그 값이 프롬프트에 실림
        p2 = _build_prompt(4.0, Coordinate(lat=37.5445, lng=127.0374), None, None, None,
                           radius_km=1.0, chain_target_km=2.4)
        assert "about 2.4 km" in p2, "적응형 체인 목표 오버라이드"
        ok(f"프롬프트: 체인 {expect_chain}km · 상한 {cap}(롤백) · err slightly longer")

        step("7. ★적응형 피드백 — [5.6, 5.3] → aim 3.2 → ratio 1.75 관측 → aim 3.0 → 합격")
        scenario(c, [{"snap_km": 5.6}, {"snap_km": 5.3}])
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.3 and d["target_missed"] is False, d
        st = stats(c)
        assert st["gemini_calls"] == 6, st  # 2 attempt × 3롤
        aims = st["chain_targets"]  # 병렬: attempt당 3개 동일 aim → [a1,a1,a1,a2,a2,a2]
        exp1 = round((5.0 + 0.2) / 1.6, 1)          # 3.2 — 초기 상수 조준
        ratio1 = 5.6 / exp1                          # ≈1.75 — mock은 aim에 순응(chain=aim)
        exp2 = round((5.0 + 0.2) / ratio1, 1)        # 3.0 — 관측 ratio 반영
        assert aims[0] == exp1 and aims[3] == exp2, \
            f"적응형 조준 attempt1={exp1} attempt2={exp2} 기대(각 3롤), got {aims}"
        ok(f"attempt1 aim {aims[0]} → ratio {ratio1:.2f} 관측 → attempt2 aim {aims[3]} → 5.3 합격")

        step("7b. ★재추첨 롤 학습 (v2.6) — 반려 롤(과대 체인)이 다음 aim 하향에 기여")
        # attempt1 gemini [×1.3, ×1.3, ×1.0]: 채택은 ×1.0(chain=aim), 반려 ×1.3 2롤.
        # median_chain = aim×1.3 → compliance 1.3 → est_ratio를 1.3배 상향 → aim2↓.
        assert c.post(f"{B8001}/__mock/scenario",
                      json={"seq": [{"snap_km": 5.6}, {"snap_km": 5.2}],
                            "gemini_seq": [1.3, 1.3, 1.0]}).status_code == 200
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.2 and d["target_missed"] is False, d
        aims2 = stats(c)["chain_targets"]
        a1 = round((5.0 + 0.2) / 1.6, 1)             # 3.2 — attempt1 초기 조준
        # v2.6: compliance 1.3 → clamp ±10% → 1.10. est = clamp(5.6/3.2 × 1.10)=1.925
        comp = min(1.3, 1.10)
        est = min(5.6 / a1 * comp, 2.2)
        a2_v26 = round((5.0 + 0.2) / est, 1)         # 2.7 (반려 롤 반영·완화)
        a2_v25 = round((5.0 + 0.2) / (5.6 / a1), 1)  # 3.0 (반려 롤 무시 시)
        assert aims2[3] == a2_v26, \
            f"attempt2 aim v2.6={a2_v26}(반려 반영·clamp) 기대, v2.5면 {a2_v25}, got {aims2[3]}"
        ok(f"반려 롤 ×1.3 → compliance clamp 1.10 → attempt2 aim {aims2[3]}(v2.5면 {a2_v25}, 완화 하향)")

        step("8. ★사전 게이트 병렬 — gemini [×1.6, ×1.0, ×1.0] → 통과 롤 채택 (v2.5)")
        assert c.post(f"{B8001}/__mock/scenario",
                      json={"seq": [{"snap_km": 5.2}], "gemini_seq": [1.6, 1.0, 1.0]}
                      ).status_code == 200
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.2 and d["target_missed"] is False, d
        st = stats(c)
        assert st["gemini_calls"] == 3, f"병렬 3롤 동시 발사 = gemini 3, got {st}"
        assert st["tmap_calls"] == 1, f"gemini만 병렬, T-map은 채택 1개, got {st}"
        ok("병렬 3롤(×1.6 밴드밖·×1.0×2 통과) → 통과 롤 채택 → 5.2 합격 · gemini 3/tmap 1")

        step("9. ★병렬 전 롤 밴드밖 → salvage — gemini [×2.0 ×3] → 최근접 롤 (v2.5)")
        assert c.post(f"{B8001}/__mock/scenario",
                      json={"seq": [{"snap_km": 5.2}],
                            "gemini_seq": [2.0, 2.0, 2.0]}).status_code == 200
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.2 and d["target_missed"] is False, d
        st = stats(c)
        assert st["gemini_calls"] == 3, f"병렬 3롤, got {st}"
        assert st["tmap_calls"] == 1, f"salvage여도 attempt당 T-map 1회, got {st}"
        assert d["radius_expanded"] is False, "salvage로 attempt1에서 완결(attempt 미소실)"
        ok("병렬 3롤 전부 밴드밖 → 최근접 salvage → 5.2 합격 · gemini 3/tmap 1")

        step("10. ★end-aware — |start−end|≈3.5km 일방(실행가능): corridor 반경 + 정상 서빙")
        scenario(c, [{"snap_km": 5.2}])
        d = gen(c, tok, target=5.0,
                end={"lat": 37.5445, "lng": 127.0374 + 0.0396}).json()  # ~3.5km 동쪽
        assert d["total_distance_km"] == 5.2 and d["target_missed"] is False, d
        assert d.get("is_one_way") is True, f"end 동봉 → is_one_way true(리포트 D 갭수정), got {d.get('is_one_way')}"
        r1 = stats(c)["radii"][0]   # 일방 gen의 stats — 루프 gen 전에 확인
        assert r1 >= 2.6, \
            f"end-aware r0 = max(1.2, |s−e|/2+1.0) ≈ 2.7 기대(구식 1.2면 기하 모순), got {r1}"
        ok(f"일방(3.5km) attempt1 radius={r1} · is_one_way=true · 5.2 합격")
        # 루프 요청은 is_one_way false
        scenario(c, [{"snap_km": 5.2}])
        d_loop = gen(c, tok, target=5.0).json()
        assert d_loop.get("is_one_way") is False, f"루프 → is_one_way false, got {d_loop.get('is_one_way')}"
        ok("루프 요청 is_one_way=false (RouteResponse 노출 갭 수정)")

        step("11b. ★traversability 게이트 (리포트 A) — 강 위 leg 후보 폐기")
        # attempt1: untraversable(강 횡단) → 폐기 / attempt2: 정상 5.2 → 채택
        scenario(c, [{"untraversable": True}, {"snap_km": 5.2}])
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.2 and d["target_missed"] is False, d
        assert d.get("polyline"), "채택 후보는 폴리라인 존재"
        ok("강 위 leg 후보 폐기 → 정상 후보 5.2 채택 (물 위 직선 서빙 안 됨)")

        step("11c. ★전 attempt untraversable → 502 (물 위 코스 주느니 실패)")
        scenario(c, [{"untraversable": True}] * 4)
        r = gen(c, tok, target=5.0)
        assert r.status_code == 502, f"전부 보행 불가 → 502, got {r.status_code}: {r.text[:120]}"
        assert r.json()["detail"]["error"] == "route_generation_failed", r.text[:150]
        ok("전 attempt 보행 불가 → 502 (폐기라 candidate 0)")

        step("11d. NO_PATH(T-map 장애)는 여전히 AI추정 폴백 — untraversable과 구분")
        scenario(c, [{"no_path": True}] * 4)
        d = gen(c, tok, target=4.0).json()
        assert d["total_distance_km"] == 4.0, "T-map 장애는 AI추정 폴백 유지(리포트 A와 별개)"
        ok("T-map 장애 → NO_PATH 폴백 유지 (traversability 폐기와 구분됨)")

        step("11. ★일방 실행가능성 게이트 (v2.3 마감) — 경계 통과 / 초과 422 / 루프 무영향")
        # 경계 직전(직선 ≈3.99km ≤ 5×0.8=4.0) → 통과
        scenario(c, [{"snap_km": 5.2}])
        r = gen(c, tok, target=5.0, end={"lat": 37.5445, "lng": 127.0374 + 0.0452})
        assert r.status_code == 200, f"경계 내(3.99≤4.0) 통과 기대, got {r.status_code}: {r.text[:150]}"
        # 초과(직선 ≈5.0km > 4.0) → 422 구조화 에러 + 최소 거리 힌트
        r = gen(c, tok, target=5.0, end={"lat": 37.5445, "lng": 127.0374 + 0.0567})
        assert r.status_code == 422, f"초과 422 기대, got {r.status_code}: {r.text[:150]}"
        det = r.json()["detail"]
        assert det["error"] == "one_way_end_too_far", det
        assert "너무 멀어요" in det["message"] and det["min_target_km"] >= 6.2, det
        # 게이트는 Gemini 비용 0 — 422 요청은 mock gemini 호출 없음
        st_before = stats(c)["gemini_calls"]
        # 루프 요청(end 없음)은 무영향
        scenario(c, [{"snap_km": 5.2}])
        r = gen(c, tok, target=5.0)
        assert r.status_code == 200, "루프 요청 무영향"
        ok(f"경계 3.99 통과 · 5.0 초과 422(min_target={det['min_target_km']}) · 루프 무영향")

        step("12. ★시간 예산 게이트 (v2.5) — 지연 주입 → 예산 초과 시 최선 판정")
        # gen_delay 0.1s + budget 0.05s: attempt1(초과 5.6) 후 경과>예산 →
        # attempt2 진입 금지 → miss_candidate 5.6 초과 서빙(missed). 1 attempt만.
        assert c.post(f"{B8001}/__mock/scenario",
                      json={"seq": [{"snap_km": 5.6}, {"snap_km": 5.2}],
                            "gen_delay_s": 0.1, "budget_s": 0.05}).status_code == 200
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.6 and d["target_missed"] is True, \
            f"예산 초과 → attempt1 최선(5.6 초과) missed 서빙, got {d}"
        st = stats(c)
        assert st["gemini_calls"] == 3, f"1 attempt만(예산 게이트로 attempt2 차단), got {st}"
        assert st["last_gen_meta"]["attempts"] == 1, "gen_meta attempts=1(조기 종료)"
        assert st["last_gen_meta"].get("elapsed_s") is not None, "elapsed_s 저장(v2.5)"
        ok(f"예산 0.05s 초과 → attempt1 최선 5.6 missed 서빙 · attempts=1 · elapsed_s={st['last_gen_meta']['elapsed_s']}")

        step("13. ★콜 타임아웃 부분 실패 (v2.5) — [timeout, ×1.0, ×1.0] → 성공 롤 채택")
        assert c.post(f"{B8001}/__mock/scenario",
                      json={"seq": [{"snap_km": 5.2}],
                            "gemini_seq": [-1, 1.0, 1.0]}).status_code == 200
        d = gen(c, tok, target=5.0).json()
        assert d["total_distance_km"] == 5.2 and d["target_missed"] is False, \
            f"타임아웃 롤 무시하고 성공 롤 채택, got {d}"
        st = stats(c)
        assert st["gemini_calls"] == 3, f"3롤 발사(1 타임아웃+2 성공), got {st}"
        ok("병렬 3롤 중 1롤 타임아웃 → 나머지 2롤로 5.2 채택 (롤 실패 처리)")

        step("14. ★콜 타임아웃 전 롤 실패 (v2.5) — [timeout×3] → 502")
        assert c.post(f"{B8001}/__mock/scenario",
                      json={"seq": [{"snap_km": 5.2}],
                            "gemini_seq": [-1, -1, -1]}).status_code == 200
        r = gen(c, tok, target=5.0)
        assert r.status_code == 502, f"전 롤 타임아웃 → 502, got {r.status_code}: {r.text[:120]}"
        assert r.json()["detail"]["error"] == "route_generation_failed", r.text[:150]
        ok("병렬 3롤 전부 타임아웃 → 502 (OpenAIAPIError 분기 · 후보 0)")

        print("\n" + "=" * 50 + "\n  MOCK 케이스 PASSED — E2E는 메인 서버로\n" + "=" * 50)

        step("E2E. 실호출 3건 (target=5.0) — 사용자 좌표(수술 전 502) 포함, 개선 방향 확인")
        e2e_cases = [
            ("성수 루프", {"lat": 37.5445, "lng": 127.0374}),
            ("여의도 루프", {"lat": 37.5285, "lng": 126.9328}),
            ("★사용자 좌표(뚝섬 인근)", {"lat": 37.5219, "lng": 127.0561}),  # 09:44 502·09:26 5.6
        ]
        for name, s in e2e_cases:
            r = gen(c, tok, base=BASE, target=5.0, start=s)
            if r.status_code == 502:
                assert r.json()["detail"]["error"] == "route_generation_failed", r.text[:200]
                print(f"    {name}: 502 (전패 — 정직 실패)")
                continue
            assert r.status_code == 200, f"{name}: {r.text[:250]}"
            d = r.json()
            total = d["total_distance_km"]
            in_band = 4.7 - 1e-9 <= total <= 5.5 + 1e-9  # v2.4 밴드 [−0.3, +0.5]
            if in_band:
                assert d["target_missed"] is False, d["target_missed"]
            else:
                assert d["target_missed"] is True and total <= 6.0 + 1e-9, \
                    f"{name} 계약 위반: {total}, missed={d['target_missed']} (캡 6.0)"
            assert d["estimated_duration_min"] == round(total * 6.5), \
                f"러닝 환산 duration 기대, got {d['estimated_duration_min']}"
            print(f"    {name}: total={total}km (오차 {total-5.0:+.2f}) "
                  f"missed={d['target_missed']}{' ★명중' if in_band else ''}")
        ok("E2E 3건 계약 준수 (사용자 좌표 개선 방향은 위 출력)")

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
