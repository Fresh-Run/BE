# 셀프 감사 잔여 백로그 (노션 이관용)

2026-07-06 전체 백엔드 감사 발견분. **🎉 전량 처리 완료(2026-07-08)** — H·M·L
소품 + 레이스 묶음(RPC) 모두 소진. 잔여는 μs급 RSVP 마감 창 하나(선택) +
운영 관측 1건(stale HTTP/2 502, 트리거 대기 — 맨 아래).

## 처리 완료

- 배치1: H1 거리/페이스 sanity, H2 챌린지 생성자 삭제 차단, M1 가짜 프라이버시 테스트, M2 datetime tz 필수
- 배치2: M5 max_length, M6 limit 클램프, M9 int 상한, M7 /places 인증
- 배치3: M4 route 학습 소유권, M10 삭제 시 알림 정리, L1 kudos 가시성, L2 iap 크기 상한, L3 502 detail 고정
- **배치4 (L4~L8, 2026-07-08)**:
  - **L4** preview-by-code — **POST(body, 권장) 추가 + GET(레거시) 유지** 병행 경로. POST는 코드가 URL/access log에 안 남음. 프론트 이관용으로 API_GUIDE에 권장 표시.
  - **L5** transfer_ownership — roles 먼저 → owner_id 플립을 커밋 지점으로 재배열 + **실패 시 보상 복구**(원상 복원, best-effort). RPC 없이 창 최소화·자가 치유.
  - **L6** RSVP 집계 — `_tallies`에 crew_members 교집합 필터 → 탈퇴자 표 제외.
  - **L7** `_week_start_utc` — crew_service가 run_service 정의를 import(단일 소스, 드리프트 제거).
  - **L8** FeedbackRequest.tags dedupe+상한(≤20), distance_km `ge=0.01`(1e-308→0.00 방지), decide_join_request **UPDATE 반환행 있을 때만 알림**(동시 승인 이중발송 방지).
  - 미처리 1건: **RSVP 마감 판정 창**(read→check→upsert 사이의 μs 시간 경쟁) — 앱 레벨 체크는 이미 최선이나 완전 차단은 DB 레벨 필요 → 아래 레이스 묶음과 성격 동일, 함께 처리 시점에 검토.

- **배치5 (레이스 묶음 H3·M3·M8, 2026-07-08)** — 설계 `docs/RACE_FIX_DESIGN.md` 대로 Postgres RPC 3종으로 원자화(`db/2026-07-08_race_fix_rpcs.sql`). 에러 계약 불변(패자는 기존 409/403/429):
  - **H3 정원** — `admit_crew_member`(crews 행 `FOR UPDATE` per-crew 직렬화). `_admit_member`가 RPC 호출로 전환.
  - **M8 크루한도** — `create_crew_limited`(owner advisory lock + count, jsonb로 컬럼 자동 매핑). `create_crew` 핸들러가 tier→limit 계산 후 1 RPC.
  - **M3 AI쿼터** — `reserve_ai_generation`(user advisory lock, Gemini 전에 슬롯 예약) + `release_ai_generation`(실패 시 회수, '실패는 무료' 보존). 옛 check/record 게이트 제거.
  - 검증: 실동시(asyncio.gather) 불변식 — 정원 초과 0(동시 5→admit 1·409 4), free 소유 1(동시 2→성공 1·403 1), 주간 count==limit(동시 3→성공 1·429 2). M3는 Gemini mock 불필요(예약이 호출 전 단계).

- **배치6 (감사 2차, 2026-07-11)**: M-A 커서 '+' 미인코딩 관용(tz 위치 공백 복원 + 가이드 인코딩 명시), M-B push_tokens 유저당 10대 상한(등록 시 정리 + 발송 시 최근 10대 — Expo 100개 한도 방어), L-1 탈퇴 시 run-photos 고아 파일 정리(slot×ext 9조합 무조건 remove), L-4 admin self-kick 문구 중립화, L-5 photos 중복 경로 422. H 0건 — 신규 기능 × 가시성 게이트 우회 미발견.

## 잔여 (선택 — μs급, 저위험)

