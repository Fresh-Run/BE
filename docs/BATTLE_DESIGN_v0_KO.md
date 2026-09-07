# BATTLE_DESIGN_v0_KO — 1v1 점수 배틀 서버 설계 (v0, 착수 확정)

> **상태(2026-09-07): 설계 확정 — 구현 착수.** 이반 화면 1차 빌드 완료(목데이터).
> 이 문서가 **설계의 진실**(§F 결정 이력 박제). 선행 스펙 `BATTLE_SPEC.md`(2026-08-26)를
> **v0(1v1)로 구체화·수정**한다. additive · 기존 계약 불변.
>
> **오너 결정 3건(2026-09-07 통화·질문 확정)** — 이 3개가 스키마·계약을 가른다:
> - **① Q4 귀속 = `runs.ran_at`(저장시각).** 근거: BATTLE_SPEC 전체 일관 + Q4 실측
>   (실클라 런 저장 gap=0 → 저장시각≈활동시각) + `ended_at` 인프라 부재(신규 컬럼+클라
>   계약 필요). `ended_at`은 HK-import가 흔해지면 **additive**로 후속(재검토 트리거).
> - **② 게이팅 = 병행.** (a) 무료 티어 **30일 롤링 관여(생성+수락) 3회** 수익화 게이트
>   (프리미엄·베타 스킵) + (b) 전 티어 **동시 active 3개** 제품 캡(스팸·정산부하 방지).
> - **③ 정산 유예 = 30분.** 단 KST 자정 daily 배치(§정산)와 정합: `ends_at + 30분`이
>   지난 뒤 **다음 자정 배치**가 최종 정산. 30분은 "종료 당일 조기 정산" 하한.
>
> **BATTLE_SPEC와의 차이(v0 구체화)**: 그룹레디(players_n/teams_m) → **1v1 고정**
> (creator/opponent). `battle_participants`/`battle_scores` → **`battles`+`battle_invites`
> +`battle_runs`** 3테이블(이반 계약 명명). 온더플라이 집계 → **`battle_runs` per-run
> 점수 영속**(정산 재계산 결정론·디버그·추월 알림 근거). 그룹 모드는 **파킹**(트리거:
> 다대다 배틀 착수 시 BATTLE_SPEC §3 그룹레디 스키마로 확장).

---

## 1. 스키마 (SQL: `db/2026-09-07_battles.sql`, APPLY/ROLLBACK 페어, **오너 실행**)

전부 **`enable row level security`**(정책 없이 — deny-by-default, 앱은 service_role. §C 표준).
FK `on delete cascade`(유저 탈퇴·배틀 삭제 시 하위 정리).

### `battles` (1v1 대전)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | uuid PK default gen_random_uuid() | |
| created_by | uuid FK→auth.users | 생성자(도전자) |
| opponent | uuid FK→auth.users | 상대(초대 대상) |
| title | text NOT NULL | ≤60자(앱 검증, 모델 max_length) |
| emoji | text | 프리셋 ≤12(앱 검증) — 저장은 emoji 문자 |
| format | text NOT NULL default 'points' | CHECK ('points','pure') |
| metric | text NOT NULL default 'distance_km' | 확장 여지 |
| duration_days | int NOT NULL | **CHECK (1..30)** |
| status | text NOT NULL default 'pending' | CHECK 아래 5+2 상태 |
| started_at | timestamptz | **수락 시점**(윈도 앵커, 룰링①). null=pending |
| ends_at | timestamptz | `started_at`의 KST날짜 + duration_days → **KST 자정 경계** |
| settled_at | timestamptz | 최종 정산 완료 시각 |
| winner | uuid | 승자(무승부·미정 null) |
| created_at | timestamptz default now() | |

- **status 5단계+2**: `pending`(대기 — 생성·초대 발송, 수락 전) → `active`(진행) →
  `ended`(종료·정산 완료). 종료계 2: `cancelled`(초대 만료 48h / 상호취소), `forfeited`
  (포기 — 즉시 패배). **"초안"은 클라 로컬**(생성 API 호출 = pending부터). **"정산"은
  상태 아님** — `settled_at` 타임스탬프 + daily 배치 진행 상태(active인 채 배치가 점수만 갱신,
  종료 시각 지나면 ended 전이).
