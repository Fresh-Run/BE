# BATTLE_SPEC.md — 배틀 피처 서버 스펙 (확정·구현 대기)

> **상태(2026-08-26): 확정 — 구현 대기.** 오픈 이슈 6건 + 3룰링 이반/오너 확정치
> 반영(§6). **구현 순서**: IAP 실연동 · 소셜 로그인 **다음**. SQL 실행·서버 구현
> 아직 없음. 이반 API 계약(.md)·점수식(FE `lib/battle-score.ts`)과 정합.
>
> **오너 3룰링 확정(2026-08-25)**: ① **윈도 앵커 = 수락 시점**(생성 시점 아님)
> ② **eligibility = 차단/비공개 유저 제외** ③ **동시 배틀 소수 제한은 앱 로직,
> 스키마는 N 허용**.

## 1. 스트릭 실확인 — 이반 질문 답 ("기존에 있나 새로 만드나")

**답: 현재 진행 중(current) streak은 저장돼 있지 않다. 새로 만들 필요 없이 `runs`로
계산한다(기존 로직 재사용).**

- 저장된 것: `monthly_insights.longest_streak_days` — **그 달의 최장** 연속일(과거
  집계값). **현재 진행 streak(오늘 기준 며칠째)은 미저장.**
- 계산 로직 이미 존재: `insight_service.py:198-205` — 러닝 **날짜 집합**을 정렬해
  `(cur-prev).days==1` 연속 카운트. 날짜 소스 = **`runs.ran_at`을 KST 날짜로 버킷**
  (run_service.py:64 "즉흥런 날짜 버킷").
- **배틀용 current streak**: 오늘부터 역순으로 distinct run-day를 훑어 연속 카운트.
  비용 **낮음**(O(run_days), 유저당 수십~수백 run — 인덱스 `runs(user_id, ran_at)`
  전제 단일 쿼리). 배치 정산(§4) 시 배틀 참가자별 1회 계산 → `streak_multiplier` 산입.
- **결론**: streak 테이블 신설 불요. `runs.ran_at` 날짜 계산을 **공용 헬퍼**로 추출
  (`insight_service` 로직 단일 소스화) 후 배틀·인사이트 공유. anti-cheat "실시간
  streak"도 이 계산(과거 run 백필로 streak 조작 방지 = ran_at 기준 + verified만).

## 2. 스키마 설계 (확정 — SQL 미실행)

> 신규 테이블은 전부 **`enable row level security`**(정책 없이 — deny-by-default,
> 앱은 service_role 접근. §C 표준). 참가자 수 제한 CHECK 없음(**N 허용**, 룰링 ③).

### `battles`
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | uuid PK | |
| format | text | `points` \| `pure`(순수 거리) — CHECK |
| metric | text | `distance_km`(기본) 등 — 확장 여지 |
| status | text | `pending`\|`active`\|`ended`\|`cancelled`\|`forfeited` — CHECK |
| starts_at | timestamptz | **수락 시점**(룰링 ①) — 활성화 시 세팅. null=pending |
| ends_at | timestamptz | `starts_at + duration_days` |
| duration_days | int | **CHECK 1..30**(≤30) |
| players_n | int | 그룹레디 config(§3). 1v1=2 |
| teams_m | int | 팀전이면 M, 개인전이면 = players_n |
| created_by | uuid | |
| created_at | timestamptz default now() | |

### `battle_participants`
| 컬럼 | 타입 | 비고 |
|---|---|---|
| battle_id | uuid FK→battles | |
| user_id | uuid | PK(battle_id, user_id) |
| team | int null | 팀전 팀 번호(개인전 null) |
| status | text | `invited`\|`accepted`\|`declined`\|`forfeited` — CHECK (forfeited=중도 기권→즉시 패배) |
| accepted_at | timestamptz null | 이 값들의 앵커가 battle.starts_at |
| **milestone_5k_run_id** | uuid null | anti-cheat 메모리 — 5k 최초 달성 run(**배틀당 1회**) |
| **milestone_10k_run_id** | uuid null | anti-cheat 메모리 — 10k 최초 달성 run(배틀당 1회) |
| streak_baseline | int default 0 | 수락 시점 streak(실시간 streak 배율 앵커·조작 방지) |

- **milestone 메모리 목적**: 5k/10k 보너스를 배틀당 **1회만** 지급. 최초 달성 run_id를
  박아, 같은 배틀에서 재달성/재제출로 중복 가산 방지(서버 메모리 = 이 컬럼).
