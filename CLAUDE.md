# CLAUDE.md — 이 프로젝트에서 Claude가 따라야 할 규칙

> 이 파일은 항상 로드된다 — **핵심 판단만** 여기 둔다. 절차 상세는
> `.claude/skills/`의 4개 스킬에 있다(맨 아래 "스킬" 절 참조).
> 규칙끼리 충돌하면 **더 구체적인 쪽**을 따른다.

## 모델별 작업 배분 (먼저 판단)

- **설계·감사·novel 판단**(잠금 전략, BM, 스키마 설계): Opus 이상.
- **구현·버그픽스·기능 확장**(설계 문서가 이미 있을 때): Sonnet 가능.
- **시드·문서 갱신·단순 반복·백필**: Haiku 가능.
- 원칙: **설계 문서 없는 큰 작업을 Sonnet/Haiku로 시작하지 말 것** — 설계만
  상위 모델로 먼저 받아 문서화한 뒤 하위 모델이 구현.

## 완료의 정의 — 아래 전부 충족 전엔 "완료" 보고 금지

1. 신규 통합 테스트 + 관련 기존 회귀 재실행, **전부 통과**(실패 시 스스로 고쳐 재실행).
2. 테스트는 상태코드만이 아니라 **DB 부수효과까지 assert**(행 생성/삭제/카운트).
3. `db/`에 SQL 파일 기록 — `[APPLY]`+`[ROLLBACK]` 페어, 실행 여부 주석.
4. `docs/API_GUIDE.md` 갱신 — 프론트가 소비하는 데이터면 **소비 규칙 표**까지
   (어느 필드로 무엇을 하는지).
5. 커밋 전 키 패턴 검사 clean:
   `git grep --cached -E "sk-[A-Za-z0-9]{16,}|eyJ[A-Za-z0-9_-]{30,}|AIza|sb_(secret|publishable)_"`
   (【제안】 `sb_*`는 Supabase 새 키 형식 — 구패턴이 못 잡은 실누출 1건에서 추가)
6. 임시 테스트 데이터 정리, **키·초대코드 값 화면 출력 0**.
7. 스테이징 영향 시: `fly deploy --app freshrun-api` + `/health` + 해당 기능
   스모크 1사이클(→ `freshrun-deploy` 스킬).
8. 보고 형식: **통과 목록 / 변경 파일 표 / 추측했던 지점 명시(판단 플래그)**.

## 검증 우선 — 추측 금지

- **스키마(컬럼·타입·제약)는 `db/*.sql`을 믿지 마라** — 초기 커밋분이 파일에
  없다(스키마 드리프트 실사례: `nickname` unique). `information_schema`/
  `pg_constraint` **실조회**로 확인. 컬럼명은 `run_service.py` 등 실사용 코드 우선.
- **성능은 원인 추측으로 고치지 마라** — 구간별 타이머 계측 먼저(실사례: 범인이
  T-map이 아니라 Gemini thinking, 34s→3s).
- **버그 리포트는 재현 먼저** — 최신 main + 서버 재시작 후 재현 시도. 재현 불가면
  "리포터 측 구코드 가능성"으로 결론(실사례 3건).
- **문서와 코드가 다르면 코드가 진실** — 문서를 고치고 보고.
- **확신 90% 미만인 정책/BM/스키마 판단은 진행 금지** — 선택지+추천+근거로
  사용자에게 질문.
- 【제안】 **공유 로직은 단일 소스** — 같은 계산(예: `_week_start_utc`)을 두 곳에
  복붙하지 말고 한 곳을 import(L7 드리프트 제거 실사례).

## 알려진 함정 (이 프로젝트에서 실제로 밟은 것들)

- `notifications.target_id`는 **uuid 타입** — raw SQL에서 text와 비교 시 캐스팅
  에러. PostgREST 경유는 자동 코어싱되므로 앱 코드는 무관.
- 【제안】 **새 알림 타입 추가 시 `notifications_type_check` CHECK 제약을
  drop→재생성**해야 한다(현재 10종 열거). 타입만 코드에 넣고 제약을 안 고치면
  삽입이 23514로 실패(run_comments 실사례).
- **Supabase 외부 접속**(GitHub Actions 등 IPv4): **Session pooler(5432)만**.
  direct(`db.*`)는 IPv6, transaction pooler(6543)는 pg_dump 불가.
- **Gemini**: thinking 기본 ON → 구조화 호출(function calling)은
  `reasoning_effort="none"` 필수. 자연어 생성물(코치·인사이트)은 thinking 유지.
  선불 크레딧 소진 시 429 RESOURCE_EXHAUSTED → 서버는 502로 변환, Sentry에
  캡처됨(체인에 RateLimitError).
- **httpx INFO 로그가 요청 URL 전체**(쿼리스트링의 키 포함)를 기록 — 로그 레벨
  유지, 민감값은 쿼리스트링 금지(POST body).
- **uvicorn은 git pull로 코드가 안 바뀐다** — 수정 후 반드시 재시작. 테스트
  실패 시 "서버가 구코드" 가능성을 먼저 의심.
- Python `round()`는 banker's rounding(1.25→1.2).
- **신규 테이블은 반드시 `enable row level security`**(정책 없이 — deny-by-default
  백스톱, 전 테이블 표준. 앱은 service_role로만 접근).
