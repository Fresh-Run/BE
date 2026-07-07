# DB 백업 · 복원

Supabase 무료 티어는 **자동 백업이 없다**(Pro부터 일일 PITR). 그래서 `public`
스키마(우리 앱 데이터 전부)를 주 1회 논리 백업한다. 워크플로:
[`.github/workflows/db-backup.yml`](../.github/workflows/db-backup.yml).

## 설계 요약 (왜 이렇게)

| 항목 | 선택 | 이유 |
|---|---|---|
| 실행 위치 | **GitHub Actions schedule** | 이미 쓰는 인프라·머신 독립·비공개 repo 무료분 충분. 로컬 크론은 맥 상시가동 필요, Fly 머신 내부는 512MB OOM·앱 다운 시 백업도 정지 |
| 방식 | **pg_dump `--schema=public`** | 단일 아티팩트·표준툴. `supabase db dump`는 role/schema/data 3파일+CLI 필요. public만 뜨면 이메일(auth 관리)은 제외돼 PII도 축소 |
| 연결 | **Session pooler(5432)** | GH 러너는 IPv4 전용 — 직결 `db.<ref>.supabase.co`는 IPv6라 불가. pg_dump는 session 모드 필요(transaction 6543 불가) |
| 저장 | **Actions artifacts, 90일 롤링** | repo 커밋은 용량·PII 영구화라 부적합. 아티팩트는 `retention-days`로 자동 만료(~12개 롤링) |
| 주기 | **주 1회**(일 18:00 UTC = 월 03:00 KST) + 수동(`workflow_dispatch`) | 저트래픽대 |
| 검증 | gzip 무결성 + 크기>1KB + `public.runs` 존재 | 가짜(0바이트) 백업이 초록으로 지나가는 것 방지 — 하나라도 실패면 job 실패 |

**백업 범위 주의**: `public` 스키마만 뜬다(runs·crews·routes·profiles·follows 등
앱 데이터 전부). **`auth.users`(이메일/비밀번호)는 포함 안 됨** — Supabase가 자체
관리하며 대시보드 Authentication에서 별도 관리/내보내기. 완전 DR(계정까지 복구)이
필요해지면 출시 때 Supabase **Pro(PITR)** 로 승급(DEPLOY_CHECKLIST F절).

## 최초 1회 설정 (사람 손)

1. Supabase 대시보드 → **Project Settings → Database → Connection string** →
   **"Session pooler"** 탭 선택 (Mode: Session, 포트 **5432**). URI를 복사한다.
   형식: `postgresql://postgres.<ref>:<비밀번호>@aws-0-<region>.pooler.supabase.com:5432/postgres`
   - 비밀번호를 잊었으면 같은 화면의 **Reset database password** 로 재발급(앱 무영향 —
     앱은 service_role 키로 접속하지 DB 비번을 안 씀).
2. GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**
   → 이름 **`SUPABASE_DB_URL`**, 값 = 위 URI 전체.
3. **Actions 탭 → DB Backup → Run workflow** 로 수동 실행 → 초록 + 아티팩트 생성 확인.

## 백업 받기 (다운로드)

Actions → 해당 DB Backup 실행 → 하단 **Artifacts** 에서 `freshrun-public-<날짜>.sql.gz`
다운로드. (90일 지나면 자동 삭제되니 장기 보관이 필요하면 개별 다운로드해 보관)

## 복원 절차

`.sql.gz`는 plain SQL을 gzip한 것. 대상 DB에 그대로 흘려넣으면 된다.
**주의**: 덤프에 `DROP ... IF EXISTS`(--clean)가 있어 대상의 기존 public 객체를
교체한다. 프로덕션에 실수로 쏘지 말 것.

```bash
# 0) 준비: 복원 대상의 Session pooler 연결 URI (새 Supabase 프로젝트 또는 로컬 PG)
TARGET="postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres"

# 1) 무결성 먼저 확인
gzip -t freshrun-public-<날짜>.sql.gz && echo "gzip OK"

# 2) 내용 미리보기(선택) — 어떤 테이블이 들었는지
zcat freshrun-public-<날짜>.sql.gz | grep -E "CREATE TABLE" | head

# 3) 복원 실행
zcat freshrun-public-<날짜>.sql.gz | psql "$TARGET"
```

- **부분 복원**(특정 테이블만): `zcat ... | grep -A9999 "COPY public.runs"` 식으로
  잘라 쓰거나, 향후 필요하면 커스텀 포맷(`-Fc`)+`pg_restore -t`로 전환.
- **auth.users FK**: `public.*.user_id`는 `auth.users(id)`를 참조한다. 완전 새 프로젝트로
  복원 시 해당 유저가 없으면 FK 위반이 날 수 있다 — 같은 프로젝트로의 롤백(계정 유지)이
  기본 시나리오이며, 계정까지 사라진 경우엔 Supabase auth 복구가 선행돼야 한다.

## 운영 메모

- **검증 실패 = 즉시 인지**: 크론이 빨간 X면 백업이 무효란 뜻 → 원인(대개 커넥션 URL
  만료/비번 변경) 확인. 초록인데도 안심 말고 분기 1회는 실제 복원 리허설 권장.
- **스케줄 유지**: GitHub은 repo가 60일 무활동이면 스케줄 워크플로를 자동 비활성화한다.
  개발이 이어지면 자연 유지되지만, 장기 휴면 시 아무 커밋이나 하면 재활성.
- **오프사이트 업그레이드(선택)**: 아티팩트는 GitHub 한 곳뿐. 더 견고히 하려면 스텝을
  추가해 Cloudflare R2/S3/Backblaze로 업로드(무료 티어 존재). 지금 규모엔 불필요.
