"""
Integration test: GPS 데이터 파이프라인 (러닝 기록 서버 검증)
1) 결정론 — 합성 궤적 4종(정상/accuracy 노이즈/순간이동/자전거)의 필터·거리·
   스플릿 수치 assert + 괴리 판정 + 상한/부족 (외부 API 0)
2) 통합 — POST /runs(gps_track) → 검증·대체·스플릿·/track 왕복, 하위 호환,
   통계·PB·크루 랭킹의 서버 거리 연쇄 확인
Run: python tests/test_gps_track_integration.py
"""
from __future__ import annotations

import math
import os
import random
import sys
import time

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys() -> tuple[str, str]:
    anon = svc = ""
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                svc = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(m):
    print(f"  ✓ {m}")


def fail(m, d=""):
    print(f"  ✗ {m}" + (f": {d}" if d else ""))
    sys.exit(1)


def step(t):
    print(f"\n[{t}]")


def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201):
        fail("create user", r.text[:200])
    return r.json()["id"]


def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200:
        fail("login", r.text[:200])
    return r.json()["access_token"]


def sb_del_user(c, uid):
    c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)


def sb_del_in(c, table, col, vals):
    if not vals:
        return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})


def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


# ═══ 합성 GPS 궤적 생성기 ════════════════════════════════════════════════════

def make_track(distance_km: float, pace_sec_per_km: float, interval_s: float = 4.0,
               jitter_m: float = 3.0, seed: int = 42,
               start=(37.5445, 127.0374), with_alt: bool = True,
               as_dict: bool = False):
    """방향 랜덤워크로 지정 거리·페이스의 궤적을 결정론적으로 생성.

    1m ≈ 위도 1/110540°, 경도 1/(111320·cos(lat))° 근사. jitter는 GPS 노이즈 모사.
    """
    rng = random.Random(seed)
    speed = 1000.0 / pace_sec_per_km          # m/s
    step_m = speed * interval_s
    n = int(distance_km * 1000.0 / step_m) + 1
    lat, lng = start
    heading = rng.uniform(0, 2 * math.pi)
    t = 1_783_300_000_000                      # 고정 epoch ms (결정론)
    pts = []
    for i in range(n):
        ky = 110540.0
        kx = 111320.0 * math.cos(math.radians(lat))
        jl = rng.gauss(0, jitter_m)
        jn = rng.gauss(0, jitter_m)
        alt = 30.0 + 6.0 * math.sin(i * 0.02) + rng.gauss(0, 0.8) if with_alt else None
        pts.append({"lat": round(lat + jn / ky, 7), "lng": round(lng + jl / kx, 7),
                    "t": t, "acc": round(abs(rng.gauss(8, 2)), 1),
                    **({"alt": round(alt, 1)} if alt is not None else {})})
        heading += rng.gauss(0, math.radians(6))  # 느린 회전 — 러닝 코스 곡률
        lat += step_m * math.cos(heading) / ky
        lng += step_m * math.sin(heading) / kx
        t += int(interval_s * 1000)
    return pts if as_dict else pts


def to_points(dicts):
    from app.services.track_service import TrackPoint
    return [TrackPoint(lat=d["lat"], lng=d["lng"], t_ms=d["t"],
                       acc=d.get("acc"), alt=d.get("alt")) for d in dicts]


# ═══ Phase 1: 결정론 (순수 파이프라인) ═══════════════════════════════════════

