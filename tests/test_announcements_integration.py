"""
Integration test: crew announcements + RSVP
(POST/GET/PATCH/DELETE /crews/{id}/announcements, PUT .../rsvp)
Run: python tests/test_announcements_integration.py
"""
from __future__ import annotations

import os, sys, time
from datetime import datetime, timedelta, timezone
import httpx

BASE = "http://localhost:8000/api"
_SB  = "https://jlmmqnpddkokyintlawd.supabase.co"
_NOBODY = "00000000-0000-4000-8000-000000000000"

def _keys() -> tuple[str, str]:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    anon = svc = ""
    with open(env) as f:
        for line in f:
            line = line.strip()
            if   line.startswith("SUPABASE_KEY="):             anon = line.split("=",1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="): svc  = line.split("=",1)[1]
    return anon, svc

_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}

def ok(m):   print(f"  ✓ {m}")
def fail(m, d=""): print(f"  ✗ {m}" + (f": {d}" if d else "")); sys.exit(1)
def step(t): print(f"\n[{t}]")

def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200,201): fail("create user", r.text[:200])
    return r.json()["id"]

def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type":"application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200: fail("login", r.text[:200])
    return r.json()["access_token"]

def sb_del_user(c, uid): c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)

def sb_del_in(c, table, col, vals):
    if not vals: return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer":"return=minimal"},
             params={col: f"in.({',' .join(vals)})"})

