# PRIVACY_DATA_MAP — 개인정보처리방침 원천 자료 (사실 기록)

> 2026-07-08 작성. 개인정보처리방침의 **원천 자료** — 법률 문구 없이 사실만 기록.
> 출처: 라이브 DB 스키마 실조회(PostgREST OpenAPI, 테이블 26개 중 PostGIS 시스템
> 테이블 3개 제외) + 코드(`app/`) + 선언 SQL(`db/`) + 운영 문서(`docs/`).
> 확인하지 못한 항목은 각 절과 맨 아래 "미확정" 절에 **[검증 불가]**로 표기.

## 1. 계정 정보

| 항목 | 저장 위치 | 수집 시점 | 비고 |
|---|---|---|---|
| 이메일, 비밀번호(해시), 가입·로그인 시각 | `auth.users` (Supabase Auth 관리) | 회원가입/로그인 | 앱은 Supabase Auth를 직접 호출(백엔드 미경유). **주간 백업 범위 밖**(pg_dump는 public 스키마만) |
| 닉네임(unique), 자기소개(bio) | `profiles.nickname/bio` | 프로필 작성·수정 | 닉네임은 공개 노출(랭킹·댓글·피드) |
| 프로필 사진 | Supabase Storage `avatars` 버킷, 경로=`{user_id}` 고정 | 업로드 시 | **public 버킷 — URL을 알면 누구나 읽기 가능**(코드 주석 근거, 대시보드 정책 [검증 불가]). 재업로드가 덮어써서 이전 파일은 남지 않음. 명시 null로 삭제 가능(Storage 포함). 5MB, jpeg/png/webp 제한. **EXIF(GPS 포함)는 클라이언트 재인코딩으로 제거 후 업로드가 계약**(러닝 사진과 동일 — public 버킷이라 잔여 리스크가 더 커서 특히 중요, 서버 사후 스캔 검토는 출시 전 항목 공유) |
| **러닝 사진** (≤3장/run, 2026-07-09~) | Storage `run-photos` **private 버킷**, 경로=`{run_id}/{slot}` | run 저장 후 업로드(선택) | **비공개 버킷 — 읽기는 run 공개범위 게이트 통과 시 발급되는 서명 URL(만료 1h)로만**(비공개 러닝 사진 URL 유출 불가 구조). **EXIF(GPS 좌표 포함)는 클라이언트 재인코딩으로 제거 후 업로드가 계약** — 서버는 원본 EXIF를 저장하지 않음(잔여 리스크: 클라 구현 누락 — 출시 전 서버 사후 스캔 검토). run에서 사진 제거·교체 시 즉시 삭제, **회원 탈퇴 시 전량 삭제**(§6, 실증 테스트 검증) |
| 신체 정보: 출생연도·체중·키·성별 | `profiles.birth_year/weight_kg/height_cm/gender` | 프로필 편집(선택 입력) | **본인 조회(`GET /me/profile`)에만 노출** — 타인이 보는 모든 응답에 미포함(테스트로 이중 검증된 표준). 체중은 칼로리 클라이언트 계산용 |
| 구독 등급 | `profiles.tier` | 구독 변경 시 | free/premium |
| 앱 설정(언어 등) | `profiles.settings` (jsonb, 화이트리스트 필터) | 설정 변경 시 | AI 생성물 언어 결정에 사용 |
| 러닝 취향 | `preferences.distance_pref/vibe_pref` | 온보딩/설정 | |
| **푸시 기기 토큰** (2026-07-11~) | `push_tokens` (Expo token·플랫폼·갱신 시각) | 로그인 후 앱이 등록(선택 — OS 권한 거부 시 미수집) | **기기 식별자 성격.** 로그아웃 시 해제 + 죽은 토큰 자동 정리 + **탈퇴 시 cascade 삭제**(테스트 검증). 토큰은 발송 외 용도 없음 |

## 2. 위치정보 (가장 민감한 축)

### GPS 궤적 — `run_tracks` (러닝 기록 시)

