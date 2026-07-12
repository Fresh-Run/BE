-- RLS 드리프트 소급: 초기 커밋 테이블 10종 enable row level security.
-- 왜: 이 10종이 RLS 미enable이라 anon key + 유저 JWT로 직접 조회 시 타인
-- 데이터가 노출됨(2026-07-12 전수 실증). 앱은 service_role로만 접근하므로
-- 정책 없이 enable하면 deny 백스톱만 켜져 앱 동작 무영향(신규 테이블 표준과
-- 동일 — push_tokens 등에서 검증된 패턴). enable은 멱등(이미 켜진 것에 무해).
-- 미실행 — 사용자가 SQL Editor에서 실행.

-- [APPLY]
alter table public.profiles         enable row level security;
alter table public.runs             enable row level security;
alter table public.routes           enable row level security;
alter table public.crews            enable row level security;
alter table public.crew_members     enable row level security;
alter table public.crew_challenges  enable row level security;
alter table public.notifications    enable row level security;
alter table public.route_comments   enable row level security;
alter table public.route_likes      enable row level security;
alter table public.preferences      enable row level security;

-- 실행 후 확인 (rowsecurity 전부 t 이어야):
-- select tablename, rowsecurity from pg_tables where schemaname = 'public'
--   and tablename in ('profiles','runs','routes','crews','crew_members',
--   'crew_challenges','notifications','route_comments','route_likes','preferences')
--   order by tablename;

-- [ROLLBACK] (원복은 노출 재개 — 권장 안 함, 문제 시 개별 테이블만)
-- alter table public.profiles disable row level security;
-- ... (필요 테이블만 disable)
