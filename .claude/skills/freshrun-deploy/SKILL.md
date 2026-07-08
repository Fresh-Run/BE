---
name: freshrun-deploy
description: FreshRun을 Fly.io에 배포하거나 스테이징에 반영·서버 이슈를 볼 때 사용. fly deploy 절차, 스모크 표준(/health + 기능 1사이클), 로그 확인, secrets 규칙, 백업 확인, "푸시≠배포" 명시를 담는다. "배포", "deploy", "스테이징 반영", "서버가 이상", "fly", "로그 확인" 요청에서 발동.
---

# 배포 / 스테이징 / 서버 이슈

앱: `https://freshrun-api.fly.dev`(도쿄 nrt, 머신 1대 512MB, workers=1).
프론트 BASE: `https://freshrun-api.fly.dev/api`. 상세는 `docs/DEPLOY_CHECKLIST.md`.

## 푸시 ≠ 배포

`git push`는 자동 배포가 **아니다**(fly-deploy 워크플로는 `FLY_API_TOKEN`
등록 시에만 동작 — 현재 수동). 코드 변경을 스테이징에 반영하려면 명시적으로:

```
fly deploy --app freshrun-api
```

Docker 빌드 → 이미지 푸시 → 머신 무중단 교체. 코드만 올라가고 secrets는 Fly에
저장된 값 유지. (`fly`는 `/opt/homebrew/bin/fly`)

> ⚠️ **재배포 후 항상 `fly scale count 1 --app freshrun-api`.** Fly는 재배포 때
> HA용으로 2대를 만들려 하는데 예산은 1대 기준.

## 배포 스모크 표준 (배포 직후 1사이클)

1. `GET /health` → `{"status":"ok","environment":"production"}` 확인.
2. test1 로그인 → 변경한 기능의 대표 엔드포인트 1회 실호출(예상 상태코드 확인).
3. 관련 회귀 스모크 1개(예: 알림 기능 배포면 알림 목록 조회).

Gemini 생성(`POST /api/routes/generate`)은 무료 티어 일일 quota에 걸릴 수
있어 배포 게이트가 아니라 별도 확인(코드 검증 완료분이면 통과).

## 로그 / 상태 확인

```
fly status --app freshrun-api            # 머신 started·checks passing·버전
fly logs --app freshrun-api --no-tail    # 최근 로그 한 번(부팅 traceback·secret 누락)
fly logs --app freshrun-api              # 실시간 스트리밍
```

> ⚠️ **fly logs 링버퍼는 짧다** — 시간이 지나면 소실(실사례: 502 예외 클래스
> 미확정). 이슈 발생 시 즉시 `--no-tail`로 캡처해 둘 것. 【제안】 사후 조사는
> Sentry 이벤트(chained exception 상세)가 1차 소스 — 스테이징 라이브.

**문제 시 1분 점검:** ① `fly status`(머신 started/checks) → ② `fly logs`(부팅
traceback = secret 누락이면 여기) → ③ `curl .../health`(200 production).

## secrets 규칙

```
fly secrets list  --app freshrun-api     # 키 이름·다이제스트만(값 안 보임)
fly secrets set KEY=값 --app freshrun-api  # 추가/변경 → 자동 재배포
fly secrets unset KEY --app freshrun-api
```

- **키 값을 화면에 출력하지 않는다**(CLAUDE.md 비밀 키 보호). `set`은 stdin
  파이프/신중히. `list`는 값이 안 보이므로 안전.
- Sentry: `fly secrets set SENTRY_DSN=<dsn>`(미설정 = no-op). IAP 실결제:
  출시 때 `IAP_MODE=apple` + 크리덴셜(현재 미설정 = 503으로 닫힘).

## 백업 확인 (→ `docs/BACKUP.md`)

- 주 1회 GH Actions `pg_dump --schema=public` → Actions artifacts(90일 롤링).
- **검증 실패(빨간 X) = 백업 무효** → 대개 커넥션 URL 만료/비번 변경. 외부
  접속은 **Session pooler(5432)만**(IPv4). GH schedule은 repo 60일 무활동 시
  비활성 → 커밋으로 재활성. `auth.users`(계정)는 백업 범위 밖(Supabase 관리).

## 서버 끄고 켜기

```
fly scale count 0 --app freshrun-api   # 완전 정지(/health도 죽음)
fly scale count 1 --app freshrun-api   # 켜기(설계 기본값)
```
