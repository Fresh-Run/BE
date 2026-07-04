"""데모 시드 스크립트 — 프론트 연동 확인용 데이터 채우기.

실행: python scripts/seed_demo_data.py  (백엔드가 localhost:8000에 떠 있어야 함)

원칙
- 가능한 한 실제 API 경유 (인증 포함) — 시딩 자체가 API 검증이 되게.
  admin insert는 API로 불가능한 것만: ① 데모 유저 생성, ② run의 ran_at
  과거 시각 조작, ③ 코스 직접 삽입 (POST /routes/generate는 OpenAI 비용
  + free 쿼터(주3회)를 소모하므로 시딩에 부적합).
- 멱등성: "감지-스킵" 방식. 모든 항목을 만들기 전에 존재 여부를 확인하고
  이미 있으면 건너뛴다. 이 스크립트는 **어떤 것도 삭제하지 않는다** —
  test1/test2의 실제 기록은 절대 건드리지 않음. 두 번 돌려도 안전.
  (runs만은 개별 식별이 어려워 "최근 14일 내 run이 3개 이상이면 그 유저
   시딩 스킵" 규칙 사용 — 데모 유저는 스크립트만 쓰므로 정확하고,
   test1/test2는 실기록이 있으면 그대로 존중하고 건너뜀)
"""
from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta, timezone

import httpx

BASE = "http://localhost:8000/api"
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"
_KST = timezone(timedelta(hours=9))
PW = "test1234"

random.seed(20260704)  # 결정적 시딩 (재실행 시 동일 값)


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

made = {"users": 0, "profiles": 0, "crews": 0, "announcements": 0, "rsvps": 0,
        "join_requests": 0, "runs": 0, "routes": 0, "likes": 0, "comments": 0,
        "bookmarks": 0, "follows": 0}


def log(m): print(f"  {m}")
def section(t): print(f"\n▸ {t}")
def die(m, d=""): print(f"  ✗ {m}" + (f": {d[:200]}" if d else "")); sys.exit(1)


def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


def login(c, email) -> str | None:
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": PW})
    return r.json()["access_token"] if r.status_code == 200 else None


def get_or_create_user(c, email) -> tuple[str, str]:
    """(user_id, token). 있으면 로그인, 없으면 admin 생성 후 로그인."""
    tok = login(c, email)
    if tok is None:
        r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                   json={"email": email, "password": PW, "email_confirm": True})
        if r.status_code not in (200, 201):
            die(f"유저 생성 실패 {email}", r.text)
        made["users"] += 1
        tok = login(c, email)
        if tok is None:
            die(f"생성 후 로그인 실패 {email}")
    uid = api(c, "GET", "/me", tok).json()["user_id"]
    return uid, tok


def ensure_profile(c, tok, nickname, bio, avatar_seed):
    """프로필이 없을 때만 생성 — 기존 프로필(실계정 커스텀)은 건드리지 않음."""
    if api(c, "GET", "/me/profile", tok).json() is not None:
        return
    body = {"nickname": nickname, "bio": bio,
            "avatar_url": f"https://api.dicebear.com/9.x/thumbs/png?seed={avatar_seed}"}
    r = api(c, "PATCH", "/me/profile", tok, json=body)
    if r.status_code == 409:  # 닉네임 선점 — 숫자 붙여 재시도
        body["nickname"] = f"{nickname}{random.randint(10, 99)}"
        r = api(c, "PATCH", "/me/profile", tok, json=body)
    if r.status_code != 200:
        die(f"프로필 생성 실패 {nickname}", r.text)
    made["profiles"] += 1


def sb_insert_route(c, uid, summary, is_public, lat, lng, dist):
    r = c.post(f"{_SB}/rest/v1/routes",
               headers={**_ADM, "Prefer": "return=representation"},
               json={"user_id": uid, "summary": summary, "total_distance_km": dist,
                     "estimated_duration_min": round(dist * 6.5),
                     "is_public": is_public, "waypoints": [],
                     "start_lat": lat, "start_lng": lng})
    if r.status_code not in (200, 201):
        die("route insert 실패", r.text)
    made["routes"] += 1
    return r.json()[0]["id"]


def ensure_route(c, tok, uid, summary, is_public, lat, lng, dist) -> str:
    """소유자의 코스 중 같은 summary가 있으면 재사용."""
    mine = api(c, "GET", "/routes", tok, params={"limit": 50}).json()
    for rt in mine:
        if rt["summary"] == summary:
            return rt["id"]
    return sb_insert_route(c, uid, summary, is_public, lat, lng, dist)