- **[크루 감사 L2] unread 카운트가 차단 발신자 메시지 포함** (`chat_service.py:370` `unread`, 관찰 2026-07-21). 본인 메시지만 제외 → 나를 차단당하게 한 상대가 unread 뱃지를 계속 올릴 수 있음. **현 블록 모델과는 일관**: `list_messages`가 차단 메시지를 완전 은닉이 아니라 content·payload null placeholder로 노출하므로, 카운트에 포함되는 것이 스레드에 보이는 placeholder와 대응. 완전 은닉을 원하면 `unread`(count 쿼리에 sender 차단 제외)와 `list_messages`(placeholder 제거) **양쪽을 함께** 전환해야 — 부분 전환은 count↔목록 불일치. **트리거**: 베타에서 차단자 채팅 스팸 불만 → 블록 모델 재결정(placeholder 유지 vs 완전 은닉) 후 일괄.
- **[크루 감사 L3] 랭킹·챌린지 기여가 멤버 탈퇴 시 소급 감소** (`crew_service.py:1263`·`1201`, 관찰 2026-07-21). `get_weekly_ranking`·`_challenge_contributions`가 **현재 member_ids 기준** 집계라 멤버가 탈퇴하면 그의 과거 verified 기여가 크루 랭킹·챌린지 달성 km에서 즉시 빠짐. **현 정책(current-members-only)과 일관**이고 verified-only 정합과 같은 축이나, 챌린지 달성도가 탈퇴로 줄어드는 게 사용자엔 의외일 수 있음. **트리거**: 챌린지 UX 피드백 → "탈퇴자 기여 스냅샷 보존" 여부 결정(집계 정책 변경이라 랭킹까지 파급 — 신중).

- **[청라 부검 (b)] pitstop 소재 선택이 근접-우선이라 최적-적합 놓침** (`route_service.create_running_route`의 pitstop 해석 → `map_service.search_places`, 관찰 2026-07-22). pitstop_keyword("공원" 등)를 Kakao 검색 **최근접 결과**로 해석 → 시작점서 더 가까운 소품(모래성공원)을 고르고, 거리 대비 명백한 최적 소재(청라호수공원, 시작서 1.3km·둘레 4.8km = 5km 요청의 이상적 순환)를 **미사용**. 실사용 청라 건(2026-07-22 19:02) 실측. **경유지 포함 자체는 정상**(해석된 pitstop은 via로 스냅돼 폴리라인에 9m 이내 포함 — 암묵 보장 확인). 문제는 해석 **랭킹**이 근접-only인 점. **제안**: pitstop 후보를 거리 + 규모/적합도(둘레·타입)로 재랭킹(target 거리에 맞는 순환 소재 우대). **트리거: 베타 중 "코스가 근처 좋은 공원/코스를 안 쓴다" 소재 선택 불만 반복 → 설계 착수.** ⚠️ 청라 부검 (a)(웨이포인트 라벨 hallucination → 중립 라벨+프론트 역지오코딩)는 **별건**: 프론트 계약 변경이라 Ivan 합의 선행·구현 보류(§3 축 B). (b)와 독립.
  - **🔴 트리거 발동 (2026-07-22, 실사용 리포트 감사)**: pitstop "공원"→**"오공김밥 청라호수공원점"(음식점)** 채택 + 폴리라인이 인접 청라호수공원 완전 회피. 파이프라인 전수 추적으로 **의도 사망 지점 2개 확정**: **(b) 1차 사망** — `map_service._kakao_search_places`가 `query="공원" + sort=distance` 텍스트검색에 **`category_group_code` 필터 없음**(`Place.category`는 파싱하나 랭킹·필터 미사용). 랜드마크 상호("…청라호수공원점")를 가진 음식점·카페가 이름 매치+근접으로 상위 도배. **실측(청라 37.5242,126.6303 "공원" 검색 top10)**: [0]모래성공원(84m) [1]와플대학(음식점) [2]나이스가이 [3]바른치킨(음식점) … **전부 "청라호수공원점" 상호 상업시설, 실제 청라호수공원은 top10 밖**. distance-only라 [0]이 소품park(모래성공원) 또는 음식점으로 요동 → 유저는 음식점 케이스 적중. **(d) 2차 확정** — `route_service`가 Gemini의 pitstop 좌표를 **Kakao [0]로 무조건 덮어씀**(적합도 검사 없이 nearest). (c) 프롬프트엔 "공원" 원문 살아있으나 (d)가 폐기. **수정 방향**(설계 착수 대기): (b) 랜드마크형 키워드는 상업 카테고리(FD6 음식점·CE7 카페) 제외 + 적합도 랭킹(이름==키워드/카테고리 매치 우대), (d) Kakao [0] 맹목 채택 대신 카테고리 적합 후보 우선. §3 축 B(청라 저해상도)와도 연동 — Gemini·Kakao 둘 다 실제 공원 좌표를 못 잡음.
  - **✅ 처리 (2026-07-22, 배포 v81)**: (b)(d) 수술 완료 — `Place.category_code` 파싱 + `map_service.rank_places_for_keyword`(랜드마크형=상업 카테고리 제외+적합도 랭킹[실명>상호차용>거리] / 상업형=그 코드만 / 미분류=현행) + route_service가 랭킹 통과 후보 채택(0이면 무필터 최근접 폴백, 502 안 냄). E2E/스모크: 청라 "공원"→**모래성공원(실제 park)** 채택(전엔 음식점). 단위 7케이스·distance 회귀 통과.
  - **[잔여 관찰 — 캐노니컬 랜드마크 미포착] (2026-07-22, 오너 룰링: 베타 수용)**: 위 수술로 **음식점→실제 park** 교정은 확실하나, **"그 동네 대표 공원(청라호수공원)" 자체를 정확히 집지는 못함** — Kakao "공원" 검색 top15에 청라호수공원 미포함(**반경 2km·5km 동일 → 반경 문제 아님**). Gemini·Kakao 둘 다 캐노니컬 랜드마크 좌표를 못 잡는 §3 축 B 영역. **베타 수용 근거**: ① 음식점 오채택은 이미 봉쇄(소품park라도 실제 공원) ② **유저 우회로 존재** — 장소 검색 UI(`GET /places`)로 사용자가 원하는 공원을 직접 지정 가능(pitstop 자동해석에 의존 안 해도 됨). **트리거: 베타에서 "대표 공원/호수를 못 집는다" 류 피드백 반복 → exact-name 2차 검색(키워드로 후보 0/소품만이면 `"{키워드}"` 정확명 재검색) 또는 랜드마크 사전(canonical POI 테이블) 설계 착수.** 지금은 발명 금지.