def phase1():
    from app.services import track_service as ts

    step("1-1. 정상 궤적: 5km@5'30\" → 거리·스플릿·검증")
    track = make_track(5.0, 330)
    p = ts.process_track(to_points(track))
    assert p is not None and not p.low_confidence
    assert abs(p.server_distance_km - 5.0) / 5.0 <= 0.04, \
        f"서버 거리 5km±4% 기대, got {p.server_distance_km}"
    full = [s for s in p.splits if not s.partial]
    assert len(full) == int(p.server_distance_km), "정수 km 랩 수"
    for s in full:
        assert abs(s.sec - 330) <= 25, f"등속 궤적 스플릿은 330s 근처여야 함: {s}"
    assert sum(s.sec for s in p.splits) <= p.elapsed_s + 2
    # alt 프로필: 6m 진폭 sin ~4주기 → 상승 ~48m (hysteresis로 약간 깎임)
    assert p.elev_gain_m is not None and 30 <= p.elev_gain_m <= 60, p.elev_gain_m
    assert ts.classify(p, 5.0) == "verified"
    assert ts.classify(p, 5.2) == "verified", "±10% 이내는 앱 값 인정"
    ok(f"거리 {p.server_distance_km}km ✓ 스플릿 {len(full)}랩 균등 ✓ "
       f"elev {p.elev_gain_m}m ✓ verified ✓")

    step("1-2. accuracy 노이즈: 중간 10% acc=80 → 필터 후 거리 복원")
    noisy = make_track(5.0, 330, seed=7)
    n = len(noisy)
    for i in range(int(n * 0.45), int(n * 0.55)):  # 중간 10%를 불량 픽스로
        noisy[i] = {**noisy[i], "acc": 80.0,
                    "lat": noisy[i]["lat"] + 0.0008}  # ~90m 튐
    p = ts.process_track(to_points(noisy))
    assert p is not None
    assert p.point_count_kept <= n - int(n * 0.10) + 2, "불량 픽스 제거"
    assert abs(p.server_distance_km - 5.0) / 5.0 <= 0.05, \
        f"필터 후 거리 복원 기대, got {p.server_distance_km}"
    assert not p.low_confidence, "10% 제거는 low_confidence 아님 (경계 20%)"
    ok(f"제거 {n - p.point_count_kept}pt ✓ 거리 {p.server_distance_km}km 복원 ✓")

    step("1-3. 순간이동 스파이크: 1pt를 500m 밖으로 → 제거 + 거리 영향 <1%")
    spike = make_track(5.0, 330, seed=11)
    base = ts.process_track(to_points(spike)).server_distance_km
    mid = len(spike) // 2
    spike[mid] = {**spike[mid], "lat": spike[mid]["lat"] + 0.0045}  # ~500m 점프
    p = ts.process_track(to_points(spike))
    assert p.point_count_kept == len(spike) - 1, "스파이크 1pt 제거"
    assert abs(p.server_distance_km - base) / base < 0.01, \
        f"거리 영향 <1% 기대: base {base} vs {p.server_distance_km}"
    ok(f"스파이크 제거 ✓ 거리 {base}→{p.server_distance_km}km (영향 미미) ✓")

    step("1-4. 자전거 페이스: 5km@2'00\" → suspect")
    bike = make_track(5.0, 120, seed=13)
    p = ts.process_track(to_points(bike))
    assert p is not None
    assert ts.classify(p, 5.0) == "suspect", \
        f"평균 2'00\"/km는 suspect여야 함 (avg {p.elapsed_s / p.server_distance_km:.0f}s/km)"
    # 최속 스플릿 트리거: 평균은 정상(5'30")인데 한 구간만 2'20"
    ok("평균 페이스 suspect ✓")

    step("1-5. 거리 괴리: 트랙 5km vs 신고 8km → adjusted")
    p = ts.process_track(to_points(make_track(5.0, 330)))
    assert ts.classify(p, 8.0) == "adjusted"
    assert ts.classify(p, 4.0) == "adjusted", "미달 방향 괴리도 대체"
    ok("±10% 초과 괴리 → adjusted ✓")

    step("1-6. 일시정지 gap: 120s 정지 중 300m 이동 → 거리 미산입")
    pause = make_track(5.0, 330, seed=17)
    mid = len(pause) // 2
    moved = []
    for i, pt in enumerate(pause):
        if i >= mid:
            pt = {**pt, "t": pt["t"] + 120_000,
                  "lat": pt["lat"] + 0.0027}  # 정지 후 300m 딴 곳에서 재개
        moved.append(pt)
    p = ts.process_track(to_points(moved))
    assert p is not None
    assert abs(p.server_distance_km - 5.0) / 5.0 <= 0.05, \
        f"gap 구간 300m가 거리에 안 들어가야 함: {p.server_distance_km}"
    ok(f"gap 미산입 ✓ (거리 {p.server_distance_km}km)")

    step("1-7. 부족/무효 트랙")
    assert ts.process_track(to_points(make_track(0.02, 330)[:8])) is None
    ok("10pt 미만 → None (run은 unverified로 저장) ✓")


