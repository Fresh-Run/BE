"""
Integration test: 프로필 신체 정보 4종 + 아바타 업로드
1) 신체 정보 왕복·부분 갱신·422 (본인 전용)
2) 프라이버시 전수 — 다른 유저가 보는 7개 경로에서 4종 필드 부재 assert
3) 아바타: upload-url 발급 → 직접 PUT → public_url → avatar_url 갱신 + MIME 거부
Run: python tests/test_profile_body_integration.py
"""
from __future__ import annotations

import os
import sys
import time
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
            if line.startswith("SUPABASE_KEY="):
                anon = line.split("=", 1)[1]
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                svc = line.split("=", 1)[1]
    return anon, svc


_ANON, _SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}

BODY_KEYS = {"birth_year", "weight_kg", "height_cm", "gender"}

# 1x1 투명 PNG (67 bytes)
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea7568c4c0000000049454e44ae426082"
)


def ok(m):
    print(f"  ✓ {m}")


def fail(m, d=""):
    print(f"  ✗ {m}" + (f": {d}" if d else ""))
    sys.exit(1)


def step(t):
    print(f"\n[{t}]")


def sb_user(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/admin/users", headers=_ADM,
               json={"email": email, "password": pw, "email_confirm": True})
    if r.status_code not in (200, 201):
        fail("create user", r.text[:200])
    return r.json()["id"]


def sb_login(c, email, pw):
    r = c.post(f"{_SB}/auth/v1/token?grant_type=password",
               headers={"apikey": _ANON, "Content-Type": "application/json"},
               json={"email": email, "password": pw})
    if r.status_code != 200:
        fail("login", r.text[:200])
    return r.json()["access_token"]


def sb_del_user(c, uid):
    c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)


def sb_del_in(c, table, col, vals):
    if not vals:
        return
    c.delete(f"{_SB}/rest/v1/{table}",
             headers={**_ADM, "Prefer": "return=minimal"},
             params={col: f"in.({','.join(vals)})"})


def api(c, method, path, tok, **kw):
    return c.request(method, f"{BASE}{path}",
                     headers={"Authorization": f"Bearer {tok}"}, **kw)


def assert_no_body_keys(items, label):
    """응답 아이템(dict 또는 dict 리스트)에 신체 정보 키가 없어야 한다."""
    if isinstance(items, dict):
        items = [items]
    for it in items:
        leaked = BODY_KEYS & set(it.keys())
        assert not leaked, f"{label}에 신체 정보 노출: {leaked}"


