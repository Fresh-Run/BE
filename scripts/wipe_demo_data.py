"""데모 데이터 초기화 — demo1~5만 삭제(파괴적). test1·test2·미지 계정 절대 미접촉.

시드 리프레시 1단계. crews.owner_id는 CASCADE라(2026-07-08 실증) demo auth.user
삭제 한 방에 소유 크루·러닝·팔로우·크루멤버·알림·채팅 전부 연쇄 소멸. 앱
delete_account은 데모 이메일을 거부(시드 보호)하므로 **admin API로 직접 삭제**.

안전 장치:
  ① dry-run 기본 — `--yes` 없으면 대상만 출력하고 아무것도 안 지운다.
  ② 대상 = demo1~5@freshrun.com **정확히 5개 이메일**로 하드코딩. 그 외 절대 안 봄.
  ③ self-assert — 대상 uid가 test1·test2 uid와 겹치지 않음 + 전 auth.users에서
     데모 5개 외 계정이 대상에 없음을 검증(하나라도 어긋나면 abort).
  ④ 보존 크루(test 소유 등)에 남은 demo-작성 공지는 명시 삭제(author_id set-null
     익명 잔재 방지) — demo 소유 크루 공지는 cascade로 자동 소멸.

실행:  python scripts/wipe_demo_data.py          # dry-run (대상 출력만)
       python scripts/wipe_demo_data.py --yes    # 실제 삭제
"""
from __future__ import annotations

import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core.account_kinds import kinds_with  # noqa: E402  (순수 상수 모듈 — 부작용 0)

_SB = "https://jlmmqnpddkokyintlawd.supabase.co"

# ⚠️ 삭제 대상은 이 5개 이메일로 고정. 절대 확장 금지.
_DEMO_EMAILS = frozenset(f"demo{i}@freshrun.com" for i in range(1, 6))
# 절대 삭제 불가 — self-assert 대조용.
_PROTECTED_EMAILS = frozenset({"test1@freshrun.com", "test2@freshrun.com"})


def _svc_key() -> str:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    with open(env) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                return line.split("=", 1)[1]
    sys.exit("SUPABASE_SERVICE_ROLE_KEY 없음")


_ADM = {"apikey": _svc_key(), "Authorization": f"Bearer {_svc_key()}",
        "Content-Type": "application/json"}


def _all_auth_users(c) -> list[dict]:
    users, page = [], 1
    while True:
        b = c.get(f"{_SB}/auth/v1/admin/users", headers=_ADM,
                  params={"page": page, "per_page": 200}).json().get("users", [])
        if not b:
            break
        users += b
        if len(b) < 200:
            break
        page += 1
    return users


def _count(c, table, col, uid) -> int:
    r = c.get(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "count=exact"},
              params={col: f"eq.{uid}", "select": col, "limit": 1})
    return int(r.headers.get("content-range", "?/0").split("/")[-1])


