"""전국 고등급 도로 지오메트리 추출 → app/data/motorways_kr.json.gz

도로 등급 서빙 게이트(2026-07-29 오너 승인)의 정적 데이터 소스.
- motorway·motorway_link: 하드 차단 축(법적 보행 금지)
- trunk·trunk_link: 관측 축(gen_meta.trunk_hit_m — 차단 없음)
Overpass를 위도 밴드로 분할 쿼리(전국 1방은 504) + 25m 리샘플 + 1e-5도 반올림.
갱신: 분기 1회 재실행(고속도로망 변경 저빈도). Run: python scripts/extract_motorways_kr.py
"""
from __future__ import annotations

import gzip
import json
import math
import os
import time
import urllib.parse
import urllib.request

OUT_BIN = os.path.join(os.path.dirname(__file__), "..", "app", "data", "motorways_kr.bin.gz")
BANDS = [(33.0, 34.6), (34.6, 35.6), (35.6, 36.4), (36.4, 37.2), (37.2, 37.8), (37.8, 38.7)]
LNG = (124.5, 131.0)
CLASSES = "motorway|motorway_link|trunk|trunk_link"
STEP_M = 25.0


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*6371000*math.asin(math.sqrt(h))


def fetch(bbox):
    q = (f'[out:json][timeout:90];way["highway"~"^({CLASSES})$"]'
         f'({bbox[0]},{LNG[0]},{bbox[1]},{LNG[1]});out tags geom;')
    data = urllib.parse.urlencode({"data": q}).encode()
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter", data=data,
        headers={"User-Agent": "freshrun-road-gate-extract/1.0",
                 "Accept": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=180).read())


def main():
    hard, obs = [], []   # [lat,lng] 리샘플 점들 (hard=motorway류, obs=trunk류)
    for i, band in enumerate(BANDS):
        for attempt in range(3):
            try:
                d = fetch(band)
                break
            except Exception as e:  # noqa: BLE001
                print(f"band {band} 시도 {attempt+1} 실패: {e}")
                time.sleep(20 * (attempt + 1))
        else:
            raise SystemExit(f"band {band} 추출 실패 — 중단(부분 데이터 저장 안 함)")
        n_ways = 0
        for e in d.get("elements", []):
            g = e.get("geometry") or []
            if not g:
                continue
            hw = (e.get("tags") or {}).get("highway", "")
            bucket = hard if hw.startswith("motorway") else obs
            seg = [(p["lat"], p["lon"]) for p in g]
            bucket.append((round(seg[0][0], 5), round(seg[0][1], 5)))
            for j in range(len(seg)-1):
                dd = hav(seg[j], seg[j+1])
                n = max(1, int(dd // STEP_M))
                for k in range(1, n+1):
                    t = k/n
                    bucket.append((round(seg[j][0]+(seg[j+1][0]-seg[j][0])*t, 5),
                                   round(seg[j][1]+(seg[j+1][1]-seg[j][1])*t, 5)))
            n_ways += 1
        print(f"band {band}: ways {n_ways}, 누적 hard {len(hard)} obs {len(obs)}")
        time.sleep(10)
    write_binary(hard, obs)


def write_binary(hard, obs):
    """콤팩트 바이너리 포맷(메모리 간이화 — 2026-07-29 512MB 머신 실측 후 필수).

    좌표를 1e5 스케일 int32로 팩, 셀해시(0.002도) 정렬 → 로더가 bisect로 조회
    (dict-of-tuples 495MB → 배열 ~20MB). 포맷: '<qq'(n_hard,n_obs) + int32 페어들.
    """
    import struct
    from array import array

    def pack(pts):
        scaled = sorted(set((int(round(la * 1e5)), int(round(lo * 1e5))) for la, lo in pts),
                        key=lambda p: ((p[0] // 200) << 20) | (p[1] // 200))
        arr = array("i")
        hashes = array("q")
        for la, lo in scaled:
            arr.append(la)
            arr.append(lo)
            hashes.append(((la // 200) << 20) | (lo // 200))
        return arr, hashes

    (ha, hh), (ob, oh) = pack(hard), pack(obs)
    os.makedirs(os.path.dirname(OUT_BIN), exist_ok=True)
    with gzip.open(OUT_BIN, "wb") as f:
        f.write(struct.pack("<qq", len(ha) // 2, len(ob) // 2))
        f.write(ha.tobytes())
        f.write(hh.tobytes())      # 셀해시 사전계산 저장 — 로더 파싱 churn 제거(v2)
        f.write(ob.tobytes())
        f.write(oh.tobytes())
    print(f"저장: {OUT_BIN} ({os.path.getsize(OUT_BIN)/1e6:.1f}MB) "
          f"hard {len(ha)//2}점 obs {len(ob)//2}점")


if __name__ == "__main__":
    main()