- **[§3 처방 ③] 뚝섬·여의도 pool 증량 (9→13) 보류** (관찰 2026-07-22, STEP3 실측). 두 좌표는 격자 est_ratio로 중심은 잡히나 **순수 산포 σ가 큼**(뚝섬 σ1.53·여의도 σ1.25, 서빙 8/10). 격자/밴드로 안 잡히고 pool 표본↑만 hit율 개선. **보류 근거**: 현 서빙 8/10에 missed는 배너로 정직 표시(베타 수용 가능), pool +4콜은 **전 생성 비용 +44%**인데 이득은 이 두 좌표 hit율뿐 — 비용 비대칭. **트리거: 베타 실사용 gen_meta에서 고σ 격자 유저의 미스율/불만이 실제 문제로 확인될 때.** 그때 후보로 **격자별 pool**(고σ 격자만 증량 — `_GRID_RATIOS`에 pool 필드 추가) 검토(지금은 발명 금지). 저팽창 격자(목동·강남)는 σ 낮아 격자 보정만으로 충분(hit 9~10/10 실증) — pool 무관.

- **[§3 pitstop overshoot] pitstop이 서빙률을 구조적으로 깎음** (관찰 2026-07-22, 오너 실사용 청라 502×2 계기). **A/B 대조 실측(청라 5km, N=5)**: pitstop 없음 med 5.0·σ0.85·hit5/5 vs pitstop "공원"(모래성공원) med **5.75**·σ**1.36**·hit**3/5**·over 5→19. **pitstop via가 aim에 미반영된 detour를 더해 overshoot** → 캡(6.0) 초과 후보 급증 → 502 꼬리↑(오너 502 2건 snaps 전부 6.5~9.0 캡초과, B arm 분포와 일치). **근인**: 최근접 pitstop(84m 모래성공원)이 시작점 근처 via가 돼 5km 루프 기하 핀치 + est_ratio 1.85가 pitstop 없는 조건 캘리브레이션이라 via detour 미반영. ⚠️ **캠페인 "청라 9/10"은 pitstop 없는 조건**(러너 3종 전부 pitstop 미포함) — pitstop 조건은 미측정이었음. **수정 방향**(구현 대기): (a) pitstop-aware est_ratio 상향 or (b) pitstop 배치를 루프 자연 지점(~target/4)으로 or (c) pitstop 조건 정식 캠페인+성적표 재작성. **트리거: pitstop 사용률 높거나 실사용 502 반복 → pitstop 조건 캠페인으로 실효 팽창비 실측 후 (a)/(b) 착수.** v82 pitstop 관측 필드(gen_meta·gen_failures)가 실사용 pitstop-502를 자동 축적.

