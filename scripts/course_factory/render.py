"""공장 후보 PNG 렌더 — out/<slug>_candidates.json 상위 K개 폴리라인 지도.

Run: .venv/bin/python scripts/course_factory/render.py <slug> [K]
출력: out/<slug>_top<i>.png
"""
from __future__ import annotations
import json, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def render(slug, k=3):
    cands = json.load(open(os.path.join(OUT, f"{slug}_candidates.json")))
    made = []
    for i, r in enumerate(cands[:k], 1):
        pts = r["pts"]
        ys = [p[0] for p in pts]; xs = [p[1] for p in pts]
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.plot(xs, ys, "-", lw=1.6, color="#1f6feb")
        ax.plot(xs[0], ys[0], "o", color="#2ea043", ms=9, label="start/end")
        ax.set_aspect("equal", "datalim")
        ax.set_title(f"[{r['tier']}] {r.get('region','')} · {r['start']} · {r['km']}km\n"
                     f"폐합{r['closure']}m 이중{r['dbl_pct']}% 둘레비{r['bbox_ratio']} "
                     f"회랑{r['longest_retrace_m']}m", fontsize=9)
        ax.legend(fontsize=8); ax.grid(alpha=0.3)
        p = os.path.join(OUT, f"{slug}_top{i}.png")
        fig.savefig(p, dpi=110, bbox_inches="tight"); plt.close(fig)
        made.append(os.path.basename(p))
    print(f"{slug}: rendered {made}")
    return made


if __name__ == "__main__":
    slug = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    render(slug, k)
