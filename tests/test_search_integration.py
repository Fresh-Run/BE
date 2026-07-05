"""
Integration test: GET /api/crews/search, GET /api/routes/search
Run: python tests/test_search_integration.py
"""
from __future__ import annotations

import os, sys, time
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"


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


def ok(m):        print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t):      print(f"\n[{t}]")

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

def sb_del_user(c, uid): c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)

def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})

def sb_insert_route(c, uid, summary, is_public):
    r = c.post(f"{_SB}/rest/v1/routes",
               headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": uid, "summary": summary,
                     "total_distance_km": 5.0, "is_public": is_public, "waypoints": []})
    if r.status_code not in (200, 201): fail("insert route", r.text[:200])
    return r.json()[0]["id"]

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def search_crews(c, tok, q, limit=20):
    r = api(c, "GET", "/crews/search", tok, params={"q": q, "limit": limit})
    assert r.status_code == 200, f"GET /crews/search → 200 이어야 함, got {r.status_code}: {r.text[:200]}"
    return r.json()

def search_routes(c, tok, q, limit=20):
    r = api(c, "GET", "/routes/search", tok, params={"q": q, "limit": limit})
    assert r.status_code == 200, f"GET /routes/search → 200 이어야 함, got {r.status_code}: {r.text[:200]}"
    return r.json()


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"sr-u{i}-{ts}@t.s" for i in range(1, 3)]
    uids: list[str] = []; toks: list[str] = []
    crew_ids: list[str] = []; all_routes: list[str] = []

    # 유일한 접미사 — 모든 이름·지역·소개에 포함시켜 타 데이터와 충돌 방지
    sfx = str(ts)[-6:]

    # 크루 이름/지역/소개 (search 쿼리는 반드시 이 값의 부분 문자열이어야 함)
    name_seoul  = f"서울런닝크루{sfx}"       # → 검색: f"런닝크루{sfx}"  (부분 일치)
    name_busan  = f"부산바다런{sfx}"
    name_other  = f"제주올레크루{sfx}"
    name_priv   = f"비공개크루{sfx}"

    area_busan  = f"해운대해수욕장{sfx}"     # → 검색: f"해운대해수욕장{sfx}"
    desc_seoul  = f"한강야경러닝코스{sfx}"   # → 검색: f"한강야경러닝코스{sfx}"

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 2명 ───────────────────────────────────────────────
            step("1. 유저 2명 생성 + 로그인")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2 = uids; tok1, tok2 = toks
            # u1이 크루 4개 생성 — 무료 1개 한도 게이트를 넘기 위해 프로필 생성 후 premium 승격
            api(c, "PATCH", "/me/profile", tok1, json={"nickname": f"검색u1-{sfx}"})
            c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM,
                    params={"user_id": f"eq.{uid1}"}, json={"tier": "premium"})
            ok(f"u1={uid1[:8]}  u2={uid2[:8]}")

            # ── 2. 크루 4개 생성 (공개3 + 비공개1) ────────────────────────
            step("2. 크루 생성 (공개3 + 비공개1)")
            def make_crew(tok, name, area, desc, is_public):
                r = api(c, "POST", "/crews", tok,
                        json={"name": name, "area": area, "description": desc,
                              "is_public": is_public})
                assert r.status_code == 200, f"crew create → 200 이어야 함, got {r.status_code}"
                return r.json()["id"]

            crew_seoul = make_crew(tok1, name_seoul, f"서울강남{sfx}", desc_seoul, True)
            crew_busan = make_crew(tok1, name_busan, area_busan, f"바다옆코스{sfx}", True)
            crew_other = make_crew(tok1, name_other, f"제주시{sfx}", f"둘레길코스{sfx}", True)
            crew_priv  = make_crew(tok1, name_priv,  f"서울{sfx}", f"숨겨진크루{sfx}", False)
            crew_ids += [crew_seoul, crew_busan, crew_other, crew_priv]

            # u2 가입 (member_count=2 확인용)
            api(c, "POST", f"/crews/{crew_seoul}/join", tok2)
            ok("공개3 + 비공개1 생성 완료")

            # ── 3. 이름으로 검색 — 부분 일치 ─────────────────────────────
            step("3. 이름 부분 일치: 검색어가 name의 부분 문자열")
            # "런닝크루{sfx}" ⊂ "서울런닝크루{sfx}" ✓
            results = search_crews(c, tok1, f"런닝크루{sfx}")
            ids = [r["id"] for r in results]
            assert crew_seoul in ids, f"서울 크루가 이름 부분 검색에 없음 (검색어=런닝크루{sfx})"
            assert crew_busan not in ids, "부산 크루가 서울 이름 검색에 나오면 안 됨"
            assert crew_other not in ids, "기타 크루가 서울 이름 검색에 나오면 안 됨"
            assert crew_priv not in ids, "비공개 크루가 검색 결과에 있으면 안 됨"
            ok(f"이름 부분 일치 ✓  비공개 제외 ✓  ({len(ids)}개 반환)")

            # ── 4. 지역(area)으로 검색 ────────────────────────────────────
            step("4. area 검색: 해운대해수욕장{sfx}")
            results = search_crews(c, tok1, f"해운대해수욕장{sfx}")
            ids = [r["id"] for r in results]
            assert crew_busan in ids, "부산 크루(area 일치)가 검색 결과에 없음"
            assert crew_seoul not in ids, "서울 크루가 해운대 검색에 나오면 안 됨"
            ok("area 부분 일치 ✓")

            # ── 5. 소개(description)으로 검색 ────────────────────────────
            step("5. description 검색: 한강야경러닝코스{sfx}")
            results = search_crews(c, tok1, f"한강야경러닝코스{sfx}")
            ids = [r["id"] for r in results]
            assert crew_seoul in ids, "서울 크루(description 일치)가 검색 결과에 없음"
            assert crew_busan not in ids, "부산 크루가 한강야경 검색에 나오면 안 됨"
            ok("description 부분 일치 ✓")

            # ── 6. 대소문자 무시 (영문 포함 크루로 확인) ─────────────────
            step("6. 대소문자 무시 — 대문자 검색 = 소문자 검색")
            # sfx 자체는 숫자라 대소문자 없음 → name에 영문 크루 하나 더 추가
            crew_eng = make_crew(tok1, f"HanRiver{sfx}", f"Seoul{sfx}", f"nightrun{sfx}", True)
            crew_ids.append(crew_eng)

            res_upper = search_crews(c, tok1, f"HANRIVER{sfx}")
            res_lower = search_crews(c, tok1, f"hanriver{sfx}")
            ids_upper = [r["id"] for r in res_upper]
            ids_lower = [r["id"] for r in res_lower]
            assert crew_eng in ids_upper, "대문자 검색에서 영문 크루가 안 나옴"
            assert crew_eng in ids_lower, "소문자 검색에서 영문 크루가 안 나옴"
            assert set(ids_upper) == set(ids_lower), "대소문자 검색 결과가 달라야 안 됨"
            ok("대소문자 무시 ✓")

            # ── 7. 빈 검색어 → [] ─────────────────────────────────────────
            step("7. 빈 검색어 → []")
            assert search_crews(c, tok1, "") == [], "빈 검색어 → [] 이어야 함"
            assert search_crews(c, tok1, "   ") == [], "공백만 → [] 이어야 함"
            ok("빈 검색어 → [] ✓")

            # ── 8. 특수문자(%, 쉼표)도 500 없이 처리 ─────────────────────
            step("8. 특수문자 검색 → 500 없이 응답")
            r1 = api(c, "GET", "/crews/search", tok1, params={"q": f"%런닝{sfx}%"})
            r2 = api(c, "GET", "/crews/search", tok1, params={"q": f"런닝{sfx},부산"})
            assert r1.status_code == 200, f"% 포함 검색 → 200 이어야 함, got {r1.status_code}"
            assert r2.status_code == 200, f"쉼표 포함 검색 → 200 이어야 함, got {r2.status_code}"
            ok("특수문자 검색 → 200 (안 깨짐) ✓")

            # ── 9. 검색 결과 메타 필드 확인 ──────────────────────────────
            step("9. 검색 결과에 member_count·owner_nickname 포함")
            results = search_crews(c, tok1, f"런닝크루{sfx}")
            for crew in results:
                assert "member_count" in crew, "member_count 없음"
                assert "owner_nickname" in crew, "owner_nickname 없음"
            seoul_r = next((r for r in results if r["id"] == crew_seoul), None)
            assert seoul_r is not None
            assert seoul_r["member_count"] == 2, \
                f"서울 크루 member_count 2여야 함, got {seoul_r['member_count']}"
            ok("member_count·owner_nickname 포함 ✓  member_count=2 ✓")

            # ── 10. 공개 코스 summary 검색 ───────────────────────────────
            step("10. 공개 코스 summary 검색")
            summary_a = f"한강야간달리기코스{sfx}"
            summary_b = f"북한산트레일{sfx}"
            route_a = sb_insert_route(c, uid1, summary_a, True)
            route_b = sb_insert_route(c, uid1, summary_b, True)
            route_hidden = sb_insert_route(c, uid1, f"한강숨겨진{sfx}", False)
            all_routes += [route_a, route_b, route_hidden]

            # "야간달리기코스{sfx}" ⊂ summary_a ✓
            results = search_routes(c, tok1, f"야간달리기코스{sfx}")
            ids = [r["id"] for r in results]
            assert route_a in ids, "한강 코스가 검색 결과에 없음"
            assert route_b not in ids, "북한산 코스가 한강 검색에 나오면 안 됨"
            assert route_hidden not in ids, "비공개 코스가 검색 결과에 있으면 안 됨"
            ok(f"공개 코스 summary 검색 ✓  비공개 제외 ✓  ({len(ids)}개)")

            # ── 11. 코스 검색 결과 메타 필드 확인 ────────────────────────
            step("11. 코스 결과에 like_count·copy_count·comment_count·is_mine 포함")
            for route in results:
                for field in ("like_count", "copy_count", "comment_count", "is_liked", "is_mine"):
                    assert field in route, f"코스 검색 결과에 {field} 없음"
            r_a = next((r for r in results if r["id"] == route_a), None)
            assert r_a is not None
            assert r_a["is_mine"] is True, "본인 코스 is_mine=True 이어야 함"
            ok("like_count·copy_count·comment_count·is_mine 포함 ✓")

            # ── 12. 코스 빈 검색어 → [] ───────────────────────────────────
            step("12. 코스 빈 검색어 → []")
            assert search_routes(c, tok1, "") == [], "코스 빈 검색어 → [] 이어야 함"
            ok("코스 빈 검색어 → [] ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)

        finally:
            step("Cleanup")
            sb_del_in(c, "routes", "id", all_routes)
            ok("routes 삭제")
            for cid in crew_ids:
                try: api(c, "DELETE", f"/crews/{cid}", tok1)
                except Exception: pass
            ok("crews 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")


if __name__ == "__main__":
    run()