- **L8 RSVP 마감 창** — `rsvp` 제출의 read→`_rsvp_open`(시간)→upsert 사이 μs wall-clock 경쟁. count 레이스가 아니라 **시간 경계**라 advisory/FOR UPDATE로 안 닫힘 — DB측 `now()` 조건부 upsert RPC가 필요(별도 기법). 마감 순간 정확히 투표하는 극단 엣지라 실질 무해, 필요 시점에 `rsvp_if_open` RPC로 처리 가능.

- **RLS 드리프트 소급 (2026-07-12, H — 채팅 설계 중 발견·즉시 처리)**: 초기
  커밋 테이블 10종이 RLS 미enable → anon key + 유저 JWT로 타인 데이터 직접
  조회 가능(profiles 신체정보·notifications 포함). 앱은 service_role 경유라
  실피해 없었으나 anon key는 공개값. 전수 실증(24개 중 노출 10 확정, 빈
  테이블 preferences는 임시 행으로 확인) → `db/2026-07-12_rls_backfill.sql`로
  일괄 enable(정책 없이 — 앱 무영향, 회귀 5종 통과) → `scripts/verify_rls.py`
  노출 0 검증. 신규 테이블 RLS 표준이 초기분에 소급 안 됐던 게 원인.

## 운영 관측 (감사 외 — 배포 후 발견, 트리거 대기)

- **stale HTTP/2 연결 재사용 → 간헐적 502** (2026-07-08 진단 → **2026-07-11
  카드 ① 적용, 관측 중**)
  - **발동**: 트리거(주 3회+) 충족 — 7/8 crews/mine 3건 동시 + 7/10 로컬 재현
    + 7/10 /me/stats Sentry + 7/11 회귀 중 2건 (4회).
  - **적용**: supabase 서브클라이언트 4종에 HTTP/1.1 httpx 클라이언트 주입
    (`SyncClientOptions.httpx_client`, `app/core/supabase_client.py`).
    keepalive 단축안은 기본 5s에서도 재발한 실증으로 기각. 주입·h2 비활성은
    결정론 검증(전 서브클라이언트 세션 속성) + 병렬 회귀 5종으로 확인.
  - **판정**: Sentry에서 `httpx.ReadError` 패턴 **2주(~7/25) 무재발이면 종결**,
    재발 시 카드 ②(전송층 에러 한정 1회 재시도) 발동.
  - **발생**: 2026-07-08, `/api/crews/mine` 외 홈 화면 병렬 호출 3건 동시 502 (Sentry 이벤트로 관측 — 연동 당일 실 에러 첫 포착).
  - **원인** (fly logs 트레이스백으로 규명): supabase-py의 동기 httpx 클라이언트가 유휴 keepalive **HTTP/2** 연결을 재사용 → 상대편(Supabase LB)이 idle timeout으로 이미 끊은 연결이라 read 실패(`httpcore _read_exception` 재사용 경로). HTTP/2 다중화 때문에 병렬 요청 여러 개가 죽은 연결 1개에 함께 올라타 **동시 실패**.
  - **심각도: 낮음~중간** — 자가 회복(클라이언트 재시도 1초 내 성공), 데이터 정합성·보안 영향 0. 단 "유휴 후 첫 요청" 패턴이라 베타 테스터의 띄엄띄엄 사용에서 재발 가능.
  - **대응 카드 (지금은 실행 안 함)**:
    - ① supabase 클라이언트 http2 비활성 또는 keepalive expiry 단축 — HTTP/1.1이면 요청 1개만 실패.
    - ② `_bad_gateway` 경로에 전송층 에러 한정 1회 재시도.
  - **발동 트리거**: Sentry에서 이 패턴 주 3회+ 관측 또는 베타 테스터 불만 → 카드 ① 우선 검토.
  - **참고**: 정확한 예외 클래스는 로그 버퍼 소실로 미확정(`httpx.ReadError` 추정) — Sentry 이벤트 상세의 chained exception에서 확인 가능.