def run():
    ts = int(time.time())
    pw = "TestPass123!"
    emails = [f"pb2-u{i}-{ts}@t.l" for i in range(1, 3)]
    uids: list[str] = []
    crew_ids: list[str] = []
    avatar_uploaded = False

    with httpx.Client(timeout=30) as c:
        try:
            step("1. 유저 2명 + 프로필 (둘 다 신체 정보 저장)")
            toks = []
            for i, e in enumerate(emails, start=1):
                uids.append(sb_user(c, e, pw))
                toks.append(sb_login(c, e, pw))
                r = api(c, "PATCH", "/me/profile", toks[-1], json={
                    "nickname": f"신체u{i}-{ts % 100000}",
                    "birth_year": 1995 + i, "weight_kg": 60.0 + i,
                    "height_cm": 168.0 + i, "gender": "female" if i == 1 else "male"})
                assert r.status_code == 200, r.text[:300]
            uid1, uid2 = uids
            tok1, tok2 = toks
            ok("생성 + 신체 정보 저장")

            step("2. 신체 정보 왕복 + 부분 갱신")
            d = api(c, "GET", "/me/profile", tok1).json()
            assert (d["birth_year"], d["weight_kg"], d["height_cm"], d["gender"]) == \
                (1996, 61.0, 169.0, "female"), d
            # 체중만 갱신 → 나머지 유지
            r = api(c, "PATCH", "/me/profile", tok1,
                    json={"nickname": f"신체u1-{ts % 100000}", "weight_kg": 63.5})
            d = r.json()
            assert d["weight_kg"] == 63.5 and d["birth_year"] == 1996 and d["gender"] == "female"
            ok("PATCH→GET 왕복 ✓ 부분 갱신 유지 ✓")

            step("3. 범위 밖 422")
            for bad in ({"birth_year": 1900}, {"birth_year": 2030},
                        {"weight_kg": 10}, {"weight_kg": 301},
                        {"height_cm": 99}, {"height_cm": 251},
                        {"gender": "alien"}):
                r = api(c, "PATCH", "/me/profile", tok1,
                        json={"nickname": f"신체u1-{ts % 100000}", **bad})
                assert r.status_code == 422, f"{bad} → 422 기대, got {r.status_code}"
            ok("경계 밖 7종 전부 422 ✓")

            step("4. 프라이버시 전수 — 타 유저 시점 7개 경로")
            # 준비: 팔로우(u1→u2), 크루(u1 owner + u2), run+kudos, 공지+RSVP
            assert api(c, "POST", f"/users/{uid2}/follow", tok1).status_code in (200, 204)
            r = api(c, "POST", "/crews", tok1, json={"name": f"신체크루-{ts}"})
            crew_id = r.json()["id"]
            crew_ids.append(crew_id)
            assert api(c, "POST", f"/crews/{crew_id}/join", tok2).status_code == 200
            r = api(c, "POST", "/runs", tok1, json={"distance_km": 5.0, "duration_sec": 1500})
            run_id = r.json()["id"]
            assert api(c, "POST", f"/runs/{run_id}/kudos", tok2).status_code == 204
            now = datetime.now(timezone.utc)
            r = api(c, "POST", f"/crews/{crew_id}/announcements", tok1, json={
                "title": "정기런", "body": "8시",
                "run_at": (now + timedelta(days=2)).isoformat(),
                "rsvp_closes_at": (now + timedelta(days=1)).isoformat()})
            ann_id = r.json()["id"]
            assert api(c, "PUT", f"/crews/{crew_id}/announcements/{ann_id}/rsvp",
                       tok1, json={"status": "going"}).status_code == 204

            # ① 공개 프로필 — 실제 라우트는 /users/{id}/profile (과거 버그: /users/{id}는
            #    404라 assert가 공허 통과했음). 응답이 진짜 프로필인지 먼저 확정.
            r = api(c, "GET", f"/users/{uid1}/profile", tok2)
            assert r.status_code == 200, r.text[:200]
            d = r.json()
            assert d.get("user_id") == uid1 and d.get("nickname"), \
                f"공개 프로필 응답이 비어있음(공허 assert 방지): {d}"
            assert_no_body_keys(d, "공개 프로필")
            # ② 팔로워 목록 (u2의 팔로워 = u1)
            d = api(c, "GET", f"/users/{uid2}/followers", tok2).json()
            assert any(x["user_id"] == uid1 for x in d)
            assert_no_body_keys(d, "팔로워 목록")
            # ③ 크루 로스터
            d = api(c, "GET", f"/crews/{crew_id}/members", tok2).json()
            assert_no_body_keys(d, "크루 로스터")
            # ④ kudos 목록
            d = api(c, "GET", f"/runs/{run_id}/kudos", tok1).json()
            assert_no_body_keys(d, "kudos 목록")
            # ⑤ RSVP 명단 (공지 상세 going_members)
            d = api(c, "GET", f"/crews/{crew_id}/announcements/{ann_id}", tok2).json()
            assert d["going_members"], "u1이 going이어야 함"
            assert_no_body_keys(d["going_members"], "RSVP 명단")
            # ⑥ 활동 피드 (u2는 안 팔로우 — u1이 u2를 팔로우했으니 u1 피드에서 확인)
            d = api(c, "GET", "/feed/activities", tok1).json()
            assert_no_body_keys(d, "활동 피드")
            # ⑦ 크루 러닝 피드
            d = api(c, "GET", f"/crews/{crew_id}/runs", tok2).json()
            assert d and any(x["user_id"] == uid1 for x in d)
            assert_no_body_keys(d, "크루 러닝 피드")
            ok("공개프로필·팔로워·로스터·kudos·RSVP·활동피드·크루피드 — 4종 필드 부재 ✓")

            step("5. 아바타: 발급 → PUT → public_url → avatar_url 갱신")
            r = api(c, "POST", "/me/avatar/upload-url", tok1)
            assert r.status_code == 200, r.text[:300]
            u = r.json()
            assert u["max_bytes"] == 5 * 1024 * 1024 and "image/png" in u["allowed_types"]
            up = c.put(u["upload_url"], content=PNG_1PX,
                       headers={"Content-Type": "image/png"})
            assert up.status_code == 200, f"업로드 실패: {up.status_code} {up.text[:200]}"
            avatar_uploaded = True
            pub = c.get(u["public_url"])
            assert pub.status_code == 200 and pub.content == PNG_1PX, "공개 읽기"
            avatar_url = f"{u['public_url']}?v={ts}"
            r = api(c, "PATCH", "/me/profile", tok1,
                    json={"nickname": f"신체u1-{ts % 100000}", "avatar_url": avatar_url})
            assert r.json()["avatar_url"] == avatar_url
            ok("발급 ✓ 직접 업로드 ✓ 공개 읽기 ✓ avatar_url 갱신 ✓")

            step("6. 아바타 제한: MIME 거부 + 재발급 덮어쓰기")
            r = api(c, "POST", "/me/avatar/upload-url", tok1)  # 재발급 (기존 삭제됨)
            u2_ = r.json()
            bad = c.put(u2_["upload_url"], content=b"not an image",
                        headers={"Content-Type": "text/plain"})
            assert bad.status_code >= 400, f"text/plain은 거부돼야 함, got {bad.status_code}"
            up = c.put(u2_["upload_url"], content=PNG_1PX,
                       headers={"Content-Type": "image/png"})
            assert up.status_code == 200, "재업로드(덮어쓰기 경로) 성공해야 함"
            ok("허용 외 MIME 거부 ✓ 고정 경로 재업로드 ✓")

            step("6b. 아바타 삭제 시맨틱 — 명시 null / 생략 유지 / \"\" 422 / 멱등")
            nick = f"신체u1-{ts % 100000}"
            r = api(c, "PATCH", "/me/profile", tok1, json={"nickname": nick})
            assert r.json()["avatar_url"] == avatar_url, "필드 생략은 유지"
            r = api(c, "PATCH", "/me/profile", tok1,
                    json={"nickname": nick, "avatar_url": ""})
            assert r.status_code == 422, f'""는 422, got {r.status_code}'
            r = api(c, "PATCH", "/me/profile", tok1,
                    json={"nickname": nick, "avatar_url": None})
            assert r.status_code == 200 and r.json()["avatar_url"] is None, r.text[:200]
            time.sleep(1)
            assert c.get(u["public_url"]).status_code != 200, "Storage 파일도 소멸해야"
            r = api(c, "PATCH", "/me/profile", tok1,
                    json={"nickname": nick, "avatar_url": None})
            assert r.status_code == 200 and r.json()["avatar_url"] is None, "멱등"
            avatar_uploaded = False  # 이미 정리됨
            ok('명시 null 삭제+Storage 소멸 ✓ 생략 유지 ✓ "" 422 ✓ 멱등 ✓')

            step("7. 기존 프로필 회귀 (닉네임 중복 409)")
            r = api(c, "PATCH", "/me/profile", tok2,
                    json={"nickname": f"신체u1-{ts % 100000}"})
            assert r.status_code == 409, f"중복 닉네임 409, got {r.status_code}"
            ok("409 ✓ (기존 동작 유지)")

            print("\n" + "=" * 50)
            print("  ALL TESTS PASSED")
            print("=" * 50)
        finally:
            step("Cleanup")
            if avatar_uploaded:
                c.delete(f"{_SB}/storage/v1/object/avatars/{uids[0]}", headers=_ADM)
            sb_del_in(c, "runs", "user_id", uids)
            sb_del_in(c, "crews", "id", crew_ids)
            sb_del_in(c, "follows", "follower_id", uids)
            sb_del_in(c, "notifications", "user_id", uids)
            sb_del_in(c, "notifications", "actor_id", uids)
            sb_del_in(c, "profiles", "user_id", uids)
            for uid in uids:
                sb_del_user(c, uid)
            ok("storage 객체·runs·crews·profiles·auth users 삭제")


if __name__ == "__main__":
    run()