def sb_insert_run(c, uid, ran_at, km, route_id=None, notes=None):
    pace = random.randint(320, 420)
    body = {"user_id": uid, "ran_at": ran_at, "distance_km": km,
            "duration_sec": round(km * pace), "avg_pace_sec_per_km": pace}
    if route_id: body["route_id"] = route_id
    if notes: body["notes"] = notes
    r = c.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=minimal"}, json=body)
    if r.status_code not in (200, 201):
        die("run insert 실패", r.text)
    made["runs"] += 1


def seed_runs_if_absent(c, tok, uid, specs):
    """최근 14일 내 run이 3개 이상이면 스킵 (멱등 + 실기록 존중)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    recent = [r for r in api(c, "GET", "/runs", tok, params={"limit": 50}).json()
              if datetime.fromisoformat(r["ran_at"].replace("Z", "+00:00")) >= cutoff]
    if len(recent) >= 3:
        log(f"    (run {len(recent)}개 이미 있음 — 스킵)")
        return
    now = datetime.now(timezone.utc)
    for days_ago, hour_kst, km, route_id, notes in specs:
        ran = (now - timedelta(days=days_ago)).astimezone(_KST).replace(
            hour=hour_kst, minute=random.randint(0, 50), second=0, microsecond=0)
        sb_insert_run(c, uid, ran.astimezone(timezone.utc).isoformat(), km, route_id, notes)


def next_saturday_kst(hour=6):
    """다음 토요일 hour시 KST. 마감(전날 21시)이 지금+1h보다 미래가 되게 보정."""
    now = datetime.now(_KST)
    days = (5 - now.weekday()) % 7 or 7
    run_at = (now + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    if run_at - timedelta(hours=9) < now + timedelta(hours=1):
        run_at += timedelta(days=7)
    return run_at


def main():
    with httpx.Client(timeout=30) as c:
        if c.get("http://localhost:8000/docs").status_code != 200:
            die("백엔드가 localhost:8000에 떠 있지 않음")

        # ── 1. 유저 + 프로필 ─────────────────────────────────────────────
        section("1. 유저 + 프로필 (test1·test2 + demo1~5)")
        DEMO = [
            ("demo1@freshrun.com", "새벽러너",   "5시 기상, 6시 한강. 비 오면 쉽니다"),
            ("demo2@freshrun.com", "한강질주",   "서브4 도전 중 🏃"),
            ("demo3@freshrun.com", "뚝섬바람",   "천천히 오래 달리기파"),
            ("demo4@freshrun.com", "마포페이서", "페이스메이커 해드립니다"),
            ("demo5@freshrun.com", "야간비행",   "퇴근 후 야간 러닝 전문"),
        ]
        users: dict[str, tuple[str, str]] = {}  # key → (uid, tok)
        t1 = login(c, "test1@freshrun.com") or die("test1 로그인 실패 (비번 확인)")
        t2 = login(c, "test2@freshrun.com") or die("test2 로그인 실패")
        uid1 = api(c, "GET", "/me", t1).json()["user_id"]
        uid2 = api(c, "GET", "/me", t2).json()["user_id"]
        users["test1"], users["test2"] = (uid1, t1), (uid2, t2)
        ensure_profile(c, t1, "한강크루장", "한강 새벽 러닝 크루 운영 중", "test1")
        ensure_profile(c, t2, "러닝러버", "기록보다 꾸준히", "test2")
        for i, (email, nick, bio) in enumerate(DEMO, start=1):
            uid, tok = get_or_create_user(c, email)
            users[f"demo{i}"] = (uid, tok)
            ensure_profile(c, tok, nick, bio, f"demo{i}")
        log(f"유저 {len(users)}명 준비 (신규 생성 {made['users']}명)")

        # ── 2. 크루 (승인제) + 멤버 ──────────────────────────────────────
        section("2. 크루: 한강 새벽 러닝 크루 (approval)")
        CREW_NAME = "한강 새벽 러닝 크루"
        crew = next((cr for cr in api(c, "GET", "/crews/mine", t1).json()
                     if cr["name"] == CREW_NAME), None)
        if crew is None:
            r = api(c, "POST", "/crews", t1, json={
                "name": CREW_NAME, "description": "매주 토요일 6시, 뚝섬에서 같이 달려요",
                "area": "서울 성동구", "sport": "러닝", "level": "무관",
                "join_policy": "approval", "max_members": 30,
                "active_days": ["토"], "active_time": "06:00", "color": "#34C759"})
            crew = r.json() if r.status_code in (200, 201) else die("크루 생성 실패", r.text)
            made["crews"] += 1
        CREW = crew["id"]

        # 승인제라 join(202) → 크루장 approve 흐름을 그대로 사용 (API 검증 겸)
        for key in ("test2", "demo1", "demo2", "demo3", "demo4"):
            uid, tok = users[key]
            r = api(c, "POST", f"/crews/{CREW}/join", tok)
            if r.status_code == 202:
                rid = r.json()["id"]
                ar = api(c, "POST", f"/crews/{CREW}/join-requests/{rid}/approve", t1)
                if ar.status_code != 204: die(f"{key} 승인 실패", ar.text)
                made["join_requests"] += 1
            elif r.status_code != 409:  # 409 = 이미 멤버/신청 — 스킵
                die(f"{key} 가입 실패", r.text)
        # demo5는 pending으로 남김 (크루장 신청 목록 화면용)
        r = api(c, "POST", f"/crews/{CREW}/join", users["demo5"][1])
        if r.status_code == 202: made["join_requests"] += 1
        log(f"크루 준비 (멤버 6명 + demo5 pending)")

        # ── 3. 공지 2개 + RSVP ───────────────────────────────────────────
        section("3. 공지 + 참석 투표")
        existing = {a["title"]: a for a in
                    api(c, "GET", f"/crews/{CREW}/announcements", t1, params={"limit": 50}).json()}
        run_at = next_saturday_kst()
        A_TITLE = "토요 정기런 — 뚝섬 6시 ⛅"
        if A_TITLE in existing:
            ann_a = existing[A_TITLE]
        else:
            r = api(c, "POST", f"/crews/{CREW}/announcements", t1, json={
                "title": A_TITLE,
                "body": "이번 주도 뚝섬한강공원 수변무대 앞에서 6시 정각 출발합니다.\n"
                        "10km 그룹 / 5km 그룹 나눠서 진행해요. 참석 투표 부탁!",
                "run_at": run_at.isoformat(),
                "place_name": "뚝섬한강공원 수변무대",
                "place_lat": 37.5299, "place_lng": 127.0703,
                "rsvp_closes_at": (run_at - timedelta(hours=9)).isoformat()})
            ann_a = r.json() if r.status_code == 201 else die("공지A 실패", r.text)
            made["announcements"] += 1
        B_TITLE = "크루 회비 및 러닝 조끼 안내"
        if B_TITLE not in existing:
            r = api(c, "POST", f"/crews/{CREW}/announcements", t1, json={
                "title": B_TITLE,
                "body": "월 회비는 없습니다 (무료). 크루 러닝 조끼 공동구매는 "
                        "참여 인원 10명 넘으면 진행할게요. 댓글 대신 크루장 DM 주세요."})
            if r.status_code != 201: die("공지B 실패", r.text)
            made["announcements"] += 1
        for key, vote in [("test2", "going"), ("demo1", "going"), ("demo2", "going"),
                          ("demo3", "maybe"), ("demo4", "not_going")]:
            r = api(c, "PUT", f"/crews/{CREW}/announcements/{ann_a['id']}/rsvp",
                    users[key][1], json={"status": vote})
            if r.status_code == 204: made["rsvps"] += 1
        log("공지 2개 + 투표 5표 (참석3/불참1/미정1)")

        # ── 4. 코스 (공개 3 + 비공개 1) + 좋아요/댓글/북마크 ─────────────
        section("4. 코스 + 소셜")
        r1 = ensure_route(c, t1, uid1, "반포 한강공원 야경 코스", True, 37.5109, 126.9956, 5.2)
        r2 = ensure_route(c, users["demo1"][1], users["demo1"][0],
                          "뚝섬 순환 러닝 코스", True, 37.5299, 127.0703, 7.0)
        r3 = ensure_route(c, t2, uid2, "여의도 벚꽃길 코스", True, 37.5285, 126.9327, 3.5)
        r4 = ensure_route(c, t1, uid1, "집 앞 개인 코스", False, 37.5445, 127.0374, 4.0)
        for key, rid in [("test2", r1), ("demo1", r1), ("demo2", r1),
                         ("demo3", r2), ("test1", r2), ("demo4", r3)]:
            if api(c, "POST", f"/routes/{rid}/like", users[key][1]).status_code == 204:
                made["likes"] += 1
        for key, rid, text in [("demo1", r1, "야경 진짜 미쳤어요, 다음 크루런 여기 어때요?"),
                               ("test2", r2, "순환이라 신호 없이 쭉 달리기 좋네요 👍"),
                               ("demo2", r1, "어제 뛰었는데 노면도 좋아요")]:
            uid, tok = users[key]
            already = any(cm["user_id"] == uid and cm["content"] == text
                          for cm in api(c, "GET", f"/routes/{rid}/comments", tok).json())
            if not already:
                if api(c, "POST", f"/routes/{rid}/comments", tok,
                       json={"content": text}).status_code == 201:
                    made["comments"] += 1
        if api(c, "POST", f"/routes/{r1}/bookmark", t2).status_code == 204:
            made["bookmarks"] += 1
        log("코스 4개 (공개3·비공개1), 좋아요 6, 댓글 3, 북마크 1")

        # ── 5. 팔로우 그래프 ─────────────────────────────────────────────
        section("5. 팔로우")
        pairs = [("test1", "test2"), ("test2", "test1"),            # 맞팔
                 ("test1", "demo1"), ("test1", "demo2"),            # 팔로잉 피드용
                 ("test2", "demo1"),
                 ("demo1", "test1"), ("demo2", "test1"), ("demo3", "test1")]
        for a, b in pairs:
            if api(c, "POST", f"/users/{users[b][0]}/follow",
                   users[a][1]).status_code == 204:
                made["follows"] += 1
        log(f"팔로우 관계 {len(pairs)}건 보장 (맞팔 포함)")

        # ── 6. 러닝 기록 (최근 2주 분산, ran_at 조작 = admin) ────────────
        section("6. 러닝 기록")
        plans = {
            "test1": [(1, 6, 8.2, r1, "새벽 공기 최고"), (3, 6, 5.0, r4, None),
                      (6, 7, 10.1, None, "주말 롱런"), (10, 6, 6.4, r1, None)],
            "test2": [(1, 20, 5.5, r3, None), (4, 21, 4.2, None, "퇴근런"),
                      (8, 20, 7.3, r2, None)],
            "demo1": [(0, 6, 7.0, r2, None), (2, 6, 6.5, r2, None),
                      (5, 6, 9.2, None, None), (9, 7, 5.0, r1, None)],
            "demo2": [(1, 7, 4.8, None, None), (5, 6, 8.8, r2, None), (12, 7, 6.0, None, None)],
            "demo3": [(2, 19, 3.2, None, None), (7, 19, 4.5, None, None), (11, 20, 3.8, None, None)],
            "demo4": [(3, 6, 10.0, None, None), (6, 6, 9.5, None, None), (13, 7, 8.4, None, None)],
        }
        for key, specs in plans.items():
            uid, tok = users[key]
            log(f"  {key}:")
            seed_runs_if_absent(c, tok, uid, specs)
        log(f"run 시딩 {made['runs']}개")

        # ── 요약 ─────────────────────────────────────────────────────────
        section("시딩 요약 (이번 실행에서 새로 만든 것)")
        for k, v in made.items():
            log(f"{k}: {v}")

        # ── 검증: test1 시점 홈 화면 API ─────────────────────────────────
        section("검증 — test1 토큰으로 주요 화면 API")
        s = api(c, "GET", "/me/stats", t1).json()
        log(f"주간 통계: 이번 주 {s['week']['total_distance_km']}km / {s['week']['run_count']}회")
        feed = api(c, "GET", f"/crews/{CREW}/runs", t1, params={"limit": 10}).json()
        log(f"크루 러닝 피드: {len(feed)}건 (최신: {feed[0]['nickname']} "
            f"{feed[0]['distance_km']}km)" if feed else "크루 피드 비어있음!")
        anns = api(c, "GET", f"/crews/{CREW}/announcements", t1).json()
        a0 = next(a for a in anns if a["run_at"])
        log(f"공지: {len(anns)}개, RSVP 집계 참석{a0['rsvp']['going']}/"
            f"불참{a0['rsvp']['not_going']}/미정{a0['rsvp']['maybe']}")
        ffeed = api(c, "GET", "/feed", t1).json()
        log(f"팔로잉 피드: {len(ffeed)}건" +
            (f" (최신: {ffeed[0]['owner_nickname']} — {ffeed[0]['summary']}, "
             f"좋아요 {ffeed[0]['like_count']})" if ffeed else " ← 비어있음!"))
        reqs = api(c, "GET", f"/crews/{CREW}/join-requests", t1).json()
        log(f"가입 신청 대기: {len(reqs)}건" +
            (f" ({reqs[0]['nickname']})" if reqs else ""))
        print("\n완료. 프론트에서 test1@freshrun.com / (공유된 비번)으로 로그인해 확인하세요.")


if __name__ == "__main__":
    main()
