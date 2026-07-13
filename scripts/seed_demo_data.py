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
        "bookmarks": 0, "follows": 0, "kudos": 0, "invite_codes": 0,
        "gps_runs": 0, "coach_scripts": 0, "insights": 0, "body_info": 0,
        "browse_crews": 0, "browse_members": 0, "pub_routes": 0, "copies": 0,
        "public_runs": 0}


import math


def make_gps_track(distance_km, pace_sec_per_km, interval_s=4.0, jitter_m=3.0,
                   seed=42, start=(37.5445, 127.0374)):
    """서울숲 인근 현실적 GPS 궤적 (test_gps_track_integration.make_track 미러링).

    방향 랜덤워크 전진 + gaussian jitter로 GPS 노이즈 모사. gps_track POST 포맷
    ([{lat,lng,t,acc,alt}])을 그대로 반환 → 서버 파이프라인이 verified·splits 산출.
    """
    rng = random.Random(seed)
    step_m = (1000.0 / pace_sec_per_km) * interval_s
    n = int(distance_km * 1000.0 / step_m) + 1
    lat, lng = start
    heading = rng.uniform(0, 2 * math.pi)
    t = 1_783_300_000_000
    pts = []
    for i in range(n):
        ky, kx = 110540.0, 111320.0 * math.cos(math.radians(lat))
        alt = 30.0 + 6.0 * math.sin(i * 0.02) + rng.gauss(0, 0.8)
        pts.append({"lat": round(lat + rng.gauss(0, jitter_m) / ky, 7),
                    "lng": round(lng + rng.gauss(0, jitter_m) / kx, 7),
                    "t": t, "acc": round(abs(rng.gauss(8, 2)), 1), "alt": round(alt, 1)})
        heading += rng.gauss(0, math.radians(6))
        lat += step_m * math.cos(heading) / ky
        lng += step_m * math.sin(heading) / kx
        t += int(interval_s * 1000)
    return pts


def ensure_premium(c, uid):
    """test1을 premium으로 (코치·인사이트 게이트용). tier는 API로 못 바꿔 admin REST."""
    r = c.get(f"{_SB}/rest/v1/profiles", headers=_ADM,
              params={"user_id": f"eq.{uid}", "select": "tier"})
    if r.status_code == 200 and r.json() and r.json()[0].get("tier") == "premium":
        return
    c.patch(f"{_SB}/rest/v1/profiles", headers=_ADM,
            params={"user_id": f"eq.{uid}"}, json={"tier": "premium"})


def ensure_browse_crew(c, owner_tok, owner_uid, body):
    """둘러보기용 크루 — owner의 /crews/mine에 동명이 없으면 생성. 반환 crew id.

    free 유저는 크루 1개 한도라, 이미 다른 크루를 소유했으면 premium 승격 후 생성.
    멱등: 같은 이름 크루가 이미 있으면 그대로 재사용.
    """
    mine = c.request("GET", f"{BASE}/crews/mine",
                     headers={"Authorization": f"Bearer {owner_tok}"}).json()
    existing = next((cr for cr in mine if cr["name"] == body["name"]), None)
    if existing:
        return existing["id"], False
    if len(mine) >= 1:  # 이미 1개 소유 → 한도 회피 위해 premium
        ensure_premium(c, owner_uid)
    r = c.request("POST", f"{BASE}/crews",
                  headers={"Authorization": f"Bearer {owner_tok}"}, json=body)
    if r.status_code not in (200, 201):
        die(f"둘러보기 크루 생성 실패 ({body['name']})", r.text)
    return r.json()["id"], True


def ensure_copy(c, source_id, copier_tok, copier_uid):
    """'이 코스 달리기' 복사 — copier가 이미 이 코스 복사본을 가지면 스킵(멱등).
    copy_count(copied_from 집계) 증가용."""
    have = c.get(f"{_SB}/rest/v1/routes", headers=_ADM,
                 params={"user_id": f"eq.{copier_uid}", "copied_from": f"eq.{source_id}",
                         "select": "id"}).json()
    if have:
        return False
    r = c.request("POST", f"{BASE}/routes/{source_id}/copy",
                  headers={"Authorization": f"Bearer {copier_tok}"})
    if r.status_code not in (200, 201):
        die("코스 복사 실패", r.text)
    return True


