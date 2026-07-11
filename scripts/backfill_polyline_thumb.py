"""run_tracks.polyline_thumb 백필 — 멱등 (null인 행만, 재실행 시 0건).

저장 파이프라인이 2026-07-11부터 저장 시 박제하므로 이 스크립트는 그 이전
트랙 전용. points(저장 폴리라인)에서 동일 로직(make_polyline_thumb)으로 생성.
실행: .venv/bin/python scripts/backfill_polyline_thumb.py
"""
from __future__ import annotations

import os
import sys

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from app.services.track_service import make_polyline_thumb  # noqa: E402


def _keys() -> str:
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                return line.split("=", 1)[1]
    raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY not found")


_SB = "https://jlmmqnpddkokyintlawd.supabase.co"
_SVC = _keys()
_ADM = {"apikey": _SVC, "Authorization": f"Bearer {_SVC}", "Content-Type": "application/json"}


def main() -> None:
    c = httpx.Client(timeout=60)
    rows = c.get(f"{_SB}/rest/v1/run_tracks", headers=_ADM,
                 params={"polyline_thumb": "is.null", "select": "run_id,points",
                         "limit": 1000}).json()
    print(f"백필 대상: {len(rows)}행 (polyline_thumb null)")
    done = 0
    for r in rows:
        points = r.get("points") or []
        if not points:
            print(f"  ! {r['run_id'][:8]}…: points 비어 있음 — 스킵")
            continue
        thumb = make_polyline_thumb(points)
        resp = c.patch(f"{_SB}/rest/v1/run_tracks", headers=_ADM,
                       params={"run_id": f"eq.{r['run_id']}"},
                       json={"polyline_thumb": thumb})
        assert resp.status_code in (200, 204), f"{r['run_id']}: {resp.status_code} {resp.text[:150]}"
        done += 1
        print(f"  ✓ {r['run_id'][:8]}…: {len(points)}pt → {len(thumb)}pt")
    print(f"완료: {done}건 채움 (재실행 시 0건이어야 멱등)")


if __name__ == "__main__":
    main()
