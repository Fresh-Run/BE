"""베타 테스터 premium 일괄 승급/회수 (베타 개방 방식 A — 코드 무변경 경로).

실행:
  python scripts/grant_beta_premium.py            # dry-run (기본 — 대상 목록만)
  python scripts/grant_beta_premium.py --apply    # 실제 승급 (free 실계정 → premium)
  python scripts/grant_beta_premium.py --revoke           # 회수 dry-run
  python scripts/grant_beta_premium.py --revoke --apply   # 실제 회수 (출시 전 리셋)

원칙
- 승급: tier='free'인 실계정 전원 → premium (admin REST — 시드 ensure_premium 선례).
- 제외(불가침): 시드 계정(test1·test2·demo1~5 — 시드가 tier 관리), 운영진
  freshrun0609(승급 원하면 로그 안내대로 수동 판단).
- 회수(--revoke): premium이면서 **subscriptions 행이 없는** 비제외 계정만 → free.
  IAP 구매자(subscriptions 행 있음)는 절대 건드리지 않는다. 수동 premium인
  시드(test1)는 제외 목록이 이중 보호.
- 멱등: 이미 목표 tier인 계정은 스킵. 수동 premium은 IAP lazy 강등이 존중
  (_lazy_iap_downgrade: 구독 행 없음 = admin 부여 → 강등 없음) — 영구 유효.
- 출력: 이메일 마스킹·닉네임·tier 전후만. uid 전체·키 값 화면 출력 금지.
"""
from __future__ import annotations

import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core.account_kinds import kinds_with  # noqa: E402  (순수 상수 모듈 — 부작용 0)

_SB = "https://jlmmqnpddkokyintlawd.supabase.co"

# 정확 매칭(email in SEED_EMAILS, line 86) — 프리픽스 아님. 그래서 test3은 test1/test2에
# 안 걸려 명시 추가 필요. 공동대표 2인 앱 로그인 계정은 출시 후에도 프리미엄 영구 유지
# (2026-08-28): test3@freshrun.com(지연)·cvcv0824@gmail.com(이반). 강등(--revoke) 불가침.
SEED_EMAILS = {"test1@freshrun.com", "test2@freshrun.com",
               "test3@freshrun.com", "cvcv0824@gmail.com"} | {
    f"demo{i}@freshrun.com" for i in range(1, 6)
}
OPERATOR_EMAIL = "freshrun0609@gmail.com"


def _svc() -> str:
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    with open(env) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                return line.split("=", 1)[1]
    raise SystemExit("SUPABASE_SERVICE_ROLE_KEY 없음")


def _mask(email: str) -> str:
    """이메일 마스킹: 앞 2자 + *** + @도메인."""
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}"


def main() -> None:
    revoke = "--revoke" in sys.argv
    apply_ = "--apply" in sys.argv
    mode = "회수(revoke)" if revoke else "승급(grant)"
    print(f"[grant_beta_premium] 모드={mode} · {'실행(--apply)' if apply_ else 'DRY-RUN(기본 — --apply로 실행)'}")

    svc = _svc()
    adm = {"apikey": svc, "Authorization": f"Bearer {svc}", "Content-Type": "application/json"}
    c = httpx.Client(timeout=60)

    # 전체 유저 (이메일 매핑)
    users: list[dict] = []
    page = 1
    while True:
        r = c.get(f"{_SB}/auth/v1/admin/users", headers=adm,
                  params={"per_page": "100", "page": str(page)}).json()
        batch = r.get("users", [])
        users.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    uid2email = {u["id"]: (u.get("email") or "") for u in users}

    profs = c.get(f"{_SB}/rest/v1/profiles", headers=adm,
                  params={"select": "user_id,nickname,tier,account_kind", "limit": "1000"}).json()
    # dual-read(P2): grant_skip 행동을 가진 kind = 자동 승급/회수 모두 스킵(보호).
    _grant_skip_kinds = kinds_with("grant_skip")
    # IAP 구매자 식별 (revoke 보호용)
    subs = c.get(f"{_SB}/rest/v1/subscriptions", headers=adm,
                 params={"select": "user_id", "limit": "5000"}).json()
    iap_uids = {s["user_id"] for s in subs}

    targets: list[dict] = []
    for p in profs:
        email = uid2email.get(p["user_id"], "")
        if not email:
            continue  # auth에 없는 고아 프로필은 손대지 않음
        # dual-read(P2, 이관): 이메일 집합 ∪ account_kind. 둘 중 하나라도 보호면 스킵 —
        # union이라 이메일이 놓친 계정도 kind로 스킵(과보호=안전: 엉뚱 계정 승급/회수
        # 방지, 이 스크립트의 핵심 리스크 봉쇄). 이메일 매칭은 P3까지 유지(제거 아님).
        if p.get("account_kind") in _grant_skip_kinds:
            continue  # kind 보호 — 승급/회수 대상에서 제외
        if email in SEED_EMAILS:
            continue  # 시드 — 시드 스크립트가 tier 관리
        if email == OPERATOR_EMAIL:
            if not revoke and p.get("tier") == "free":
                print(f"  ℹ️ 운영진({_mask(email)})은 현재 free — 자동 승급 대상에서 제외함. "
                      f"원하면 admin REST로 수동 승급할 것.")
            continue
        tier = p.get("tier") or "free"
        if revoke:
            # premium + subscriptions 행 없음(=이 스크립트/수동 부여)만 회수
            if tier == "premium" and p["user_id"] not in iap_uids:
                targets.append({**p, "email": email, "to": "free"})
            elif tier == "premium" and p["user_id"] in iap_uids:
                print(f"  🔒 IAP 구매자 보호: {_mask(email)} — 건드리지 않음")
        else:
            if tier == "free":
                targets.append({**p, "email": email, "to": "premium"})
            # 이미 premium이면 멱등 스킵(출력 생략)

    print(f"\n대상 {len(targets)}명:")
    for t in targets:
        print(f"  {_mask(t['email']):30} nick={t.get('nickname') or '(없음)':16} "
              f"{t.get('tier') or 'free'} → {t['to']}")
    if not targets:
        print("  (없음)")

    if not apply_:
        print("\nDRY-RUN 종료 — 실제 변경 없음. 실행하려면 --apply.")
        return

    done = 0
    for t in targets:
        r = c.patch(f"{_SB}/rest/v1/profiles?user_id=eq.{t['user_id']}",
                    headers=adm, json={"tier": t["to"]})
        okk = r.status_code in (200, 204)
        done += okk
        print(f"  {'✓' if okk else '✗ ' + str(r.status_code)} {_mask(t['email'])} → {t['to']}")
    print(f"\n완료: {done}/{len(targets)}건 변경.")


if __name__ == "__main__":
    main()
