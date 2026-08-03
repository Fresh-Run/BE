"""
Unit: 추천 러너 rank-select 후 shuffle (2026-08-03, Ivan 트리거 앞당김 승인)

①셔플돼도 집합 동일(구성원 불변) ②시드 상이 반복 호출 → 순서 실변화(결정적)
③limit 선발 경로 불변. DB 무접촉(전부 mock)·잔여 0.

Run: python tests/test_suggested_shuffle.py
"""
import asyncio, random, sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import AsyncMock, patch
from app.services import profile_service as ps

PROFS = [{"user_id": f"u{i}", "nickname": f"n{i}", "avatar_url": None,
          "bio": "b", "created_at": f"2026-07-{10+i:02d}"} for i in range(8)]

class _Res:
    def __init__(self, data): self.data = data

def fake_thread(fn):
    async def _run(f): return f()
    return _run

async def main():
    calls = {"n": 0}
    def table_router(name):
        class Q:
            def __getattr__(self, _):
                def m(*a, **k): return self
                return m
            def execute(self):
                calls["n"] += 1
                if calls["n"] in (1, 4):   # profiles / (재호출) profiles
                    pass
                return _Res(PROFS if name == "profiles" else [])
        return Q()
    class SB:
        def table(self, name): return table_router(name)
    with patch.object(ps, "get_supabase_admin", lambda: SB()), \
         patch.object(ps, "blocked_ids_batch", AsyncMock(return_value=set())), \
         patch.object(ps, "visible_owners", AsyncMock(return_value={p["user_id"] for p in PROFS})):
        random.seed(1)
        a = await ps.suggested_users("viewer", limit=8)
        random.seed(2)
        b = await ps.suggested_users("viewer", limit=8)
    ids_a = [x["user_id"] for x in a]; ids_b = [x["user_id"] for x in b]
    assert set(ids_a) == set(ids_b) == {p["user_id"] for p in PROFS}, "집합 동일"
    assert ids_a != ids_b, f"시드 상이 → 순서 변화: {ids_a} vs {ids_b}"
    lim = await_none = None
    with patch.object(ps, "get_supabase_admin", lambda: SB()), \
         patch.object(ps, "blocked_ids_batch", AsyncMock(return_value=set())), \
         patch.object(ps, "visible_owners", AsyncMock(return_value=set())):
        random.seed(3)
        c = await ps.suggested_users("viewer", limit=3)
    assert len(c) == 3, "limit 선발 불변"
    print("집합 동일 ✓ 순서 가변(시드 결정적) ✓ limit 3 선발 ✓")

asyncio.run(main())

print("\n" + "=" * 50 + "\n  ALL TESTS PASSED\n" + "=" * 50)