def ensure_crew_member(c, crew_id, uid):
    """크루 멤버 보장 — admin insert(멱등). approval/비공개 크루도 시딩 가능
    (승인·초대 흐름 없이). 이미 멤버면 스킵."""
    have = c.get(f"{_SB}/rest/v1/crew_members", headers=_ADM,
                 params={"crew_id": f"eq.{crew_id}", "user_id": f"eq.{uid}",
                         "select": "user_id"}).json()
    if have:
        return False
    r = c.post(f"{_SB}/rest/v1/crew_members", headers={**_ADM, "Prefer": "return=minimal"},
               json={"crew_id": crew_id, "user_id": uid, "role": "member"})
    if r.status_code not in (200, 201):
        die("멤버 삽입 실패", r.text)
    return True


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
    """프로필이 없을 때만 생성 — 기존 프로필(실계정 커스텀)은 건드리지 않음.

    예외 1건: avatar_url이 **null이면 시드 아바타만 재부여** — 검증 스크립트가
    데모 아바타를 지워도 재실행으로 복구되게(멱등 보수 2026-07-12). non-null
    (수동 변경 포함)은 절대 안 덮고, 닉네임·bio도 건드리지 않는다.
    """
    cur = api(c, "GET", "/me/profile", tok).json()
    if cur is not None:
        if cur.get("avatar_url") is None:
            r = api(c, "PATCH", "/me/profile", tok, json={
                "nickname": cur["nickname"],  # PATCH 계약상 필수 — 현재값 그대로
                "avatar_url": f"https://api.dicebear.com/9.x/thumbs/png?seed={avatar_seed}",
            })
            if r.status_code != 200:
                die(f"아바타 재부여 실패 {cur['nickname']}", r.text)
            made["avatar_refills"] = made.get("avatar_refills", 0) + 1
            log(f"  아바타 재부여: {cur['nickname']}")
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


def sb_insert_run(c, uid, ran_at, km, route_id=None, notes=None, visibility="followers"):
    # baseline은 followers (신규 환경에서도 대부분 followers, 일부만 public 승격 →
    # 자연스러운 mix). 공개 프로필 데모용 public 전환은 섹션 12에서 수정 API 경유.
    pace = random.randint(320, 420)
    body = {"user_id": uid, "ran_at": ran_at, "distance_km": km,
            "duration_sec": round(km * pace), "avg_pace_sec_per_km": pace,
            "visibility": visibility}
    if route_id: body["route_id"] = route_id
    if notes: body["notes"] = notes
    r = c.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=minimal"}, json=body)
    if r.status_code not in (200, 201):
        die("run insert 실패", r.text)
    made["runs"] += 1