def main() -> None:
    execute = "--yes" in sys.argv
    c = httpx.Client(timeout=30)

    users = _all_auth_users(c)
    by_email = {u.get("email"): u["id"] for u in users if u.get("email")}

    # dual-read(P2, 이관): profiles.account_kind → uid별 kind 조회.
    # ⚠️ 파괴 스크립트 원칙: **PROTECTION만 union으로 확장**한다. 삭제 target은 이메일
    #    그대로(확장 금지 — target을 넓히면 "삭제 과다"라 unsafe 방향). kind는 ①보호 집합
    #    확장 ②disjoint assert 강화에만 쓴다. 이메일 매칭은 P3까지 유지(제거 아님).
    profs = c.get(f"{_SB}/rest/v1/profiles", headers=_ADM,
                  params={"select": "user_id,account_kind", "limit": "5000"}).json()
    uid2kind = {p["user_id"]: p.get("account_kind") for p in profs}
    # wipe_protect 보유 kind(owner/internal/qa)의 uid — 절대 삭제 금지 집합.
    kind_protected_uids = {uid for uid, k in uid2kind.items()
                           if k in kinds_with("wipe_protect")}

    # 대상·보호 uid 해석
    target = {e: by_email[e] for e in _DEMO_EMAILS if e in by_email}   # 이메일 그대로(확장 금지)
    protected = {e: by_email[e] for e in _PROTECTED_EMAILS if e in by_email}
    target_uids = set(target.values())
    protected_uids = set(protected.values()) | kind_protected_uids     # ← 보호만 union(과보호=안전)

    # ── self-assert (하나라도 어긋나면 즉시 중단) ──────────────────────────
    # 이제 protected_uids가 kind 보호(owner/internal/qa)까지 포함 → 이 disjoint가 더 강함.
    assert target_uids.isdisjoint(protected_uids), \
        "FATAL: 삭제 대상 uid가 보호 계정(test1/test2 또는 owner/internal/qa kind)과 겹침 — 중단"
    demo_only = {by_email[e] for e in _DEMO_EMAILS if e in by_email}
    assert target_uids == demo_only, "FATAL: 대상이 데모 5개 외를 포함 — 중단"
    # 대상 이메일이 정확히 데모 패턴인지 재확인
    for e in target:
        assert e in _DEMO_EMAILS, f"FATAL: 비데모 이메일 {e} — 중단"
    # dual-read 강화: 삭제 대상 uid는 owner/internal/qa kind를 절대 안 가진다(과삭제 봉쇄).
    # demo 이메일이 실수로 보호 kind로 태깅됐으면 여기서 즉시 abort.
    for uid in target_uids:
        k = uid2kind.get(uid)
        assert k in (None, "demo"), \
            f"FATAL: 삭제 대상 {uid} 의 account_kind={k} (demo/null 아님 — 보호 kind 오염) 중단"

    print("=" * 60)
    print(f"데모 데이터 초기화 {'(실제 삭제)' if execute else '(DRY-RUN — 아무것도 안 지움)'}")
    print("=" * 60)
    print(f"\n총 auth.users {len(users)}명 · 보호 계정 {len(protected_uids)}명"
          f"(test1/test2 이메일 ∪ owner/internal/qa kind {len(kind_protected_uids)}명) "
          f"· 데모 외 {len(users) - len(target_uids) - len(protected_uids)}명(미접촉)")
    # requirement 5: 삭제 대상에 보호 계정 0 을 명시(assert가 이미 보장, 여기선 눈으로 확인).
    print(f"  삭제 대상 ∩ 보호 계정 = {len(target_uids & protected_uids)}명 (0이어야 정상)")

    if not target:
        print("\n삭제할 데모 계정 없음(이미 정리됨). 종료.")
        return

    print(f"\n▼ 삭제 대상 {len(target)}명 (cascade로 소유 크루·러닝·크루멤버·알림 등 연쇄 소멸):")
    for e, uid in sorted(target.items()):
        crews = _count(c, "crews", "owner_id", uid)
        runs = _count(c, "runs", "user_id", uid)
        cm = _count(c, "crew_members", "user_id", uid)
        print(f"  {e:22} {uid}  (소유크루 {crews}·러닝 {runs}·크루멤버 {cm})")

    # 보존 크루에 남는 demo-작성 공지 — 명시 삭제 대상(demo 소유 크루 공지는 cascade)
    demo_crew_ids = set()
    for uid in target_uids:
        r = c.get(f"{_SB}/rest/v1/crews", headers=_ADM,
                  params={"owner_id": f"eq.{uid}", "select": "id"})
        demo_crew_ids |= {row["id"] for row in r.json()}
    orphan_anns = []
    for uid in target_uids:
        r = c.get(f"{_SB}/rest/v1/crew_announcements", headers=_ADM,
                  params={"author_id": f"eq.{uid}", "select": "id,crew_id"})
        orphan_anns += [a for a in r.json() if a["crew_id"] not in demo_crew_ids]
    print(f"\n▼ 보존 크루의 demo-작성 공지 {len(orphan_anns)}건 (명시 삭제 — 익명 잔재 방지)")

    if not execute:
        print("\n[DRY-RUN] 실제 삭제하려면:  python scripts/wipe_demo_data.py --yes")
        return

    # ── 실제 삭제 ────────────────────────────────────────────────────────
    print("\n실행 중…")
    for a in orphan_anns:
        c.delete(f"{_SB}/rest/v1/crew_announcements", headers=_ADM,
                 params={"id": f"eq.{a['id']}"})
    print(f"  보존 크루 demo 공지 {len(orphan_anns)}건 삭제")
    for e, uid in sorted(target.items()):
        r = c.delete(f"{_SB}/auth/v1/admin/users/{uid}", headers=_ADM)
        assert r.status_code in (200, 204), f"{e} 삭제 실패: {r.text[:200]}"
        print(f"  삭제: {e} ({uid}) — cascade 완료")

    # ── 사후 검증 ────────────────────────────────────────────────────────
    after = {u.get("email") for u in _all_auth_users(c)}
    assert not (_DEMO_EMAILS & after), "FATAL: 데모 계정 잔존 — 확인 필요"
    assert _PROTECTED_EMAILS <= after, "FATAL: 보호 계정(test1/test2) 소실 — 즉시 확인!"
    print(f"\n✓ 완료. 데모 5명 삭제됨 · test1/test2 보존 확인 · 데모 외 미접촉.")
    print("  다음: python scripts/seed_demo_data.py 로 재생성.")


