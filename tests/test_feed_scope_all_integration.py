"""
Integration: /feed/nearby scope 파라미터 (2026-08-01, Ivan 계약 — 전체 탭 전국 모드)

1. scope 미전송 = scope=nearby와 응답 JSON 동일(바이트 동일 계약)
2. nearby: 서울 반경 내만(뉴욕 제외) — 현행 회귀
3. all: 뉴욕 포함(전 세계) + private run·비공개 계정 owner 미노출(가시성 불변)
4. all: 정렬 ran_at desc·limit/offset 슬라이싱 일치(전역 목록 기준)
5. all + 해외 좌표(호바트) 전송 → 200(bbox 게이트는 nearby 전용)
   / nearby + 해외 좌표 → 400 유지
6. 허용 외 값 → 422 validation_error

Run: python tests/test_feed_scope_all_integration.py  (TestClient 인프로세스)
임시 유저·run 종료 시 전삭·잔여 0.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.main import app  # noqa: E402

_SB = os.environ.get("SUPABASE_URL") or settings.supabase_url
_ADM = {"apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json"}
TS = int(time.time())
uids: list[str] = []
run_ids: list[str] = []


def ok(m):
    print(f"  ✓ {m}")


def sb_user(tag):
    r = httpx.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                   json={"email": f"scope-{tag}-{TS}@t.l", "password": "test1234",
                         "email_confirm": True}, timeout=30)
    r.raise_for_status()
    uids.append(r.json()["id"])
    return r.json()["id"]


def sb_login(tag):
    r = httpx.post(f"{_SB}/auth/v1/token?grant_type=password",
                   headers={"apikey": settings.supabase_key,
                            "Content-Type": "application/json"},
                   json={"email": f"scope-{tag}-{TS}@t.l", "password": "test1234"},
                   timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def sb_run(uid, lat, lng, vis, ran_at, title):
    r = httpx.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=representation"},
                   json={"user_id": uid, "distance_km": 3.0, "duration_sec": 1200,
                         "visibility": vis, "ran_at": ran_at, "title": title,
                         "start_lat": lat, "start_lng": lng}, timeout=30)
    r.raise_for_status()
    run_ids.append(r.json()[0]["id"])
    return r.json()[0]["id"]


def run_tests():
    a = sb_user("a")
    b = sb_user("b")
    c_uid = sb_user("c")
    e = sb_user("e")
    tok = sb_login("a")
    # E = 비공개 계정 (public run이어도 탐색 미노출 — 프라이버시 계약).
    # 신규 auth 유저는 profiles 행이 없어 PATCH가 0행 no-op — upsert로 확실히.
    httpx.post(f"{_SB}/rest/v1/profiles",
               headers={**_ADM, "Prefer": "resolution=merge-duplicates"},
               params={"on_conflict": "user_id"},
               json={"user_id": e, "nickname": f"scope-e-{TS}",
                     "visibility": "private"}, timeout=30).raise_for_status()

    seoul_pub = sb_run(b, 37.55, 126.99, "public", "2026-08-01T01:00:00Z", f"sc-{TS}-seoul")
    seoul_prv = sb_run(b, 37.55, 126.99, "private", "2026-08-01T02:00:00Z", f"sc-{TS}-priv")
    ny_pub = sb_run(c_uid, 40.7655, -73.998, "public", "2026-08-01T03:00:00Z", f"sc-{TS}-ny")
    hidden = sb_run(e, 37.55, 126.99, "public", "2026-08-01T04:00:00Z", f"sc-{TS}-hidden")

    c = TestClient(app)

    def feed(**params):
        r = c.get("/api/feed/nearby", params=params,
                  headers={"Authorization": f"Bearer {tok}"})
        return r

    def ids_of(resp):
        return [x["run_id"] for x in resp.json()]

    print("[1. 미전송 = scope=nearby 응답 동일]")
    r0 = feed(lat=37.55, lng=126.99)
    r1 = feed(lat=37.55, lng=126.99, scope="nearby")
    assert r0.status_code == r1.status_code == 200

    def stable(resp):   # photo_thumb 서명 URL은 콜마다 만료 토큰이 달라 제외
        return [{k: v for k, v in x.items() if k != "photo_thumb"} for x in resp.json()]
    assert stable(r0) == stable(r1), "미전송과 nearby가 달라지면 안 됨"
    ok("미전송 == scope=nearby (휘발 서명 URL 제외 전 필드 동일)")

    print("\n[2. nearby — 서울 반경 내만(현행)]")
    ids = ids_of(r0)
    assert seoul_pub in ids and ny_pub not in ids, (seoul_pub in ids, ny_pub in ids)
    assert seoul_prv not in ids and hidden not in ids
    ok("서울 public ✓ 뉴욕(반경 밖)·private·비공개 계정 ✗")

    print("\n[3. all — 전 세계 + 가시성 불변]")
    ra = feed(lat=37.55, lng=126.99, scope="all", limit=100)
    ids = ids_of(ra)
    assert seoul_pub in ids and ny_pub in ids, "all은 뉴욕 포함"
    assert seoul_prv not in ids, "private run 미노출 불변"
    assert hidden not in ids, "비공개 계정 owner 미노출 불변"
    ok("서울+뉴욕 포함 ✓ private·비공개 계정 여전히 ✗")

    print("\n[4. all — 정렬·limit/offset 슬라이싱]")
    full = ids_of(feed(scope="all", limit=100))
    i_ny, i_seoul = full.index(ny_pub), full.index(seoul_pub)
    assert i_ny < i_seoul, "ran_at desc — 뉴욕(03시)이 서울(01시)보다 앞"
    assert ids_of(feed(scope="all", limit=3)) == full[:3]
    assert ids_of(feed(scope="all", limit=2, offset=2)) == full[2:4]
    ok("desc 정렬 ✓ limit=full[:3] ✓ offset 슬라이스 일치 ✓")

    print("\n[5. 해외 좌표 — all 200 / nearby 400 유지]")
    r = feed(lat=-42.88, lng=147.33, scope="all")   # 호바트
    assert r.status_code == 200, r.text
    r = feed(lat=-42.88, lng=147.33)                 # nearby(기본)
    assert r.status_code == 400 and "Korea" in r.json()["detail"], r.text
    ok("all은 좌표 무시(호바트 200) · nearby는 bbox 400 불변")

    print("\n[6. 허용 외 값 → 422 validation_error]")
    r = feed(lat=37.55, lng=126.99, scope="national")
    assert r.status_code == 422 and r.json().get("error_code") == "validation_error", r.text
    ok("scope=national → 422 + validation_error")


def cleanup():
    sb = get_supabase_admin()
    if run_ids:
        sb.table("runs").delete().in_("id", run_ids).execute()
    for u in uids:
        httpx.delete(f"{_SB}/auth/v1/admin/users/{u}", headers=_ADM, timeout=30)
    left = sb.table("runs").select("id").in_("id", run_ids).execute().data if run_ids else []
    assert left == []
    print(f"\n[cleanup] runs {len(run_ids)}·유저 {len(uids)} 삭제·잔여 0")


if __name__ == "__main__":
    try:
        run_tests()
        print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
    finally:
        cleanup()