def sb_get(c, table, **params):
    r = c.get(f"{_SB}/rest/v1/{table}", headers=_ADM, params=params)
    return r.json() if r.status_code == 200 else []

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def iso(dt): return dt.isoformat()


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"an-u{i}-{ts}@t.l" for i in range(1,5)]
    uids: list[str] = []
    toks: list[str] = []
    crew_id = None
    now = datetime.now(timezone.utc)

    with httpx.Client(timeout=20) as c:
        try:
            # ── 1. 유저 4명 (u1=크루장, u2·u3=크루원, u4=비멤버) + 크루 ──
            step("1. 유저 4명 + 프로필 + 크루 생성/가입")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2, uid3, uid4 = uids; tok1, tok2, tok3, tok4 = toks
            for i, tok in enumerate(toks, start=1):
                r = api(c, "PATCH", "/me/profile", tok,
                        json={"nickname": f"공지u{i}-{ts%100000}"})
                assert r.status_code == 200
            r = api(c, "POST", "/crews", tok1, json={"name": f"공지테스트크루-{ts}"})
            assert r.status_code in (200, 201), r.text[:200]
            crew_id = r.json()["id"]
            for tok in (tok2, tok3):
                assert api(c, "POST", f"/crews/{crew_id}/join", tok).status_code in (200, 201)
            ok(f"crew={crew_id[:8]}… (u1 owner, u2·u3 member, u4 비멤버)")

            # ── 2. 권한 매트릭스: 작성 ────────────────────────────────────
            step("2. 작성 권한: 크루장만")
            body_a = {"title": "토요 정기런", "body": "한강공원 8시!",
                      "run_at": iso(now + timedelta(days=2)),
                      "place_name": "뚝섬한강공원", "place_lat": 37.5299, "place_lng": 127.0703,
                      "rsvp_closes_at": iso(now + timedelta(days=1))}
            r = api(c, "POST", f"/crews/{crew_id}/announcements", tok2, json=body_a)
            assert r.status_code == 403, f"크루원 작성 → 403, got {r.status_code}"
            r = api(c, "POST", f"/crews/{_NOBODY}/announcements", tok1, json=body_a)
            assert r.status_code == 404, f"없는 크루 → 404, got {r.status_code}"
            r = api(c, "POST", f"/crews/{crew_id}/announcements", tok1, json=body_a)
            assert r.status_code == 201, r.text[:300]
            ann_a = r.json()
            assert ann_a["title"] == "토요 정기런" and ann_a["place_name"] == "뚝섬한강공원"
            assert ann_a["rsvp_open"] is True and ann_a["my_rsvp"] is None
            assert ann_a["rsvp"] == {"going": 0, "not_going": 0, "maybe": 0}
            assert ann_a["author_nickname"] == f"공지u1-{ts%100000}"
            ok("u2 403 ✓ 없는 크루 404 ✓ 크루장 201 + 필드 ✓")

            # ── 3. 알림: 크루원 전체 (작성자 제외) ────────────────────────
            step("3. 알림: u2·u3 도착, u1(작성자) 제외")
            def ann_notis(tok):
                r = api(c, "GET", "/notifications", tok)
                return [n for n in r.json() if n["type"] == "crew_announcement"]
            for tok, name in [(tok2, "u2"), (tok3, "u3")]:
                ns = ann_notis(tok)
                assert len(ns) == 1, f"{name} 알림 1건이어야 함, got {len(ns)}"
                assert ns[0]["actor_id"] == uid1
                assert ns[0]["target_id"] == ann_a["id"]
                assert ns[0]["target_type"] == "announcement"
            assert ann_notis(tok1) == [], "작성자 본인은 알림 제외"
            ok("u2·u3 각 1건 (target=공지 id) ✓ u1 0건 ✓")

            # ── 4. 조회 권한 + CHECK 제약 ─────────────────────────────────
            step("4. 조회 권한(비멤버 403) + CHECK 제약 400")
            assert api(c, "GET", f"/crews/{crew_id}/announcements", tok4).status_code == 403
            assert api(c, "GET", f"/crews/{crew_id}/announcements/{ann_a['id']}", tok4).status_code == 403
            assert api(c, "GET", f"/crews/{crew_id}/announcements/{_NOBODY}", tok2).status_code == 404
            bad = [
                {"title": "반쪽좌표", "body": "x", "place_lat": 37.5},                      # 쌍 위반
                {"title": "런없이마감", "body": "x", "rsvp_closes_at": iso(now + timedelta(days=1))},  # run_at 없이 마감
                {"title": "마감이후", "body": "x", "run_at": iso(now + timedelta(days=1)),
                 "rsvp_closes_at": iso(now + timedelta(days=2))},                           # 마감 > run_at
            ]
            for b in bad:
                r = api(c, "POST", f"/crews/{crew_id}/announcements", tok1, json=b)
                assert r.status_code == 400, f"CHECK 위반({b['title']}) → 400, got {r.status_code}"
                assert r.json()["detail"]["error"] == "invalid_announcement"
            ok("비멤버 403 ✓ 없는 공지 404 ✓ CHECK 3종 전부 400 ✓")

            # ── 5. RSVP: 투표·재투표 덮어쓰기·집계·명단 ───────────────────
            step("5. RSVP: 한 명당 한 표 + 집계 + 명단 + my_rsvp")
            A = ann_a["id"]
            def put_rsvp(tok, status_, ann=A):
                return api(c, "PUT", f"/crews/{crew_id}/announcements/{ann}/rsvp",
                           tok, json={"status": status_})
            def detail(tok, ann=A):
                r = api(c, "GET", f"/crews/{crew_id}/announcements/{ann}", tok)
                assert r.status_code == 200, r.text[:200]
                return r.json()
            assert put_rsvp(tok3, "going").status_code == 204     # u3 참석 (먼저)
            assert put_rsvp(tok2, "going").status_code == 204     # u2 참석
            assert put_rsvp(tok2, "maybe").status_code == 204     # u2 재투표 → 미정 (덮어쓰기)
            assert put_rsvp(tok1, "going").status_code == 204     # u1(크루장도 멤버) 참석
            assert put_rsvp(tok4, "going").status_code == 403     # 비멤버
            d = detail(tok2)
            assert d["rsvp"] == {"going": 2, "not_going": 0, "maybe": 1}, d["rsvp"]
            assert d["my_rsvp"] == "maybe"
            assert detail(tok3)["my_rsvp"] == "going"
            names = [m["nickname"] for m in d["going_members"]]
            assert names == [f"공지u3-{ts%100000}", f"공지u1-{ts%100000}"], \
                f"참석자 명단(투표순) 불일치: {names}"
            ok("재투표 덮어쓰기 ✓ 집계 2/0/1 ✓ my_rsvp ✓ 명단(u3,u1) ✓ 비멤버 403 ✓")

            # ── 6. 마감·불가 케이스 ───────────────────────────────────────
            step("6. 마감(409) + run_at 없음(400)")
            r = api(c, "POST", f"/crews/{crew_id}/announcements", tok1, json={
                "title": "이미 마감된 런", "body": "마감 테스트",
                "run_at": iso(now + timedelta(days=2)),
                "rsvp_closes_at": iso(now - timedelta(hours=1))})
            assert r.status_code == 201, r.text[:200]
            ann_b = r.json()
            assert ann_b["rsvp_open"] is False
            r = put_rsvp(tok2, "going", ann_b["id"])
            assert r.status_code == 409 and r.json()["detail"]["error"] == "rsvp_closed"
            r = api(c, "POST", f"/crews/{crew_id}/announcements", tok1,
                    json={"title": "일반 공지", "body": "러닝 일시 없음"})
            assert r.status_code == 201
            ann_c = r.json()
            assert ann_c["rsvp_open"] is False
            r = put_rsvp(tok2, "going", ann_c["id"])
            assert r.status_code == 400 and r.json()["detail"]["error"] == "rsvp_not_available"
            ok("마감 공지 409 ✓ run_at 없는 공지 400 ✓")

            # ── 7. 수정: 크루장만 + 알림 미발송 ───────────────────────────
            step("7. 수정 권한 + 알림 폭탄 방지")
            before = len(ann_notis(tok2))
            r = api(c, "PATCH", f"/crews/{crew_id}/announcements/{A}", tok2,
                    json={"title": "해킹"})
            assert r.status_code == 403
            r = api(c, "PATCH", f"/crews/{crew_id}/announcements/{A}", tok1,
                    json={"title": "토요 정기런 (장소 변경)"})
            assert r.status_code == 200 and r.json()["title"] == "토요 정기런 (장소 변경)"
            assert r.json()["rsvp"]["going"] == 2, "수정해도 투표 유지"
            assert len(ann_notis(tok2)) == before, "수정 시 알림이 늘면 안 됨"
            ok("u2 수정 403 ✓ 수정 반영+투표 유지 ✓ 알림 미발송 ✓")

            # ── 8. 목록 + 페이지네이션 ────────────────────────────────────
            step("8. 목록 최신순 + limit/offset")
            r = api(c, "GET", f"/crews/{crew_id}/announcements", tok2)
            items = r.json()
            assert [a["id"] for a in items] == [ann_c["id"], ann_b["id"], A], "최신순"
            assert items[2]["rsvp"]["going"] == 2 and items[2]["my_rsvp"] == "maybe", \
                "목록에도 집계·my_rsvp 포함"
            p1 = api(c, "GET", f"/crews/{crew_id}/announcements", tok2,
                     params={"limit": 2, "offset": 0}).json()
            p2 = api(c, "GET", f"/crews/{crew_id}/announcements", tok2,
                     params={"limit": 2, "offset": 2}).json()
            assert [a["id"] for a in p1] == [ann_c["id"], ann_b["id"]]
            assert [a["id"] for a in p2] == [A]
            ok("최신순 [C,B,A] ✓ 목록 집계 포함 ✓ limit=2 분할 ✓")

            # ── 9. 탈퇴/강퇴 시 투표 정리 ─────────────────────────────────
            step("9. u3 탈퇴 + u2 강퇴 → 집계·명단에서 제거")
            assert api(c, "DELETE", f"/crews/{crew_id}/leave", tok3).status_code in (200, 204)
            d = detail(tok1)
            assert d["rsvp"] == {"going": 1, "not_going": 0, "maybe": 1}, d["rsvp"]
            assert all(m["user_id"] != uid3 for m in d["going_members"]), "탈퇴자 명단 제거"
            r = api(c, "DELETE", f"/crews/{crew_id}/members/{uid2}", tok1)
            assert r.status_code in (200, 204), r.text[:200]
            d = detail(tok1)
            assert d["rsvp"] == {"going": 1, "not_going": 0, "maybe": 0}, d["rsvp"]
            ok("탈퇴 → going 2→1 ✓ 강퇴 → maybe 1→0 ✓ 명단 정확 ✓")

            # ── 10. 삭제: 크루장만 + 투표 CASCADE ─────────────────────────
            step("10. 삭제 권한 + RSVP CASCADE")
            r = api(c, "DELETE", f"/crews/{crew_id}/announcements/{A}", tok4)
            assert r.status_code in (403, 404), "비멤버 삭제 불가"
            r = api(c, "DELETE", f"/crews/{crew_id}/announcements/{A}", tok1)
            assert r.status_code == 204
            assert api(c, "GET", f"/crews/{crew_id}/announcements/{A}", tok1).status_code == 404
            leftover = sb_get(c, "crew_announcement_rsvps",
                              announcement_id=f"eq.{A}", select="user_id")
            assert leftover == [], f"CASCADE 후 투표 0건이어야 함, got {len(leftover)}"
            ok("삭제 204 ✓ 재조회 404 ✓ 투표 CASCADE 0건 ✓")

            print("\n" + "="*50)
            print("  ALL TESTS PASSED")
            print("="*50)

        finally:
            step("Cleanup")
            if crew_id:
                sb_del_in(c, "crews", "id", [crew_id])   # members/announcements/rsvps CASCADE
                ok("crew 삭제 (CASCADE)")
            sb_del_in(c, "notifications", "user_id", [u for u in uids if u])
            sb_del_in(c, "notifications", "actor_id", [u for u in uids if u])
            ok("notifications 삭제")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")

if __name__ == "__main__":
    run()