- **Gemini spend cap 초과 → 코스 생성·코치 신규 전 유저 502** (2026-07-09, 해소됨)
  - **발생**: AI Studio 프로젝트 월간 spend cap 초과 → `POST /routes/generate` 연속 502 `route_generation_failed` (~수 시간, 프론트 리포트로 인지). 크레딧 소진과 **동일한 429 RESOURCE_EXHAUSTED**라 잔액이 있어도 발생 — CLAUDE.md 함정 항목 보강함.
  - **규명**: fly logs 링버퍼 소실 전 원본 예외 확보 + Sentry 체인(RateLimitError)으로 즉시 판정. 최소 body 실호출 재현 → cap 상향 후 스모크 200 확인.
  - **조치**: 코드 수정 없음(429→502 변환·'실패는 무료' 쿼터 보존 전부 설계대로 동작). **cap을 ₩5,000으로 현실화**(결제 액션). 재발 시 확인처: https://ai.studio/spend
  - ~~출시 전 검토: Sentry `include_local_variables=False`~~ → **해소**
    (2026-07-11 적용 — App Privacy "충돌 데이터 신원 미연결" 정합. before_send
    가로채기 대조 검증: True에서 지역변수·이메일 값 노출, False에서 전부 부재).

## 기능 백로그 (트리거 대기)

- ~~**코스 생성 에러 구분 — 쿼터 소진 vs 산포 전패**~~ **[해결 2026-07-21]** (등록 2026-07-21). 계기 승격: 같은 날 v2.7 E2E가 실증 — T-map 429(QUOTA_EXCEEDED) 전패 시 nopath 폴백이 **폴리라인 없는 가짜 코스를 200으로 서빙**("앱은 거짓말하지 않는다" 위반). **구현**: (1) `map_service.TmapQuotaExceeded` 예외 — `_tmap_walk_leg`가 429를 LegNotRoutable/일반 장애와 구분 승격. (2) `route_service`가 스냅 실패를 `snap_errors{quota,legnotroutable,other}`로 분류·로그·gen_meta 영속화(무기록 삼킴 수정 — 이 삼킴이 당일 진단을 막았음). (3) `_quota_dominant`(쿼터가 스냅 시도 **엄격 과반**)면 nopath 폴백 금지 → **503 `route_generation_unavailable`**("잠시 후 다시 시도"). 보수적: 과반 미달·실 스냅 존재·지오 no-path 지배면 기존 동작 유지. (4) 잠복 버그 수정: `_log_perf_failed`가 폐기된 `attempts`/`pre_rejects` 키 참조 → 실패 경로에서 KeyError→502로 삼켜지며 503 분기를 가리던 것. 테스트: `test_quota_honesty_integration.py`(5케이스) + v2.7 회귀 10건. Gemini 429(RESOURCE_EXHAUSTED)는 별건(현 502 변환 유지 — 알려진 함정) — T-map 축만 처리.