- **원본은 저장하지 않는다.** 클라이언트가 보내는 원본 포인트(lat, lng, t_ms,
  accuracy, altitude)는 요청 처리 중에만 사용하고, 서버는 **가공 결과만** 저장:
  - `points`: 필터·평활·간축(Douglas-Peucker) 후 **좌표만** `{lat, lng}`,
    **소수 6자리 반올림(≈0.1m 정밀도)**. 포인트 단위 타임스탬프·accuracy·고도는
    저장 안 함.
  - `splits`: km 랩별 소요 시간·고도 상승(집계).
  - 관측 지표: `max_speed_kmh`, `avg_accuracy_m`, `raw_point_count`,
    `kept_point_count` (필터 동작·부정 사용 추적용 집계).
- 한국 bbox(위도 33–39, 경도 124–132) 밖 좌표는 수신 시 필터로 폐기.
- 노출: run의 `visibility`(public/followers/private, 기본 followers)에 따름.
  궤적 조회(`GET /runs/{id}/track`)도 동일 게이트(2026-07-08부터 공개범위 내
  타인 허용 — 범위 밖은 404 은닉, 가시성 매트릭스 테스트로 검증).

### 기타 위치 데이터

| 항목 | 저장 위치 | 수집 시점 | 비고 |
|---|---|---|---|
| 코스 출발지 좌표 | `routes.start_lat/start_lng` | AI 코스 생성 시 | **자택·직장 추정 가능성 있는 좌표.** 공개 코스(`is_public`)면 타인에게 노출 |
| 코스 경로·경유지 | `routes.polyline/waypoints` (jsonb) | 코스 생성 시 | 경유지에 장소명·주소 포함 가능(Kakao 검색 결과) |
| 러닝 일시 | `runs.ran_at` | 기록 저장 시 | 시간대 패턴 분석에 사용(월간 인사이트) |
| 러닝 지역명 (2026-07-11~) | `runs.area` (예: "성수동") | 기록 저장 시(선택) — 프론트가 좌표를 역지오코딩해 전송 | 동 단위 거친 해상도. run `visibility` 게이트 뒤에서만 노출(카드·상세) |
| 크루 활동 지역 | `crews.lat/lng/sido/sigungu/area` | 크루 생성·수정 | 역지오코딩은 **프론트가 Kakao Local SDK로 클라이언트 측 수행** 후 결과만 전송 |
| 공지 집결지 | `crew_announcements.place_name/place_lat/place_lng` | 공지 작성 시 | 크루원에게 노출 |

## 3. 활동 데이터

| 항목 | 저장 위치 | 수집 시점 |
|---|---|---|
| 러닝 기록(거리·시간·페이스·제목·메모·피드백 태그·검증 상태) | `runs` | 기록 저장/수정 |
| 생성 코스(목표 거리·요약·메모 자유 텍스트) | `routes` | 코스 생성 |
| 댓글(자유 텍스트) | `route_comments`, `run_comments` | 작성 시 |
| 좋아요/북마크/kudos | `route_likes`, `route_bookmarks`, `run_kudos` | 클릭 시 |
| 팔로우 관계 | `follows` | 팔로우 시 |
| 크루 소속·역할·가입 신청(결정자·결정 시각 포함) | `crews`, `crew_members`, `crew_join_requests` | 크루 활동 시 |
| 공지·RSVP·챌린지 | `crew_announcements`, `crew_announcement_rsvps`, `crew_challenges` | 크루 활동 시 |
| 알림(행위자 id·대상 id·딥링크 payload) | `notifications` | 상호작용 발생 시 |
| AI 생성물 캐시(코치 스크립트·월간 코칭 텍스트) | `coach_scripts`, `monthly_insights` | AI 기능 사용 시 |
| AI 생성 이력(사용자·시각만) | `route_generations` | 코스 생성 시 (주간 쿼터 산정용) |
| 구독(Apple 거래 id 포함) | `subscriptions`, `iap_notifications_raw`(Apple 알림 원본 jsonb) | IAP 사용 시 — **현재 미개통**(`IAP_MODE` 미설정 = 503) |