- **KST 자정 정렬(룰링①·정산 정합)**: `started_at`=수락 순간(UTC) 저장, `ends_at`=
  수락일의 **KST 날짜**+duration_days의 **KST 00:00** → 배틀은 항상 자정~자정(daily 배치 창 정합).

### `battle_invites` (48h 만료)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | uuid PK | |
| battle_id | uuid FK→battles | v0: 배틀당 1행(1v1) |
| inviter | uuid | = battles.created_by |
| invitee | uuid | = battles.opponent |
| status | text NOT NULL default 'pending' | CHECK ('pending','accepted','declined','expired','cancelled') |
| expires_at | timestamptz NOT NULL | 생성 + **48h** |
| responded_at | timestamptz | 수락/거절 시각 |
| created_at | timestamptz default now() | |

- **만료**: `expires_at < now()` & status=pending → daily 배치(또는 조회 시 lazy)가
  `expired` + battle `cancelled`. 수락은 만료 전만 유효.

### `battle_runs` (런↔배틀 귀속 + per-run 점수)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | uuid PK | |
| battle_id | uuid FK→battles | |
| user_id | uuid | 참가자(created_by 또는 opponent) |
| run_id | uuid FK→runs | |
| attributed_at | timestamptz NOT NULL | **= runs.ran_at**(귀속 시각, Q4=① 저장시각) |
| counted | boolean NOT NULL default false | verified·非flagged·≥1.5km·창내 = true |
| run_score | numeric NOT NULL default 0 | per-run 점수(정산 재계산) |
| breakdown | jsonb | base/completion/pace/early_bird/milestone 분해 |
| created_at | timestamptz default now() | |
| | | **UNIQUE (battle_id, run_id)** — 런당 배틀별 1회 |

- **귀속 기준(Q4=①)**: `attributed_at = ran_at`이 `[started_at, ends_at)` 창 내면 그 배틀에
  귀속. daily 배치가 참가자의 창내 verified 런을 `battle_runs`에 upsert(멱등, UNIQUE).
- **milestone 메모리**: BATTLE_SPEC의 participant 컬럼 대신 **정산 시 결정론 계산** —
  참가자의 counted 런을 `ran_at` asc 정렬, **첫 ≥5km 런 = +30, 첫 ≥10km 런 = +50**
  (breakdown에 기록). 재계산이 결정론이라 중복 지급 불가(별도 메모리 컬럼 불요).

### 알림 3종(BATTLE_SPEC §5) — `notifications_type_check` drop→재생성(§C 함정)
`battle_invited`·`battle_overtaken`·`battle_won` 추가. `push_service` 템플릿·카테고리 동반.

---

## 2. 게이팅 (병행 — 결정②)

배틀 **생성**(POST /battles) 및 **수락**(POST /battles/{id}/accept) 진입 시:
1. **무료 30일 롤링 3회**(수익화): 티어 free이고 `SEED_EMAILS`·베타 아님이면,
   최근 30일(now−30d) 내 그 유저가 **관여(생성 or 수락)한 배틀 수 ≥ 3**이면 **403
   `battle_free_limit`**. 프리미엄·베타·시드 스킵. (관여 = created_by=me OR
   accepted invite. `battles.created_at` 또는 `invites.responded_at` 기준 카운트.)
2. **동시 active 3개**(제품 캡, 전 티어): 그 유저가 참가자인 `status='active'` 배틀 수
   ≥ 3이면 **409 `battle_active_cap`**. (생성·수락 모두 검사 — 4번째 진입 거부.)

- **베타/티어 연계**: `quota_service.get_tier`(premium 판정) + `beta_default_premium`은
  이미 tier=premium로 부여되므로 **베타 = premium 취급**되어 자동 스킵. `SEED_EMAILS`
  (test1~3·demo·cvcv)는 tier=premium(수동)이라 역시 스킵 — 별도 이메일 체크 불요
  (tier 단일 게이트로 충분, 단일 소스). **레이스**: 카운트→생성 창은 §정산의 원자성
  대상 아님(과금 아닌 소프트 한도, 근사 3회 허용). 필요 시 RPC 원자화 후속.