- ~~**인앱 개인 초대**~~ — **처리됨(2026-07-13)**: `POST /crews/{id}/invitations {user_id}`(크루원 발송, 비크루원·차단 404·이미 멤버 409). `crew_invited` 알림 payload에 초대코드 → 수신자 preview→join 재사용. 푸시 템플릿+crewJoin 카테고리(M-11 정합). SQL 0(선등록 type). 초대코드 생성 단일 소스화(`_issue_invite_code`).
- **[M] `_park_coverage`가 route_service 15-park셋 기준 — 앵커 후보 저평가** (등재 2026-07-24, 앵커 혼합 풀 §9 부활 E2E 파생). `_park_coverage(route, park_coords)`의 `park_coords`가 route_service의 `search_places("공원", near=start, limit=15)` 결과 하나뿐. 앵커 롤은 **더 넓은 앵커셋**(anchor_service 다키워드 공원·수변·트레일)에서 뽑히므로, 앵커의 실공원이 그 15개에 없으면 커버리지 저평가 → **tiebreak(park 최우선)에서 앵커 후보가 부당 패배** 가능. E2E 실사례: 미노스/공원 앵커 루프 park 0.67(실제 앵커는 실공원인데 route_service 15셋에 없어 미카운트). **영향**: 앵커 채택률·park 합격선(②) 과소평가 — 실질 퇴행 아니나 측정·선택 왜곡. **수정안**: 커버리지 산정 park_coords를 **route_service 15셋 ∪ 앵커셋 좌표**의 합집합으로(앵커 롤이 있을 때). 또는 앵커 waypoint는 정의상 park이므로 앵커 engine 후보엔 park 하한 부여. **심각도 M**(앵커 활성 시 선택 품질 직접 영향). **트리거: 앵커 롤아웃 확대 전 — gen_meta engine A/B에서 앵커 park 저평가가 채택률을 누르는지 확인 후.**
- **[M] 앵커 park 하한 0.85가 수변 주파 실패 시에도 보너스 유지 — tiebreak 왜곡** (등재 2026-07-27, 실사용 판독 파생 — route d2113d13 가로수길 5.5km, 07-27 00:33 KST). 8647993의 앵커 park 하한 0.85는 "앵커=실공원·수변 경유" 전제의 저평가 교정인데, **수변 쌍 주파가 스냅에서 실패해도 하한이 그대로 붙는다**. 실측: 채택 anchor 후보의 "한강" 앵커 폴리라인 최근접 **275m 미도달**, 수변 체류 ~446m(전체 5,485m의 8%), 서측 매듭 이중주행 1,070m(편도 ~535m) — 그런데 park 0.85 보너스로 v87 후보들을 tiebreak서 이겨 서빙. **결정: observe-first**(오너 확정 2026-07-27). **즉각 수정 반증 표본**: 이 건의 대안 후보는 v87 park 0.6@5.6km(밴드 초과)·v87 park 0.0@5.1km뿐 — 하한을 제거해도 더 나쁜 후보(park 0.0)가 서빙됐을 것이라 이 표본에선 수정 이득이 없음(왜곡은 측정값이지 서빙 품질 퇴행이 아님). **수정안 후보**(착수 시): 하한 부여를 수변 앵커 실도달 조건부(폴리라인 최근접 ≤200m류)로 제한, 또는 주파 실패 시 실측 park_coverage로 폴백. **판정 트리거: gen_meta 축적에서 anchor 채택 건의 수변 앵커 미도달 비율이 유의하게 나타나고, 그 케이스들의 차선 후보가 실제로 더 나은(주파 성공·park 실측 우위) 사례가 확인될 때 조건부 하한 착수.** **(2026-07-27 보강)** 오너 취향 실측(ROUTE_GEN §8.19 — 만족 표본만 실공원 통과, 불만족 표본은 근접-only)으로 "근접≠통과" 갭이 실증됨.
- **[L] 앵커 롤 T-map pedestrian 400 — 간헐 광역 노이즈(오진 정정)** (등재 2026-07-24, 정정 2026-07-24). ⚠️ **직전 M 격상은 오진이었음.** 조사·수정(아래) 결과 "앵커 채택 0/30·한강 도달률 병목"의 **실원인은 400이 아니라 (a) 필터 자책 회귀 + (b) 링 캘리브레이션**이었다. 실증: ① 미노스·청라 앵커 체인 전 leg **직접 T-map 호출 8/8 성공(400 0건)** — 400 재현 불가. ② 파이프라인 계측: 앵커는 **스냅 성공하나 밴드 밖 착지**(미노스 3.9/4.5 미달·청라 6.0 초과)라 채택 탈락 — 400 무관. ③ dest_e2e(직전 5/5) 이후 유일 변경이 `91bcb32`(업소 필터)였고, 필터의 `은행`이 **논현·신사 은행나무공원**(은행나무=ginkgo)을 오탐 제거해 링 축소→미달. **수정 완료**(2026-07-24): 필터 정밀화(공원류 무효 가드) + 수변 링 chain_target 격자적응(_WATER_CHAIN_FRAC). 결과 앵커 채택 0/30→미노스 5/5·한강 11/15. 실제 400은 미노스 #4류 **간헐 광역 T-map 실패**(앵커+v87 동반 사망→502)로, 앵커 특유 아님 → **[L] 재분류**. **잔여**: 청라류 고팽창·희소앵커는 수변 앵커가 팩터 무관 초과라 in-band 불가(v87이 서빙, 한강 도달은 됨) — 기하 한계, 별도 레버 필요 시만.
- **[L] 공원 내부 출발 시 그 공원이 pitstop 후보서 제외** (관찰 등재 2026-07-22). pitstop 위치 밴드의 **하한 200m**(핀치 방지 — 코앞 지점이 루프 기하를 눌러 overshoot→502 유발하던 것 교정, 청라 부검 근거)이, **공원 안/바로 옆에서 출발**하면 그 공원의 대표 좌표가 200m 미만이라 밴드서 탈락시켜 **정작 서 있는 공원이 경유지로 안 잡히는** 부작용. 예: 서울숲 입구 출발 → 서울숲이 <200m라 제외되고 다음 후보(응봉산 등) 채택. **심각도 L**(가용성엔 무해 — 다른 실공원이 밴드 내서 채택됨, "그 공원"만 아닐 뿐). **수정안 후보**: 출발 지근(<200m) 대형 공원은 "목적지"가 아닌 "출발 앵커"로 별도 처리하거나, 밴드 하한을 공원 면적 비례로 완화. **트리거: 베타에서 "공원에서 출발했는데 그 공원이 경유지로 안 잡힌다" 류 피드백 누적 시.**
- **[L] 희소 GPS run이 server_distance=0인데 has_track=True로 저장 → /track 0.0 노출** (등재 2026-07-23, 코스연결 런 0.18-vs-0.0 조사에서 파생). GPS 포인트 간격이 **PAUSE_GAP_S(60s) 지배**(터널·앱 백그라운드로 샘플이 드묾)면 `process_track`이 전 세그먼트를 정지로 보고 `server_distance_km=0.0`·`splits=[]`로 처리. 그런데 `processed`가 None이 아니라 **run_tracks 행이 저장돼 has_track=True** → `GET /runs/{id}/track`이 `server_distance_km=0.0` 반환 → UI에 "거리 X km인데 트랙 0.0" 혼란 가능. **run 거리 자체는 정확히 보존**(unverified, 신고값 유지 — ±10% 대체는 line 333 `server_distance<=0→unverified` 단락으로 정상 미발동, 0거리 트랙으로 실런 거리를 덮지 않는 보수 설계). **수정 방향**: `create_run`이 `processed.server_distance_km <= 0`이면 run_tracks를 저장하지 않는다(has_track=False → 퇴화 지도 자체를 회피, run은 unverified로 정상 저장). **심각도 L**(저빈도 엣지, 데이터 정확성엔 무해). **트리거: 베타에서 "트랙 거리 0" UI 혼란 리포트 시.** (실 DB 유일 사례는 test1 데모 시드 run bf97ca74 — 시드 편차, 프로덕션 버그 아님.)
- **【부분 처리 2026-07-29】 도로 등급 축은 서빙 게이트로 구현** — dentist(동해) 실유저
  증언+OSM 실측(IC 램프 왕복 4/9코스)으로 **motorway·램프 연속 ≥100m 하드 차단**
  (`_road_hit_m`, 정적 OSM 데이터 4.9MB·상주 +35MB) + trunk 관측(`trunk_hit_m`)·T-map
  roadType 관측 배선. nopath 가짜 카드 서빙(폴리라인 0점 200)도 동시 정직화(502
  `fail=no_path`). 상세: ROUTE_GEN §8.20. 아파트/사유지 축은 아래 기존 판정 유지.
