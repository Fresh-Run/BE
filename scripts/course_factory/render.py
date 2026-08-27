"""공장 후보 PNG 렌더 — out/<slug>_candidates.json 상위 K개 폴리라인 지도.

두 모드:
  grid  — 맨 격자 위 폴리라인(형상 판정 — 자기교차·둘레비). out/<slug>_top<i>.png
  map   — 실제 타일 배경 위 폴리라인(보행 환경 판정 — 수변/공원 산책로 vs
          차도 옆). 위경도→웹메르카토르(EPSG:3857) 정합. out/<slug>_top<i>_map.png
          네트워크 필요(타일 다운로드).

배경 타일 프로바이더(§C — **타일 소스는 변동적**, 2026-08-28 교체):
  기존 CartoDB Positron이 API키 요구→"API KEY REQUIRED" 워터마크로 판정 무효화,
  OSM Mapnik은 usage-policy 403 차단. 배경지도 육안이 canonical 등재/롤백 판정의
  핵심이라 **무키·무워터마크·usage-policy 허용** 소스로 교체 + 폴백 체인.
  - 1차 **Esri WorldImagery(위성)** — 한국 커버·무키·무워터마크·ArcGIS Online
    저작자표시 사용 허용. 위성은 녹지(수목 캐노피)·수면·도로/건물 대비가 명확해
    공원/수변 추종 vs street-grid 판정에 충분(일산 호수공원 재렌더 검증).
  - 폴백 Esri.WorldStreetMap → WorldTopoMap(무워터마크. 단 한국은 벡터 결측
    'Map data not yet available' 가능 — 위성 서버 장애 시 최후 안전판).
  - **CartoDB·OSM Mapnik 제외**(워터마크·403). 새 소스가 또 죽으면 아래
    _MAP_PROVIDER_CHAIN 한 곳만 교체.
  저작자표시는 채택된 provider의 attribution을 프레임 내 명기(라이선스 준수).

Run: .venv/bin/python scripts/course_factory/render.py <slug> [K] [grid|map|both]
"""
from __future__ import annotations
import json, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

# 배경 타일 폴백 체인 — 무키·무워터마크·usage-policy 허용만(§C). dotted 이름으로
# 두어 provider 죽을 때 이 리스트만 교체. 순서 = 신뢰도(위성 1차, 벡터 폴백).
_MAP_PROVIDER_CHAIN = [
    "Esri.WorldImagery",     # 위성 — 한국 커버·무키·무워터마크(2026-08-28 확인)
    "Esri.WorldStreetMap",   # 폴백(무워터마크 — 한국 벡터 결측 가능)
    "Esri.WorldTopoMap",     # 폴백2
]


def _resolve_provider(dotted):
    """'Esri.WorldImagery' → cx.providers.Esri.WorldImagery(TileProvider)."""
    import contextily as cx
    node = cx.providers
    for part in dotted.split("."):
        node = node[part]
    return node


def _add_basemap_with_fallback(ax):
    """체인을 순회해 첫 성공 provider로 basemap 추가. 반환 (이름, attribution)|(None,None)."""
    import contextily as cx
    for dotted in _MAP_PROVIDER_CHAIN:
        try:
            prov = _resolve_provider(dotted)
            cx.add_basemap(ax, source=prov, crs="EPSG:3857")
            return dotted, str(prov.get("attribution", ""))
        except Exception as e:  # noqa: BLE001 — 다음 provider 시도
            print(f"  ⚠ 타일 provider {dotted} 실패({type(e).__name__}) — 폴백 시도")
    return None, None


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
        used, attrib = _add_basemap_with_fallback(ax)
        if used is None:   # 전 provider 실패 시 맨 배경으로라도 저장
            ax.set_facecolor("#f0f0f0")
            print(f"  ⚠ {slug} top{i}: 전 타일 provider 실패 — 무배경 저장")
        else:
            # 라이선스 준수 — 채택 provider 저작자표시 프레임 내 명기(ASCII 축약)
            ax.text(0.01, 0.01, f"Tiles: {used} | {attrib[:60]}", transform=ax.transAxes,
                    fontsize=6, va="bottom", ha="left", color="#333",
                    bbox=dict(boxstyle="round", fc="white", ec="none", alpha=0.6))
        # 제목은 ASCII(matplotlib 기본 폰트 한글 미지원) — 지도 라벨은 타일에 한글 baked
        ax.set_title(f"[{r['tier']}] {slug} #{i} - {r['km']}km  "
                     f"self_cross={r.get('self_cross','?')} retrace={r['longest_retrace_m']}m "
                     f"[{used or 'NO-TILE'}]",
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
