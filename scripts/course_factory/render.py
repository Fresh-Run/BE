"""공장 후보 PNG 렌더 — out/<slug>_candidates.json 상위 K개 폴리라인 지도.

두 모드:
  grid  — 맨 격자 위 폴리라인(형상 판정 — 자기교차·둘레비). out/<slug>_top<i>.png
  map   — 실제 OSM 타일 배경 위 폴리라인(보행 환경 판정 — 수변/공원 산책로 vs
          차도 옆). 위경도→웹메르카토르(EPSG:3857) 정합. out/<slug>_top<i>_map.png
          타일: CartoDB Positron(© OpenStreetMap contributors © CARTO — ODbL/CC-BY,
          저작자표시 프레임 내 명기). 네트워크 필요(타일 다운로드).

Run: .venv/bin/python scripts/course_factory/render.py <slug> [K] [grid|map|both]
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


def render_map(slug, k=3):
    """실제 OSM 타일 배경 위 폴리라인 — 보행 환경 육안 판정용(_map suffix)."""
    import contextily as cx
    from pyproj import Transformer
    T = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)  # (lon,lat)->(x,y)
    cands = json.load(open(os.path.join(OUT, f"{slug}_candidates.json")))
    made = []
    for i, r in enumerate(cands[:k], 1):
        pts = r["pts"]
        xs, ys = T.transform([p[1] for p in pts], [p[0] for p in pts])
        fig, ax = plt.subplots(figsize=(7, 7))
        ax.plot(xs, ys, "-", lw=2.2, color="#d62728", alpha=0.9)          # 코스(빨강)
        ax.plot(xs[0], ys[0], "o", color="#2ea043", ms=11, mec="white", label="start/end")
        ax.set_aspect("equal")
        # 여백(코스 bbox 15% 패딩)으로 주변 지형 문맥 확보
        pad = max(max(xs) - min(xs), max(ys) - min(ys)) * 0.15 + 50
        ax.set_xlim(min(xs) - pad, max(xs) + pad)
        ax.set_ylim(min(ys) - pad, max(ys) + pad)
        try:
            cx.add_basemap(ax, source=cx.providers.CartoDB.Positron, crs="EPSG:3857",
                           attribution="© OpenStreetMap contributors © CARTO")
        except Exception as e:   # 타일 네트워크 실패 시 맨 배경으로라도 저장
            ax.set_facecolor("#f0f0f0")
            print(f"  ⚠ {slug} top{i}: 타일 실패({type(e).__name__}) — 무배경 저장")
        # 제목은 ASCII(matplotlib 기본 폰트 한글 미지원) — 지도 라벨은 타일에 한글 baked
        ax.set_title(f"[{r['tier']}] {slug} #{i} - {r['km']}km  "
                     f"self_cross={r.get('self_cross','?')} retrace={r['longest_retrace_m']}m",
                     fontsize=9)
        ax.set_xticks([]); ax.set_yticks([]); ax.legend(fontsize=8, loc="upper right")
        p = os.path.join(OUT, f"{slug}_top{i}_map.png")
        fig.savefig(p, dpi=130, bbox_inches="tight"); plt.close(fig)
        made.append(os.path.basename(p))
    print(f"{slug}: rendered(map) {made}")
    return made


if __name__ == "__main__":
    slug = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    mode = sys.argv[3] if len(sys.argv) > 3 else "grid"
    if mode in ("grid", "both"):
        render(slug, k)
    if mode in ("map", "both"):
        render_map(slug, k)