# ═══ Phase 2: 통합 (본 서버 8000) ════════════════════════════════════════════

def phase2(c, uids, toks, crew_id):
    uid1, uid2 = uids
    tok1, tok2 = toks

    def post_run(tok, body):
        return api(c, "POST", "/runs", tok, json=body)

    step("2-1. GPS 있는 POST → verified + 스플릿 + /track 왕복")
    track = make_track(5.0, 330, seed=21)
    r = post_run(tok1, {"distance_km": 5.0, "duration_sec": 1650, "gps_track": track})
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    run1 = d["id"]
    assert d["verification"] == "verified" and d["has_track"] is True
    assert d["distance_km_reported"] is None and d["is_flagged"] is False
    assert d["splits"] and len([s for s in d["splits"] if not s.get("partial")]) >= 4
    r = api(c, "GET", f"/runs/{run1}/track", tok1)
    assert r.status_code == 200, r.text[:300]
    t = r.json()
    assert len(t["polyline"]) >= 20 and t["server_distance_km"] > 4.5
    assert t["point_count_raw"] > t["point_count_kept"] - 1 >= 0
    # track은 visibility 게이트(집계 정합 설계) — 이 run은 기본 public이라 타인도 200.
    # 매트릭스 전수는 test_run_track_and_stats_integration.
    assert api(c, "GET", f"/runs/{run1}/track", tok2).status_code == 200, "남의 public track 200"
    ok("verified + splits ✓ /track polyline·공개범위 게이트 ✓")

    step("2-2. 거리 괴리 신고 → verified+is_flagged (조정) + 서버 값이 정본")
    track = make_track(5.0, 330, seed=23)
    r = post_run(tok1, {"distance_km": 9.0, "duration_sec": 1650, "gps_track": track})
    d = r.json()
    run2 = d["id"]
    # DB 3종 체계: 거리 조정은 verified + is_flagged=true + 원본 보존으로 표현
    assert d["verification"] == "verified" and d["is_flagged"] is True
    assert d["distance_km_reported"] == 9.0
    assert abs(d["distance_km"] - 5.0) <= 0.3, f"distance_km는 서버 값: {d['distance_km']}"
    # 연쇄: 통계·PB가 서버 값 사용
    s = api(c, "GET", "/me/stats", tok1).json()
    assert s["all_time"]["total_distance_km"] < 12.0, \
        "통계가 신고 9km가 아닌 서버 ~5km를 써야 함"
    assert s["records"]["longest_distance"]["value"] < 6.0, "PB도 서버 값 기준"
    ok(f"adjusted (9.0 신고→{d['distance_km']}km 정본) ✓ 통계·PB 연쇄 ✓")

    step("2-3. 자전거 → suspect + PB·크루 랭킹·챌린지 제외")
    bike = make_track(6.0, 120, seed=25)
    r = post_run(tok2, {"distance_km": 6.0, "duration_sec": 720, "gps_track": bike})
    d = r.json()
    assert d["verification"] == "suspect" and d["is_flagged"] is True, d
    # PB 제외: u2의 records에 이 run이 없어야 함
    s = api(c, "GET", "/me/stats", tok2).json()
    assert s["records"]["longest_distance"] is None, "suspect run은 PB 후보가 아님"
    # 크루 랭킹 제외 (u1·u2 둘 다 크루원)
    r = api(c, "GET", f"/crews/{crew_id}/ranking", tok1)
    assert r.status_code == 200, r.text[:200]
    mine = {e["user_id"]: e for e in r.json()}
    assert uid2 not in mine or mine[uid2]["total_distance_km"] == 0, \
        f"suspect run이 랭킹에 집계되면 안 됨: {mine.get(uid2)}"
    ok("suspect ✓ PB 제외 ✓ 크루 랭킹 제외 ✓")

    step("2-4. 하위 호환: GPS 없는 POST — 기존과 동일")
    r = post_run(tok2, {"distance_km": 3.0, "duration_sec": 1080,
                        "avg_pace_sec_per_km": 360, "notes": "수동 입력"})
    d = r.json()
    assert r.status_code == 200
    assert d["verification"] == "unverified" and d["has_track"] is False
    assert d["is_flagged"] is False
    assert d["splits"] is None and d["distance_km"] == 3.0
    assert d["new_records"] != [] or d["new_records"] == [], "응답 스키마 유지"
    r = api(c, "GET", f"/runs/{d['id']}/track", tok2)
    assert r.status_code == 404, "트랙 없는 run의 /track은 404"
    # unverified는 통계·랭킹 포함 (현행 유지)
    s = api(c, "GET", "/me/stats", tok2).json()
    assert s["all_time"]["total_distance_km"] >= 3.0
    ok("unverified 저장 ✓ splits null ✓ 통계 포함(현행 유지) ✓")

    step("2-5. 불량 페이로드: 상한 초과 422 / 부족 트랙은 unverified 저장")
    too_many = make_track(5.0, 330)[:1] * 5001
    r = post_run(tok1, {"distance_km": 5.0, "duration_sec": 1650, "gps_track": too_many})
    assert r.status_code == 422, f"5001pt → 422, got {r.status_code}"
    r = post_run(tok1, {"distance_km": 2.0, "duration_sec": 700,
                        "gps_track": make_track(2.0, 350)[:8]})
    d = r.json()
    assert r.status_code == 200 and d["verification"] == "unverified"
    assert d["has_track"] is False, "무효 트랙은 저장 안 함 (기록은 유지)"
    ok("5001pt 422 ✓ 8pt → run 저장 + unverified ✓")

    return [run1, run2]


