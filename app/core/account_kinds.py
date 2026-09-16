"""계정 보호 kind → 행동 매핑 **단일 소스** (user_id 기반 보호 이관 P2, dual-read).

`profiles.account_kind`(P1 컬럼, db/2026-09-15_account_kind_column.sql) 값별로 어떤 보호가
적용되는지 한 곳에 정의한다. 앱 런타임(profile_service·stats_service)과 오프라인 스크립트
(grant_beta_premium·wipe_demo_data·seed_inventory)가 **모두 이걸 참조** — 이메일 문자열
매칭과 dual-read(합집합)로 P3(컷오버)까지 병행한다.

원칙(설계 P2):
  · **보호/제외 집합은 union(이메일 ∪ kind)** — 어느 경로도 보호를 못 떨어뜨림(superset).
    실수는 **과보호(안전) 방향**으로만. (delete_block·stats_exclude·wipe_protect·grant_skip·
    premium_lock·seed_exclude)
  · **파괴 대상(wipe_target)은 union으로 확장하지 않는다** — target을 넓히면 "삭제 과다"라
    unsafe 방향. wipe는 protection만 union으로 넓히고, target은 이메일 그대로 두되
    disjoint assert를 kind로 강화한다(wipe_demo_data 참조).

⚠️ **순수 상수 모듈 — import 부작용 0**(config/supabase/env 미import). 스크립트도 안전하게
   `from app.core.account_kinds import ...` 가능(무거운 초기화 없음).

§B 결정 이력 — 현 이메일 집합보다 넓어지는 3지점(과보호/안전 방향). **오너 승인 완료
   (2026-09-16)** — 아래대로 확정 반영:
  · stats_exclude에 owner 추가 → 오너(test3·cvcv) 러닝이 소셜프루프 통계에서 빠짐
    (이메일 집합엔 owner 없었음). 보수적(내부자 미포함) 방향 — 승인.
  · delete_block에 owner/internal/qa-empty 추가 → 앱 자가 탈퇴 차단
    (이메일 _DEMO_EMAILS엔 test1/2·demo만). 오너 계정 오삭제 방지 — 승인.
  · seed_exclude/grant_skip이 qa-empty·cvcv까지 확대 → 실질 무해(픽스처·이미 보호) — 승인.
  재검토 트리거: P3 컷오버 시 이메일 매칭 제거 전 이 매핑이 라이브 계정과 정합인지 재확인.
"""
from __future__ import annotations

# CHECK 제약과 동일 4값 (db/2026-09-15_account_kind_column.sql).
ALL_KINDS: frozenset[str] = frozenset({"owner", "demo", "qa", "internal"})

# kind → 적용 보호 행동 집합. 행동 의미:
#   premium_lock : 베타 프리미엄 회수(--revoke) 불가침(강등 금지).
#   grant_skip   : 자동 프리미엄 승급 대상에서 제외(tier를 시드/수동으로 관리).
#   stats_exclude: 소셜프루프 통계(course-run share)에서 제외(비실사용 계정).
#   delete_block : 앱 회원탈퇴(DELETE /me) 차단.
#   wipe_protect : wipe_demo_data 파괴 대상에서 **절대 제외**(보호).
#   wipe_target  : wipe_demo_data 리셋/삭제 **대상**(데모 데이터 초기화). demo 전용.
#   seed_exclude : seed_inventory 시드 재료(실주 트랙)에서 제외.
_KIND_BEHAVIOR: dict[str, frozenset[str]] = {
    "owner": frozenset(
        {"premium_lock", "grant_skip", "stats_exclude", "delete_block",
         "wipe_protect", "seed_exclude"}),
    "internal": frozenset(
        {"premium_lock", "grant_skip", "stats_exclude", "delete_block",
         "wipe_protect", "seed_exclude"}),
    "qa": frozenset(
        {"grant_skip", "stats_exclude", "delete_block",
         "wipe_protect", "seed_exclude"}),
    "demo": frozenset(
        {"grant_skip", "stats_exclude", "delete_block",
         "wipe_target", "seed_exclude"}),
}


def kinds_with(behavior: str) -> frozenset[str]:
    """주어진 보호 행동을 갖는 kind 집합. (예: kinds_with('wipe_protect') = {owner,internal,qa})

    dual-read 지점은 이 결과로 `account_kind in kinds_with(<behavior>)`를 판정해
    이메일 집합과 OR(union)한다.
    """
    return frozenset(k for k, behaviors in _KIND_BEHAVIOR.items() if behavior in behaviors)
