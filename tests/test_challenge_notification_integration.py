"""
Integration test: challenge_completed notifications
Run: python tests/test_challenge_notification_integration.py
"""
from __future__ import annotations

import os, sys, time
import httpx
from datetime import datetime, timedelta, timezone

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

def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)

def _track(distance_km: float, pace_s_per_km: int = 360):
    """직선 GPS 궤적 — 챌린지는 verified run만 집계(집계 정합 정책)라 트랙 동봉."""
    import time as _t
    step_m = 22.24
    n = round(distance_km * 1000 / step_m) + 1
    t0 = (int(_t.time()) - 7200) * 1000
    return [{"lat": 37.5445 + i * 0.0002, "lng": 127.0374,
             "t": t0 + i * round(step_m * pace_s_per_km), "acc": 5.0} for i in range(n)]

def log_run(c, tok, distance_km):
    r = api(c, "POST", "/runs", tok, json={"distance_km": distance_km, "duration_sec": 1800,
                                           "gps_track": _track(distance_km)})
    assert r.status_code == 200, f"POST /runs → 200 이어야 함, got {r.status_code}: {r.text[:200]}"
    return r.json()["id"]

def get_notifications(c, tok, ntype=None):
    r = api(c, "GET", "/notifications", tok, params={"limit": 50})
    assert r.status_code == 200, f"GET /notifications → 200 이어야 함, got {r.status_code}"
    notifs = r.json()
    if ntype:
        notifs = [n for n in notifs if n["type"] == ntype]
    return notifs

def iso(dt: datetime) -> str:
    return dt.isoformat()


def run():
    ts = int(time.time()); pw = "TestPass123!"
    emails = [f"ch-ntf-u{i}-{ts}@t.c" for i in range(1, 4)]
    uids: list[str] = []; toks: list[str] = []
    crew_ids: list[str] = []; run_ids: list[str] = []

    now = datetime.now(timezone.utc)
    starts_at = iso(now - timedelta(minutes=30))   # 30분 전 시작
    ends_at   = iso(now + timedelta(hours=2))       # 2시간 후 종료

    with httpx.Client(timeout=30) as c:
        try:
            # ── 1. 유저 3명 (owner=u1, member=u2, solo=u3) ────────────────
            step("1. 유저 3명 생성 + 로그인")
            for e in emails:
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
            uid1, uid2, uid3 = uids
            tok1, tok2, tok3 = toks
            ok(f"u1={uid1[:8]}(owner)  u2={uid2[:8]}(member)  u3={uid3[:8]}(solo)")

            # ── 2. 크루 생성 + u2 가입 ────────────────────────────────────
            step("2. 크루 생성 + u2 가입")
            r = api(c, "POST", "/crews", tok1,
                    json={"name": f"챌린지알림크루{ts}", "is_public": True})
            assert r.status_code == 200, f"crew create → 200 이어야 함, got {r.status_code}"
            crew_id = r.json()["id"]
            crew_ids.append(crew_id)

            r = api(c, "POST", f"/crews/{crew_id}/join", tok2)
            assert r.status_code == 200, f"u2 join → 200 이어야 함, got {r.status_code}"
            ok(f"crew={crew_id[:8]}  멤버: u1(owner)+u2")

            # ── 3. 챌린지 생성 (목표 10km, 현재 활성) ────────────────────
            step("3. 챌린지 생성 (goal=10km, 현재 활성)")
            r = api(c, "POST", f"/crews/{crew_id}/challenges", tok1,
                    json={"title": "10km 달성 챌린지", "goal_km": 10.0,
                          "starts_at": starts_at, "ends_at": ends_at})
            assert r.status_code == 200, f"challenge create → 200 이어야 함, got {r.status_code}"
            ch = r.json()
            assert ch["is_active"], "챌린지가 활성 상태여야 함"
            ok(f"challenge 생성 ✓  is_active={ch['is_active']}")

            # ── 4. 목표 미달 (u1: 3km) → 알림 없음 ──────────────────────
            step("4. u1이 3km 뜀 (누적 3km, 목표 10km 미달) → 알림 없음")
            run_ids.append(log_run(c, tok1, 3.0))
            notifs_after_3km = get_notifications(c, tok1, "challenge_completed")
            assert len(notifs_after_3km) == 0, \
                f"미달 시 알림이 생기면 안 됨: {notifs_after_3km}"
            ok("3km 미달 → challenge_completed 알림 없음 ✓")

            # ── 5. 목표 달성 (u2: 8km, 누적 11km) → 멤버 전원 알림 ──────
            step("5. u2가 8km 뜀 (누적 11km >= 10km) → u1·u2 모두 알림")
            run_ids.append(log_run(c, tok2, 8.0))

            notifs1 = get_notifications(c, tok1, "challenge_completed")
            notifs2 = get_notifications(c, tok2, "challenge_completed")
            assert len(notifs1) == 1, f"u1 challenge_completed 알림 1개여야 함, got {len(notifs1)}"
            assert len(notifs2) == 1, f"u2 challenge_completed 알림 1개여야 함, got {len(notifs2)}"

            n1 = notifs1[0]
            assert n1["actor_id"] == uid2, f"actor=u2여야 함, got {n1['actor_id']}"
            assert n1["target_id"] == crew_id, f"target_id=crew_id여야 함"
            assert n1["target_type"] == "crew", f"target_type='crew'여야 함"
            assert n1["type"] == "challenge_completed"

            n2 = notifs2[0]
            assert n2["actor_id"] == uid2, f"u2 알림의 actor=u2여야 함"
            ok(f"u1·u2 모두 challenge_completed 알림 ✓  actor={n1['actor_id'][:8]}")

            # ── 6. 달성 후 또 뜀 → 알림 추가 없음 (completed_notified=true) ─
            step("6. 달성 후 u1이 5km 더 뜀 → 추가 알림 없음")
            run_ids.append(log_run(c, tok1, 5.0))
            notifs1_after = get_notifications(c, tok1, "challenge_completed")
            assert len(notifs1_after) == 1, \
                f"달성 후 추가 알림 없어야 함, got {len(notifs1_after)}"
            ok("completed_notified=true → 추가 알림 없음 ✓")

            # ── 7. 크루 없는 유저(u3)가 뜀 → early exit, 에러 없음 ────────
            step("7. 크루 없는 u3가 뜀 → 에러 없이 early exit")
            run_ids.append(log_run(c, tok3, 5.0))
            notifs3 = get_notifications(c, tok3, "challenge_completed")
            assert len(notifs3) == 0, f"u3 알림이 있으면 안 됨: {notifs3}"
            ok("크루 없는 유저 early exit ✓  에러 없음 ✓")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)

        finally:
            step("Cleanup")
            sb_del_in(c, "notifications", "user_id", [u for u in uids if u])
            ok("notifications 삭제")
            sb_del_in(c, "runs", "id", run_ids)
            ok("runs 삭제")
            # crew delete cascades crew_members + crew_challenges
            for cid in crew_ids:
                r = api(c, "DELETE", f"/crews/{cid}", tok1)
            ok("crews 삭제 (members·challenges cascade)")
            sb_del_in(c, "profiles", "user_id", [u for u in uids if u])
            ok("profiles 삭제")
            for uid in uids:
                if uid: sb_del_user(c, uid)
            ok("auth users 삭제")


if __name__ == "__main__":
    run()