# ── test1/test2 데이터 재정리 (별도 모드 — demo 삭제와 독립) ─────────────────
# 삭제만 하는 테이블 화이트리스트. crews·crew_members·crew_messages·blocks·
# crew_announcements는 절대 포함 안 됨(구조적 self-assert).
_RESET_DELETE_TABLES = frozenset({
    "runs", "run_kudos", "route_comments", "run_comments", "follows", "monthly_insights"})
_RESET_PROTECT_TABLES = frozenset({
    "crews", "crew_members", "crew_messages", "blocks", "crew_announcements"})
_RESET_EMAILS = frozenset({"test1@freshrun.com", "test2@freshrun.com"})


def _cnt(c, table, q) -> int:
    r = c.get(f"{_SB}/rest/v1/{table}", headers={**_ADM, "Prefer": "count=exact"},
              params={**q, "select": "*", "limit": 1})
    return int(r.headers.get("content-range", "?/0").split("/")[-1])


def reset_test_data(c, execute: bool) -> None:
    """test1·test2의 **본인 러닝·소셜·팔로우만** 삭제 — 계정·크루·크루멤버십·
    crew_messages·blocks·route_generations·body_info는 무접촉. 재시딩 §13이 유일한
    지역 러닝이 되게 정리(month_rank 정합)."""
    # 구조적 self-assert: 삭제 테이블에 보호 테이블 부재
    assert _RESET_DELETE_TABLES.isdisjoint(_RESET_PROTECT_TABLES), "FATAL: 삭제/보호 테이블 겹침"

    users = _all_auth_users(c)
    by_email = {u.get("email"): u["id"] for u in users if u.get("email")}
    # dual-read(P2, 이관) 판단: 이 리셋은 **파괴 target**(test1/2 러닝 삭제)이라 kind로
    # 확장하지 않는다(target 확장 = 삭제 과다 = unsafe 방향, wipe 원칙). target은 이메일
    # 정확 2개로 고정 유지. 보호는 이미 테이블 화이트리스트(_RESET_PROTECT_TABLES)+계정
    # 무접촉+before/after 불변 assert가 담당 — kind union 불요. (union은 protection에만.)
    uids = {e: by_email[e] for e in _RESET_EMAILS if e in by_email}
    assert set(uids) == _RESET_EMAILS, "FATAL: test1/test2 uid 해석 실패"
    uid_list = list(uids.values())
    in_uids = f"({','.join(uid_list)})"

    # 보존 대상 BEFORE 스냅샷 (사후 불변 검증용)
    before = {
        "crews": sum(_cnt(c, "crews", {"owner_id": f"eq.{u}"}) for u in uid_list),
        "crew_members": sum(_cnt(c, "crew_members", {"user_id": f"eq.{u}"}) for u in uid_list),
        "crew_messages": sum(_cnt(c, "crew_messages", {"sender_id": f"eq.{u}"}) for u in uid_list),
        "blocks": _cnt(c, "blocks", {}),
        "route_generations": sum(_cnt(c, "route_generations", {"user_id": f"eq.{u}"}) for u in uid_list),
    }
    print("=" * 60)
    print(f"test1/test2 데이터 재정리 {'(실제 삭제)' if execute else '(DRY-RUN)'}")
    print("=" * 60)
    print(f"\n대상: {sorted(uids)}")
    print("\n▼ 삭제 대상 (본인 러닝·소셜·팔로우):")
    print(f"  runs: {sum(_cnt(c,'runs',{'user_id':f'eq.{u}'}) for u in uid_list)} (+cascade run_tracks·남의 kudos/댓글·photos)")
    print(f"  준 run_kudos: {_cnt(c,'run_kudos',{'user_id':f'in.{in_uids}'})}")
    print(f"  준 route_comments: {_cnt(c,'route_comments',{'user_id':f'in.{in_uids}'})} · run_comments: {_cnt(c,'run_comments',{'user_id':f'in.{in_uids}'})}")
    print(f"  follows(양방향): follower {_cnt(c,'follows',{'follower_id':f'in.{in_uids}'})} + following {_cnt(c,'follows',{'following_id':f'in.{in_uids}'})}")
    print(f"  monthly_insights: {_cnt(c,'monthly_insights',{'user_id':f'in.{in_uids}'})}")
    print(f"\n▼ 보존(무접촉): 계정·소유크루 {before['crews']}·크루멤버십 {before['crew_members']}·"
          f"crew_messages {before['crew_messages']}·blocks {before['blocks']}·route_generations {before['route_generations']}·body_info·coach")

    if not execute:
        print("\n[DRY-RUN] 실제 삭제:  python scripts/wipe_demo_data.py --reset-test-data --yes")
        return

    print("\n실행 중…")
    def d(table, params):
        assert table in _RESET_DELETE_TABLES, f"FATAL: 허용 안 된 테이블 삭제 시도 {table}"
        c.delete(f"{_SB}/rest/v1/{table}", headers=_ADM, params=params)
    d("run_kudos", {"user_id": f"in.{in_uids}"})          # 준 kudos(남의 run)
    d("route_comments", {"user_id": f"in.{in_uids}"})
    d("run_comments", {"user_id": f"in.{in_uids}"})
    d("follows", {"follower_id": f"in.{in_uids}"})        # 양방향
    d("follows", {"following_id": f"in.{in_uids}"})
    d("monthly_insights", {"user_id": f"in.{in_uids}"})
    d("runs", {"user_id": f"in.{in_uids}"})               # 마지막 — cascade 파생
    print("  삭제 완료")

    # 사후 검증: 삭제 대상 0 + 보존 대상 불변
    after = {
        "crews": sum(_cnt(c, "crews", {"owner_id": f"eq.{u}"}) for u in uid_list),
        "crew_members": sum(_cnt(c, "crew_members", {"user_id": f"eq.{u}"}) for u in uid_list),
        "crew_messages": sum(_cnt(c, "crew_messages", {"sender_id": f"eq.{u}"}) for u in uid_list),
        "blocks": _cnt(c, "blocks", {}),
        "route_generations": sum(_cnt(c, "route_generations", {"user_id": f"eq.{u}"}) for u in uid_list),
    }
    assert before == after, f"FATAL: 보존 데이터 변동! before={before} after={after}"
    remain = sum(_cnt(c, "runs", {"user_id": f"eq.{u}"}) for u in uid_list)
    assert remain == 0, f"FATAL: test1/test2 run 잔존 {remain}"
    alive = {u.get("email") for u in _all_auth_users(c)}
    assert _RESET_EMAILS <= alive, "FATAL: test1/test2 계정 소실!"
    print(f"\n✓ 완료. test1/test2 러닝·소셜·팔로우 삭제 · 크루 데이터 불변({after}) · 계정 보존.")
    print("  다음: python scripts/seed_demo_data.py 로 지역 러닝 재생성.")


if __name__ == "__main__":
    if "--reset-test-data" in sys.argv:
        reset_test_data(httpx.Client(timeout=30), "--yes" in sys.argv)
    else:
        main()
