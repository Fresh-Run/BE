from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from scripts.course_factory.tagging_probe import ratio_for  # noqa: E402

CANDS = {
    "서울 뚝섬한강(수변정정)": (37.5245, 127.0695),
    "인천 송도 센트럴파크(코어)": (37.3880, 126.6430),
    "화성 동탄호수공원": (37.1990, 127.0990),
    "세종 중앙공원/금강": (36.5030, 127.2620),
    "하남 미사 한강공원": (37.5620, 127.1930),
    "부산 수영강/센텀": (35.1710, 129.1250),
    "서울 여의도한강": (37.5270, 126.9330),
}
for n, c in CANDS.items():
    t = time.time()
    try:
        r, wm, rm, nn, _ = ratio_for(c)
        v = "PASS" if r >= 1.5 else ("경계" if r >= 1.0 else "제외")
        print(f"{n:24} ratio={r:5.2f} [{v:4}] walk={wm/1000:.0f}km road={rm/1000:.0f}km ({time.time()-t:.0f}s)", flush=True)
    except Exception as e:
        print(f"{n:24} FAIL {type(e).__name__} {str(e)[:60]}", flush=True)
print("DONE", flush=True)
