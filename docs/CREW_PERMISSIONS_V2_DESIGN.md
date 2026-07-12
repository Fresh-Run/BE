# CREW_PERMISSIONS_V2_DESIGN — 크루 세부 권한 (설계)

> 2026-07-13. 상태: **배포됨** (5건 승인·SQL 적용·구현 완료). admin v1의 role 2단
> (owner/admin 일괄 허용)을 **per-운영진 permission set(5키)**으로 확장.
> tier-agnostic(프리미엄 게이트는 11월 IAP 사이클). freshrun-feature 절차:
> 이 문서 승인 → SQL 페어 실행(사용자) → 구현.

## 0. 확정 스코프 (시안 + 친구 합의)

권한 5키 (전부 bool):
| 키 | 의미 | 분류 |
|---|---|---|
| `announcements` | 공지 CRUD | 일반 |
| `challenges` | 챌린지 생성·수정 | 일반 |
| `edit_crew` | 크루 정보 수정 + 커버/아이콘 이미지 | 일반 |
| `kick_members` | 멤버 추방 | **주의** |
| `manage_admins` | 다른 운영진 지정·해제·권한 조정 | **주의** |

- **범위 밖(박제 금지)**: 멤버 초대(=all-members 유지, `POST /crews/{id}/invitations`),
  크루 러닝 시작(미정의 개념).
- owner는 전 권한 **암묵 보유**(레코드 불요 — 게이트에서 owner 단락).

---

## 1. 저장 모델 — 비교 · 추천

| 방식 | 장점 | 단점 | 우리 패턴 적합성 |
|---|---|---|---|
| **JSONB (`crew_members.permissions`)** | settings JSONB 선례와 동형·additive 키 확장 자유·행 조회에 무료 편승(_member_role/명단이 이미 crew_members 행을 읽음)·앱 화이트리스트 검증(`_sanitize_settings` 선례) | DB 레벨 키 제약 없음(앱이 검증) | **★ 최적** |
| 비트마스크 (int) | compact | 불투명(디버깅·로그 난독)·키 추가 시 비트 관리·프론트 파싱 부담 | 낮음 |
| 별도 테이블 (`crew_member_permissions`) | 정규화·쿼리 가능 | 5-bool에 조인 추가·CRUD 복잡·행 조회 N+1 유발 | 과설계 |

**추천: JSONB `crew_members.permissions`**. 근거: `profiles.settings` jsonb
화이트리스트 선례와 정합, additive-friendly, 멤버 행 조회에 이미 편승(추가 쿼리
0). 앱 레이어 화이트리스트로 미지 키 방어(settings `_sanitize` 패턴 재사용).

- **값 스키마**: `{"announcements":bool,"challenges":bool,"edit_crew":bool,
  "kick_members":bool,"manage_admins":bool}`. role=member·owner는 `null`
  (member=권한 없음, owner=암묵 전권 — 레코드 불요).
- **RLS**: crew_members는 이미 enable(백스톱). 컬럼 추가만.

---

## 2. 게이트 전환 — ensure_manager/owner → ensure_permission (호출처 전수 분류)

신규 게이트: `ensure_permission(crew_id, caller_id, key)` — owner면 통과, 아니면
role=admin **AND** `permissions[key]==true`면 통과, 아니면 `NotOwner`(기존 403
계약 유지). 호출처 실감사 결과:

| 현재 게이트 | 함수 (file) | v2 전환 | 비고 |
|---|---|---|---|
| ensure_manager | create/update/delete_announcement (announcement_service) ×3 | `ensure_permission(…, "announcements")` | |
| ensure_manager | create_challenge (crew_service) | `…"challenges"` | (챌린지 수정 API는 현재 없음 — 생성만) |
| ensure_manager | kick_member | `…"kick_members"` | |
| ensure_manager | create_crew_image_upload_url | `…"edit_crew"` | 이미지=edit_crew |
| **ensure_owner** | update_crew | `…"edit_crew"` | **v1은 owner 전용 → v2에서 admin에게 개방(edit_crew)** |
| **ensure_owner** | set_member_role | **manage_admins**(신규 — 아래 §3) | v1 owner 전용 |
| ensure_manager | **delete_message (chat_service)** | **⚠️ 5키에 없음** — 아래 판단 플래그 | 채팅 모더레이션 |
| ensure_owner (유지) | invite_code·regenerate·list/decide_join_request·transfer_ownership·delete_crew | **owner 전용 유지** | 5키 밖 — 크루 존립·소유권은 owner만 |

### ⚠️ 감사 발견 (설계-결정 필요 — 시안 전제와 코드 불일치)

