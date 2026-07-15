"""
Integration test: 감사 배치 3 (M4 route 학습 소유권, L1 kudos 가시성 게이트,
M10 삭제 시 알림 정리, L2 iap 알림 크기 상한, L3 502 detail 고정)
Run: python tests/test_audit_batch3_integration.py
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

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


def _route_row(c, user_id, summary, is_public):
    r = c.post(f"{_SB}/rest/v1/routes", headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": user_id, "summary": summary, "target_distance_km": 5.0,
                     "total_distance_km": 5.0, "is_public": is_public,
                     "start_lat": 37.5445, "start_lng": 127.0374})
    assert r.status_code in (200, 201), r.text[:200]
    return r.json()[0]["id"]


def run():
    ts = int(time.time())
    emails = [f"ab3-u{i}-{ts}@t.l" for i in range(1, 4)]  # A, B(팔로워/크루원), C(무관)
    uids, crew_ids, route_ids, run_ids = [], [], [], []

    with httpx.Client(timeout=40) as c:
        try:
            step("공용: 유저 3명 (A 소유자, B 팔로워, C 무관)")
            toks = []
            for i, e in enumerate(emails, start=1):
                uids.append(sb_user(c, e))
                toks.append(sb_login(c, e))
                assert api(c, "PATCH", "/me/profile", toks[-1],
                           json={"nickname": f"소품u{i}-{ts%100000}"}).status_code == 200
            uid_a, uid_b, uid_c = uids
            tok_a, tok_b, tok_c = toks
            # B가 A를 팔로우 (활동 피드 가시성)
            assert api(c, "POST", f"/users/{uid_a}/follow", tok_b).status_code in (200, 204)
            ok("유저 3명 + B→A 팔로우")

            step("1. M4 — avoid_from_route_id 남의 비공개 route 학습 차단")
            # A의 비공개 route (C가 이 id로 학습 시도)
            priv = _route_row(c, uid_a, "A 비공개 코스", is_public=False)
            route_ids.append(priv)
            # 남의 route로 생성 요청 → 차단(학습 무시)돼도 생성 자체는 성공(200)해야 함
            r = api(c, "POST", "/routes/generate", tok_c, json={
                "start": {"lat": 37.5445, "lng": 127.0374},
                "target_distance_km": 3, "avoid_from_route_id": priv})
            assert r.status_code == 200, r.text[:300]
            route_ids.append(r.json().get("id")) if r.json().get("id") else None
            # 검증: collect_route_avoidance_hints가 소유자 필터로 []를 반환하는지 순수 확인
            import asyncio
            from app.services import feedback_service as fs
            hints_other = asyncio.run(fs.collect_route_avoidance_hints(priv, owner_id=uid_c))
            hints_owner = asyncio.run(fs.collect_route_avoidance_hints(priv, owner_id=uid_a))
            assert hints_other == [], "남의 route 학습은 [] 여야 함"
            assert isinstance(hints_owner, list), "본인 route는 정상 조회"
            ok("남의 route 학습 차단 ✓ (owner 불일치 → []) 생성은 200 ✓")

            step("2. L1 — kudos 가시성 게이트 (팔로우/크루 O, 무관 X)")
            # A가 run 생성 — visibility="followers" 명시 (2026-07-15 갱신: 이 테스트는
            # visibility v1(07-07) 전날 작성돼 "미지정=소유자만" 시절 기대였음. v1부터
            # 미지정 기본이 public이라 "무관 C는 404" 감사 의도를 보존하려면 followers 명시)
            r = api(c, "POST", "/runs", tok_a,
                    json={"distance_km": 5.0, "duration_sec": 1650, "visibility": "followers"})
            run_a = r.json()["id"]; run_ids.append(run_a)
            # B(팔로워)는 kudos 가능 + 목록 조회 가능
            assert api(c, "POST", f"/runs/{run_a}/kudos", tok_b).status_code == 204
            r = api(c, "GET", f"/runs/{run_a}/kudos", tok_b)
            assert r.status_code == 200 and any(x["user_id"] == uid_b for x in r.json())
            # C(무관: 팔로우X 크루X)는 kudos·목록 둘 다 404 (존재 은닉)
            assert api(c, "POST", f"/runs/{run_a}/kudos", tok_c).status_code == 404
            assert api(c, "GET", f"/runs/{run_a}/kudos", tok_c).status_code == 404
            # 소유자 본인은 목록 조회 가능
            assert api(c, "GET", f"/runs/{run_a}/kudos", tok_a).status_code == 200
            ok("팔로워 kudos·목록 200 ✓ 무관 유저 404 ✓ 소유자 200 ✓")

            step("3. M10 — 공지 삭제 후 알림 정리 + unread_count 정확")
            r = api(c, "POST", "/crews", tok_a, json={"name": f"소품크루-{ts}"})
            crew_id = r.json()["id"]; crew_ids.append(crew_id)
            assert api(c, "POST", f"/crews/{crew_id}/join", tok_b).status_code == 200
            before = api(c, "GET", "/notifications/unread-count", tok_b).json()
            before_n = before if isinstance(before, int) else before.get("count", before.get("unread_count"))
            now = datetime.now(timezone.utc)
            r = api(c, "POST", f"/crews/{crew_id}/announcements", tok_a, json={
                "title": "정리 테스트", "body": "본문",
                "run_at": (now + timedelta(days=2)).isoformat(),
                "rsvp_closes_at": (now + timedelta(days=1)).isoformat()})
            ann_id = r.json()["id"]
            # B에게 공지 알림 발송됨 → unread 증가
            mid = api(c, "GET", "/notifications/unread-count", tok_b).json()
            mid_n = mid if isinstance(mid, int) else mid.get("count", mid.get("unread_count"))
            assert mid_n == before_n + 1, f"공지 알림으로 unread +1 기대: {before_n}→{mid_n}"
            # 공지 삭제 → 그 알림 정리 → unread 원복
            assert api(c, "DELETE", f"/crews/{crew_id}/announcements/{ann_id}", tok_a).status_code in (200, 204)
            after = api(c, "GET", "/notifications/unread-count", tok_b).json()
            after_n = after if isinstance(after, int) else after.get("count", after.get("unread_count"))
            assert after_n == before_n, f"삭제 후 unread 원복 기대: {mid_n}→{after_n} (유령 알림 없음)"
            # DB에도 해당 알림 부재
            rows = c.get(f"{_SB}/rest/v1/notifications", headers=_ADM,
                         params={"target_id": f"eq.{ann_id}", "select": "id"}).json()
            assert rows == [], f"삭제된 공지 알림이 DB에 남음: {rows}"
            ok("공지 알림 발송(+1)→삭제 정리(원복) ✓ DB 유령 알림 없음 ✓")

            step("4. L2 — iap/notifications 거대 페이로드 413")
            # 무인증 엔드포인트 (Apple용) — 큰 Content-Length는 413
            big = "h." + ("x" * (60 * 1024)) + ".sig"
            r = c.post(f"{BASE}/iap/notifications", json={"signedPayload": big})
            assert r.status_code == 413, f"거대 페이로드 → 413, got {r.status_code}"
            # 정상 크기는 200 + 저장
            small = f"h.{ts}payload.sig"
            r = c.post(f"{BASE}/iap/notifications", json={"signedPayload": small})
            assert r.status_code == 200 and r.json() == {"status": "ok"}
            ok("거대 페이로드 413 ✓ 정상 200 ✓")

            step("5. L3 — 502 detail에 DB 제약 상세 부재 (고정 문자열)")
            # 잘못된 UUID로 조회 유발 → postgrest 에러 → 502지만 detail은 고정
            r = api(c, "GET", "/runs/not-a-valid-uuid/track", tok_a)
            # 404(소유 아님) 또는 502(파싱 에러) — 어느 쪽이든 detail에 postgrest 원문 없어야
            if r.status_code == 502:
                d = str(r.json().get("detail", ""))
                assert "일시적인 서버 오류" in d, f"고정 메시지 기대: {d}"
                assert "column" not in d.lower() and "uuid" not in d.lower() and "22P02" not in d, \
                    f"DB 제약 상세가 노출됨: {d}"
                ok("502 detail 고정 문자열 ✓ (DB 원문 부재)")
            else:
                # 404로 처리된 경우도 원문 노출 없음 — 통과
                assert "column" not in r.text.lower()
                ok(f"{r.status_code} 처리 — DB 원문 노출 없음 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            sb_del_in(c, "runs", "user_id", uids)
            sb_del_in(c, "routes", "user_id", uids)
            sb_del_in(c, "crews", "id", crew_ids)
            sb_del_in(c, "follows", "follower_id", uids)
            sb_del_in(c, "notifications", "user_id", uids)
            sb_del_in(c, "notifications", "actor_id", uids)
            c.delete(f"{_SB}/rest/v1/iap_notifications_raw",
                     headers={**_ADM, "Prefer": "return=minimal"},
                     params={"payload->>signedPayload": "like.h.*"})
            sb_del_in(c, "profiles", "user_id", uids)
            for u in uids:
                c.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM)
            ok("runs·routes·crews·follows·notifications·iap·profiles·auth 삭제")


if __name__ == "__main__":
    run()
