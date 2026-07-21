"""소셜프루프 집계 통계 (Ivan 퍼널 v1). 개별 run 미노출 — 카운트만.

course-run share: 최근 N일 window(ran_at 기준)에서 코스 연결 run(route_id not
null) 비율. global은 **비실사용 계정(시드/데모/QA/운영진) 제외** — 실측상 데모가
window run의 95%라 포함 시 소셜프루프가 사실상 데모 통계가 됨(진정성 훼손).
total < 20이면 share=null(민망한 초기 숫자 방어). 집계는 전체 run 기준이라
visibility 무관(개별 노출 없음 — 프라이버시 무해, API_GUIDE 명시).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.core.supabase_client import get_supabase_admin
from app.models.schemas import CourseRunShareResponse
from app.services.profile_service import _DEMO_EMAILS

# 소셜프루프 왜곡 방지 — 비실사용 계정 전부 제외(시드/데모 + QA + 운영진).
# 실측(2026-07-21, 30일 window): 이들이 전체 run의 95%(37/39).
_EXCLUDED_EMAILS = _DEMO_EMAILS | {"qa-empty@freshrun.com", "freshrun0609@gmail.com"}

_MIN_SAMPLE = 20   # total_runs 이 값 미만이면 share=null (지시 확정)
_MAX_WINDOW_DAYS = 90
_DEFAULT_WINDOW_DAYS = 30

# 제외 대상 uid 캐시 — 계정 고정이라 프로세스 1회 조회(저빈도 엔드포인트).
_excluded_uids_cache: set[str] | None = None


async def _excluded_uids() -> set[str]:
    global _excluded_uids_cache
    if _excluded_uids_cache is not None:
        return _excluded_uids_cache
    supabase = get_supabase_admin()
    # auth.users에서 제외 이메일의 uid 매핑(supabase-py admin — delete_user 선례).
    page = await asyncio.to_thread(
        lambda: supabase.auth.admin.list_users()
    )
    users = page if isinstance(page, list) else getattr(page, "users", page)
    _excluded_uids_cache = {
        u.id for u in users if getattr(u, "email", None) in _EXCLUDED_EMAILS
    }
    return _excluded_uids_cache


async def _count_runs(cutoff: str, *, course_only: bool,
                      user_id: str | None, exclude_uids: set[str]) -> int:
    """window 내 run 수 (route_id not null 옵션·본인/제외 필터). 카운트만."""
    supabase = get_supabase_admin()

    def _q():
        q = (supabase.table("runs")
             .select("id", count="exact")
             .gte("ran_at", cutoff))
        if course_only:
            q = q.not_.is_("route_id", "null")
        if user_id is not None:
            q = q.eq("user_id", user_id)
        elif exclude_uids:
            q = q.not_.in_("user_id", list(exclude_uids))
        return q.execute()

    res = await asyncio.to_thread(_q)
    return res.count or 0


async def course_run_share(
    scope: str, window_days: int, user_id: str
) -> CourseRunShareResponse:
    """코스 연결 run 비율 (scope global/me, 최근 window_days).

    global: 비실사용 계정 제외 전체. me: 인증 유저 본인.
    total_runs < 20 → share=null. share는 course_runs/total_runs(소수 3자리).
    """
    window_days = max(1, min(window_days, _MAX_WINDOW_DAYS))
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=window_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    if scope == "me":
        exclude: set[str] = set()
        uid: str | None = user_id
    else:  # global — 비실사용 제외
        exclude = await _excluded_uids()
        uid = None

    total = await _count_runs(cutoff, course_only=False, user_id=uid, exclude_uids=exclude)
    course = await _count_runs(cutoff, course_only=True, user_id=uid, exclude_uids=exclude)

    share = round(course / total, 3) if total >= _MIN_SAMPLE else None
    return CourseRunShareResponse(
        scope=scope, window_days=window_days,
        total_runs=total, course_runs=course, share=share,
    )