**F1. `chat_service.delete_message`가 ensure_manager인데 5키에 홈이 없음.**
- v1 admin은 채팅 메시지 삭제(모더레이션)도 가능했다. 5키 어디에도 자연스럽게
  안 맞음. **추천**: 채팅 모더레이션은 **role 기반(any admin/owner) 유지** —
  permission 키에서 분리(별도 `_is_manager_role` 경량 체크). 근거: 확정 5키 밖
  개념을 임의 키에 박제하지 않는다(스코프 규율). 향후 `moderate_chat` 키 수요
  시 6번째로 추가. **대안**: `announcements`에 묶기(둘 다 "크루 소통 관리") —
  비추(성격 다름). → **owner 판단 요청**.

**F2. `edit_crew` 소급 = 부분 확장.** v1 admin은 크루 **이미지**(ensure_manager)는
가능했으나 크루 **정보 수정**(update_crew=owner 전용)은 **불가**였다. edit_crew
한 키가 둘을 묶으므로 소급 ON이면 admin이 정보 수정 능력을 새로 얻는다(경미한
확장). 소급 OFF면 **이미지 능력을 잃는다(축소 — 금지)**. **추천: edit_crew 소급
ON** — 가졌던 이미지 능력 보존이 우선(축소 금지), 정보-수정 확장은 admin=고신뢰
전제라 수용. (5키 고정이라 이미지/정보 분리 불가.)

**F3. `manage_admins` 소급 = 위험한 은닉 확장.** v1 admin은 role 변경이 **불가**
(owner 전용)였다. 시안 지시("소급 전부 ON")를 문자 그대로 따르면 **모든 기존
admin이 다른 admin을 지정·해제할 수 있게 됨** — 위임 사슬 리스크의 은닉 발생
(preservation이 아니라 expansion). **추천: manage_admins 소급 OFF**. 근거:
"동작 보존"의 핵심은 "권한이 조용히 **줄면** 안 됨"인데, manage_admins는 admin이
애초에 **안 가졌던** 권한이라 OFF가 진짜 보존. 가장 위험한 키라 보수적 기본이
안전. → **시안의 "전부 ON"에서 이탈하는 판단이라 owner 확인 요청.**

**소급 기본값 추천(F2·F3 반영)**: 기존 role=admin 행 →
`{announcements:true, challenges:true, edit_crew:true, kick_members:true,
manage_admins:false}`. (전부 ON이 아니라 **manage_admins만 false**.)

---

## 3. manage_admins — 위임 사슬 리스크 · grant 범위 제한

`set_member_role`(role 변경)과 permissions 조정을 manage_admins 보유자에게 개방
하면 admin이 admin을 만들 수 있다. 무제한이면 권한 상향(escalation)·admin 카르텔
리스크. **추천 규칙(두 제약 결합)**:

1. **자기가 가진 권한만 부여 가능** (no self-escalation): manage_admins admin은
   자신이 보유한 키만 타 admin에게 grant. 안 가진 edit_crew를 남에게 못 줌.
2. **"주의" 2키(`kick_members`·`manage_admins`)는 owner만 grant** — manage_admins
   admin이라도 이 둘은 부여 불가(자기가 가졌어도). 근거: 크루의 위험 권한이
   owner 동의 없이 번지면 안 됨("주의" 분류의 의미). manage_admins admin은
   로스터 관리(promote/demote) + 안전 3키(announcements·challenges·edit_crew)만
   조정.
3. **불변식**: owner는 대상 불가(RoleTargetIsOwner 422 — 기존 유지). admin은
   owner를 demote/수정 불가. 자기 자신의 manage_admins는 **셀프 회수 불가**
   (락아웃 방지 — owner만 회수). admin→member 강등은 manage_admins로 가능하나
   대상이 owner면 불가.

요약 grant 매트릭스:
| grant 주체 | announcements·challenges·edit_crew | kick_members·manage_admins | promote/demote(role) |
|---|---|---|---|
| owner | ○ (전부) | ○ | ○ |
| admin + manage_admins | ○ **단 자기 보유분만** | ✗ (owner만) | ○ (member↔admin, owner 제외) |
| 그 외 | ✗ | ✗ | ✗ |

---

## 4. API

| method | 경로 | 게이트 | 비고 |
|---|---|---|---|
| PATCH | `/crews/{id}/members/{uid}/permissions` `{announcements?,challenges?,edit_crew?,kick_members?,manage_admins?}` | owner **또는** manage_admins admin(§3 제약) | 부분 PATCH(보낸 키만). 대상은 **role=admin이어야**(member/owner 대상 422). 미지 키 422(화이트리스트). "주의" 2키는 owner만(admin이 보내면 403) |
| PATCH | `/crews/{id}/members/{uid}/role` `{role}` | v1 owner 전용 → **manage_admins로 확장**(§3) | admin 승격 시 **시안 기본 permissions 자동 부여**: `{announcements:true,challenges:true,edit_crew:false,kick_members:false,manage_admins:false}` (⚠️ 시안 재확인 후 확정). member 강등 시 permissions=null |
| GET | `/crews/{id}/members` | 기존 | 각 항목에 **`permissions`**(admin만 obj, member=null, owner=5키 all-true 합성) |
| GET | `/crews/{id}` | 기존 | **`admin_count`**(role=admin 수 — 관리 화면 통계 소품 동승) |

