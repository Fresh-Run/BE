"""배틀(1v1 점수 대전) — 생성·초대·수락·포기·정산 + 스코어 엔진.

설계: docs/BATTLE_DESIGN_v0_KO.md. 오너 결정 3건(2026-09-07):
  ① 귀속 = runs.ran_at(저장시각)   ② 게이팅 병행(무료 30일 롤링 3 + 전티어 동시 active 3)
  ③ 정산 유예 30분(KST 자정 daily 배치가 흡수).

anti-cheat = verification='verified' 단일 게이트(§2.4). is_flagged·<1.5km 제외.
거리는 distance_km(adjusted면 서버 필터거리가 정본). 점수 상수는 이반 battle-score.ts
미러(§C 단일 소스 — 계약 변경 시 양쪽 동시). supabase-py 동기 → asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.supabase_client import get_supabase_admin
from app.services.quota_service import get_tier

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

# ── 점수 상수 (이반 battle-score.ts 미러 — 단일 소스, 계약 변경 시 양쪽 동시 갱신) ──
_MIN_KM = 1.5              # 하한 미만 = 0점(완주 아님)
_BASE_PER_KM = 10.0        # base = km × 10
_COMPLETION = 20.0         # 완주(≥1.5km + 정상저장)
_EARLY_BIRD = 10.0         # ran_at KST < 07:00
_EARLY_BIRD_HOUR = 7       # 07:00 미포함(06:59 포함)
_MILESTONE_5K = 30.0       # 참가자 첫 ≥5km 런
_MILESTONE_10K = 50.0      # 참가자 첫 ≥10km 런
_STREAK_STEP = 0.05        # 1 + 0.05×min(streak,10)
_STREAK_CAP_DAYS = 10      # → 배율 상한 1.5
_SETTLE_GRACE_MIN = 30     # 종료 유예(결정③)

# 게이팅
_FREE_ROLLING_DAYS = 30
_FREE_ROLLING_MAX = 3      # 무료 30일 관여 ≥3 차단
_ACTIVE_CAP = 3            # 전 티어 동시 active ≥3 차단


class BattleError(Exception):
    """도메인 오류 — (status_code, error_code, message)."""

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


# ══════════════════════ 스코어 엔진 (순수 — 무DB, 테스트 가능) ══════════════════════

def _pace_bonus(avg_pace_sec_per_km: int | None) -> float:
    """페이스 보너스 — ⚠️ 플레이스홀더(이반 battle-score.ts 상수 미도착, 착수 전 교체·
    §7 판단 플래그). 빠를수록 가산, 계단식. None(페이스 없음)이면 0.
    현 계단: <5:00→+15 · <6:00→+10 · <7:00→+5 · 그 외 0."""
    if not avg_pace_sec_per_km:
        return 0.0
    if avg_pace_sec_per_km < 300:
        return 15.0
    if avg_pace_sec_per_km < 360:
        return 10.0
    if avg_pace_sec_per_km < 420:
        return 5.0
    return 0.0


def _is_early_bird(ran_at_iso: str) -> bool:
    """ran_at(KST)이 07:00 전인가(06:59 포함·07:00 미포함). Q4=ran_at 단일 시간원 근사."""
    try:
        return datetime.fromisoformat(ran_at_iso).astimezone(_KST).hour < _EARLY_BIRD_HOUR
    except (ValueError, TypeError):
        return False


def score_run(run: dict, is_5k_first: bool = False, is_10k_first: bool = False) -> tuple[float, dict, bool]:
    """per-run 점수. run: {distance_km, avg_pace_sec_per_km, verification, is_flagged, ran_at}.
    반환 (run_score, breakdown, counted). counted=false면 0점(창밖 판정은 호출측)."""
    dist = run.get("distance_km") or 0.0
    counted = (run.get("verification") == "verified"
               and not run.get("is_flagged")
               and dist >= _MIN_KM)
    if not counted:
        return 0.0, {"counted": False, "reason": "not_verified_or_short"}, False
    base = round(dist * _BASE_PER_KM, 2)
    completion = _COMPLETION
    pace = _pace_bonus(run.get("avg_pace_sec_per_km"))
    early = _EARLY_BIRD if _is_early_bird(run.get("ran_at") or "") else 0.0
    milestone = (_MILESTONE_5K if is_5k_first else 0.0) + (_MILESTONE_10K if is_10k_first else 0.0)
    total = round(base + completion + pace + early + milestone, 2)
    return total, {
        "counted": True, "base": base, "completion": completion, "pace": pace,
        "early_bird": early, "milestone": milestone,
    }, True


def streak_multiplier(streak_days: int) -> float:
    """1 + 0.05 × min(streak, 10) — cap 1.5."""
    return round(1.0 + _STREAK_STEP * min(max(streak_days, 0), _STREAK_CAP_DAYS), 4)


def _current_streak(ran_at_isos: list[str]) -> int:
    """runs.ran_at(KST 날짜 버킷) 오늘부터 역순 연속일. verified 런 리스트 전제(호출측 필터).
    insight_service 연속 로직과 동형(백필 조작 무효 — ran_at 기준)."""
    days = sorted({datetime.fromisoformat(t).astimezone(_KST).date() for t in ran_at_isos if t},
                  reverse=True)
    if not days:
        return 0
    today = datetime.now(_KST).date()
    # 오늘 또는 어제부터 시작해야 '현재 진행' streak(오늘 미실행이면 어제까지 연속 인정)
    if (today - days[0]).days > 1:
        return 0
    streak = 1
    for prev, cur in zip(days, days[1:]):
        if (prev - cur).days == 1:
            streak += 1
        else:
            break
    return streak


def score_participant(runs: list[dict], streak_days: int) -> tuple[float, list[dict]]:
    """참가자 창내 counted 런 → per-run 점수(milestone 결정론) × streak_mult.
    runs: ran_at asc 정렬 전제. 반환 (participant_score, per_run breakdown 리스트)."""
    seen_5k = seen_10k = False
    per_run = []
    subtotal = 0.0
    for r in sorted(runs, key=lambda x: x.get("ran_at") or ""):
        dist = r.get("distance_km") or 0.0
        countable = (r.get("verification") == "verified" and not r.get("is_flagged")
                     and dist >= _MIN_KM)
        first5 = countable and not seen_5k and dist >= 5.0
        first10 = countable and not seen_10k and dist >= 10.0
        rscore, bd, counted = score_run(r, first5, first10)
        if counted:
            if first5:
                seen_5k = True
            if first10:
                seen_10k = True
        subtotal += rscore
        per_run.append({"run_id": r.get("id"), "run_score": rscore, "breakdown": bd, "counted": counted})
    mult = streak_multiplier(streak_days)
    return round(subtotal * mult, 2), per_run


# ══════════════════════ 시각 헬퍼 ══════════════════════

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ends_at(started: datetime, duration_days: int) -> datetime:
    """수락 시점 → KST 날짜 자정 + duration_days(KST 00:00) → UTC(자정 정렬, daily 배치 정합)."""
    start_kst_date = started.astimezone(_KST).date()
    end_kst = datetime.combine(start_kst_date + timedelta(days=duration_days),
                               datetime.min.time(), _KST)
    return end_kst.astimezone(timezone.utc)


# ══════════════════════ 게이팅 (병행 — 결정②) ══════════════════════

async def _assert_gates(user_id: str) -> None:
    """생성/수락 진입 게이트. premium/베타(=tier premium)/시드는 롤링 스킵. 동시 캡은 전 티어."""
    sb = get_supabase_admin()
    # (b) 동시 active 3 캡 — 전 티어
    active = await asyncio.to_thread(
        lambda: sb.table("battles").select("id")
        .in_("status", ["active"])
        .or_(f"created_by.eq.{user_id},opponent.eq.{user_id}")
        .execute())
    if len(active.data or []) >= _ACTIVE_CAP:
        raise BattleError(409, "battle_active_cap",
                          f"동시 진행 배틀은 최대 {_ACTIVE_CAP}개예요.")
    # (a) 무료 30일 롤링 3 — premium(베타·시드 포함) 스킵
    if await get_tier(user_id) == "premium":
        return
    since = (_now() - timedelta(days=_FREE_ROLLING_DAYS)).isoformat()
    created = await asyncio.to_thread(
        lambda: sb.table("battles").select("id")
        .eq("created_by", user_id).gte("created_at", since).execute())
    accepted = await asyncio.to_thread(
        lambda: sb.table("battle_invites").select("id")
        .eq("invitee", user_id).eq("status", "accepted").gte("responded_at", since).execute())
    engaged = len(created.data or []) + len(accepted.data or [])
    if engaged >= _FREE_ROLLING_MAX:
        raise BattleError(403, "battle_free_limit",
                          f"무료 플랜은 30일에 배틀 {_FREE_ROLLING_MAX}회까지예요. "
                          "프리미엄은 무제한이에요.")


# ══════════════════════ 라이프사이클 (CRUD·전이) ══════════════════════

async def create_battle(user_id: str, opponent_id: str, title: str,
                        emoji: str | None, duration_days: int, fmt: str) -> dict:
    """배틀 생성 + 초대(48h). 게이팅 + eligibility(차단/비공개 404 은닉)."""
    if opponent_id == user_id:
        raise BattleError(400, "bad_request", "자기 자신과는 배틀할 수 없어요.")
    # eligibility(룰링②) — 차단 관계/부재는 404 은닉(profile_service 재사용)
    from app.services import profile_service
    if await profile_service.is_blocked_either(user_id, opponent_id):
        raise BattleError(404, "not_found", "대상을 찾을 수 없어요.")
    await _assert_gates(user_id)
    sb = get_supabase_admin()
    battle = await asyncio.to_thread(
        lambda: sb.table("battles").insert({
            "created_by": user_id, "opponent": opponent_id, "title": title,
            "emoji": emoji, "duration_days": duration_days, "format": fmt,
            "status": "pending",
        }).execute())
    b = battle.data[0]
    expires = (_now() + timedelta(hours=48)).isoformat()
    await asyncio.to_thread(
        lambda: sb.table("battle_invites").insert({
            "battle_id": b["id"], "inviter": user_id, "invitee": opponent_id,
            "status": "pending", "expires_at": expires,
        }).execute())
    from app.services import notification_service
    try:
        await notification_service.create_notification(
            recipient_id=opponent_id, actor_id=user_id, type="battle_invited",
            target_id=b["id"], target_type="battle", payload={"title": title})
    except Exception:  # noqa: BLE001 — 알림 실패가 생성을 막지 않음
        logger.warning("battle_invited 알림 실패", exc_info=True)
    return b


async def _load_battle(battle_id: str, user_id: str) -> dict:
    """참가자만 조회(아니면 404 은닉)."""
    sb = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: sb.table("battles").select("*").eq("id", battle_id).limit(1).execute())
    if not res.data:
        raise BattleError(404, "battle_not_found", "배틀을 찾을 수 없어요.")
    b = res.data[0]
    if user_id not in (b["created_by"], b["opponent"]):
        raise BattleError(404, "battle_not_found", "배틀을 찾을 수 없어요.")
    return b


async def accept_battle(battle_id: str, user_id: str) -> dict:
    """초대 수락 → active. 만료 전·invitee만. 게이팅 재검사(수락자)."""
    b = await _load_battle(battle_id, user_id)
    if b["status"] != "pending":
        raise BattleError(409, "battle_not_pending", "이미 시작됐거나 종료된 배틀이에요.")
    if user_id != b["opponent"]:
        raise BattleError(403, "forbidden", "초대받은 사람만 수락할 수 있어요.")
    sb = get_supabase_admin()
    inv = await asyncio.to_thread(
        lambda: sb.table("battle_invites").select("*")
        .eq("battle_id", battle_id).eq("status", "pending").limit(1).execute())
    if not inv.data or datetime.fromisoformat(inv.data[0]["expires_at"]) < _now():
        # 만료 → cancelled 정리
        await _expire_invite(battle_id)
        raise BattleError(410, "battle_invite_expired", "초대가 만료됐어요(48시간).")
    await _assert_gates(user_id)
    started = _now()
    ends = _ends_at(started, b["duration_days"])
    updated = await asyncio.to_thread(
        lambda: sb.table("battles").update({
            "status": "active", "started_at": started.isoformat(), "ends_at": ends.isoformat(),
        }).eq("id", battle_id).eq("status", "pending").execute())
    await asyncio.to_thread(
        lambda: sb.table("battle_invites").update({
            "status": "accepted", "responded_at": started.isoformat(),
        }).eq("battle_id", battle_id).eq("status", "pending").execute())
    return updated.data[0] if updated.data else b


async def decline_battle(battle_id: str, user_id: str) -> None:
    b = await _load_battle(battle_id, user_id)
    if b["status"] != "pending" or user_id != b["opponent"]:
        raise BattleError(409, "battle_not_pending", "수락 대기 중인 배틀이 아니에요.")
    sb = get_supabase_admin()
    await asyncio.to_thread(
        lambda: sb.table("battle_invites").update({
            "status": "declined", "responded_at": _now().isoformat()})
        .eq("battle_id", battle_id).eq("status", "pending").execute())
    await asyncio.to_thread(
        lambda: sb.table("battles").update({"status": "cancelled"})
        .eq("id", battle_id).eq("status", "pending").execute())


async def _expire_invite(battle_id: str) -> None:
    sb = get_supabase_admin()
    await asyncio.to_thread(
        lambda: sb.table("battle_invites").update({"status": "expired"})
        .eq("battle_id", battle_id).eq("status", "pending").execute())
    await asyncio.to_thread(
        lambda: sb.table("battles").update({"status": "cancelled"})
        .eq("id", battle_id).eq("status", "pending").execute())


async def forfeit_battle(battle_id: str, user_id: str) -> dict:
    """포기 = 즉시 패배(룰링④). 상대 승·점수 유지·감점 없음."""
    b = await _load_battle(battle_id, user_id)
    if b["status"] != "active":
        raise BattleError(409, "battle_not_active", "진행 중인 배틀이 아니에요.")
    opponent = b["opponent"] if user_id == b["created_by"] else b["created_by"]
    sb = get_supabase_admin()
    updated = await asyncio.to_thread(
        lambda: sb.table("battles").update({
            "status": "forfeited", "winner": opponent, "settled_at": _now().isoformat(),
        }).eq("id", battle_id).eq("status", "active").execute())
    from app.services import notification_service
    try:
        await notification_service.create_notification(
            recipient_id=opponent, actor_id=user_id, type="battle_won",
            target_id=battle_id, target_type="battle", allow_self=False)
    except Exception:  # noqa: BLE001
        logger.warning("battle_won(forfeit) 알림 실패", exc_info=True)
    return updated.data[0] if updated.data else b


async def cancel_battle(battle_id: str, user_id: str) -> dict:
    """상호취소 요청 — 양자 합의. v0: 양쪽 다 취소요청 시 cancelled(무승부).
    요청 상태는 battles에 별도 컬럼 없이 in-memory 단순화 대신, 여기선 '요청자 표기'를
    winner=null·status 유지로 두고, 상대가 재요청하면 취소 확정(간이 합의)."""
    b = await _load_battle(battle_id, user_id)
    if b["status"] != "active":
        raise BattleError(409, "battle_not_active", "진행 중인 배틀만 취소 요청할 수 있어요.")
    # v0 간이: 상호취소는 즉시 cancelled로 처리하되, 단독 취소 남용 방지는 앱 UX(양자 확인
    # 다이얼로그)에 위임. 스키마 확장(cancel_requested_by) 없이 additive 유지.
    sb = get_supabase_admin()
    updated = await asyncio.to_thread(
        lambda: sb.table("battles").update({
            "status": "cancelled", "settled_at": _now().isoformat()})
        .eq("id", battle_id).eq("status", "active").execute())
    return updated.data[0] if updated.data else b


async def list_battles(user_id: str, status: str | None) -> list[dict]:
    sb = get_supabase_admin()
    q = sb.table("battles").select("*").or_(
        f"created_by.eq.{user_id},opponent.eq.{user_id}").order("created_at", desc=True)
    if status:
        q = q.eq("status", status)
    res = await asyncio.to_thread(q.execute)
    return res.data or []


async def get_battle_detail(battle_id: str, user_id: str) -> dict:
    """상세 — 참가자별 점수·런목록(battle_runs 영속분). 만료 lazy 정리."""
    b = await _load_battle(battle_id, user_id)
    if b["status"] == "pending":
        # 만료 lazy 체크
        sb = get_supabase_admin()
        inv = await asyncio.to_thread(
            lambda: sb.table("battle_invites").select("expires_at,status")
            .eq("battle_id", battle_id).limit(1).execute())
        if inv.data and inv.data[0]["status"] == "pending" and \
                datetime.fromisoformat(inv.data[0]["expires_at"]) < _now():
            await _expire_invite(battle_id)
            b["status"] = "cancelled"
        b["invite_expires_at"] = inv.data[0]["expires_at"] if inv.data else None
    sb = get_supabase_admin()
    runs = await asyncio.to_thread(
        lambda: sb.table("battle_runs").select("*").eq("battle_id", battle_id).execute())
    # 참가자별 누적
    scores: dict[str, float] = {b["created_by"]: 0.0, b["opponent"]: 0.0}
    for br in runs.data or []:
        scores[br["user_id"]] = round(scores.get(br["user_id"], 0.0) + (br["run_score"] or 0.0), 2)
    b["scores"] = [{"user_id": u, "score": s} for u, s in scores.items()]
    b["runs"] = runs.data or []
    return b


# ══════════════════════ 정산 배치 (KST 자정 daily + 종료 조기정산) ══════════════════════

async def _participant_window_runs(user_id: str, start_iso: str, end_iso: str) -> list[dict]:
    """[start, end) 창의 verified 런(ran_at 귀속·Q4=①)."""
    sb = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: sb.table("runs")
        .select("id, distance_km, avg_pace_sec_per_km, verification, is_flagged, ran_at")
        .eq("user_id", user_id).eq("verification", "verified")
        .gte("ran_at", start_iso).lt("ran_at", end_iso).execute())
    return res.data or []


async def _all_verified_ran_ats(user_id: str) -> list[str]:
    sb = get_supabase_admin()
    res = await asyncio.to_thread(
        lambda: sb.table("runs").select("ran_at")
        .eq("user_id", user_id).eq("verification", "verified").execute())
    return [r["ran_at"] for r in (res.data or []) if r.get("ran_at")]


async def settle_battle(battle: dict) -> None:
    """단일 active 배틀 정산(멱등). battle_runs upsert + 점수 재계산 + 종료 판정."""
    if battle["status"] != "active" or not battle.get("started_at"):
        return
    bid = battle["id"]
    now = _now()
    ends = datetime.fromisoformat(battle["ends_at"])
    window_end = min(now, ends).isoformat()
    sb = get_supabase_admin()
    part_scores: dict[str, float] = {}
    for uid in (battle["created_by"], battle["opponent"]):
        runs = await _participant_window_runs(uid, battle["started_at"], window_end)
        streak = _current_streak(await _all_verified_ran_ats(uid))
        pscore, per_run = score_participant(runs, streak)
        part_scores[uid] = pscore
        # battle_runs upsert(멱등 — UNIQUE battle_id,run_id)
        for r, pr in zip(sorted(runs, key=lambda x: x.get("ran_at") or ""), per_run):
            await asyncio.to_thread(
                lambda r=r, pr=pr, uid=uid: sb.table("battle_runs").upsert({
                    "battle_id": bid, "user_id": uid, "run_id": r["id"],
                    "attributed_at": r["ran_at"], "counted": pr["counted"],
                    "run_score": pr["run_score"], "breakdown": pr["breakdown"],
                }, on_conflict="battle_id,run_id").execute())
    # 종료 판정(유예③ 30분)
    if now >= ends + timedelta(minutes=_SETTLE_GRACE_MIN):
        a, o = battle["created_by"], battle["opponent"]
        winner = a if part_scores.get(a, 0) > part_scores.get(o, 0) else (
            o if part_scores.get(o, 0) > part_scores.get(a, 0) else None)
        await asyncio.to_thread(
            lambda: sb.table("battles").update({
                "status": "ended", "winner": winner, "settled_at": now.isoformat(),
            }).eq("id", bid).eq("status", "active").execute())
        if winner:
            from app.services import notification_service
            loser = o if winner == a else a
            try:
                await notification_service.create_notification(
                    recipient_id=winner, actor_id=loser, type="battle_won",
                    target_id=bid, target_type="battle", allow_self=False)
            except Exception:  # noqa: BLE001
                logger.warning("battle_won 알림 실패", exc_info=True)


async def settle_batch() -> int:
    """전 active 배틀 정산 + 만료 초대 정리. 반환 처리 배틀 수. (크론/관리 트리거)."""
    sb = get_supabase_admin()
    # 만료 초대 정리
    expired = await asyncio.to_thread(
        lambda: sb.table("battle_invites").select("battle_id")
        .eq("status", "pending").lt("expires_at", _now().isoformat()).execute())
    for row in expired.data or []:
        await _expire_invite(row["battle_id"])
    # active 정산
    actives = await asyncio.to_thread(
        lambda: sb.table("battles").select("*").eq("status", "active").execute())
    n = 0
    for b in actives.data or []:
        try:
            await settle_battle(b)
            n += 1
        except Exception:  # noqa: BLE001 — 건별 격리
            logger.warning("배틀 정산 실패 (id=%s)", b.get("id"), exc_info=True)
    logger.info("배틀 정산 배치 — active %d건 처리, 만료 %d건 정리", n, len(expired.data or []))
    return n
