-- 크루 둘러보기(당근식): 행정구역 + 대표좌표 + 카드 태그
-- 적용: Supabase SQL Editor에서 [APPLY] 실행 (실행 완료됨)
-- area는 유지(표시용 동네명·검색). 전부 nullable/기본값이라 non-breaking.

-- ─────────────────────────────────────────────────────────────
-- [APPLY]
-- ─────────────────────────────────────────────────────────────
alter table public.crews
  add column if not exists sido    text,               -- "서울특별시" (17개 광역 전체명)
  add column if not exists sigungu text,               -- "성동구" (시군구명, 자유 문자열)
  add column if not exists lat     double precision,   -- 대표 좌표 (모임장소/활동중심)
  add column if not exists lng     double precision,
  add column if not exists tags    text[] not null default '{}';  -- 카드 태그 (서버 정의 어휘)

-- sido는 17개 광역만 (서버 Pydantic Literal과 이중 방어). NULL 허용(기존/미설정 크루).
alter table public.crews
  add constraint crews_sido_check check (
    sido is null or sido in (
      '서울특별시','부산광역시','대구광역시','인천광역시','광주광역시',
      '대전광역시','울산광역시','세종특별자치시','경기도','강원특별자치도',
      '충청북도','충청남도','전북특별자치도','전라남도','경상북도',
      '경상남도','제주특별자치도'
    )
  );
-- tags 값 검증은 앱 레이어(Pydantic Literal 13종)에서 — 배열 원소 CHECK는 과함.

-- ─────────────────────────────────────────────────────────────
-- [ROLLBACK]
-- ─────────────────────────────────────────────────────────────
-- alter table public.crews drop constraint if exists crews_sido_check;
-- alter table public.crews drop column if exists tags;
-- alter table public.crews drop column if exists lng;
-- alter table public.crews drop column if exists lat;
-- alter table public.crews drop column if exists sigungu;
-- alter table public.crews drop column if exists sido;