- **eligibility(룰링 ②)**: 초대 시 차단 관계·비공개 계정 검사 — 차단/비대상은 **404
  은닉**(프로젝트 표준). `battle_participants` 삽입 전 게이트(follow/block 서비스 재사용).

### `battle_scores` (배치 정산 산출 — §4)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| battle_id, user_id | uuid | PK(battle_id, user_id, as_of_date) |
| as_of_date | date | **"어제까지" 정산일**(§4) |
| score | numeric | 참가자 누적 점수 |
| breakdown | jsonb | base/completion/pace/streak/milestone/earlybird 분해(디버그·FE 표시) |
| computed_at | timestamptz | |

### 크루 챌린지 머시너리 재사용 범위
- **직접 재사용**: `crew_service._challenge_contributions`(1235) = 창(starts~ends) ×
  `verification='verified'` × user별 km 합. 배틀 참가자별 km 집계에 **동형** — 창을
  battle.starts_at~ends_at, 대상을 battle_participants로 바꿔 이식.
- **재사용 안 함**: 크루 랭킹의 current-member 필터(배틀은 고정 참가자), 챌린지 target_km
  진행률(배틀은 점수식 §3). 집계 **쿼리 골격만** 공유, 점수 계산은 배틀 전용.

## 3. 점수 엔진 (이반 공식 1:1, 그룹레디)

`lib/battle-score.ts`와 **1:1**(서버가 진실, FE는 프리뷰 미러). run별 점수 → 참가자
누적 → (팀전) 팀 합. **`is_flagged`(anti-cheat) run 제외**, `verification='verified'`만.

```
per-run 점수(1.5km 하한 미만 = 0):
  if distance_km < 1.5 or is_flagged or verification != 'verified': 0
  base        = distance_km * 10
  completion  = +20 (완주 = distance_km >= 1.5 AND 정상 저장 완료. 중도 포기 0)
  pace_bonus  = f(avg_pace) (이반 lib 상수 1:1)
  milestone   = +5k보너스(배틀 첫 5k run) + 10k보너스(배틀 첫 10k run)   # 메모리 컬럼
  early_bird  = +보너스(run 시작 시각 < 07:00 KST — 06:59 포함/07:00 미포함, 클라 엔진 동일)
  run_score   = (base + completion + pace_bonus + milestone + early_bird)

참가자 배율:
  streak_multiplier = 1 + 0.05 * min(streak, 10)   # cap 1.5
  participant_score = Σ run_score * streak_multiplier   # streak은 정산일 기준 §1 계산

그룹레디(config: players_n=N, teams_m=M):
  개인전(M=N): 참가자 점수 직접 순위.
  팀전(M<N):   team_score = Σ(팀원 participant_score). 1v1 = N=2·M=2.
```
- **단일 소스 원칙**: 점수 상수(×10·+20·0.05·cap1.5·5k/10k·하한1.5)는 이반 `battle-score.ts`
  값을 **서버 상수로 미러**(드리프트 방지 — 계약 변경 시 양쪽 동시 갱신, §C 계약 규칙).
- **is_flagged**: anti-cheat 플래그(비정상 pace·milestone 재제출 등 배치가 세팅). flagged
  run은 점수 0 + 관측 로그.

## 4. 집계 방식 — 일 1회 배치 정산 (어드바이저 권고)

- **KST 자정 배치**: active 배틀 전수 순회 → 참가자별 `[starts_at, 어제 23:59:59]` 창의
  verified·비flagged run 집계 → §3 점수 → `battle_scores(as_of_date=어제)` upsert.
  **서빙은 "어제까지 점수"**(오늘 run은 다음 자정까지 미반영).
- **실시간 대비 이점**: run마다 재계산·라이브 리더보드 갱신 없음(부하 예측 가능),
  **streak·milestone을 1일 1회 결정론 계산**(실시간 경합·중복 지급 리스크 제거),
  anti-cheat 판정 일괄. 트레이드오프: 순위가 "어제 기준"(실시간 아님) — 배틀 UX는
  "어제까지 스탠딩"으로 명시.
- **트리거**: 스케줄러(GH Actions cron 또는 fly). ⚠️ GH Actions는 repo 60일 무활동
  비활성(§C) — fly 스케줄 또는 keepalive 병행 검토.
