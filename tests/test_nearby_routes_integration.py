"""
Integration test: GET /api/routes/nearby
- 2단계 필터 검증: SQL bounding box → Python Haversine
- box 모서리(박스 안, 원 밖) 케이스 포함
Run: python tests/test_nearby_routes_integration.py
"""
from __future__ import annotations

import os, sys, time, math
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"

# ── 테스트 중심점: 서울 시청 부근 ────────────────────────────────────────────
CENTER_LAT = 37.5665
CENTER_LNG = 126.9780
RADIUS_KM  = 5.0

# ── 테스트 좌표 정의 ─────────────────────────────────────────────────────────
# A: 중심에서 북쪽 0.4 km → 반경 안
NEAR_A_LAT, NEAR_A_LNG = 37.5702, 126.9780

# B: 중심에서 SW 1.3 km → 반경 안
NEAR_B_LAT, NEAR_B_LNG = 37.5585, 126.9670

# C: 박스 안이지만 원 밖 (~6.4 km) — Haversine 2단계가 걸러야 함
#   lat diff = 0.0435 < lat_delta(≈0.0450)  ✓ 박스 안
#   lng diff = 0.0470 < lng_delta(≈0.0568)  ✓ 박스 안
#   실제 거리 ≈ 6.4 km > 5 km              ✓ 원 밖
BOX_ONLY_LAT, BOX_ONLY_LNG = 37.6100, 127.0250

# D: 부산 (멀리) → 박스도 원도 밖
FAR_LAT, FAR_LNG = 35.1796, 129.0756


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lng2 - lng1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _keys() -> tuple[str, str]:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):             anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def ok(m):         print(f"  ✓ {m}")
def fail(m, d=""):  print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):       print(f"\n[{t}]")

def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201): fail("create user", r.text[:200])
    return r.json()["id"]

def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]

def sb_del_user(c, uid):
    c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)

def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})

