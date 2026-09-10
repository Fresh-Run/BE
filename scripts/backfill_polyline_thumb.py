"""run_tracks.polyline_thumb 백필/재생성 — points(전체)에서 make_polyline_thumb 재계산.

두 용도:
  ① null 채움(2026-07-11 이전 트랙 — 저장 시 미박제분).
  ② eps 변경 소급(2026-09-11 THUMB_EPSILON_M 25→15) — 기존 non-null thumb는 옛 eps라
     신 thumb와 다르면 갱신. points·상세(get_run_track)는 무접촉·불변.

멱등: 같은 points → 같은 thumb. 이미 신 thumb면 동일(스킵). 재실행 시 대상 0건.
mass 업데이트라 dry-run 기본 — 대상 수·표본만. --apply로 실제 갱신.

실행:
  python scripts/backfill_polyline_thumb.py            # dry-run
  python scripts/backfill_polyline_thumb.py --apply    # 실제 갱신
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.supabase_client import get_supabase_admin  # noqa: E402
from app.services import track_service as ts  # noqa: E402


def main() -> None:
    apply_ = "--apply" in sys.argv
    print(f"[backfill polyline_thumb] eps={ts.THUMB_EPSILON_M} max={ts.THUMB_MAX_POINTS} · "
          f"{'실행(--apply)' if apply_ else 'DRY-RUN(--apply로 실행)'}")
    sb = get_supabase_admin()
    rows, off = [], 0
    while True:
        b = (sb.table("run_tracks").select("run_id, points, polyline_thumb")
             .range(off, off + 999).execute().data)
        rows += b
        if len(b) < 1000:
            break
        off += 1000
    print(f"run_tracks {len(rows)}행 스캔")

    changed = same = skipped = 0
    for r in rows:
        pts = r.get("points") or []
        if len(pts) < 2:
            skipped += 1
            continue
        new_thumb = ts.make_polyline_thumb(pts)
        old_thumb = r.get("polyline_thumb") or []
        if new_thumb == old_thumb:
            same += 1
            continue
        changed += 1
        if apply_:
            sb.table("run_tracks").update({"polyline_thumb": new_thumb}).eq(
                "run_id", r["run_id"]).execute()
        elif changed <= 6:  # dry-run 표본
            print(f"  {r['run_id'][:8]}: {len(old_thumb)}점 → {len(new_thumb)}점")

    print(f"\n대상 {changed}행 {'갱신 완료' if apply_ else '(dry-run — 미변경)'} · "
          f"동일 {same} · 스킵 {skipped}(포인트 부족)")
    if not apply_ and changed:
        print("실제 갱신하려면 --apply.")


if __name__ == "__main__":
    main()