- **정산 시 anti-cheat**: milestone_5k/10k_run_id 최초 세팅(이미 있으면 스킵),
  streak_multiplier 계산, 비정상 run is_flagged 마킹.

## 5. 알림 설계 (신규 타입 3)

`notifications_type_check` **drop→재생성**으로 3종 추가(§C 함정 — 타입만 넣고 제약
미수정 시 23514). `push_service._TEMPLATES` + `_CATEGORY` 매핑 동반(누락 시 부팅 assert).

| 타입 | 트리거 | 수신 | 스로틀 |
|---|---|---|---|
| `battle_invited` | 초대 생성 | 초대받은 유저 | — |
| `battle_overtaken` | 정산서 순위 역전(내가 밀림) | 추월당한 유저 | **1회/일**(배틀별) |
| `battle_won` | 배틀 종료 정산 | 승자(팀전=팀원) | — |

- `battle_overtaken` 스로틀: 배치가 1일 1회라 자연히 **정산당 최대 1회** — 추가로
  (actor, recipient, battle, type) 최근 24h 억제(감사 2차 L-2 억제안 패턴 재사용).
- `send_notification(allow_self=False)` 기본. 배틀 종료 알림은 자기 승리라 `battle_won`은
  self 허용 검토(pb_achieved 선례).

## 6. 구현 순서 · 오픈 이슈

- **순서**: IAP 실연동 → 소셜 로그인 → 배틀. 스펙(이 문서)은 선행 확정.
- **엔드포인트 5종**(이반 계약 .md 수신분 — 스펙 매핑, 구현 대기): 배틀 생성/초대 ·
  수락(=starts_at 앵커) · 목록/상세(점수·순위) · 취소/포기 · (관리) 정산 재실행.
  **경로 순서**: 고정 경로 먼저(§ 일반 규칙). uuid path param은 `validate_uuid_path_params`
  가드 자동 커버(비uuid 404).
- **오픈 이슈 — 전부 확정(2026-08-26 이반/오너)**:
  ① **완주(completion +20) = 1.5km 이상 + 정상 저장 완료** run. 중도 포기(강종 등)는
     보너스 없음(§3 completion 조건 = distance_km ≥ 1.5 AND 저장 완료).
  ② **early_bird 경계 = 시작 시각 < 07:00 KST**(06:59 포함, 07:00 미포함). 클라
     `battle-score.ts` 엔진과 동일 경계.
  ③ **팀 불균형 정규화 = v1 스킵**(1v1 전용). 그룹(N players/M teams) 모드 시 별도
     논의 → **파킹**(아래).
  ④ **중도 포기/기권 = 즉시 패배**. 포기자 점수는 그 시점 고정, **상대 점수는 그대로
     유지**(감점·재계산 없음). status→`forfeited`, 승패 즉시 확정.
  ⑤ **duration_days = 최소 1 · 최대 30**(CHECK 1..30 — §2 스키마 반영).
  ⑥ **동시 배틀 캡 = 3개**. 스키마는 N 허용(룰링 ③), **앱 로직에서 유저당 active
     배틀 3개 강제**(4번째 생성/수락 시 거부).
- **파킹(그룹 모드 시)**: 팀전 참가자 수 불균형 점수 정규화 — v1(1v1)은 스킵.
  **트리거: 그룹 배틀(M<N·팀 인원 상이) 착수 시** 정규화 규칙(팀 평균 vs 합) 재논의.
- **스트릭 정산(백필 치팅 차단, 확정)**: current streak은 **KST 자정 daily 배치에서
  `runs.ran_at` 기준 재계산**(§1·§4). 과거 날짜로 run을 백필해도 정산이 ran_at 날짜
  버킷 + verified만 세므로 조작 무효. `streak_multiplier`는 정산일 streak로 산입.
- **3룰링 재확인(확정)**: ① 윈도 앵커 = 수락 시점(starts_at) ② eligibility = 차단/
  비공개 유저 **404 은닉** ③ 동시 배틀 스키마 N 허용(제한은 앱 3개).
- **anti-cheat 서버 필수 2건(확정)**: (a) milestone memory = 배틀당 1회 지급
  (milestone_*_run_id 컬럼) (b) streak = ran_at 기준 verified 계산(백필 조작 차단).
  둘 다 **서버 정산 단계에서만** 판정(클라 신뢰 0).
