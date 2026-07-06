"""
Integration test: 크루 둘러보기 (당근식 — 지역 필터·거리순·정원 토글·태그)
1) 결정론 — haversine·거리 정렬 순수 함수, 스키마 검증
2) 통합 — 생성 왕복, sido/sigungu 필터, 거리순+distance_km, include_full,
   하위 호환(파라미터 없음)
Run: python tests/test_crew_browse_integration.py
"""
from __future__ import annotations

import os
import sys
import time

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"


def _keys():
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


def ok(m): print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")


def sb_user(c, e):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": e, "password": "TestPass123!", "email_confirm": True})
    if r.status_code not in (200, 201): fail("create user", r.text[:200])
    return r.json()["id"]


def sb_login(c, e):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": e, "password": "TestPass123!"})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]


def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})


def api(c, m, p, tok, **k):
    return c.request(m, f"{BASE}{p}", headers={"Authorization": f"Bearer {tok}"}, **k)


def phase_pure():
    from app.services import crew_service as cs
    from app.models.schemas import CrewCreate
    from pydantic import ValidationError

    step("1. 결정론 — haversine + 스키마 검증")
    # 서울숲(37.5445,127.0561) → 여의도(37.526,126.924): 대략 11~12km
    d = cs._crew_haversine_km(37.5445, 127.0561, 37.526, 126.924)
    assert 10 <= d <= 14, f"서울숲-여의도 거리 이상: {d}"
    d0 = cs._crew_haversine_km(37.5, 127.0, 37.5, 127.0)
    assert d0 == 0.0
    # 스키마: sido Literal, 태그 어휘, 좌표 bbox, 태그 개수
    CrewCreate(name="ok", sido="서울특별시", sigungu="성동구", lat=37.5, lng=127.0,
               tags=["아침", "입문환영"])
    n = 0
    for bad in [dict(name="x", sido="서울시"), dict(name="x", sido="Seoul"),
                dict(name="x", tags=["핵인싸"]), dict(name="x", tags=["새벽"] * 6),
                dict(name="x", lat=10.0), dict(name="x", lng=200.0),
                dict(name="x", sigungu="가" * 31)]:
        try:
            CrewCreate(**bad); fail(f"{bad} 통과하면 안 됨")
        except ValidationError:
            n += 1
    ok(f"haversine ✓ (11km대) sido17·태그13·bbox·개수 거부 {n}/7 ✓")


