"""
Integration test: 위치 기반 public run 탐색 피드 (GET /feed/nearby) — 2026-07-15

설계: docs/NEARBY_FEED_DESIGN.md §7 매트릭스 전수.
필터 합성: visibility='public' → bbox → 본인 제외 → 팔로우 유저 제외 →
visible_owners(차단 양방향+비공개 계정 제외) → haversine 원형 후필터. 최신순.

매트릭스:
 1  반경 5km 내 타인 public run          → 노출
 2  반경 밖(~15km) public run            → 제외
 3  반경 내 followers run                → 제외 (visibility 게이트)
 4  반경 내 private run                  → 제외
 5  본인 public run(반경 내)             → 제외 (본인)
 6  팔로우 중 유저의 반경 내 public run  → 제외 (팔로우)
 7  차단(양방향) owner의 public run      → 제외 (visible_owners)
 8  비공개 계정(profile private) public run, 비팔로우 → 제외 (프라이버시 핵심, 이중검증)
 9  트랙 없는(start_lat null) public run → 제외
 10 bbox 안·원 밖 모서리 run             → 제외 (haversine 후필터)
 11 radius_km 상한(>20) 처리             → 20으로 clamp
 12 lat 누락                             → 400
 13 페이지네이션(limit/offset)           → 중복·누락 없음
 14 신규 run 저장 시 start_lat 자동 채움 → 트랙 첫 점과 일치

Run: python tests/test_nearby_feed_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import math
import os
import sys
import time

import httpx

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"

# 기준점 (서울 반포 부근) — 모든 상대 좌표의 원점
ORIGIN_LAT, ORIGIN_LNG = 37.5109, 126.9956


def _keys() -> tuple[str, str]:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                svc = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}
TS = int(time.time())


def ok(m): print(f"  ✓ {m}")
def step(t): print(f"\n[{t}]")


def offset_coord(lat, lng, north_km, east_km):
    """기준 좌표에서 north/east km 만큼 떨어진 좌표."""
    dlat = north_km / 111.0
    dlng = east_km / (111.0 * math.cos(math.radians(lat)))
    return lat + dlat, lng + dlng


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
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {token}"}, **kw)


def make_gps(lat, lng, n=12, step_m=30):
    """(lat,lng)에서 시작하는 단순 직선 GPS 트랙 — 첫 점이 시작 좌표가 됨."""
    pts = []
    for i in range(n):
        dlat = (i * step_m) / 111000.0
        pts.append({"lat": round(lat + dlat, 6), "lng": round(lng, 6),
                    "t": i * 6000, "acc": 5.0})
    return pts


def save_run(c, tok, lat, lng, vis, title=None, with_track=True):
    body = {"distance_km": 2.0, "duration_sec": 720, "visibility": vis}
    if title:
        body["title"] = title
    if with_track:
        body["gps_track"] = make_gps(lat, lng)
    r = api(c, "POST", "/runs", tok, json=body)
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]


def nearby(c, tok, lat=ORIGIN_LAT, lng=ORIGIN_LNG, radius_km=10, limit=20, offset=0):
    return api(c, "GET", "/feed/nearby", tok,
               params={"lat": lat, "lng": lng, "radius_km": radius_km,
                       "limit": limit, "offset": offset})


def run_ids_in(resp):
    return {x["run_id"] for x in resp.json()}


def run_tests():
    c = httpx.Client(timeout=60)
    uids, tk = {}, {}
    created = []
    SECRET8 = f"비공개계정런{TS}"
    try:
        step("0. 유저 준비: V(뷰어)·N(근처)·F(반경밖)·FOL(팔로우대상)·"
             "BLK(차단)·PRIV(비공개계정)")
        for k in ("v", "n", "f", "fol", "blk", "priv"):
            uids[k] = sb_user(c, f"nf-{k}-{TS}@test.com")
            tk[k] = sb_login(c, f"nf-{k}-{TS}@test.com")
            assert api(c, "PATCH", "/me/profile", tk[k],
                       json={"nickname": f"NF{k}{TS}"}).status_code == 200
        # V가 FOL을 팔로우
        assert api(c, "POST", f"/users/{uids['fol']}/follow", tk["v"]).status_code == 204
        # V ↔ BLK 차단
        assert api(c, "POST", f"/users/{uids['blk']}/block", tk["v"]).status_code == 204
        # PRIV 계정을 비공개로
        assert api(c, "PATCH", "/me/profile", tk["priv"],
                   json={"visibility": "private"}).status_code == 200
        ok("V→FOL 팔로우, V↔BLK 차단, PRIV 비공개 계정")

        step("1~10. run 생성 (좌표·visibility 다양)")
        near = offset_coord(ORIGIN_LAT, ORIGIN_LNG, 3, 0)        # 3km 북
        far = offset_coord(ORIGIN_LAT, ORIGIN_LNG, 15, 0)       # 15km 북 (반경 밖)
        corner = offset_coord(ORIGIN_LAT, ORIGIN_LNG, 9, 9)     # bbox 안, 원 밖(~12.7km)
        r_near_pub = save_run(c, tk["n"], *near, "public", title="근처공개")     # 1
        r_far_pub = save_run(c, tk["n"], *far, "public", title="먼공개")         # 2
        r_near_fol_vis = save_run(c, tk["n"], *near, "followers", title="근처팔로워공개")  # 3
        r_near_priv = save_run(c, tk["n"], *near, "private", title="근처비공개")  # 4
        r_self = save_run(c, tk["v"], *near, "public", title="본인런")          # 5
        r_followed = save_run(c, tk["fol"], *near, "public", title="팔로우런")   # 6
        r_blocked = save_run(c, tk["blk"], *near, "public", title="차단런")      # 7
        r_privacct = save_run(c, tk["priv"], *near, "public", title=SECRET8)     # 8
        r_notrack = save_run(c, tk["n"], *near, "public", title="트랙없음",
                             with_track=False)                                   # 9
        r_corner = save_run(c, tk["n"], *corner, "public", title="모서리")       # 10
        created = [r_near_pub, r_far_pub, r_near_fol_vis, r_near_priv, r_self,
                   r_followed, r_blocked, r_privacct, r_notrack, r_corner]
        ok(f"run 10건 생성 (근처공개·먼공개·팔로워·비공개·본인·팔로우·차단·"
           f"비공개계정·트랙없음·모서리)")

        step("14. 신규 run 저장 시 start_lat 자동 채움 (트랙 첫 점 일치)")
        row = c.get(f"{_SB}/rest/v1/runs", headers=_ADM,
                    params={"select": "start_lat,start_lng",
                            "id": f"eq.{r_near_pub}"}).json()[0]
        exp_lat = round(near[0], 6)
        assert row["start_lat"] is not None and abs(row["start_lat"] - exp_lat) < 1e-4, \
            f"start_lat 자동 채움 실패: {row['start_lat']} vs {exp_lat}"
        # 트랙 없는 run은 null
        row9 = c.get(f"{_SB}/rest/v1/runs", headers=_ADM,
                     params={"select": "start_lat", "id": f"eq.{r_notrack}"}).json()[0]
        assert row9["start_lat"] is None, "트랙 없는 run은 start_lat null이어야"
        ok(f"트랙 run start_lat={row['start_lat']} (첫 점 일치) · 트랙없음 run=null")

        step("1~10 판정. V 관점 /feed/nearby (반경 10km)")
        resp = nearby(c, tk["v"])
        assert resp.status_code == 200, resp.text[:200]
        got = run_ids_in(resp)
        # 노출되어야: 근처공개(1)만
        assert r_near_pub in got, "1. 반경 내 public 노출 실패"
        ok("1. 반경 내 public run 노출")
        for label, rid in [("2. 반경 밖", r_far_pub), ("3. followers", r_near_fol_vis),
                           ("4. private", r_near_priv), ("5. 본인", r_self),
                           ("6. 팔로우 유저", r_followed), ("7. 차단", r_blocked),
                           ("8. 비공개 계정", r_privacct), ("9. 트랙없음", r_notrack),
                           ("10. 원 밖 모서리", r_corner)]:
            assert rid not in got, f"{label} run이 노출됨(제외 실패)"
            ok(f"{label} run 제외")

        step("8. 프라이버시 이중검증 — 비공개 계정 흔적 응답 전체에 부재")
        raw = resp.text
        assert SECRET8 not in raw, "비공개 계정 run 제목이 응답에 누출"
        assert f"NFpriv{TS}" not in raw, "비공개 계정 닉네임이 응답에 누출"
        ok("비공개 계정 run_id·제목·닉네임 모두 응답 전체에 부재")

        step("11. radius_km 상한 clamp — >20 요청도 20으로")
        # 30km run: clamp(20) 밖 → 제외돼야. 15km run(r_far): clamp(20) 안 → 노출.
        # radius=999가 그대로 먹혔다면 30km도 떴을 것 → clamp 증명.
        r_veryfar = save_run(c, tk["n"], *offset_coord(ORIGIN_LAT, ORIGIN_LNG, 30, 0),
                             "public", title="30km런")
        created.append(r_veryfar)
        resp_big = nearby(c, tk["v"], radius_km=999)
        assert resp_big.status_code == 200
        got_big = run_ids_in(resp_big)
        assert r_veryfar not in got_big, "30km run이 clamp(20) 밖이라 제외돼야(clamp 미작동)"
        assert r_far_pub in got_big, "15km run은 clamp(20) 안이라 노출돼야"
        assert r_near_pub in got_big, "근처 run 노출"
        ok("radius 999 → 20 clamp: 30km 제외 · 15km/근처 노출 (clamp 증명)")

        step("12. lat 누락 → 400")
        r400 = api(c, "GET", "/feed/nearby", tk["v"], params={"lng": ORIGIN_LNG})
        assert r400.status_code == 400, f"lat 누락 400 기대, got {r400.status_code}"
        r_oob = api(c, "GET", "/feed/nearby", tk["v"],
                    params={"lat": 10.0, "lng": ORIGIN_LNG})  # 한국 밖
        assert r_oob.status_code == 400, "한국 bbox 밖 400 기대"
        ok("lat 누락·한국 bbox 밖 둘 다 400")

        step("13. 페이지네이션 — 근처 public run 2건으로 limit=1 분할")
        r_near_pub2 = save_run(c, tk["n"], *offset_coord(ORIGIN_LAT, ORIGIN_LNG, 2, 0),
                               "public", title="근처공개2")
        created.append(r_near_pub2)
        p0 = run_ids_in(nearby(c, tk["v"], limit=1, offset=0))
        p1 = run_ids_in(nearby(c, tk["v"], limit=1, offset=1))
        assert len(p0) == 1 and len(p1) == 1, "각 페이지 1건"
        assert p0.isdisjoint(p1), "페이지 간 중복 없음"
        union = p0 | p1
        assert {r_near_pub, r_near_pub2} <= union, "두 근처 public run 모두 페이지에 등장"
        ok(f"limit=1 페이지네이션: 중복 없음, 두 run 모두 커버")

        print("\n" + "=" * 52 + "\n  ALL TESTS PASSED\n" + "=" * 52)
    finally:
        step("Cleanup")
        for uid in uids.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        print("  유저 삭제 (runs·follows·blocks·run_tracks cascade)")


if __name__ == "__main__":
    run_tests()