- GH Actions schedule은 repo **60일 무활동 시 비활성**.
- **시간대**: DB는 UTC 저장, 주/월 경계는 **KST 기준** 계산. 클라이언트 naive
  datetime은 422 거부.
- 【제안】 **Fly는 재배포 때 HA용 머신 2대를 자동 생성** → 예산(1대)은 항상
  `fly scale count 1`로 축소.
- **데모 계정**: test1(premium, 수동)·test2·demo1~5, 비번 전부 `test1234`.
  시드는 멱등(감지-스킵)·삭제 금지.
- supabase-py 동기 httpx의 **유휴 HTTP/2 keepalive 연결**이 상대편 idle timeout
  후 재사용되며 **간헐 502** 유발 가능 — 자가 회복형(재시도 1초 내 성공). 상세와
  대응 카드는 `docs/AUDIT_BACKLOG.md` "운영 관측" 절.

## 하위 호환 — additive가 기본

- **새 응답 필드**: 기본값 있는 Optional로(non-breaking).
- **새 컬럼**: nullable 또는 default로. 소급이 필요하면 "노출 보존" 원칙 —
  예: `visibility`를 default `'followers'`로 추가(기존 백필) 후
  `set default 'public'`(신규만). → 상세는 `freshrun-sql` 스킬.
- **기존 엔드포인트 동작 변경 금지**. 경로 변경이 필요하면 신규 추가 + 레거시
  유지(실사례: preview-by-code POST 병행).
- **에러 계약 불변**: 내부 구현이 바뀌어도(RPC 전환 등) 패자가 받는 상태코드 유지.
- 【제안】 **best-effort 정리**(예약 해제·알림 삭제)는 실패해도 다음 리셋/회수로
  복구되므로 치명 처리하지 말고 로그만.

## 일반 개발 규칙

- 백엔드는 **FastAPI + supabase-py(service_role)**. 데이터 접근은 항상
  `get_supabase_admin()`.
- supabase-py는 동기 라이브러리 → 모든 호출을 **`asyncio.to_thread`로 감싼다**.
- **경로 순서**: 고정 경로(`/routes/public`, `/crews/mine`, `/crews/{id}/members`,
  `/crews/{id}/ranking`)는 반드시 패턴 경로(`/routes/{id}`, `/crews/{id}`)보다
  앞에 선언.
- 앱 레벨 트랜잭션이 없다(PostgREST) — **원자성이 필요한 다단계는 Postgres
  RPC로 내린다**(→ `freshrun-sql`). RPC로 못 묶는 다단계는 커밋 지점을 마지막에
  배치 + 실패 시 보상 복구(【제안】 L5 transfer_ownership 실사례).

## 자동 테스트 규칙

- 새 기능 뒤 `tests/test_<기능명>_integration.py`를 만들고 **직접 실행**해 전부
  통과 확인. Supabase admin API로 임시 유저 생성 → 종료 후 생성 데이터 전부 삭제.
- 각 단계 `assert`로 기댓값 검증, 실패 시 원인 찾아 수정 후 재실행(통과까지 반복).

**테스트 레시피** (판단을 절차로):
- **프라이버시 필드**는 이중 검증: 응답에 키 부재 **+** 값 문자열이 응답 전체에 부재.
- **권한 차단은 403이 아니라 404**(존재 은닉)가 이 프로젝트 표준 — 테스트도 404 기대.
- **레이스 검증**: mock 순차 패치는 DB 원자성에 무효. `asyncio.gather` 실동시 +
  불변식 assert(정원 초과 0건 같은). → `freshrun-audit`.
- **가시성 기능**은 매트릭스로: 상태 종류 × 관계 종류 × 노출 경로 전수.
- **Gemini 실호출 최소화**(회당 ~2원): 결정론/mock으로 커버, 실호출은 1~2회
  스모크만. 비용이 승인분 초과 시 사유와 함께 보고.
- 실패 시 **"코드 버그 / 테스트 논리 오류 / 환경(구코드·연결)"** 구분해 보고.

## 비밀 키 / 자격증명 보호

- `.env`의 모든 키(`SUPABASE_SERVICE_ROLE_KEY`, `OPENAI_API_KEY`,
  `KAKAO_REST_API_KEY`, `TMAP_APP_KEY`, `SUPABASE_KEY` 등)는 **절대 터미널
  출력이나 대화에 표시하지 않는다.**
- `.env` 전체를 `cat`하지 않는다. 필요하면 키 이름만 grep하거나 코드에서 조용히 읽는다.
- 테스트·스크립트에서 키는 `os.environ`/파일에서 변수에 담고 `print`·로그 금지.
- 사용자 설명 시에도 키 값 자체는 언급하지 않는다.

## 보고 규율

- 계획에서 벗어난 판단(스킵·대체·범위 조정)은 반드시 **"판단 플래그"**로 명시 —
  조용히 하지 마라.
- 확인 못 한 것은 **"검증 불가"**로 표기(완료인 척 금지).
- 실패 후 통과한 경우 **실패 원인 1줄 분석** 포함(같은 구멍 재발 방지).

## 스킬 (절차 상세는 여기)

- **freshrun-feature** — 새 기능/엔드포인트/테이블 추가 시.
- **freshrun-sql** — SQL/마이그레이션/RPC 작성 시.
- **freshrun-audit** — 감사/보안 점검/버그 사냥 시.
- **freshrun-deploy** — 배포/스테이징 반영/서버 이슈 시.