## 4. 기기·로그 정보

- **DB에 IP 주소 컬럼 없음.** 기기 식별자는 **푸시 토큰이 유일**(`push_tokens`,
  2026-07-11~ — §1 참조, 푸시 발송 외 용도 없음). Supabase Auth가 자체 관리하는
  인증 로그는 Supabase 측에 존재(대시보드에서 확인 가능).
- **서버 로그(Fly.io)**: 짧은 링버퍼로 단기 보존, 영구 보관 없음. httpx INFO
  로그가 외부 API 요청 URL을 기록(민감값 쿼리스트링 금지 규칙 운용).
- **Sentry (에러 트래킹, 스테이징 라이브, US 리전)** — sentry-sdk 2.18.0,
  `traces_sample_rate=0`(에러만), `send_default_pii` 미설정=False:
  - **전송 안 됨**: 사용자 id·이메일·IP·쿠키(Authorization/Cookie 헤더는 SDK 기본 필터).
  - **전송됨**: 에러 스택·요청 URL/메서드/일반 헤더·environment 태그.
  - **요청 body 미첨부**(`max_request_body_size="never"`, 07-08) + **스택
    지역변수 미포함**(`include_local_variables=False`, 07-11 — 대조 검증 완료).
    이벤트에 남는 것: 에러 스택(코드 위치만)·URL·메서드·일반 헤더·environment.
    App Privacy "충돌 데이터, 신원 미연결" 신고와 정합 — 방침에는 "오류 진단
    데이터(개인 식별·요청 내용 미포함)가 미국 Sentry로 전송"으로 기술 가능.

## 5. 제3자 제공 / 처리위탁

| 대상 | 성격 | 전송되는 데이터 (정확히) | 소재/리전 |
|---|---|---|---|
| Supabase | 처리위탁 (DB·Auth·Storage) | 위 1~3절 전부 + 인증 정보 | **서울(동북아)** — 배포 시 확인 기록(`docs/DEPLOY_CHECKLIST.md`), 대시보드 재확인 권장 |
| Fly.io | 처리위탁 (API 서버) | 모든 API 트래픽 통과(저장은 단기 로그만) | 도쿄(nrt) |
| Google Gemini | AI 처리 (코스 생성) | **출발(·도착) 좌표, 목표 거리, 경유지 키워드, 사용자 메모(notes) 자유 텍스트, 회피 태그, 탐색 반경.** 이메일·닉네임·사용자 id 미전송 | Google API |
| Google Gemini | AI 처리 (오디오 코치) | 코스 요약명, 경유지 이름·설명, 러닝 횟수, 평균 페이스. **좌표 미전송** | Google API |
| Google Gemini | AI 처리 (월간 인사이트) | 월간 집계 통계만(총거리·횟수·페이스·주차별 추이·최고 기록·시간대 패턴). 좌표·텍스트 미전송 | Google API |
| T-map (SK) | 보행 경로 계산 | 좌표만(출발·도착 x/y) — `MAP_PROVIDER=tmap` | 국내 |
| Kakao Local | 장소 검색(경유지 해석) | 검색 키워드 + 기준 좌표 + 반경. (별도로 **프론트**가 Kakao SDK로 크루 위치 역지오코딩) | 국내 |
| OpenWeather | 날씨 조회 | **원본 좌표 그대로**(반올림은 서버 캐시 키에만 적용, 요청은 원좌표) | 해외 |
| Sentry | 에러 수집 | 4절 참조 | **미국** |
| **Expo Push Service** (2026-07-11~) | 푸시 발송 중계 | 기기 토큰 + 알림 문구(**닉네임·행위 유형만** — 콘텐츠 내용·이메일 미전송) + 딥링크 id | 해외(Expo/미국) — FCM·APNs로 재중계 |
| Apple | IAP 구독 검증 (**예정, 현재 미개통**) | 거래 id·구독 상태 | 해외 |
| Naver Map | **미사용** (키만 존재, 코드상 미구현 — place search는 NotImplemented) | — | — |

