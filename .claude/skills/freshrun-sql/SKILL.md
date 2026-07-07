---
name: freshrun-sql
description: FreshRun DB의 SQL·마이그레이션·RPC를 작성할 때 사용. APPLY/ROLLBACK 페어 양식, RLS enable 표준, 타입 확인(uuid 캐스팅 함정), 백필 2단계 default 트릭, RPC 잠금 선택 기준(FOR UPDATE vs advisory lock)을 담는다. "마이그레이션", "SQL 작성", "RPC", "테이블 변경", "제약 추가" 요청에서 발동.
---

# SQL / 마이그레이션 / RPC 작성

**대전제:** 앱 레벨 트랜잭션이 없다(supabase-py=PostgREST). 원자성이 필요하면
Postgres 함수(RPC)로 내린다. 우리는 DB에 직접 DDL을 치지 않는다 — SQL 파일을
`db/`에 기록하고 **사용자가 Supabase SQL Editor에서 실행**한다.

## 파일 양식 — `db/<날짜>_<주제>.sql`

상단 주석에 "무엇을·왜", 그리고 **실행 여부**("적용됨(사용자 실행)" / "새 환경에서만")를
남긴다. 본문은 `[APPLY]`와 `[ROLLBACK]` 두 섹션(롤백은 주석 처리해 보관):

```sql
-- <제목>: 무엇을 · 왜. 적용됨(사용자 실행 — RLS enable 포함).

-- [APPLY]
create table if not exists public.<t> ( ... );
create index if not exists <t>_..._idx on public.<t> (...);
alter table public.<t> enable row level security;   -- 표준: 정책 없이 deny-by-default

-- [ROLLBACK]
-- drop table if exists public.<t>;
```

- 모든 DDL은 idempotent(`if not exists` / `if exists` / `create or replace`).
- **RLS enable은 신규 테이블 전 표준** — 앱은 service_role로만 접근하므로 정책
  없이도 동작하고, anon/authenticated 직접 접근을 막는 백스톱이 된다.

## 타입 확인 — 캐스팅 함정

- **`db/*.sql`을 스키마의 진실로 믿지 마라** — 초기 커밋분이 파일에 없다(드리프트
  실사례: `profiles.nickname` unique가 파일엔 없는데 DB엔 있음). 작성 전
  `information_schema.columns` / `pg_constraint` 실조회로 타입·제약 확인.
- **`notifications.target_id`는 uuid** — raw SQL에서 text와 비교하면 캐스팅
  에러. `where target_id = _x::uuid`처럼 명시 캐스팅. (PostgREST 경유는 자동
  코어싱 → 앱 코드는 무관, raw SQL/RPC에서만 주의.)
- **알림 타입 추가 시** `notifications_type_check` CHECK 제약을 `drop`→`add`로
  재작성(현재 10종 열거). 타입만 넣고 제약을 안 고치면 삽입이 23514로 실패.

## 백필 — 2단계 default 트릭 (노출 보존)

기존 행의 노출/의미를 보존하며 신규 기본값을 바꿔야 할 때:

```sql
-- 1) 기존 행이 보존값을 갖도록 default로 추가(기존 전부 백필됨)
alter table public.runs add column visibility text not null default 'followers'
  check (visibility in ('public','followers','private'));
-- 2) 신규 행만 새 기본값으로
alter table public.runs alter column visibility set default 'public';
```

## RPC 잠금 선택 기준 (→ `docs/RACE_FIX_DESIGN.md`)

check-then-act 레이스는 조건부 INSERT로 못 막는다(MVCC: 동시 미커밋 INSERT가
count에 안 잡힘 → stale). **명시적 잠금으로 직렬화**해야 count가 정확하다.

| 자원 형태 | 잠금 | 예시 |
|---|---|---|
| **잠글 실제 행이 있음** | `SELECT ... FOR UPDATE` | 크루 정원 = `crews` 1행 잠금 → per-crew 직렬화(동시 삭제도 방어) — `admit_crew_member` |
| **"개수"가 자원**(잠글 단일 행 없음) | `pg_advisory_xact_lock(hashtext('<도메인>:'||_id))` | 크루 생성 한도·주간 AI 쿼터 — `create_crew_limited`, `reserve_ai_generation` |

- advisory lock은 **xact 스코프**(커밋 시 자동 해제). 잠금 안에 외부 호출
  (Gemini/T-map)을 넣지 마라 — 느린 구간이 직렬화된다. 예: AI 쿼터는 Gemini
  **전에** 슬롯 예약(reserve) → 실패 시 해제(release, best-effort).
- 다필드 INSERT는 **jsonb + `jsonb_populate_record`**로 받아 시그니처 폭발
  방지(컬럼 추가 시 SQL 무변경).
- 함수는 service_role만 호출 → `SECURITY INVOKER` 기본으로 충분.
- **에러 계약 불변**: RPC 전환 후에도 패자가 받는 상태코드(409/403/429) 유지.

## 배포 순서

RPC/함수는 `CREATE OR REPLACE`라 먼저 적용해도 무해(옛 코드와 공존) →
그 다음 앱 코드 전환. 롤백은 역순(앱 revert 먼저, 함수는 남겨도 무해).