---

## 3. 스코어링 (verified-only, §2.4 단일 게이트 재사용)

**anti-cheat = `verification='verified'` 단일 게이트**(§2.4). `max_speed_kmh` 직접 게이트
**금지**(터널·협곡 GPS 아티팩트 오배제 — 관측용). `is_flagged`·<1.5km 제외. 거리는
`distance_km`(adjusted면 서버 필터거리가 정본).

```
per-run(창내·verified·非flagged·≥1.5km 아니면 counted=false·score=0):
  base        = distance_km * 10
  completion  = +20                              (완주 = ≥1.5km + 정상저장)
  pace_bonus  = _pace_bonus(avg_pace_sec_per_km) (이반 battle-score.ts 미러 — §단일소스)
  early_bird  = +10  if ran_at(KST) 시각 < 07:00 (06:59 포함·07:00 미포함)
  milestone   = +30 (참가자 첫 ≥5km 런) + +50 (첫 ≥10km 런)   # 정산 결정론
  run_score   = base + completion + pace_bonus + early_bird + milestone

참가자 점수:
  streak_multiplier = 1 + 0.05 * min(current_streak, 10)   # cap 1.5 (스트릭×1.5)
  participant_score = Σ run_score * streak_multiplier

승자: participant_score 큰 쪽. 동점 = winner null(무승부). 포기자 있으면 상대 승(§4).
```

- **단일 소스(§C)**: 상수(×10·+20·+10·+30/+50·0.05·cap1.5·하한1.5·07:00)는 이반
  `battle-score.ts` 값을 **서버 상수로 미러**. **`_pace_bonus`는 이반 lib 상수 미도착 —
  v0는 플레이스홀더 계단식**(문서 명기, 착수 전 이반 값으로 교체·판단 플래그).
- **early_bird(ran_at 근사)**: 서버는 런 **시작 시각 미보유**(ran_at=저장시각, GPS t
  스트립). Q4=ran_at 단일 시간원 일관성상 **ran_at KST로 판정** — 실시간 트래킹은
  ran_at≈종료시각이라 "07시 전 저장" = 이른 아침 런에 근사 부합. **한계**: 06:40 시작
  07:10 저장 런은 early_bird 미부여(엄격측). 클라 시작시각 계약 시 v1.1 정밀화(파킹).
- **streak**: `runs.ran_at` KST 날짜 버킷 + verified, 오늘부터 역순 연속(BATTLE_SPEC §1
  공용 헬퍼). 정산일 기준 재계산(백필 조작 무효).

---

## 4. 라이프사이클 · 정산

**상태 전이**:
- 생성(POST /battles): `pending` + battle_invites(48h). 게이팅 검사(§2).
- 수락(accept): 만료 전만. `pending`→`active`, `started_at`=now, `ends_at`=KST자정+duration.
  게이팅 §2 재검사(수락자 기준). invite status=accepted.
- 거절(decline): invite=declined, battle=`cancelled`.
- 만료(48h): invite=expired, battle=`cancelled`(daily 배치 or lazy).
- 포기(forfeit): active→`forfeited`. **포기자 점수 그 시점 고정, 상대 유지·감점 없음**
  (룰링④). winner=상대, settled_at=now 즉시 확정.
- 상호취소(mutual cancel): active 배틀을 **양자 합의** 취소 — 요청자 표시(cancel_requested
  jsonb 또는 별도), 상대가 confirm하면 `cancelled`. v0: **양쪽 다 취소요청 시 취소**
  (한쪽 요청은 대기, 상대 요청 합류 시 확정 — 단순화). 무승부 처리(winner null).

