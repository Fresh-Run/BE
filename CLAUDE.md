# CLAUDE.md — 이 프로젝트에서 Claude가 따라야 할 규칙

## 비밀 키 / 자격증명 보호

- `.env`에 있는 모든 키(`SUPABASE_SERVICE_ROLE_KEY`, `OPENAI_API_KEY`, `KAKAO_REST_API_KEY`, `TMAP_APP_KEY`, `SUPABASE_KEY` 등)는 **절대 터미널 출력이나 대화에 표시하지 않는다.**
- `.env` 전체를 `cat`으로 출력하는 명령을 실행하지 않는다. 특정 설정값이 필요하면 키 이름만 grep하거나 코드에서 조용히 읽는다.
- 테스트·스크립트에서 키가 필요할 때는 `os.environ` 또는 파일에서 읽어 변수에 담고, 그 값을 `print`하거나 로그에 남기지 않는다.
- 사용자에게 결과를 설명할 때도 키 값 자체는 언급하지 않는다.

## 자동 테스트 규칙

- 새 기능을 구현한 뒤에는 `tests/test_<기능명>_integration.py` 형식의 통합 테스트 스크립트를 만들고 직접 실행해 전부 통과하는 것을 확인한다.
- 테스트 스크립트는 Supabase admin API로 임시 유저를 생성하고, 테스트 종료 후 생성한 데이터(유저·크루·기록 등)를 모두 삭제한다.
- 각 단계마다 assert로 기댓값을 검증하고, 실패 시 원인을 찾아 수정 후 재실행한다. 전부 통과할 때까지 반복한다.

## 일반 개발 규칙

- 백엔드는 FastAPI + supabase-py(service_role 클라이언트) 구조다. 데이터 접근은 항상 `get_supabase_admin()`을 쓴다.
- supabase-py는 동기 라이브러리이므로 모든 호출은 `asyncio.to_thread`로 감싼다.
- 경로 순서: 고정 경로(`/routes/public`, `/crews/mine`, `/crews/{id}/members`, `/crews/{id}/ranking`)는 반드시 패턴 경로(`/routes/{id}`, `/crews/{id}`)보다 앞에 선언한다.
- 컬럼 이름은 실제 테이블과 반드시 일치시킨다. 코드 작성 전 `run_service.py` 등 기존 서비스에서 실제 사용 중인 컬럼명을 먼저 확인한다.
