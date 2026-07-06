-- 저장 화면 확장 + 공개 프로필: runs에 title + visibility
-- 적용됨(사용자 실행). 백필 트릭으로 기존 run은 followers, 신규는 public.

-- [APPLY]
alter table public.runs
  add column if not exists title text,
  add column if not exists visibility text not null default 'followers'
    check (visibility in ('public','followers','private'));

-- 기존 행은 위 default로 이미 'followers'(당시 노출=팔로워/크루 보존).
-- 신규 기본값만 'public'(시안 저장 화면 기본 "전체 공개")으로 전환.
alter table public.runs alter column visibility set default 'public';

-- 공개 프로필의 "그 유저 public run 최신순" 조회 최적화
create index if not exists runs_user_visibility_ran_at_idx
  on public.runs (user_id, visibility, ran_at desc);

-- [ROLLBACK]
-- drop index if exists runs_user_visibility_ran_at_idx;
-- alter table public.runs drop column if exists visibility;
-- alter table public.runs drop column if exists title;