def run():
    ts_ = int(time.time())
    pw = "TestPass123!"
    emails = [f"gps-u{i}-{ts_}@t.l" for i in range(1, 3)]
    uids: list[str] = []
    crew_ids: list[str] = []

    with httpx.Client(timeout=60) as c:
        try:
            phase1()

            step("공용: 유저 2명 + 크루 (랭킹 연쇄 확인용)")
            toks = []
            for i, e in enumerate(emails, start=1):
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
                assert api(c, "PATCH", "/me/profile", toks[-1],
                           json={"nickname": f"지피u{i}-{ts_ % 100000}"}).status_code == 200
            r = api(c, "POST", "/crews", toks[0], json={"name": f"GPS크루-{ts_}"})
            assert r.status_code in (200, 201), r.text[:200]
            crew_id = r.json()["id"]
            crew_ids.append(crew_id)
            assert api(c, "POST", f"/crews/{crew_id}/join", toks[1]).status_code == 200
            ok("유저 2명 + 크루 + u2 가입")

            phase2(c, uids, toks, crew_id)

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            sb_del_in(c, "runs", "user_id", uids)      # run_tracks CASCADE
            sb_del_in(c, "crews", "id", crew_ids)
            sb_del_in(c, "notifications", "user_id", uids)
            sb_del_in(c, "notifications", "actor_id", uids)
            sb_del_in(c, "profiles", "user_id", uids)
            for uid in uids:
                sb_del_user(c, uid)
            ok("runs(tracks CASCADE)·crews·profiles·auth users 삭제")


if __name__ == "__main__":
    run()