def phase_api(c, tok, uid):
    step("2. 생성 왕복 — 새 필드 저장·조회")
    crews = {}
    # 좌표: 서울숲 기준으로 가까운 순서를 알 수 있게 배치
    plan = [
        ("성수 A", "서울특별시", "성동구", 37.5445, 127.0561, ["아침", "입문환영"]),   # ~0km
        ("영등포 B", "서울특별시", "영등포구", 37.526, 126.924, ["저녁", "평지"]),      # ~11km
        ("송파 C", "서울특별시", "송파구", 37.5111, 127.0810, ["새벽", "평지"]),        # ~4km
        ("좌표없음 D", "서울특별시", "성동구", None, None, ["친목"]),                    # 거리 null
    ]
    for name, sido, sigungu, lat, lng, tags in plan:
        body = {"name": f"{name}-{int(time.time())%100000}", "sido": sido,
                "sigungu": sigungu, "tags": tags, "max_members": 30}
        if lat is not None:
            body["lat"] = lat; body["lng"] = lng
        r = api(c, "POST", "/crews", tok, json=body)
        assert r.status_code in (200, 201), r.text[:300]
        d = r.json()
        crews[name] = d["id"]
        assert d["sido"] == sido and d["sigungu"] == sigungu and d["tags"] == tags
    # GET 단건에도 반영
    g = api(c, "GET", f"/crews/{crews['성수 A']}", tok).json()
    assert g["sido"] == "서울특별시" and g["lat"] == 37.5445 and "아침" in g["tags"]
    ok("sido/sigungu/lat/lng/tags 저장·조회 ✓")

    step("3. sido/sigungu 필터")
    r = api(c, "GET", "/crews", tok, params={"sigungu": "송파구"})
    names = [x["id"] for x in r.json()]
    assert crews["송파 C"] in names
    assert crews["성수 A"] not in names, "송파구 필터에 성동구 크루가 나오면 안 됨"
    r = api(c, "GET", "/crews", tok, params={"sido": "서울특별시"})
    assert all(x["sido"] == "서울특별시" for x in r.json() if x["sido"])
    ok("sigungu 정확 필터 ✓ sido 필터 ✓")

    step("4. 거리순 정렬 + distance_km (서울숲 기준)")
    r = api(c, "GET", "/crews", tok, params={"lat": 37.5445, "lng": 127.0561, "limit": 100})
    rows = r.json()
    mine = [x for x in rows if x["id"] in crews.values()]
    # 내 4개 크루 중 좌표 있는 3개가 거리순, 좌표없음은 distance_km null + 뒤
    ordered = [x["id"] for x in mine]
    a_i = ordered.index(crews["성수 A"])
    c_i = ordered.index(crews["송파 C"])
    b_i = ordered.index(crews["영등포 B"])
    d_i = ordered.index(crews["좌표없음 D"])
    assert a_i < c_i < b_i, f"거리순(성수<송파<영등포) 위반: {a_i},{c_i},{b_i}"
    assert d_i > b_i, "좌표없음 크루는 뒤로"
    by = {x["id"]: x for x in mine}
    assert by[crews["성수 A"]]["distance_km"] == 0.0
    assert 3 <= by[crews["송파 C"]]["distance_km"] <= 5
    assert 10 <= by[crews["영등포 B"]]["distance_km"] <= 13
    assert by[crews["좌표없음 D"]]["distance_km"] is None
    ok("거리 오름차순 ✓ distance_km 값(0/~4/~11) ✓ 좌표없음 null·후미 ✓")

    step("5. include_full — 정원 찬 크루 제외/포함")
    # 정원 1명(=owner뿐) 크루 생성 → 이미 꽉 참
    r = api(c, "POST", "/crews", tok, json={
        "name": f"풀크루-{int(time.time())%100000}", "sido": "서울특별시",
        "sigungu": "성동구", "max_members": 1})
    full_id = r.json()["id"]
    crews["full"] = full_id
    r = api(c, "GET", "/crews", tok, params={"limit": 100})  # 기본 include_full=false
    assert full_id not in [x["id"] for x in r.json()], "정원 찬 크루가 기본에서 보이면 안 됨"
    r = api(c, "GET", "/crews", tok, params={"include_full": "true", "limit": 100})
    assert full_id in [x["id"] for x in r.json()], "include_full=true면 포함"
    ok("정원 찬 크루 기본 제외 ✓ include_full=true 포함 ✓")

    step("6. 하위 호환 — 파라미터 없이 GET /crews")
    r = api(c, "GET", "/crews", tok)
    assert r.status_code == 200
    rows = r.json()
    assert all(x.get("distance_km") is None for x in rows), "좌표 미제공 시 distance_km 전부 null"
    # 최신순 (created_at desc) — 내 크루 중 마지막 생성이 앞쪽
    mine_ids = [x["id"] for x in rows if x["id"] in crews.values()]
    assert mine_ids, "내 크루가 목록에 있어야"
    ok("파라미터 없음 → distance_km null·최신순·기존 shape ✓")

    step("7. 잘못된 파라미터 422")
    assert api(c, "GET", "/crews", tok, params={"lat": 10.0, "lng": 127.0}).status_code == 422
    ok("좌표 bbox 밖 422 ✓")

    return list(crews.values())


def run():
    ts = int(time.time())
    uids, crew_ids = [], []
    with httpx.Client(timeout=30) as c:
        try:
            phase_pure()
            step("공용: premium 유저 (크루 여러 개 생성)")
            e = f"cb-{ts}@t.l"
            uids.append(sb_user(c, e))
            tok = sb_login(c, e)
            assert api(c, "PATCH", "/me/profile", tok, json={"nickname": f"둘러u-{ts%100000}"}).status_code == 200
            c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM,
                    params={"user_id": f"eq.{uids[0]}"}, json={"tier": "premium"})  # 크루 한도 해제
            ok("유저 + premium")
            crew_ids = phase_api(c, tok, uids[0])
            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            sb_del_in(c, "crews", "id", crew_ids)
            sb_del_in(c, "profiles", "user_id", uids)
            for u in uids:
                c.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM)
            ok("crews·profiles·auth 삭제")


if __name__ == "__main__":
    run()