- **신규 admin 기본 permissions** vs **소급 admin 기본**은 **다르다**: 신규=시안
  보수 기본(edit_crew·kick·manage_admins OFF), 소급=동작 보존(edit_crew ON,
  manage_admins OFF). 문서·주석에 명시.
- owner 행의 permissions: 응답에서 all-true 합성(프론트 렌더 일관 — owner는
  전 토글 ON·비활성으로 표시 가능). 저장은 null(암묵 전권).

---

## 5. 하위 호환

- **`role` 필드 유지** — admin 판별은 `role`, **행동 가능 여부는 `permissions`**.
  프론트 기존 role 분기(owner/admin/member 표시·정렬) 무영향. permissions·
  admin_count는 **additive**(Optional/기본값) — 안 읽는 프론트는 무변화.
- **에러 계약 불변**: 권한 없는 admin의 차단은 **403**(ensure_manager의 NotOwner
  → 기존 403 유지). 존재 은닉(404) 대상 아님(크루원엔 크루 존재가 이미 보임).
- **소급 UPDATE로 기존 운영진 동작 보존**(§2 F2·F3 추천 기본값). 축소 0.

---

## 6. 알림 — 권한 변경 통지?

- **추천: v2에선 통지 없음**(v1 role 변경도 무통지 — set_member_role은 알림
  미발송). 근거: 권한 변경은 행정적·저긴급, 대상 admin은 다음 크루 관리 화면
  진입 시 자기 permissions 확인. 통지 추가 = 신규 notif type(CHECK 재작성)+
  템플릿 = 한계 가치 대비 비용 큼. **수요 시 후속**(`admin_permissions_changed`
  type 선등록 후보로만 기록). → v1 "role 변경 통지는 묶음에서"와 동일하게 보류.

---

## 7. 테스트 계획

- **권한 매트릭스**: 5키 × {owner / admin-보유 / admin-미보유 / member} × 각
  보호 엔드포인트(공지 CRUD·챌린지·update_crew·이미지·kick·role·permissions).
  기대: owner 항상 통과 / admin은 해당 키 보유 시만 통과(미보유 403) / member 403.
- **소급 기본값**: 마이그레이션 후 기존 admin이 announcements·challenges·edit_crew·
  kick 통과, manage_admins 차단(F3) — DB 부수효과(permissions jsonb) assert.
- **신규 admin 기본**: promote 직후 permissions=시안 기본(edit_crew·kick·
  manage_admins OFF) assert.
- **위임 사슬 제한(§3)**: manage_admins admin이 (a) 자기 미보유 키 grant 시도 →
  거부 (b) kick_members·manage_admins grant 시도 → 403(owner만) (c) 안전 키
  grant → 성공 (d) owner 대상 수정 → 422 (e) 셀프 manage_admins 회수 → 거부.
- **admin_count**: promote/demote/kick·owner 위임 후 카운트 갱신 assert.
- **하위 호환**: role 필드·기존 role 분기 무영향 / permissions 없는 구프론트
  호출 무변화.
- **회귀**: crew_admin_area·crew_manage·announcements·challenge·crew_images·
  crew_invitations.

---

## 8. SQL 페어 (승인 후 사용자 실행 — 아직 미실행)

```sql
-- [APPLY]
alter table public.crew_members add column if not exists permissions jsonb;

-- 소급: 기존 admin은 v1 동작 보존 (F2·F3 추천 — manage_admins만 false).
-- ⚠️ 시안이 "전부 ON"을 고수하면 manage_admins도 true로 바꿔 실행.
update public.crew_members
   set permissions = '{"announcements":true,"challenges":true,"edit_crew":true,'
                     '"kick_members":true,"manage_admins":false}'::jsonb
 where role = 'admin' and permissions is null;

-- 실행 후 확인:
-- select role, count(*), count(permissions) from public.crew_members group by role;

-- [ROLLBACK]
-- alter table public.crew_members drop column if exists permissions;
```

---

## 9. 판단 플래그 (승인 시 확정 필요)

1. **F3 manage_admins 소급 = OFF 추천**(시안 "전부 ON"에서 이탈). v1 admin이
   role 관리 권한이 없었으므로 OFF가 진짜 "동작 보존". → **명시 승인 필요.**
2. **F1 채팅 모더레이션(delete_message)**: 5키 밖 → role 기반(any admin) 유지
   추천. → 확인.
3. **신규 admin 시안 기본값**(edit_crew·kick·manage_admins OFF): 시안 토글 초기
   상태 기준 — **시안 재확인 후 확정**(스펙에 "실제 기본값은 시안 재확인").
4. **위임 사슬 §3 규칙**(자기 보유분만 + 주의 2키 owner-only) 채택 여부.
5. **manage_admins admin의 role 변경 개방** 자체 승인(v1 owner 전용 → 확장).

승인·확정 후: SQL 페어 실행(사용자) → 구현(게이트 전환·API·응답·테스트).