- **경로 접근성 필터 — 사유지·아파트 단지 내부 배제 레이어** (등재 2026-07-22, 경로 품질 진단 #6). 현 파이프라인은 Gemini가 발명한 좌표가 아파트 단지 내부·주차장·사유지를 관통해도 걸러낼 지도 레이어가 없다. STEP 2 프롬프트가 "관통 금지"를 FORBIDDEN에 넣어 경감하나 근절 불가(LLM 무맥락 — 진단 B1). **구현안**: OSM `landuse=residential`/`access=private` 폴리곤 또는 Kakao 경계 데이터로 웨이포인트·스냅 경로 교차 검사 → 위반 후보 감점/폐기(선택 층). **트리거: 베타 중 아파트 관통 리포트 누적 시** 또는 ROUTE_GEN_STRATEGY_V2 §8.4 앵커 에픽 착수 시(앵커가 실재 공공 지점이라 접근성 문제 대부분 자연 소거 — 앵커 이행 시 이 필터 불요할 수 있음, 중복 투자 회피 위해 앵커 판정과 묶어 검토). **【완화 검토 2026-07-23】** 부검 청라 route 2건 폴리라인 중간점 12점 역지오코딩 실측: **아파트 신호 1/12**(그마저 인접 도로 building_name edge-adjacency 추정), 나머지 청라동 도로/지번. **T-map 스냅이 암묵적 완화**로 작동(Gemini가 단지 내부 좌표를 발명해도 스냅 경로는 공공 보행 도로망을 따름) + v87 프롬프트 FORBIDDEN "관통 금지". → **현 심각도 낮음, 무거운 폴리곤 필터 착수 불요.** 데이터 원하면 **저비용 관측**(선택 route의 waypoint 4~6점만 역지오코딩 → gen_meta `apt_signal` 카운트)로 베타 실측 후 필터 여부 재판정 가능(폴리곤 레이어 전 단계). 표본 소수(2 route)라 베타 축적으로 재확인.
- **[L] 댓글 삭제 시 run_commented 알림 미정리 — 스테일 알림 UX 갭** (등재 2026-07-30,
  실증: "누리보고싶다→뭐지" 건 07/29 — 지연 run 댓글 2건 삭제 후에도 알림 잔존, "알림
  왔는데 가보면 댓글 없음"으로 오너 관찰됨). `delete_run_comment`(run_service.py:1248)는
  행만 삭제 — M10 알림 정리는 run 삭제 시만 커버. 실피해는 스테일 알림뿐(잘못된 노출
  없음). **수정 방향 후보(착수 금지)**: ① 댓글 삭제 시 해당 (actor,type,target) 알림
  동반 정리 ② 클라가 알림 진입 시 404를 우아하게 처리("삭제된 댓글이에요"). **트리거:
  유저 불만 발생 시.**
- **알림 중복 억제 (감사 2차 L-2)** — 팔로우/kudos 토글 반복이 알림+푸시를 매번 재발송(기존 인앱 축의 푸시 증폭). 최근 N시간 내 동일 (actor, recipient, type) 억제안. **트리거: 베타 중 테스터 불만 시 승격.**
- **Expo 배치 발송 최적화 (감사 2차 L-6)** — 공지·챌린지 완료 시 크루원 N명 = 푸시 태스크 N개·Expo N요청. 100/요청 배치로 묶기. 트리거: 크루 규모 성장 시.
- **UV '현재값' 소스 교체 검토** — 현 `/2.5/uvi`는 '오늘 최고(solar-noon)' 시맨틱(2026-07-12 계약 relabel로 대응). **트리거: 베타 중 '현재 UV' 요구 피드백 시** ⓑ 재검토 — One Call 3.0(유료 구독) 또는 Open-Meteo(신규 처리위탁 — PRIVACY_DATA_MAP 갱신 동반).
- **러닝 공유 카드 (프론트 주도)** — 시안 외 신규 확정(2026-07-09, 결정: 지연 — 유저 공유 = 0원 마케팅 채널, 스트라바 Share Activity 참고). RN 뷰 캡처 방식, **백엔드 갭 0**(`GET /runs/{id}/track` 폴리라인 + 러닝 스탯으로 충족). 웹 랜딩(링크 공유용)은 베타 범위 밖. **트리거: 프론트 착수.**
- **러닝 내비 maneuvers[] (T2 후보, 실현성 확정 2026-07-26)** — T-map 보행 응답 Point features에 `turnType`·`description` **100% 채움**(실덤프 확인 — "우회전 후 …를 따라 32m 이동" 한국어 안내 + 코드 + 좌표 + 랜드마크). 스냅 시 Point 캡처 + **`routes.maneuvers` jsonb additive**. 캐노니컬은 **진입 leg만 보유/코스 루프 null 폴백 계약**. **신규 콜 0**(같은 응답, 현재 LineString만 쓰고 Point 버림). **트리거: 외부 게이트 후 Ivan과 T2 협의.**
- ~~**PB 축하 푸시 (`notif.pb` 게이트 연결)**~~ — **처리됨(2026-07-13)**: `create_run`의 `new_records[]` 비지 않으면 본인에게 `pb_achieved` 인앱+푸시(self-only 알림, allow_self=True). 신규 type CHECK 재작성(db/2026-07-13_notif_pb_achieved.sql)+`_TEMPLATES`/`_CATEGORY`(pb)+기록 종류별 문구. (`runReminder`·`weekly`는 스케줄러 필요라 여전히 별도.)
