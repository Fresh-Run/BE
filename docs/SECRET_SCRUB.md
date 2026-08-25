# SECRET_SCRUB.md — git 히스토리 시크릿 제거 절차

> **긴급도: 낮음(위생).** 대상 노출 키(초기 커밋 `e9161a7`
> `tests/test_ranking_integration.py`의 옛 service_role)는 **2026-07-08 회전 완료**로
> **이미 무효**다(신규 `sb_secret_` 키 설명에 "old key leaked in git history" 명기, 서버는
> 신규 키 사용 중). 따라서 이 문서는 **죽은 시크릿의 잔존 텍스트를 히스토리에서 지우는
> 방어심화**이지, 활성 침해 대응이 아니다.
>
> **실행 트리거: 출시 전 위생 정리 단계.** 지금 당장 강제 아님.
>
> ⚠️ **filter-repo 실행은 오너 명시 승인 필수.** 히스토리 재작성은 되돌리기 어렵고
> (전 커밋 해시 변경) 모든 클론을 깨뜨린다. 이 문서는 절차 설계만 — Claude는 승인 없이
> 실행하지 않는다.

## 0. 사전 확인 (실행 전)

- [ ] 노출 키가 실제로 회전·무효인지 재확인(Supabase 콘솔 API Keys — 옛 키 revoked/미표시).
      **혹시라도 살아있으면 스크럽 전에 회전이 먼저**(스크럽은 회전을 대체하지 않는다).
- [ ] 진행 중 열린 PR·미머지 브랜치 목록화 — 히스토리 재작성 후 전부 재베이스/재생성 필요.
- [ ] 최신 상태 백업: `git clone --mirror <origin> freshrun-backup-<날짜>` (되돌림 안전망).

## 1. 스크럽 대상 식별

```
# 값 노출 금지 — 마스킹 출력. 유입 커밋·파일 확인
git log --all -p \
  | grep -E "sb_(secret|publishable)_|eyJ[A-Za-z0-9_-]{30,}|service_role|sk-[A-Za-z0-9]{16,}|AIza" \
  | sed -E 's/(.{40}).*/\1.../'
git log --all --oneline -S "<리터럴 일부>"   # 유입 커밋 추적
```
- 알려진 대상: `tests/test_ranking_integration.py` — service_role JWT(`eyJ…`) + `sb_secret_…`
  (초기 `e9161a7` 유입, `2e4c467`에서 HEAD 제거·히스토리 잔존).
- `.env.example`의 `your-…` placeholder는 **대상 아님**(실값 아님).

## 2. filter-repo 실행 (오너 승인 후, --mirror 사본에서)

```
pip install git-filter-repo
git clone --mirror <origin> freshrun-scrub && cd freshrun-scrub

# 대체 규칙 파일 — 실값 대신 리터럴/정규식만 기술(화면 노출 최소화)
cat > repl.txt <<'EOF'
<노출된 sb_secret 값>==>***REMOVED***
regex:eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXV[A-Za-z0-9_.-]+==>***REMOVED***
EOF

git filter-repo --replace-text repl.txt
git push --force --all
git push --force --tags
```
- `--replace-text`는 값만 치환(파일·커밋 구조 보존) — 파일은 HEAD에 이미 키 없이 존재하므로
  파일 삭제(`--invert-paths`)가 아니라 **텍스트 치환**이 정답.
- 실행 후 `repl.txt`는 즉시 삭제(노출값 포함).

## 3. 클론 재동기화 공지 (Ivan 포함 — 필수)

히스토리 재작성 후 **기존 클론은 rebase 금지, 삭제 후 재클론**(구클론의 `objects/`·reflog에
죽은 키가 그대로 남는다). 공지 문안:

> FreshRun 백엔드 git 히스토리를 재작성했습니다(과거 커밋의 무효화된 시크릿 텍스트 제거).
> **기존 로컬 클론을 삭제하고 새로 clone 해주세요.** 기존 클론에서 pull/rebase 하지 마세요
> (충돌·죽은 오브젝트 잔존). 미머지 작업 있으면 재클론 후 cherry-pick 하세요.

- 파트너 클론 드리프트 전례(Ivan 9커밋, 2026-08-04) — 재클론 확인까지 추적.

## 4. GitHub 캐시 purge 요청

force-push 후에도 GitHub은 **도달 불가 커밋을 캐시에 보관**할 수 있다(fork·PR ref 경유
노출 가능). → GitHub Support에 **"rewritten history, purge cached views/unreachable commits"**
요청. 단 best-effort — **죽은 키라 실피해 0**, 이건 흔적 제거 차원.

## 5. 완료 후

- [ ] §1 스캔 재실행 → 매치 0 확인(마스킹 출력 비어야 함).
- [ ] 열린 PR·브랜치 재생성.
- [ ] `docs/AUDIT_BACKLOG.md`·`IAP_LAUNCH_CHECKLIST.md`의 스크럽 항목 완료 표기.

## 참고 — 근본 원인·재발 방지

- 원인: 초기 커밋에 테스트용 실키 하드코딩. §A5 pre-commit 검사(`--cached`)는 스테이지만
  봐서 이미 커밋된 히스토리를 못 잡음 → 7월 노출 미검출.
- 방지: CLAUDE.md §A5 + `freshrun-audit` 스킬 "히스토리 시크릿 스캔" 절(정기·출시 전
  전수 스캔). 테스트 키는 항상 `os.environ`에서 로드(하드코딩 금지 — 비밀 키 보호 절).