def sb_insert_route(c, uid, summary, start_lat, start_lng, is_public):
    """직접 DB에 좌표를 지정해 코스 삽입."""
    r = c.post(f"{_SB}/rest/v1/routes",
               headers={**_ADM, "Prefer": "return=representation"},
               json={
                   "user_id": uid, "summary": summary,
                   "total_distance_km": 5.0, "is_public": is_public,
                   "waypoints": [], "start_lat": start_lat, "start_lng": start_lng,
               })
    if r.status_code not in (200, 201): fail("insert route", r.text[:200])
    return r.json()[0]["id"]

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def nearby(c, tok, lat=None, lng=None, radius_km=None, sort_by="newest", limit=20):
    params = {"sort_by": sort_by, "limit": limit}
    if lat       is not None: params["lat"]       = lat
    if lng       is not None: params["lng"]       = lng
    if radius_km is not None: params["radius_km"] = radius_km
    return api(c, "GET", "/routes/nearby", tok, params=params)


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"nr-u{i}-{ts}@t.s" for i in range(1, 3)]
    uids: list[str] = []; toks: list[str] = []
    route_ids: list[str] = []
    sfx = str(ts)[-6:]

    # 좌표 거리 사전 검증 (테스트 논리 보증)
    assert _haversine_km(CENTER_LAT, CENTER_LNG, NEAR_A_LAT, NEAR_A_LNG) < RADIUS_KM, \
        "A 지점이 반경 안이어야 함"
    assert _haversine_km(CENTER_LAT, CENTER_LNG, NEAR_B_LAT, NEAR_B_LNG) < RADIUS_KM, \
        "B 지점이 반경 안이어야 함"
    assert _haversine_km(CENTER_LAT, CENTER_LNG, BOX_ONLY_LAT, BOX_ONLY_LNG) > RADIUS_KM, \
        "C 지점(박스 모서리)이 반경 밖이어야 함"
    assert _haversine_km(CENTER_LAT, CENTER_LNG, FAR_LAT, FAR_LNG) > RADIUS_KM, \
        "부산 지점이 반경 밖이어야 함"

    # C 지점이 bounding box 안인지 확인
    lat_delta = RADIUS_KM / 111.0
    lng_delta = RADIUS_KM / (111.0 * math.cos(math.radians(CENTER_LAT)))
    assert abs(BOX_ONLY_LAT - CENTER_LAT) < lat_delta, "C lat이 박스 안이어야 함"
    assert abs(BOX_ONLY_LNG - CENTER_LNG) < lng_delta, "C lng이 박스 안이어야 함"

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 2명 ───────────────────────────────────────────────
            step("1. 유저 2명 생성 + 로그인")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2 = uids; tok1, tok2 = toks
            ok(f"u1={uid1[:8]}  u2={uid2[:8]}")

            # ── 2. 코스 5개 삽입 ──────────────────────────────────────────
            step("2. 코스 삽입 (근처2 + 박스모서리1 + 부산1 + 비공개근처1)")
            r_near_a    = sb_insert_route(c, uid1, f"서울한강코스A{sfx}",  NEAR_A_LAT,  NEAR_A_LNG,  True)
            r_near_b    = sb_insert_route(c, uid1, f"서울남산코스B{sfx}",  NEAR_B_LAT,  NEAR_B_LNG,  True)
            r_box_only  = sb_insert_route(c, uid1, f"박스모서리코스{sfx}", BOX_ONLY_LAT, BOX_ONLY_LNG, True)
            r_far       = sb_insert_route(c, uid1, f"부산해운대코스{sfx}", FAR_LAT,     FAR_LNG,     True)
            r_private   = sb_insert_route(c, uid1, f"비공개근처코스{sfx}", NEAR_A_LAT,  NEAR_A_LNG,  False)
            route_ids  += [r_near_a, r_near_b, r_box_only, r_far, r_private]
            ok(f"5개 삽입 완료  (근처A={r_near_a[:8]}, 근처B={r_near_b[:8]}, "
               f"박스모서리={r_box_only[:8]}, 부산={r_far[:8]}, 비공개={r_private[:8]})")

            # ── 3. 서울 중심 반경 5km 조회 ────────────────────────────────
            step("3. 서울 반경 5km 조회 → 근처A·B만, 박스모서리·부산·비공개 제외")
            r = nearby(c, tok1, CENTER_LAT, CENTER_LNG, RADIUS_KM)
            assert r.status_code == 200, f"200 이어야 함, got {r.status_code}: {r.text[:200]}"
            ids = [x["id"] for x in r.json()]

            assert r_near_a   in ids,     "근처 코스 A가 결과에 없음"
            assert r_near_b   in ids,     "근처 코스 B가 결과에 없음"
            assert r_box_only not in ids, "박스모서리 코스가 결과에 있으면 안 됨 (Haversine 2단계 실패)"
            assert r_far      not in ids, "부산 코스가 결과에 있으면 안 됨"
            assert r_private  not in ids, "비공개 코스가 결과에 있으면 안 됨"
            ok(f"근처 {len(ids)}개 반환 ✓  박스모서리 제외 ✓  부산 제외 ✓  비공개 제외 ✓")

            # ── 4. 박스 모서리 케이스 — 2단계 Haversine 명시 검증 ─────────
            step("4. 박스모서리 코스 거리 재확인 (박스 안, 원 밖)")
            dist_c = _haversine_km(CENTER_LAT, CENTER_LNG, BOX_ONLY_LAT, BOX_ONLY_LNG)
            ok(f"박스모서리 실제 거리={dist_c:.2f} km (반경={RADIUS_KM} km) — "
               f"박스 통과, Haversine 차단 ✓")
            assert r_box_only not in ids, "Haversine 2단계가 박스모서리를 걸러야 함"

            # ── 5. 파라미터 누락 → 400 ───────────────────────────────────
            step("5. 파라미터 누락 → 400")
            assert nearby(c, tok1, lat=CENTER_LAT, lng=CENTER_LNG).status_code == 400, \
                "radius_km 없으면 400 이어야 함"
            assert nearby(c, tok1, lat=CENTER_LAT, radius_km=RADIUS_KM).status_code == 400, \
                "lng 없으면 400 이어야 함"
            assert nearby(c, tok1, lng=CENTER_LNG, radius_km=RADIUS_KM).status_code == 400, \
                "lat 없으면 400 이어야 함"
            assert nearby(c, tok1).status_code == 400, "모두 없으면 400 이어야 함"
            ok("파라미터 누락 → 400 ✓")

            # ── 6. 결과에 메타 필드 포함 ─────────────────────────────────
            step("6. 결과에 like_count·copy_count·comment_count·is_liked·is_mine 포함")
            results = r.json()
            for route in results:
                for field in ("like_count", "copy_count", "comment_count", "is_liked", "is_mine"):
                    assert field in route, f"결과에 {field} 없음"
            a_res = next(x for x in results if x["id"] == r_near_a)
            assert a_res["is_mine"] is True, "본인 코스 is_mine=True 이어야 함"
            ok("메타 필드 포함 ✓  is_mine=True ✓")

            # ── 7. sort_by=popular 작동 확인 ─────────────────────────────
            step("7. sort_by=popular → 200, 근처 코스 포함")
            # u2가 r_near_a를 좋아요/복사 → copy_count 차이 생성
            api(c, "POST", f"/routes/{r_near_a}/copy", tok2)
            r_pop = nearby(c, tok1, CENTER_LAT, CENTER_LNG, RADIUS_KM, sort_by="popular")
            assert r_pop.status_code == 200, f"sort_by=popular → 200 이어야 함, got {r_pop.status_code}"
            pop_ids = [x["id"] for x in r_pop.json()]
            assert r_near_a in pop_ids, "sort_by=popular 결과에 근처A 없음"
            assert r_near_b in pop_ids, "sort_by=popular 결과에 근처B 없음"
            # 첫 번째 결과가 copy_count가 더 높은 r_near_a 이어야 함
            assert pop_ids[0] == r_near_a, \
                f"sort_by=popular 첫 번째가 r_near_a 이어야 함, got {pop_ids[0]}"
            ok("sort_by=popular 작동 ✓  copy_count 기준 정렬 ✓")

            # ── 8. 부산 중심으로 조회 → 서울 코스 없음 ──────────────────
            step("8. 부산(FAR) 중심 5km 조회 → 서울 코스 없음")
            r_busan = nearby(c, tok1, FAR_LAT, FAR_LNG, RADIUS_KM)
            assert r_busan.status_code == 200
            busan_ids = [x["id"] for x in r_busan.json()]
            assert r_near_a not in busan_ids, "부산 조회에 서울A 코스가 있으면 안 됨"
            assert r_near_b not in busan_ids, "부산 조회에 서울B 코스가 있으면 안 됨"
            assert r_far    in  busan_ids,    "부산 코스가 부산 조회 결과에 없음"
            ok("부산 조회 → 부산 코스만 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)

        finally:
            step("Cleanup")
            # 복사본 삭제 (u2가 복사한 코스)
            copy_res = c.get(f"{_SB}/rest/v1/routes",
                             headers=_ADM,
                             params={"copied_from": f"eq.{r_near_a if route_ids else 'none'}",
                                     "user_id": f"eq.{uid2 if uids else 'none'}"})
            copy_ids = [x["id"] for x in copy_res.json()] if copy_res.status_code == 200 else []
            sb_del_in(c, "routes", "id", copy_ids + route_ids)
            ok("routes 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")


if __name__ == "__main__":
    run()