def _title_for_hour(ran_at_iso):
    """KST 시각 기반 기본 제목 (프론트의 시간대 기본값 흉내)."""
    h = datetime.fromisoformat(ran_at_iso.replace("Z", "+00:00")).astimezone(_KST).hour
    if 4 <= h < 6:   return "새벽 러닝"
    if 6 <= h < 11:  return "아침 러닝"
    if 11 <= h < 17: return "한낮 러닝"
    if 17 <= h < 21: return "저녁 러닝"
    return "야간 러닝"


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
                "active_days": ["토"], "active_time": "06:00", "color": "#34C759",
                "sido": "서울특별시", "sigungu": "성동구",
                "lat": 37.547, "lng": 127.044, "tags": ["새벽", "평지"]})
            crew = r.json() if r.status_code in (200, 201) else die("크루 생성 실패", r.text)
            made["crews"] += 1
        elif not crew.get("sido"):  # 백필: 기존 크루에 지역·좌표·태그
            api(c, "PATCH", f"/crews/{crew['id']}", t1, json={
                "sido": "서울특별시", "sigungu": "성동구",
                "lat": 37.547, "lng": 127.044, "tags": ["새벽", "평지"]})
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
        # 초대 코드: 없을 때만 발급 (재실행 시 기존 코드 유지 — 값은 출력 안 함)
        if api(c, "GET", f"/crews/{CREW}/invite", t1).status_code == 404:
            r = api(c, "POST", f"/crews/{CREW}/invite", t1)
            if r.status_code != 201: die("초대 코드 발급 실패", r.text)
            made["invite_codes"] += 1
        log(f"크루 준비 (멤버 6명 + demo5 pending + 초대 코드 발급됨)")

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

        # ── 7. kudos (본인 run 제외, POST가 멱등이라 재실행 안전) ────────
        section("7. run kudos")
        member_keys = ["test1", "test2", "demo1", "demo2", "demo3", "demo4"]
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        for oi, owner in enumerate(member_keys):
            _, otok = users[owner]
            # private run은 소유자만 보이므로 kudos 대상에서 제외 (크루원은
            # followers·public만 kudos 가능 — visibility 게이트와 일관)
            runs = [r for r in api(c, "GET", "/runs", otok, params={"limit": 10}).json()
                    if datetime.fromisoformat(r["ran_at"].replace("Z", "+00:00")) >= cutoff
                    and r.get("visibility") != "private"]
            others = [k for k in member_keys if k != owner]
            # 결정적 분배: n번째 run에 (2~3명)이 돌아가며 kudos
            for ri, run in enumerate(runs[:3]):
                for kj in range(2 + (ri % 2)):
                    kudoser = others[(oi + ri + kj) % len(others)]
                    r = api(c, "POST", f"/runs/{run['id']}/kudos", users[kudoser][1])
                    if r.status_code == 204:
                        made["kudos"] += 1
                    elif r.status_code not in (400, 404):  # 400=self, 404=미가시(관대)
                        die(f"kudos 실패 {kudoser}→{owner}", r.text)
        log(f"kudos {made['kudos']}건 보장 (본인·private run 제외 분배)")

        # ── 8. GPS 검증 run (verification=verified + splits) ─────────────
        section("8. GPS 검증 run (서울숲 궤적)")
        # (유저키, 거리km, 페이스sec, seed) — POST /runs가 gps_track을 파이프라인에 태움
        gps_plan = [("test1", 5.0, 330, 101), ("test1", 8.0, 345, 102),
                    ("demo1", 6.5, 320, 103)]
        # 멱등: 유저별 all-or-nothing — 이미 has_track run이 하나라도 있으면 그
        # 유저의 GPS 시딩 전체를 스킵 (계획 항목별 부분 재생성이 중복을 만들지 않도록).
        has_gps = {}  # key → 이미 GPS run 보유 여부
        for key in {k for k, *_ in gps_plan}:
            _, tok = users[key]
            has_gps[key] = any(r.get("has_track")
                               for r in api(c, "GET", "/runs", tok, params={"limit": 50}).json())
        for key, dist, pace, seed in gps_plan:
            _, tok = users[key]
            if has_gps[key]:
                log(f"  {key}: GPS run 이미 있음 — 스킵")
                continue
            track = make_gps_track(dist, pace, seed=seed)
            r = api(c, "POST", "/runs", tok, json={
                "distance_km": dist, "duration_sec": int(dist * pace), "gps_track": track,
                "visibility": "followers"})  # baseline; 섹션 12에서 일부 public 승격
            if r.status_code != 200:
                die(f"GPS run 실패 {key}", r.text)
            d = r.json()
            made["gps_runs"] += 1
            log(f"  {key}: {d['distance_km']}km verification={d['verification']} "
                f"splits={len(d['splits'] or [])}랩 track={d['has_track']}")

        # ── 9. 프리미엄 콘텐츠 (test1: 코치 스크립트·월간 인사이트·신체정보) ──
        section("9. 프리미엄 콘텐츠 (test1)")
        ensure_premium(c, uid1)
        # 신체정보 (본인 /me/profile에만 노출 — 멱등: birth_year 있으면 스킵)
        prof = api(c, "GET", "/me/profile", t1).json()
        if prof and prof.get("birth_year") is None:
            r = api(c, "PATCH", "/me/profile", t1, json={
                "nickname": prof["nickname"], "birth_year": 1992,
                "weight_kg": 68.5, "height_cm": 176, "gender": "male"})
            if r.status_code == 200:
                made["body_info"] += 1
            log("  신체정보 저장 (birth 1992·68.5kg·176cm·male — 본인만 조회)")
        else:
            log("  신체정보 이미 있음 — 스킵")
        # 코치 스크립트 (test1 공개 코스 r1 — route당 1회 캐시, 재실행 무비용)
        r = api(c, "POST", f"/routes/{r1}/coach-script", t1)
        if r.status_code == 200:
            cs = r.json()
            if not cs["from_cache"]:
                made["coach_scripts"] += 1
            log(f"  코치 스크립트: cues {len(cs['cues'])}개 "
                f"(from_cache={cs['from_cache']}) — {cs['cues'][0]['text'][:30]}…")
        else:
            log(f"  코치 스크립트 생성 실패 ({r.status_code}) — 건너뜀")
        # 월간 인사이트 (지난달 2026-06 — 캐시됨, 재실행 무비용)
        r = api(c, "GET", "/me/insights/monthly", t1, params={"year": 2026, "month": 6})
        if r.status_code == 200:
            ins = r.json()
            if ins.get("ai"):
                if not ins["ai"]["from_cache"]:
                    made["insights"] += 1
                log(f"  월간 인사이트 2026-06: {ins['stats']['run_count']}회 "
                    f"{ins['stats']['total_distance_km']}km, ai coaching "
                    f"{len(ins['ai']['coaching'])}자 (from_cache={ins['ai']['from_cache']})")
            else:
                log("  월간 인사이트 2026-06: 해당 월 run 0 → ai null (지난달 run 없음)")
        else:
            log(f"  월간 인사이트 실패 ({r.status_code})")

        # ── 10. 둘러보기 크루 (데모 유저 소유, test1/test2 미가입) ────────
        section("10. 둘러보기 크루 (미가입 크루로 노출)")
        # (owner, name, area, sport, level, is_public, join_policy, desc, [멤버],
        #  sigungu, lat, lng, [태그2])  — sido는 전부 서울특별시
        BROWSE = [
            ("demo1", "성수동 러닝 크루", "성수동", "러닝", "입문", True, "open",
             "성수동 카페거리에서 만나 서울숲까지. 초보 환영!", ["demo2", "demo3"],
             "성동구", 37.544, 127.056, ["아침", "입문환영"]),
            ("demo2", "여의도 퇴근런", "여의도", "러닝", "중급", True, "open",
             "평일 저녁 7시, 여의도공원 한 바퀴 후 한강까지", ["demo4"],
             "영등포구", 37.526, 126.924, ["저녁", "평지"]),
            ("demo3", "반포 한강 나이트런", "반포", "러닝", "무관", True, "approval",
             "달빛 아래 반포대교 무지개분수 코스. 승인제로 운영해요", ["demo1", "demo5"],
             "서초구", 37.513, 126.996, ["야간", "친목"]),
            ("demo4", "잠실 새벽 5시", "잠실", "러닝", "중급", True, "open",
             "출근 전 석촌호수 두 바퀴. 새벽형 인간 모여라", ["demo2", "demo3", "demo5"],
             "송파구", 37.511, 127.081, ["새벽", "평지"]),
            ("demo5", "마포 주말 트레일", "마포", "트레일", "중급", True, "approval",
             "주말 아침 안산·매봉산 트레일. 흙길 좋아하는 분", ["demo1"],
             "마포구", 37.556, 126.925, ["주말", "트레일"]),
            ("demo1", "강남 인터벌 클럽", "강남", "러닝", "고급", False, "approval",
             "양재천 인터벌 훈련. 비공개(초대 전용), 서브3 목표", ["demo4"],
             "강남구", 37.497, 127.038, ["기록도전", "평지"]),
        ]
        crew_ann = {  # 크루 이름 → 공지 (일부만)
            "성수동 러닝 크루": ("이번 주 토요일 정기런", "8시 서울숲 정문 집합, 5km 가볍게!"),
            "잠실 새벽 5시": ("겨울 새벽 러닝 안내", "영하권엔 6시로 미룹니다. 방한 필수!"),
        }
        for (owner, name, area, sport, level, is_pub, policy, desc, members,
             sigungu, lat, lng, tags) in BROWSE:
            ouid, otok = users[owner]
            cid, created = ensure_browse_crew(c, otok, ouid, {
                "name": name, "area": area, "sport": sport, "level": level,
                "description": desc, "is_public": is_pub, "join_policy": policy,
                "max_members": 30, "sido": "서울특별시", "sigungu": sigungu,
                "lat": lat, "lng": lng, "tags": tags})
            if created:
                made["browse_crews"] += 1
            # 백필: 기존 크루(구코드로 생성돼 좌표 없음)에 지역·좌표·태그 채움
            elif not api(c, "GET", f"/crews/{cid}", otok).json().get("sido"):
                api(c, "PATCH", f"/crews/{cid}", otok, json={
                    "sido": "서울특별시", "sigungu": sigungu,
                    "lat": lat, "lng": lng, "tags": tags})
            for mkey in members:
                if ensure_crew_member(c, cid, users[mkey][0]):
                    made["browse_members"] += 1
            # 공지 (owner 토큰으로, 감지-스킵)
            if name in crew_ann:
                title, bd = crew_ann[name]
                anns = api(c, "GET", f"/crews/{cid}/announcements", otok,
                           params={"limit": 50}).json()
                if not any(a["title"] == title for a in anns):
                    r = api(c, "POST", f"/crews/{cid}/announcements", otok,
                            json={"title": title, "body": bd})
                    if r.status_code == 201:
                        made["announcements"] += 1
            mc = api(c, "GET", f"/crews/{cid}", otok).json()["member_count"]
            vis = "공개" if is_pub else "비공개"
            log(f"  {name} (owner {owner}, {vis}/{policy}, {level}) — 멤버 {mc}명"
                + ("" if created else " [기존]"))
        log(f"둘러보기 크루 {len([1 for b in BROWSE])}개 보장 "
            f"(신규 {made['browse_crews']}, 멤버 추가 {made['browse_members']})")

        # ── 10-b. 모집 마감 크루 (둘러보기 include_full 토글 눈검증용) ──────
        # 정원 3 = owner(demo1) + 멤버 2 → member_count == max_members.
        # demo1은 premium(생성 한도 없음). 좌표는 성수 실좌표 — 거리순 정렬 겸용.
        # 멱등: ensure_browse_crew(동명 감지-스킵) + ensure_crew_member(존재 스킵).
        ouid, otok = users["demo1"]
        cid, created = ensure_browse_crew(c, otok, ouid, {
            "name": "성수 새벽 소수정예", "area": "성수동", "sport": "러닝",
            "level": "중급", "description": "정원 3명이 꽉 찼어요 — 자리 나면 공지할게요!",
            "is_public": True, "join_policy": "approval", "max_members": 3,
            "sido": "서울특별시", "sigungu": "성동구",
            "lat": 37.542, "lng": 127.052, "tags": ["새벽", "친목"]})
        if created:
            made["browse_crews"] += 1
        for mkey in ("demo2", "demo4"):
            if ensure_crew_member(c, cid, users[mkey][0]):
                made["browse_members"] += 1
        mc = api(c, "GET", f"/crews/{cid}", otok).json()["member_count"]
        if mc != 3:
            die(f"모집 마감 크루 정원 불일치 — member_count {mc} (기대 3)")
        log(f"  성수 새벽 소수정예 — 모집 마감 {mc}/3"
            + ("" if created else " [기존]"))

        # ── 11. 공개 코스 피드 확장 (홈 '전체' 탭 = GET /routes/public) ────
        section("11. 공개 코스 피드 (전체 탭 — 좋아요·댓글·복사)")
        # (owner, summary, lat, lng, dist, [좋아요 누를 키], [(댓글키,내용)], [복사 키])
        PUB = [
            ("test1", "성수 서울숲 야경 5km 루프", 37.544, 127.056, 5.0,
             ["test2", "demo1", "demo2", "demo3", "demo4", "demo5"],
             [("demo1", "야경 진짜 미쳤어요 🌃"), ("test2", "루프라 길 안 잃어서 좋네요")],
             ["demo2", "demo3"]),                                  # 인기+복사
            ("test2", "여의도 리버사이드 7km", 37.526, 126.924, 7.0,
             ["test1", "demo1", "demo2", "demo3", "demo5"],
             [("demo2", "강바람 맞으며 달리기 최고")], ["demo4"]),   # 인기+복사
            ("demo3", "강남 양재천 인터벌 8km", 37.497, 127.038, 8.0,
             ["test1", "test2", "demo1", "demo2", "demo4"],
             [("demo1", "인터벌 훈련하기 딱이에요")], ["test1"]),    # 인기+복사
            ("demo2", "반포 무지개분수 나이트런 5.5km", 37.513, 126.996, 5.5,
             ["test1", "demo5"], [], []),                          # 중간
            ("demo1", "잠실 석촌호수 두 바퀴 4.5km", 37.511, 127.081, 4.5,
             ["test2", "demo3", "demo4"], [], []),                 # 중간
            ("demo4", "뚝섬 자전거길 러닝 6km", 37.531, 127.070, 6.0,
             ["demo1", "demo2"], [], []),                          # 중간
            ("test1", "서울숲 아침 조깅 3.2km", 37.5445, 127.0374, 3.2,
             ["demo1"], [], []),                                   # 신규 느낌
            ("test2", "마포 노을공원 언덕 6.2km", 37.556, 126.925, 6.2, [], [], []),  # 신규
            ("demo5", "남산 순환 트레일 5km", 37.551, 126.988, 5.0, [], [], []),      # 신규
        ]
        for owner, summary, lat, lng, dist, likers, comments, copiers in PUB:
            ouid, otok = users[owner]
            before = made["routes"]
            rid = ensure_route(c, otok, ouid, summary, True, lat, lng, dist)
            if made["routes"] > before:
                made["pub_routes"] += 1
            for lk in likers:
                api(c, "POST", f"/routes/{rid}/like", users[lk][1])  # 멱등(204)
            for ck, text in comments:
                exist = api(c, "GET", f"/routes/{rid}/comments", users[ck][1]).json()
                if not any(cm["content"] == text for cm in exist):
                    api(c, "POST", f"/routes/{rid}/comments", users[ck][1],
                        json={"content": text})
            for cp in copiers:
                if ensure_copy(c, rid, users[cp][1], users[cp][0]):
                    made["copies"] += 1
        log(f"공개 코스 {len(PUB)}개 보장 (신규 {made['pub_routes']}, 복사 {made['copies']})")

        # ── 12. 공개 프로필 데모: 일부 run을 public으로 (수정 API 경유) ────
        section("12. 공개 프로필용 public run 승격 (PATCH /runs, 멱등)")
        # {유저키: 공개로 둘 run 목표 개수} — 개수 기반이라 실제 run 분포와
        # 무관하게 견고. GPS(has_track) 우선 승격해 카드 다양성 확보.
        PUBLIC_PLAN = {"test1": 4, "test2": 1, "demo1": 2, "demo2": 1, "demo4": 1}
        for key, want in PUBLIC_PLAN.items():
            uid, tok = users[key]
            runs = api(c, "GET", "/runs", tok, params={"limit": 50}).json()
            already = sum(1 for r in runs if r.get("visibility") == "public")
            need = want - already
            if need <= 0:
                continue  # 멱등: 이미 목표만큼 공개면 스킵
            # 승격 후보: private 아님 + 아직 public 아님. GPS 우선, 그다음 최신순.
            cand = [r for r in runs if r.get("visibility") == "followers"]
            cand.sort(key=lambda r: (not r.get("has_track"), r["ran_at"]), reverse=False)
            cand.sort(key=lambda r: not r.get("has_track"))  # has_track=True 먼저
            for r in cand[:need]:
                body = {"visibility": "public"}
                if not r.get("title"):
                    body["title"] = _title_for_hour(r["ran_at"])
                if api(c, "PATCH", f"/runs/{r['id']}", tok, json=body).status_code == 200:
                    made["public_runs"] += 1
        log(f"public 승격 {made['public_runs']}건 (수정 API 경유)")

        # ── 13. 지역 배정 러닝 (test1 한강로동 month_rank·test2 청라동) ────────
        section("13. 지역 배정 + month_rank (test1 한강로동 verified 3회 / test2 청라동)")
        def _insert_run_ex(uid, ran_at, km, **extra):
            pace = extra.pop("pace", random.randint(320, 420))
            body = {"user_id": uid, "ran_at": ran_at, "distance_km": km,
                    "duration_sec": round(km * pace), "avg_pace_sec_per_km": pace,
                    "visibility": extra.pop("visibility", "public")}
            body.update(extra)
            r = c.post(f"{_SB}/rest/v1/runs", headers={**_ADM, "Prefer": "return=minimal"}, json=body)
            if r.status_code not in (200, 201): die("run(ex) insert 실패", r.text)
        # 멱등: test1이 한강로동 러닝 이미 있으면 스킵
        t1_runs = api(c, "GET", "/runs", t1, params={"limit": 50}).json()
        if not any(r.get("area") == "한강로동" for r in t1_runs):
            now = datetime.now(timezone.utc)
            # month_rank = best_5k 노림: 거리 분산 + **최근(d=0)이 짧고 빠름**.
            # (days_ago, km, pace) — 8km느림·6.5km빠름·5km(최근)빠름. best_5k 환산에서
            # 최근 5km@320(t5k 1600)이 6.5km@305(t5k 1525)에만 뒤져 **rank 2**,
            # longest_distance는 최근 5km가 하위 → best_5k(동순위 우선순위상)로 선정.
            # 최근 run은 d=0(now)이라 §8 GPS run(now())보다도 나중 = "이번 기록".
            for d, km, pace in [(4, 8.0, 400), (2, 6.5, 305), (0, 5.0, 320)]:
                if d == 0:
                    ran_utc = datetime.now(timezone.utc).isoformat()   # §8 이후 = 최근
                else:
                    ran_utc = ((now - timedelta(days=d)).astimezone(_KST)
                               .replace(hour=6, minute=10, second=0, microsecond=0)
                               .astimezone(timezone.utc).isoformat())
                _insert_run_ex(uid1, ran_utc, km, area="한강로동", verification="verified", pace=pace)
            made["runs"] += 3
            log("  test1 한강로동 verified 3회(8·6.5·5km, 최근 5km 빠름) → month_rank best_5k")
        else:
            log("  test1 한강로동 러닝 이미 있음 — 스킵")
        t2_runs = api(c, "GET", "/runs", t2, params={"limit": 50}).json()
        if not any(r.get("area") == "청라동" for r in t2_runs):
            now = datetime.now(timezone.utc)
            for d, km in [(2, 5.0), (6, 8.0)]:
                ran = (now - timedelta(days=d)).astimezone(_KST).replace(hour=19, minute=0, second=0, microsecond=0)
                _insert_run_ex(uid2, ran.astimezone(timezone.utc).isoformat(), km,
                               area="청라동", verification="verified", visibility="followers")
            made["runs"] += 2
            log("  test2 청라동 개인런 2회")
        else:
            log("  test2 청라동 러닝 이미 있음 — 스킵")

        # ── 14. 크루 채팅 (한강 크루) + system 메시지 유입용 신규 공지 ────────
        section("14. 크루 채팅 — text 메시지 + 반응 + system(공지)")
        # 보존 크루라 기존 공지는 멱등 스킵 → system 훅 미발동. 신규 공지 1건으로
        # 공지→system 메시지 유입 데모(v1.5). 멱등: 제목 존재 시 스킵.
        SYS_ANN = "번개 러닝 ☕ 목요일 저녁 성수"
        existing_anns = {a["title"] for a in
                         api(c, "GET", f"/crews/{CREW}/announcements", t1, params={"limit": 50}).json()}
        if SYS_ANN not in existing_anns:
            r = api(c, "POST", f"/crews/{CREW}/announcements", t1, json={
                "title": SYS_ANN, "body": "목요일 19시 성수 뚝섬. 가볍게 5km + 커피 ☕",
                "place_name": "뚝섬유원지역 3번 출구", "place_lat": 37.5311, "place_lng": 127.0668})
            if r.status_code == 201:
                made["announcements"] += 1
                log("  신규 공지 1건 → 크루 채팅에 system 메시지 자동 유입")
        msgs = api(c, "GET", f"/crews/{CREW}/chat/messages", t1, params={"limit": 50}).json()
        if len([m for m in msgs if m["type"] == "text"]) < 3:
            m1 = api(c, "POST", f"/crews/{CREW}/chat/messages", t1,
                     json={"content": "이번 주 토요일 뚝섬 6시! 다들 참석 투표 부탁해요 🙌"}).json()
            api(c, "POST", f"/crews/{CREW}/chat/messages", users["demo1"][1],
                json={"content": "저 갑니다! 10km 그룹이요"})
            api(c, "POST", f"/crews/{CREW}/chat/messages", users["demo2"][1],
                json={"content": "5km 그룹 합류할게요~"})
            # 반응(데모1이 크루장 메시지에 🔥)
            api(c, "POST", f"/crews/{CREW}/chat/messages/{m1['id']}/react",
                users["demo1"][1], json={"emoji": "🔥"})
            log("  채팅 text 3 + 반응 1 (공지 생성 시 system 메시지는 §3에서 자동)")
        else:
            log("  채팅 메시지 이미 있음 — 스킵")

        # ── 15. 정기런 세션 태깅 (한강 크루, 성수 demos) ────────────────────
        section("15. 정기런 세션 — demo2·demo3 crew_id 태그 (같은 날 → N명 참여)")
        tagged = c.get(f"{_SB}/rest/v1/runs", headers=_ADM,
                       params={"crew_id": f"eq.{CREW}", "select": "id", "limit": 1}).json()
        if not tagged:
            today_kst = datetime.now(_KST).date().isoformat()
            skey = f"c:{CREW}:{today_kst}"
            ran = datetime.now(_KST).replace(hour=6, minute=20, second=0, microsecond=0)
            for key in ("demo2", "demo3"):
                _insert_run_ex(users[key][0], ran.astimezone(timezone.utc).isoformat(), 8.0,
                               area="성수동", verification="verified",
                               crew_id=CREW, session_key=skey, visibility="public")
            made["runs"] += 2
            log(f"  정기런 세션 태깅 2인(demo2·demo3, 성수동) → 크루 피드 'N명 참여' 배지")
        else:
            log("  정기런 태그 run 이미 있음 — 스킵")

        # ── 16. 세부 권한 (demo1을 운영진 승격 — 기본 announcements·challenges) ──
        section("16. 세부 권한 — demo1 admin 승격")
        members = api(c, "GET", f"/crews/{CREW}/members", t1).json()
        demo1_role = next((m["role"] for m in members if m["user_id"] == users["demo1"][0]), None)
        if demo1_role == "member":
            r = api(c, "PATCH", f"/crews/{CREW}/members/{users['demo1'][0]}/role", t1,
                    json={"role": "admin"})
            log("  demo1 → admin (기본 권한: announcements·challenges ON)" if r.status_code == 200
                else f"  demo1 승격 실패 {r.status_code}")
        else:
            log(f"  demo1 이미 {demo1_role} — 스킵")

        # ── 17. 차단 관계 (demo4 ↔ demo5) ─────────────────────────────────
        section("17. 차단 — demo4가 demo5 차단 (양방향 필터 데모)")
        r = api(c, "POST", f"/users/{users['demo5'][0]}/block", users["demo4"][1])
        log("  demo4 → demo5 차단(멱등)" if r.status_code == 204 else f"  차단 {r.status_code}")

        # ── 18. 프로필 샘플 (비공개=요청제) ────────────────────────────────
        # 승인제 통합(FOLLOW_CHANGES_DESIGN.md Part B): visibility='private'이면
        # 무조건 팔로우 요청제. demo2·demo3 둘 다 비공개로 요청제 데모.
        section("18. 프로필 샘플 — demo2·demo3 비공개(팔로우 요청제)")
        api(c, "PATCH", "/me/profile", users["demo2"][1], json={"visibility": "private"})
        api(c, "PATCH", "/me/profile", users["demo3"][1], json={"visibility": "private"})
        log("  demo2·demo3 visibility=private (비공개 → 팔로우 요청제)")

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
        # 홈 '전체' 탭 — 공개 코스 피드 (인기순 / 최신순)
        pop = api(c, "GET", "/routes/public", t1, params={"sort": "popular", "limit": 20}).json()
        log(f"전체 탭(GET /routes/public): 공개 코스 {len(pop)}개")
        log("  [인기순 top5 — 좋아요·댓글·복사]")
        for r in pop[:5]:
            log(f"  · {r['summary']} (장 {r.get('owner_nickname')}) — "
                f"♥{r['like_count']} 💬{r['comment_count']} ⟳{r['copy_count']}"
                + (" [내 코스]" if r.get("is_mine") else ""))
        new = api(c, "GET", "/routes/public", t1, params={"sort": "newest", "limit": 5}).json()
        log(f"  [최신순 top3] " + " / ".join(r["summary"] for r in new[:3]))
        mine_pub = [r for r in pop if r.get("is_mine")]
        log(f"  → test1 소유 공개 코스 {len(mine_pub)}개, 받은 좋아요 "
            f"{sum(r['like_count'] for r in mine_pub)}개")
        reqs = api(c, "GET", f"/crews/{CREW}/join-requests", t1).json()
        log(f"가입 신청 대기: {len(reqs)}건" +
            (f" ({reqs[0]['nickname']})" if reqs else ""))
        acts = api(c, "GET", "/feed/activities", t1, params={"limit": 8}).json()
        log(f"활동 피드: {len(acts)}건")
        for a in acts[:5]:
            who = "나" if a["is_mine"] else a["nickname"]
            log(f"  · {who} {a['distance_km']}km — kudos {a['kudos_count']}"
                f"{' (내가 누름)' if a['my_kudos'] else ''}")
        mine_with_kudos = [a for a in acts if a["is_mine"] and a["kudos_count"] > 0]
        log(f"  → 내 run 중 kudos 받은 것: {len(mine_with_kudos)}건")

        # GPS 검증 run — 활동 피드에 뜨는 run 중 verified·splits 확인 (상세 조회)
        my_runs = api(c, "GET", "/runs", t1, params={"limit": 50}).json()
        gps_runs = [r for r in my_runs if r.get("has_track")]
        log(f"GPS 검증 run: {len(gps_runs)}건")
        for r in gps_runs[:3]:
            splits = r.get("splits") or []
            log(f"  · {r['distance_km']}km verification={r['verification']} "
                f"splits={len(splits)}랩" +
                (f" (1랩 {splits[0]['sec']}초, 고도 {splits[0].get('elev_gain_m')}m)"
                 if splits else ""))
        if gps_runs:
            tr = api(c, "GET", f"/runs/{gps_runs[0]['id']}/track", t1).json()
            log(f"  → track: polyline {len(tr['polyline'])}pt, 서버거리 "
                f"{tr['server_distance_km']}km (원본 {tr['point_count_raw']}→"
                f"필터 {tr['point_count_kept']}pt), 총고도 {tr.get('elev_gain_m')}m")
        # 크루 피드에도 verified run이 있는지 (demo1의 GPS run)
        cfeed = api(c, "GET", f"/crews/{CREW}/runs", t1, params={"limit": 20}).json()
        log(f"크루 피드 {len(cfeed)}건 (프론트가 run 상세로 verification·splits 조회)")

        # 프리미엄 콘텐츠 확인
        prof = api(c, "GET", "/me/profile", t1).json()
        log(f"신체정보 (본인만): birth {prof.get('birth_year')} · "
            f"{prof.get('weight_kg')}kg · {prof.get('height_cm')}cm · {prof.get('gender')}")
        cs = api(c, "POST", f"/routes/{r1}/coach-script", t1).json()
        log(f"코치 스크립트 (코스 r1): cues {len(cs['cues'])}개 · "
            f"start='{next((q['text'] for q in cs['cues'] if q['trigger']=='start'), '')[:34]}…'")
        ins = api(c, "GET", "/me/insights/monthly", t1, params={"year": 2026, "month": 6}).json()
        if ins.get("ai"):
            log(f"월간 인사이트 2026-06: {ins['stats']['run_count']}회 "
                f"{ins['stats']['total_distance_km']}km · plan {len(ins['ai']['plan'])}슬롯 · "
                f"coaching '{ins['ai']['coaching'][:40]}…'")
        else:
            log("월간 인사이트 2026-06: ai=null (해당 월 test1 run 없음 — run 시딩 날짜 확인)")

        # 둘러보기 — test1이 가입 안 한 크루 (프론트 둘러보기 탭)
        browse = api(c, "GET", "/crews", t1).json()
        my_crew_ids = {cr["id"] for cr in api(c, "GET", "/crews/mine", t1).json()}
        not_joined = [cr for cr in browse if cr["id"] not in my_crew_ids]
        log(f"둘러보기(GET /crews): 전체 {len(browse)}개 중 test1 미가입 "
            f"{len(not_joined)}개")
        for cr in sorted(not_joined, key=lambda x: x["name"])[:8]:
            vis = "공개" if cr["is_public"] else "비공개"
            log(f"  · {cr['name']} — {cr.get('area')}/{cr['level']}/"
                f"{vis}·{cr['join_policy']} · 멤버 {cr['member_count']}명 "
                f"(장 {cr.get('owner_nickname')})")
        # 검색도 동작 확인
        sr = api(c, "GET", "/crews/search", t1, params={"q": "한강"}).json()
        log(f"크루 검색 '한강': {len(sr)}건")
        # 당근식 둘러보기 — 성수동 기준 가까운 순 + distance_km + 태그
        near = api(c, "GET", "/crews", t1,
                   params={"lat": 37.5445, "lng": 127.0561, "include_full": "false"}).json()
        log(f"둘러보기(거리순, 성수동 기준): {len(near)}개")
        for cr in near[:6]:
            dk = cr.get("distance_km")
            log(f"  · {cr['name']} — {cr.get('sigungu')} "
                f"{(str(dk)+'km') if dk is not None else '거리?'} "
                f"태그{cr.get('tags')} 멤버 {cr['member_count']}")
        # 행정구역 필터
        seongdong = api(c, "GET", "/crews", t1, params={"sigungu": "성동구"}).json()
        log(f"성동구 필터: {len(seongdong)}개 ({', '.join(x['name'] for x in seongdong)})")

        # 공개 프로필 — 비팔로워(demo4, test1 미팔로우) 시점: public run만 노출
        uid1 = users["test1"][0]
        nf_tok = users["demo4"][1]  # demo4는 test1을 팔로우하지 않음
        prof = api(c, "GET", f"/users/{uid1}/profile", nf_tok).json()
        pub_runs = api(c, "GET", f"/users/{uid1}/runs", nf_tok).json()
        vis = {x.get("visibility") for x in pub_runs}
        log(f"공개 프로필(test1) — 비팔로워 시점: 게시 러닝 {len(pub_runs)}개, "
            f"public_run_count={prof['public_run_count']} "
            f"(일치: {len(pub_runs) == prof['public_run_count']})")
        log(f"  노출 run: {[(x.get('title'), x['distance_km']) for x in pub_runs]}")
        log(f"  비팔로워엔 visibility null 확인: {vis in ({None}, set())}")

        print("\n완료. 프론트에서 test1@freshrun.com / (공유된 비번)으로 로그인해 확인하세요.")


if __name__ == "__main__":
    main()