**정산 배치(KST 자정 daily + 종료 조기정산)**:
- 트리거: fly 스케줄(GH Actions는 60일 무활동 비활성 §C). `battle_service.settle_batch()`.
- 각 `active` 배틀: 참가자별 `[started_at, min(now, ends_at))` 창의 verified·非flagged
  런을 `battle_runs` upsert(멱등) → per-run 점수 재계산 → milestone 결정론 → streak_mult →
  participant_score. **결과 영속**(battle_runs.run_score/breakdown). 순위 역전 시
  `battle_overtaken` 알림(1일 1회 자연 스로틀).
- **종료 판정**: `now >= ends_at + 30분`(유예③)이면 최종 정산 → winner 확정, status=`ended`,
  settled_at=now, `battle_won` 알림. (30분 유예 = 종료 직후 조기 정산 시 지각 저장 흡수;
  daily 배치 주기상 통상 자정에 최종 정산되어 유예가 자연 흡수됨.)
- **멱등**: 배치는 언제 몇 번 돌아도 같은 결과(battle_runs UNIQUE + 결정론 재계산).

---

## 5. 엔드포인트 (이반 목데이터 → 실연결, API_GUIDE 계약)

경로 순서: 고정 경로 먼저(§ 일반 규칙). uuid path param은 `validate_uuid_path_params`
자동 커버.

| 메서드·경로 | 용도 |
|---|---|
| `POST /battles` | 생성(+초대). 게이팅. body: opponent·title·emoji·duration_days·format? |
| `GET /battles` | 내 배틀 리스트 — `?status=active\|pending\|ended`(생략 전체) |
| `GET /battles/{id}` | 상세 — 점수·순위·런목록(breakdown)·상대 |
| `POST /battles/{id}/accept` | 수락(=진행 전이·게이팅) |
| `POST /battles/{id}/decline` | 거절 |
| `POST /battles/{id}/forfeit` | 포기(즉시 패배) |
| `POST /battles/{id}/cancel` | 상호취소 요청(양자 합의) |
| `POST /battles/settle` | (관리·크론) 정산 배치 재실행 — admin/서비스 전용 |

- 권한: 참가자(created_by·opponent)만 상세·전이 — 아니면 **404 은닉**(표준).
- eligibility(룰링②): 생성 시 opponent 차단/비공개 관계 검사 → **404 은닉**.

---

## 6. 테스트 계획 (§E)

- **스코어 순수**(무DB): per-run 공식·streak_mult·milestone 결정론·early_bird 경계·
  <1.5km/flagged 0점.
- **게이팅**: 30일 롤링 3회 경계(2→OK, 3→403)·프리미엄/베타 스킵·동시 active 3캡(409).
- **라이프사이클**: pending→active(수락)·48h 만료·decline·forfeit(즉시패배·상대유지)·
  상호취소. 상태 전이 불변식.
- **정산**: 창내 verified만 집계·adjusted 정본·멱등(2회 실행 동일)·종료+30분 winner 확정.
- **레이스**: `asyncio.gather` 동시 수락/생성 — 동시 active 캡 불변식(초과 0), 정산 동시.
- **DB 부수효과 assert**(battle_runs 행·status 전이·winner). SQL 미적용 시 **검증 불가**
  표기(오너 실행 후 재검, 순수 스코어·게이팅 카운트 로직은 무DB 커버).

---

## 7. 결정 이력 (§F 재검토 트리거)

- **Q4=ran_at**(2026-09-07): 재검토 트리거 = HK-import 런이 흔해져 저장 지각이 정당 런을
  자름이 관측되면 `ended_at` additive 컬럼+클라 계약.
- **게이팅 병행**(2026-09-07): 30일 롤링(수익화)+동시3(제품). 재검토 = 전환율·스팸 관측.
- **유예 30분**(2026-09-07): daily 배치가 사실상 흡수. 재검토 = 조기정산 UX 요구 시.
- **1v1 고정·그룹 파킹**: 트리거 = 다대다 배틀 착수 → BATTLE_SPEC §3 그룹레디로 확장.
- **_pace_bonus 플레이스홀더**: 이반 `battle-score.ts` 상수 도착 시 미러 교체(단일 소스).
- **early_bird ran_at 근사**: 클라 런 시작시각 계약 시 정밀화.
