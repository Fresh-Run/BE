"""전 public 테이블 RLS 검증 — anon key + 유저 JWT로 직접 조회가 전부 차단(0 rows)인지.

RLS 백필(db/2026-07-12_rls_backfill.sql) 실행 후 이걸 돌려 노출 0을 확인한다.
빈 테이블 위양성을 피하려고 service_role 실행수와 대조: svc>0 & anon=0 = deny 확정,
svc=0 = 판정 불가(빈 테이블은 임시 행으로 별도 확인).
실행: python scripts/verify_rls.py
"""
from __future__ import annotations

import os
import sys

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SB = "https://jlmmqnpddkokyintlawd.supabase.co"

_SYS_TABLES = {"geography_columns", "geometry_columns", "spatial_ref_sys"}


def _env() -> dict:
    e = {}
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                e[k] = v
    return e


def _count(c, sb, table, headers) -> int:
    r = c.get(f"{sb}/rest/v1/{table}", headers={**headers, "Prefer": "count=exact"},
              params={"select": "*", "limit": 1})
    if r.status_code != 200:
        return -1  # 비200 = 차단(정상)
    cr = r.headers.get("content-range", "?/?").split("/")[-1]
    return int(cr) if cr.isdigit() else 0


def main() -> None:
    env = _env()
    sb, anon, svc = env["SUPABASE_URL"], env["SUPABASE_KEY"], env["SUPABASE_SERVICE_ROLE_KEY"]
    c = httpx.Client(timeout=30)
    adm = {"apikey": svc, "Authorization": f"Bearer {svc}"}

    spec = c.get(f"{sb}/rest/v1/", headers=adm).json()
    tables = sorted(t for t in spec.get("definitions", {}) if t not in _SYS_TABLES)

    tok = c.post(f"{sb}/auth/v1/token?grant_type=password",
                 headers={"apikey": anon, "Content-Type": "application/json"},
                 json={"email": "test1@freshrun.com", "password": "test1234"}).json()["access_token"]
    ah = {"apikey": anon, "Authorization": f"Bearer {tok}"}

    exposed, empty, ok = [], [], []
    for t in tables:
        anon_n = _count(c, sb, t, ah)
        if anon_n > 0:
            exposed.append(t)
        elif anon_n == 0 and _count(c, sb, t, adm) == 0:
            empty.append(t)  # 빈 테이블 — 임시 행 프로브가 필요할 수 있음
        else:
            ok.append(t)

    print(f"전 {len(tables)}개 테이블 검증")
    # 확장 소유 시스템 테이블 — PostGIS가 소유해 우리가 RLS를 못 켠다(소유권 없음).
    # Advisor에 'rls_disabled'로 뜨지만 유저 데이터 무관(공개 좌표계 참조). anon
    # 쓰기 권한은 REVOKE로 차단(db/2026-07-15_spatial_ref_sys_revoke.sql). 우리
    # 앱은 이 테이블·PostGIS 함수를 직접 쓰지 않음 → 제외해도 커버리지 손실 0.
    print(f"⚙️  _SYS_TABLES 제외(확장 소유, RLS enable 불가·무해): "
          f"{', '.join(sorted(_SYS_TABLES))}")
    print(f"🟢 RLS deny 확정 (svc 데이터 有 & anon 0/차단): {len(ok)}")
    if empty:
        print(f"⚪ 빈 테이블 (판정 보류 — 데이터 없어 0): {', '.join(empty)}")
    if exposed:
        print(f"\n🔴 노출 {len(exposed)}개 — RLS 미enable:\n  " + "\n  ".join(exposed))
        sys.exit(1)
    print("\n✅ anon 직접 조회로 실데이터 노출되는 테이블 0 — RLS 백스톱 전수 정상")


if __name__ == "__main__":
    main()
