"""
Integration test: 궤적 공개 조회 + 커서 페이지네이션 + 집계 정합
(docs/RUN_TRACK_AND_STATS_DESIGN.md)

1) GET /runs/{id}/track 가시성 매트릭스 — visibility 3종 × 관계 3종(본인/
   팔로워/무관계) 전수 + 404 케이스 좌표값 부재(이중검증) + 트랙 없는 run 404.
2) GET /runs ?before= 커서 — 페이지 이어붙여 중복·누락 0, naive datetime 422.
3) 집계 verified만 — best_pace가 unverified 오염에 면역 / unverified 새 run은
   new_records 빈 배열 / 개인 totals는 포함 유지 / 크루 랭킹·챌린지 verified 합만
   / verified 0개 유저 records null.

Run: python tests/test_run_track_and_stats_integration.py  (로컬 서버 필요)
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timedelta, timezone
import httpx

BASE = "http://localhost:8000/api"
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
START_LAT, START_LNG = 37.5445, 127.0374


def ok(m):        print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):      print(f"\n[{t}]")


def sb_create_user(c, email):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": "test1234", "email_confirm": True})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()["id"]


def sb_login(c, email):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": "test1234"})
    assert r.status_code == 200, r.text[:200]
    return r.json()["access_token"]


def api(c, method, path, token, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {token}"}, **kw)


def make_track(distance_km: float, pace_s_per_km: int = 360):
    """직선 궤적 — 22.24m/포인트, 지정 페이스. verified 판정용(정확 거리 신고)."""
    step_m = 22.24
    n = round(distance_km * 1000 / step_m) + 1
    dt_ms = round(step_m / 1000 * pace_s_per_km * 1000)  # 포인트 간 ms
    t0 = (TS - 7200) * 1000
    return [{"lat": START_LAT + i * 0.0002, "lng": START_LNG,
             "t": t0 + i * dt_ms, "acc": 5.0} for i in range(n)]


def post_run(c, token, distance_km, duration_sec, ran_at=None, visibility="public",
             with_track=True, pace_s_per_km=None):
    # ran_at는 서버가 now()로 강제(create_run) — 바디로 보내면 forbid 422. 파라미터는
    # 호출부 시그니처 보존용으로 남기되 body에 넣지 않는다(전송해도 무시되던 dead payload).
    body = {"distance_km": distance_km, "duration_sec": duration_sec,
            "visibility": visibility}
    if with_track:
        pace = pace_s_per_km or round(duration_sec / distance_km)
        body["gps_track"] = make_track(distance_km, pace)
    r = api(c, "POST", "/runs", token, json=body)
    assert r.status_code in (200, 201), f"run 저장 실패: {r.status_code} {r.text[:250]}"
    return r.json()


def iso_hours_ago(h: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def run_tests():
    c = httpx.Client(timeout=120)
    users = {}
    try:
        step("0. 유저 A(주인)·F(팔로워)·S(무관계) 준비")
        for k in ("a", "f", "s"):
            users[k] = sb_create_user(c, f"trackstat-{k}-{TS}@test.com")
        tok_a = sb_login(c, f"trackstat-a-{TS}@test.com")
        tok_f = sb_login(c, f"trackstat-f-{TS}@test.com")
        tok_s = sb_login(c, f"trackstat-s-{TS}@test.com")
        for k, tok in (("a", tok_a), ("f", tok_f), ("s", tok_s)):
            assert api(c, "PATCH", "/me/profile", tok,
                       json={"nickname": f"TS{k}{TS}"}).status_code == 200
        assert api(c, "POST", f"/users/{users['a']}/follow", tok_f).status_code == 204
        ok("유저 3명 + F→A 팔로우")

        step("1. A의 run 배치 — verified 3종(visibility별) + 트랙 없는 run")
        runs = {}
        for i, vis in enumerate(("public", "followers", "private")):
            d = post_run(c, tok_a, 2.0, 720, iso_hours_ago(5 - i), visibility=vis)
            assert d.get("verification") == "verified", \
                f"{vis} run이 verified가 아님: {d.get('verification')}"
            assert d.get("has_track") is True
            runs[vis] = d["id"]
        no_track = post_run(c, tok_a, 5.0, 1125, iso_hours_ago(1),
                            with_track=False)  # 3'45"/km — 오염 시나리오 (실사례)
        assert no_track.get("verification") == "unverified"
        assert no_track.get("new_records") == [], \
            f"unverified run이 PB 경신 후보가 됨: {no_track.get('new_records')}"
        runs["no_track"] = no_track["id"]
        ok("verified public/followers/private + unverified(빠른 페이스, 경신 모달 없음)")

        step("2. 궤적 가시성 매트릭스 (3 visibility × 본인/팔로워/무관계)")
        matrix = [  # (viewer_tok, run_key, 기대 코드)
            (tok_a, "public", 200), (tok_a, "followers", 200), (tok_a, "private", 200),
            (tok_f, "public", 200), (tok_f, "followers", 200), (tok_f, "private", 404),
            (tok_s, "public", 200), (tok_s, "followers", 404), (tok_s, "private", 404),
        ]
        names = {id(tok_a): "본인", id(tok_f): "팔로워", id(tok_s): "무관계"}
        for tok, key, want in matrix:
            r = api(c, "GET", f"/runs/{runs[key]}/track", tok)
            assert r.status_code == want, \
                f"{names[id(tok)]}×{key}: {want} 기대, got {r.status_code}"
            if want == 404:  # 이중검증: 좌표값이 응답 전체에 없어야 (위치정보 은닉)
                assert "37.5" not in r.text and "polyline" not in r.text, \
                    f"{names[id(tok)]}×{key}: 404인데 좌표 흔적 노출"
            else:
                poly = r.json()["polyline"]
                # 직선 궤적은 DP 간축이 시작·끝 2점으로 줄임 — 형식만 확인
                assert len(poly) >= 2 and "lat" in poly[0] and "lng" in poly[0], \
                    f"폴리라인 형식: {poly[:2]}"
        r = api(c, "GET", f"/runs/{runs['no_track']}/track", tok_a)
        assert r.status_code == 404, f"트랙 없는 run은 404, got {r.status_code}"
        ok("9칸 매트릭스 + 404 좌표 부재 + 트랙 없는 run 404")

        step("3. 커서 페이지네이션 — 중복·누락 0, naive 422")
        listed, before = [], None
        for _ in range(10):
            path = "/runs?limit=2" + (f"&before={before}" if before else "")
            page = api(c, "GET", path, tok_a).json()
            if not page:
                break
            listed.extend(r["id"] for r in page)
            before = page[-1]["ran_at"].replace("+00:00", "Z")
        assert len(listed) == 4 and len(set(listed)) == 4, \
            f"4건 기대(중복 없이), got {len(listed)} (uniq {len(set(listed))})"
        all_ids = {v for v in runs.values()}
        assert set(listed) == all_ids, "커서 순회가 전체와 불일치 (누락)"
        # polyline_thumb: 트랙 run은 Coordinate 배열(≤36pt), 무트랙 run은 null
        full = api(c, "GET", "/runs?limit=10", tok_a).json()
        by = {r["id"]: r for r in full}
        pt = by[runs["public"]]["polyline_thumb"]
        assert pt and 2 <= len(pt) <= 36 and "lat" in pt[0], f"트랙 run thumb: {pt and pt[:1]}"
        assert by[runs["no_track"]]["polyline_thumb"] is None, "무트랙 run은 null"
        prof = api(c, "GET", f"/users/{users['a']}/runs", tok_f).json()
        pub_card = next(x for x in prof if x["run_id"] == runs["public"])
        assert pub_card["polyline_thumb"], "공개 프로필 카드에도 thumb"
        r = api(c, "GET", "/runs?before=2026-07-08T10:00:00", tok_a)
        assert r.status_code == 422, f"naive before는 422, got {r.status_code}"
        assert "timezone" in r.text, "422에 timezone 안내 필요"
        # 감사 M-A: '+' 미인코딩(공백 도착) 관용 — tz 위치 공백을 '+'로 복원
        r = c.get(f"{BASE}/runs?limit=1&before=2026-07-10T10:00:00+00:00",
                  headers={"Authorization": f"Bearer {tok_a}"})
        assert r.status_code == 200, f"raw '+' 관용 처리: {r.status_code}"
        ok("2건씩 순회 = 전체 4건 일치 + naive 422(timezone 안내)")

        step("4. 개인 집계 — records는 verified만, totals는 전부")
        st = api(c, "GET", "/me/stats", tok_a).json()
        bp = st["records"]["best_pace"]
        assert bp is not None and abs(bp["value"] - 360) <= 5, \
            f"best_pace는 verified(6'00\")여야: {bp}"
        assert st["all_time"]["run_count"] == 4, \
            f"개인 totals는 unverified 포함(4건): {st['all_time']['run_count']}"
        assert abs(st["all_time"]["total_distance_km"] - 11.0) <= 0.3, \
            f"총거리 ~11km(2+2+2+5): {st['all_time']['total_distance_km']}"
        ok(f"best_pace={bp['value']}(오염 면역) · totals 4건/11km(포함 유지)")

        step("5. 크루 랭킹·챌린지 — verified 합만")
        r = api(c, "POST", "/crews", tok_a, json={"name": f"집계크루{TS}"})
        assert r.status_code in (200, 201), r.text[:200]
        crew = r.json()["id"]
        r = api(c, "POST", f"/crews/{crew}/challenges", tok_a, json={
            "title": "집계 챌린지", "goal_km": 100,  # 시안 상한(le=100); 랭킹 합만 검증이라 목표값 무관
            "starts_at": iso_hours_ago(24), "ends_at": iso_hours_ago(-24)})
        assert r.status_code in (200, 201), r.text[:250]
        rank = api(c, "GET", f"/crews/{crew}/ranking", tok_a).json()
        me = next((e for e in rank if e["user_id"] == users["a"]), None)
        assert me is not None, f"랭킹에 A 없음: {rank}"
        assert abs(me["distance_km"] - 6.0) <= 0.3, \
            f"랭킹 합은 verified 6km(11 아님): {me['distance_km']}"
        ch = api(c, "GET", f"/crews/{crew}/challenges/current", tok_a).json()
        assert ch and abs(ch["achieved_km"] - 6.0) <= 0.3, \
            f"챌린지 달성도 verified 6km: {ch and ch['achieved_km']}"
        ok(f"랭킹 {me['distance_km']}km · 챌린지 {ch['achieved_km']}km (unverified 5km 미포함)")

        step("6. verified 0개 유저 — records null")
        post_run(c, tok_s, 3.0, 900, iso_hours_ago(2), with_track=False)
        st = api(c, "GET", "/me/stats", tok_s).json()
        assert st["records"]["best_pace"] is None, \
            f"verified 없으면 best_pace null: {st['records']['best_pace']}"
        assert st["all_time"]["run_count"] == 1, "히스토리는 남아야"
        ok("records null + 히스토리 1건 유지")

        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        step("Cleanup: 테스트 데이터 삭제")
        # 계정 삭제 cascade가 전부 정리 (탈퇴 기능의 산물) — 크루는 A 단독 소유라 함께 삭제
        for uid in users.values():
            c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        left = 0
        for t in ("runs", "routes", "crews"):
            col = "owner_id" if t == "crews" else "user_id"
            for uid in users.values():
                r = c.get(f"{_SB}/rest/v1/{t}", headers={**_ADM, "Prefer": "count=exact"},
                          params={col: f"eq.{uid}", "select": "*", "limit": 1})
                cr = r.headers.get("content-range", "?/0").split("/")[-1]
                left += int(cr) if cr.isdigit() else 0
        print(f"  잔존 확인: {left}건" + (" ✓" if left == 0 else " ⚠️"))


if __name__ == "__main__":
    run_tests()