## 6. 보관 기간 / 삭제 — 현재 사실

- **보관 기간 정책 없음** — 모든 데이터 무기한 보관. TTL·자동 정리 잡 없음.
- **사용자가 직접 삭제할 수 있는 것**: 알림(개별·전체), 자기 댓글, 좋아요·북마크·
  kudos·팔로우 취소, 크루 탈퇴, (소유자) 크루 삭제 — 크루 삭제 시 공지·RSVP는
  cascade 삭제.
- **개별 삭제 불가 항목**: **러닝 기록(`runs`)과 코스(`routes`)는 개별 삭제
  API가 없다**(수정 `PATCH /runs`만 존재). 단 아래 회원 탈퇴가 일괄 삭제를
  제공하므로 삭제권 자체는 충족. 개별 삭제 UI는 시안에도 없음(범위 제외 —
  `ACCOUNT_DELETION_DESIGN.md` §0).
- **회원 탈퇴: `DELETE /me`** (2026-07-08 구현) — 계정과 모든 데이터 **즉시
  완전 삭제**(유예 없음). 상세 설계·실증은 `ACCOUNT_DELETION_DESIGN.md`.
  - 다른 멤버가 있는 소유 크루가 있으면 409로 차단(위임/삭제 후 탈퇴),
    본인뿐인 크루는 함께 삭제. 데모 계정은 403으로 보호.
  - 아바타(Storage)는 FK가 없어 탈퇴 처리에서 명시 삭제.
  - 같은 이메일 재가입 가능(새 계정, 이전 데이터 없음).
- **탈퇴 시 데이터 처리 — 라이브 DB 실증으로 확정** (2026-07-08, 테이블별
  격리 프로브):
  - cascade **삭제**: profiles(닉네임·신체정보), preferences(FK 재작성
    `db/2026-07-08_account_deletion.sql` 적용 후), runs(+GPS 궤적·타인의
    kudos/런댓글), routes(+타인의 댓글·좋아요·북마크), 크루 멤버십, 팔로우,
    알림(내가 받은 것 + **내가 유발해 타인이 받은 것**), 코치 스크립트,
    월간 인사이트, 구독, route_generations.
  - **보존**: 크루 공지·챌린지(작성자만 NULL 익명화), 가입 신청의 결정자
    기록(NULL), **타인이 복사해 간 코스**(`copied_from`만 NULL — 실증 SET NULL).
- **백업 잔존**: 주 1회 pg_dump(public 스키마) → GitHub Actions artifacts
  **90일 롤링**. 삭제된 데이터도 백업에는 최대 90일 잔존. `auth.users`는 백업
  범위 밖.
- 데모 계정(test1·test2·demo1~5)은 실사용자 아님 — 방침 대상 외.

## 7. 미확정 — 방침 확정 전 확인 필요

1. ~~초기 테이블 8종의 탈퇴 cascade~~ → **해소** (2026-07-08 실증 확정, §6·`ACCOUNT_DELETION_DESIGN.md` §1).
2. ~~Sentry body 첨부~~ → **해소** — `max_request_body_size="never"` 적용(2026-07-08). 이제 에러 이벤트에 요청 body 미첨부. 스택 로컬 변수(`include_local_variables`)는 유지 — 방침에는 "오류 진단 데이터가 미국 Sentry로 전송"으로 기술.
3. **avatars 버킷 public 읽기 정책** — 코드 주석 근거뿐, 대시보드에서 확인.
4. **Supabase 리전** — 배포 체크리스트 기록(서울)이 근거, 대시보드 재확인 권장.
5. ~~회원 탈퇴 API 부재~~ → **해소** (`DELETE /me`, §6). run/route 개별 삭제는 시안에 없어 범위 제외 — 방침에는 "계정 삭제로 일괄 파기"로 기술 가능.
