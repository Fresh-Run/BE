// FreshRun — 커뮤니티 tab, crew-centric rebuild.
// Screen 1: calm main page (내 크루 list, mega-challenges live in the same list,
//           a persistent "주변 크루 둘러보기" entry, one small meetups row).
// Screen 2: FrCrewDetail (pushed) — crew header + active challenge + crew ranking.
const CMF = window.FR_FONT;

// ── crew data ──────────────────────────────────────────
// type 'challenge' = public mega-challenge shown as a crew card. Each crew owns
// an active challenge + a small-group ranking (current user = 지윤).
const FR_MY_CREWS = [
  {
    id: 'cr-seongsu', type: 'crew', name: '성수 새벽 크루', members: 42, area: '성수 · 뚝섬', myRank: 3, unread: 2, seed: 'crew-seongsu',
    challenge: { title: '주간 50K 릴레이', done: 36.2, goal: 50, days: 4 },
    ranking: [
      { name: '오세훈', km: 48.1 }, { name: '강다은', km: 41.5 }, { name: '지윤', km: 36.2, me: true },
      { name: '문가영', km: 33.8 }, { name: '백승호', km: 29.4 }, { name: '서지안', km: 24.0 },
    ],
  },
  {
    id: 'cr-pacers', type: 'crew', name: '한강 페이서스', members: 118, area: '여의도 · 반포', myRank: 12, unread: 0, seed: 'crew-hangang',
    challenge: { title: '서브4 빌드업', done: 22.0, goal: 40, days: 9 },
    ranking: [
      { name: '임도윤', km: 39.2 }, { name: '조하늘', km: 37.6 }, { name: '신우진', km: 35.1 },
      { name: '권나래', km: 31.8 }, { name: '지윤', km: 22.0, me: true }, { name: '홍민재', km: 19.4 },
    ],
  },
];

const FR_NEARBY_COUNT = 12;

// nearby crews to discover (둘러보기 탭). max = capacity (full when members >= max)
const FR_NEARBY_CREWS = [
  { id: 'nb1', name: '뚝섬 선셋 러너스', members: 86, max: 120, area: '뚝섬 · 성수', region: '성수', dist: '0.4km', tags: ['저녁', '평지'], level: '무관', seed: 'nb-ttukseom' },
  { id: 'nb2', name: '서울숲 새벽 크루', members: 54, max: 60, area: '서울숲 · 성수', region: '성수', dist: '0.8km', tags: ['새벽', '경치'], level: '입문', seed: 'nb-seoulforest' },
  { id: 'nb3', name: '한강 페이스메이커', members: 212, max: 212, area: '반포 · 잠원', region: '한강', dist: '1.2km', tags: ['스피드', '강변'], level: '고급', seed: 'nb-hangang' },
  { id: 'nb4', name: '성수 점심 런', members: 38, max: 50, area: '성수동', region: '성수', dist: '1.5km', tags: ['점심', '도심'], level: '중급', seed: 'nb-seongsu' },
  { id: 'nb5', name: '남산 힐러너스', members: 73, max: 73, area: '남산 · 회현', region: '남산', dist: '2.1km', tags: ['언덕', '훈련'], level: '고급', seed: 'nb-namsan' },
  { id: 'nb6', name: '응봉산 모닝 크루', members: 41, max: 80, area: '응봉 · 금호', region: '응봉', dist: '2.6km', tags: ['새벽', '언덕'], level: '중급', seed: 'nb-eungbong' },
  { id: 'nb7', name: '여의도 라이트런', members: 64, max: 100, area: '여의도', region: '여의도', dist: '3.4km', tags: ['저녁', '강변'], level: '입문', seed: 'nb-yeouido' },
  { id: 'nb8', name: '한강 나이트 크루', members: 150, max: 150, area: '반포 한강공원', region: '한강', dist: '3.9km', tags: ['야간', '강변'], level: '무관', seed: 'nb-hannight' },
];

// joinable challenges (챌린지 탭). Reuses the existing challenge card format.
const FR_OPEN_CHALLENGES = [
  { id: 'oc1', title: '여의도 벚꽃 30K', sport: '러닝', badge: '시즌', area: '여의도 한강공원', period: '6.1 – 6.30', goal: 30, done: 0, days: 18, members: 642, seed: 'oc-yeouido' },
  { id: 'oc2', title: '성수 새벽 7일 루틴', sport: '러닝', badge: '입문', area: '성수 · 뚝섬', period: '6.24 – 6.30', goal: 14, done: 0, days: 6, members: 318, seed: 'oc-seongsu' },
  { id: 'oc3', title: '한강 라이딩 200K', sport: '라이딩', badge: '챌린지', area: '한강 자전거길', period: '6.1 – 6.30', goal: 200, done: 0, days: 12, members: 209, seed: 'oc-riding' },
  { id: 'oc4', title: '남산 둘레길 워킹', sport: '워킹', badge: '입문', area: '남산 · 회현', period: '6.10 – 7.10', goal: 40, done: 0, days: 24, members: 487, seed: 'oc-namsan' },
];

// my in-progress challenges (액티브 탭) — pulled from my crews + a personal goal
const FR_ACTIVE_SUMMARY = { weekDone: 22.4, weekGoal: 30, streak: 5, sessions: 4 };

// ── tab bar: text tabs + lime underline ────────────────
function FrCmTabs({ c, tabs, active, onChange }) {
  const grn = c.dark ? c.accent : '#3C7A14';
  return (
    <div style={{ display: 'flex', gap: 22, padding: '16px 20px 0', borderBottom: `1px solid ${c.border}` }}>
      {tabs.map(t => {
        const on = active === t.id;
        return (
          <button key={t.id} onClick={() => onChange(t.id)} style={{ position: 'relative', background: 'none', border: 'none', padding: '0 0 12px', cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
            <span style={{ fontFamily: CMF, fontSize: 15, fontWeight: on ? 700 : 600, color: on ? c.text : c.faint, letterSpacing: -0.3, transition: 'color .15s' }}>{t.label}</span>
            {on && <span style={{ position: 'absolute', left: 0, right: 0, bottom: -1, height: 2.5, borderRadius: 99, background: c.accent }} />}
          </button>
        );
      })}
    </div>
  );
}

// horizontal filter chips (pill, green border when active)
function FrCmChips({ c, chips, active, onChange }) {
  const grn = c.dark ? c.accent : '#3C7A14';
  return (
    <div style={{ display: 'flex', gap: 8, overflowX: 'auto', padding: '14px 20px 2px', WebkitOverflowScrolling: 'touch' }}>
      {chips.map(ch => {
        const on = active === ch;
        return (
          <button key={ch} onClick={() => onChange(ch)} style={{ flexShrink: 0, height: 34, padding: '0 15px', borderRadius: 999, cursor: 'pointer', background: on ? c.accentDim : c.surface, border: `1.5px solid ${on ? c.accent : c.border}`, fontFamily: CMF, fontSize: 13, fontWeight: 700, color: on ? grn : c.sub, letterSpacing: -0.2, whiteSpace: 'nowrap', WebkitTapHighlightColor: 'transparent' }}>{ch}</button>
        );
      })}
    </div>
  );
}

// joinable-challenge card (챌린지 탭)
function FrOpenChallengeCard({ c, ch, joined, onJoin }) {
  const grn = c.dark ? c.accent : '#3C7A14';
  const pct = Math.round((ch.done / ch.goal) * 100);
  return (
    <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 20, overflow: 'hidden', boxShadow: c.shadow }}>
      <div style={{ position: 'relative', height: 120 }}>
        <FrMiniMap seed={ch.seed} width="100%" height={120} radius={0} hero />
        <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(180deg, rgba(8,12,4,0.42), rgba(8,12,4,0.08))' }} />
        <div style={{ position: 'absolute', top: 12, left: 12, display: 'flex', gap: 7 }}>
          <span style={{ fontFamily: CMF, fontSize: 11, fontWeight: 700, color: '#0D1A06', background: '#7CF03D', borderRadius: 999, padding: '4px 10px', whiteSpace: 'nowrap' }}>{ch.badge}</span>
          <span style={{ fontFamily: CMF, fontSize: 11, fontWeight: 700, color: '#fff', background: 'rgba(0,0,0,0.42)', backdropFilter: 'blur(4px)', borderRadius: 999, padding: '4px 10px', whiteSpace: 'nowrap' }}>{ch.sport}</span>
        </div>
        <span style={{ position: 'absolute', top: 12, right: 12, fontFamily: CMF, fontSize: 11.5, fontWeight: 800, color: '#0D1A06', background: '#7CF03D', borderRadius: 8, padding: '4px 9px', letterSpacing: -0.2 }}>D-{ch.days}</span>
      </div>
      <div style={{ padding: 16 }}>
        <div style={{ fontFamily: CMF, fontSize: 17, fontWeight: 700, color: c.text, letterSpacing: -0.5 }}>{ch.title}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 7 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><FrXIcon name="calendar" size={13} color={c.faint} sw={1.9} /><span style={{ fontFamily: CMF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2 }}>{ch.period}</span></span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><FrIcon name="pin" size={13} color={c.faint} sw={1.9} /><span style={{ fontFamily: CMF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{ch.area}</span></span>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginTop: 14, marginBottom: 6 }}>
          <span style={{ fontFamily: CMF, fontSize: 12.5, fontWeight: 600, color: c.sub, letterSpacing: -0.2 }}>목표 {ch.goal}km</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontFamily: CMF, fontSize: 12, color: c.faint }}><FrIcon name="users" size={12} color={c.faint} sw={2} />{ch.members.toLocaleString()}명 참여</span>
        </div>
        <div style={{ height: 6, borderRadius: 99, background: c.surfaceAlt, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: (joined ? pct || 4 : 0) + '%', background: c.accent, borderRadius: 99, transition: 'width .3s' }} />
        </div>
        <button onClick={() => onJoin(ch.id)} style={{ width: '100%', height: 48, borderRadius: 13, border: joined ? `1px solid ${c.border}` : 'none', background: joined ? c.surfaceAlt : c.accent, color: joined ? c.sub : c.accentText, fontFamily: CMF, fontSize: 14.5, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 14 }}>{joined ? '참여 중' : '챌린지 참여하기'}</button>
      </div>
    </div>
  );
}

// active progress card (액티브 탭) — reuses crew challenge model, shows my progress
function FrActiveChallengeRow({ c, crew, onOpen }) {
  const grn = c.dark ? c.accent : '#3C7A14';
  const ch = crew.challenge;
  const pct = Math.round((ch.done / ch.goal) * 100);
  return (
    <button onClick={() => onOpen(crew)} style={{ width: '100%', textAlign: 'left', display: 'block', background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 15, cursor: 'pointer', boxShadow: c.shadow, WebkitTapHighlightColor: 'transparent' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontFamily: CMF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{ch.title}</span>
        <span style={{ fontFamily: CMF, fontSize: 11.5, fontWeight: 800, color: c.accentText, background: c.accent, borderRadius: 8, padding: '4px 9px', letterSpacing: -0.2, flexShrink: 0 }}>D-{ch.days}</span>
      </div>
      <div style={{ fontFamily: CMF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 3 }}>{crew.name}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 13 }}>
        <span style={{ fontFamily: CMF, fontSize: 22, fontWeight: 700, color: grn, letterSpacing: -0.7, fontVariantNumeric: 'tabular-nums' }}>{ch.done}</span>
        <span style={{ fontFamily: CMF, fontSize: 13, fontWeight: 600, color: c.faint }}>/ {ch.goal}km</span>
        <span style={{ fontFamily: CMF, fontSize: 12.5, fontWeight: 700, color: grn, marginLeft: 'auto' }}>{pct}%</span>
      </div>
      <div style={{ height: 7, borderRadius: 99, background: c.surfaceAlt, marginTop: 9, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: pct + '%', background: c.accent, borderRadius: 99 }} />
      </div>
    </button>
  );
}

// ── small shared bits ──────────────────────────────────
function FrCmSectionHead({ c, title, action, onAction }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 13 }}>
      <span style={{ fontFamily: CMF, fontSize: 17, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap' }}>{title}</span>
      {action && <button onClick={onAction} style={{ fontFamily: CMF, fontSize: 13, fontWeight: 600, color: c.sub, letterSpacing: -0.2, background: 'none', border: 'none', cursor: 'pointer', padding: 0, whiteSpace: 'nowrap' }}>{action}</button>}
    </div>
  );
}

function FrRankMedal({ c, rank, light }) {
  const med = { 1: '#E8B53D', 2: '#AEB6BE', 3: '#D08B4F' }[rank];
  if (med) return (
    <span style={{ width: 26, height: 26, borderRadius: 999, background: med, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      <span style={{ fontFamily: CMF, fontSize: 12.5, fontWeight: 800, color: '#fff' }}>{rank}</span>
    </span>
  );
  return <span style={{ width: 26, textAlign: 'center', fontFamily: CMF, fontSize: 13, fontWeight: 700, color: light ? 'rgba(255,255,255,0.6)' : c.faint, flexShrink: 0 }}>{rank}</span>;
}

// ── Screen 1: crew card ────────────────────────────────
function FrCrewCard({ c, crew, onOpen, fav, onFav }) {
  const grn = c.dark ? c.accent : '#3C7A14';
  const ch = crew.challenge;
  const pct = Math.round((ch.done / ch.goal) * 100);
  const isChallenge = crew.type === 'challenge';
  return (
    <button onClick={() => onOpen(crew)} style={{ width: '100%', textAlign: 'left', display: 'block', background: c.surface, border: `1px solid ${c.border}`, borderRadius: 20, padding: 15, cursor: 'pointer', boxShadow: c.shadow, WebkitTapHighlightColor: 'transparent' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 13 }}>
        <div style={{ width: 52, height: 52, borderRadius: 15, overflow: 'hidden', flexShrink: 0, position: 'relative' }}>
          <FrMiniMap seed={crew.seed} width={52} height={52} radius={15} />
          {isChallenge && <span style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(8,12,4,0.42)' }}><FrIcon name="trophy" size={20} color="#7CF03D" sw={1.9} /></span>}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{ fontFamily: CMF, fontSize: 15.5, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{crew.name}</span>
            {!crew.owner && crew.unread > 0 && <span style={{ width: 8, height: 8, borderRadius: 999, background: c.danger, flexShrink: 0 }} />}
            {crew.owner && <span style={{ display: 'flex', alignItems: 'center', gap: 3, fontFamily: CMF, fontSize: 10, fontWeight: 800, color: '#0D1A06', background: '#E8B53D', borderRadius: 6, padding: '2px 6px', letterSpacing: 0.2, flexShrink: 0 }}><FrXIcon name="crown" size={10} color="#0D1A06" sw={2} />크루장</span>}
            {isChallenge && <span style={{ fontFamily: CMF, fontSize: 10, fontWeight: 800, color: grn, background: c.accentDim, borderRadius: 6, padding: '2px 6px', letterSpacing: 0.2, flexShrink: 0 }}>챌린지</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 3 }}>
            <FrIcon name="users" size={12} color={c.faint} sw={2} />
            <span style={{ fontFamily: CMF, fontSize: 12, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{crew.members.toLocaleString()}명 · {crew.area}</span>
          </div>
        </div>
        <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          {onFav && (
            <span onClick={(e) => { e.stopPropagation(); onFav(crew.id); }} role="button" aria-label="즐겨찾기" style={{ width: 32, height: 32, borderRadius: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
              <FrXIcon name="star" size={19} color={fav ? '#E8B53D' : c.faint} fill={fav ? '#E8B53D' : 'none'} sw={1.9} />
            </span>
          )}
          <div style={{ textAlign: 'right' }}>
            {crew.owner && (
              <>
                <div style={{ fontFamily: CMF, fontSize: 10.5, fontWeight: 600, color: c.faint, letterSpacing: 0.2 }}>크루원</div>
                <div style={{ fontFamily: CMF, fontSize: 17, fontWeight: 800, color: grn, letterSpacing: -0.4, marginTop: 1, whiteSpace: 'nowrap' }}>{crew.members.toLocaleString()}</div>
              </>
            )}
          </div>
        </div>
      </div>
      {/* active challenge strip — challenges/goals are visually dominant */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ fontFamily: CMF, fontSize: 12, fontWeight: 600, color: c.sub, letterSpacing: -0.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{ch.title}</span>
            <span style={{ fontFamily: CMF, fontSize: 11.5, fontWeight: 700, color: c.faint, flexShrink: 0, marginLeft: 8 }}>{ch.done} / {ch.goal}km</span>
          </div>
          <div style={{ height: 6, borderRadius: 99, background: c.surfaceAlt, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: pct + '%', background: c.accent, borderRadius: 99 }} />
          </div>
        </div>
        {!ch.none && <span style={{ flexShrink: 0, fontFamily: CMF, fontSize: 11.5, fontWeight: 800, color: c.accentText, background: c.accent, borderRadius: 8, padding: '5px 9px', letterSpacing: -0.2 }}>D-{ch.days}</span>}
      </div>
    </button>
  );
}

// persistent discover entry (prominent when the user has no crews)
function FrDiscoverCrews({ c, count, prominent, onClick }) {
  const grn = c.dark ? c.accent : '#3C7A14';
  if (prominent) {
    return (
      <button onClick={onClick} style={{ width: '100%', textAlign: 'left', position: 'relative', overflow: 'hidden', background: '#0C1206', border: 'none', borderRadius: 22, padding: 20, cursor: 'pointer', boxShadow: c.shadow }}>
        <div style={{ position: 'absolute', top: -34, right: -34, width: 130, height: 130, borderRadius: 999, background: '#7CF03D', opacity: 0.18 }} />
        <div style={{ position: 'relative' }}>
          <span style={{ display: 'flex', width: 48, height: 48, borderRadius: 14, background: '#7CF03D', alignItems: 'center', justifyContent: 'center' }}>
            <FrIcon name="users" size={24} color="#0D1A06" sw={2} />
          </span>
          <div style={{ fontFamily: CMF, fontSize: 19, fontWeight: 700, color: '#fff', letterSpacing: -0.5, marginTop: 14 }}>주변 크루 둘러보기</div>
          <p style={{ fontFamily: CMF, fontSize: 13, lineHeight: 1.5, color: 'rgba(255,255,255,0.75)', letterSpacing: -0.2, margin: '7px 0 0' }}>근처에서 <b style={{ color: '#7CF03D' }}>{count}개</b>의 크루가 활동 중이에요. 함께 달릴 크루를 찾아보세요.</p>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 16, height: 44, padding: '0 18px', borderRadius: 999, background: '#7CF03D', color: '#0D1A06', fontFamily: CMF, fontSize: 14.5, fontWeight: 700, letterSpacing: -0.3 }}>
            크루 찾기 <FrXIcon name="chevright" size={16} color="#0D1A06" sw={2.4} />
          </span>
        </div>
      </button>
    );
  }
  return (
    <button onClick={onClick} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 13, background: c.surface, border: `1.5px dashed ${c.fieldBorder}`, borderRadius: 18, padding: 15, cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
      <span style={{ flexShrink: 0, width: 44, height: 44, borderRadius: 13, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <FrIcon name="users" size={21} color={grn} sw={2} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontFamily: CMF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>주변 크루 둘러보기</div>
        <div style={{ fontFamily: CMF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, marginTop: 2 }}>근처 {count}개 크루 활동 중</div>
      </div>
      <FrXIcon name="chevright" size={18} color={c.faint} sw={2.2} />
    </button>
  );
}

// ── Screen 2: crew detail ──────────────────────────────
function FrCrewRankRow({ c, r, rank, role }) {
  const grn = c.dark ? c.accent : '#3C7A14';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 12px', borderRadius: 14, background: r.me ? c.accentDim : 'transparent', border: r.me ? `1px solid ${c.accent}55` : '1px solid transparent' }}>
      <FrRankMedal c={c} rank={rank} />
      <FrAvatar name={r.name} size={38} ring={r.me ? c.accent : c.border} />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontFamily: CMF, fontSize: 14.5, fontWeight: r.me ? 700 : 600, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.name}</span>
        {r.me && <span style={{ fontFamily: CMF, fontSize: 10.5, fontWeight: 800, color: c.accentText, background: c.accent, borderRadius: 6, padding: '1px 6px', flexShrink: 0 }}>나</span>}
        {role === 'owner' && <span style={{ display: 'flex', alignItems: 'center', gap: 2, fontFamily: CMF, fontSize: 10, fontWeight: 800, color: '#0D1A06', background: '#E8B53D', borderRadius: 5, padding: '1px 5px', flexShrink: 0 }}><FrXIcon name="crown" size={9} color="#0D1A06" sw={2} />크루장</span>}
        {role === 'manager' && <span style={{ fontFamily: CMF, fontSize: 10, fontWeight: 800, color: grn, background: c.accentDim, borderRadius: 5, padding: '1px 5px', flexShrink: 0 }}>운영진</span>}
      </div>
      <span style={{ fontFamily: CMF, fontSize: 14.5, fontWeight: 700, color: r.me ? grn : c.sub, letterSpacing: -0.3, fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>{r.km}<span style={{ fontSize: 10.5, color: c.faint, fontWeight: 600 }}> km</span></span>
    </div>
  );
}

// attendance poll inside an announcement (참석 / 불참 vote)
function FrAttendancePoll({ c, poll, onVote }) {
  const grn = c.dark ? c.accent : '#3C7A14';
  const total = poll.yes + poll.no;
  const yesPct = total ? Math.round((poll.yes / total) * 100) : 0;
  const noPct = total ? 100 - yesPct : 0;
  const Opt = ({ vote, label, count, pct, ic }) => {
    const sel = poll.myVote === vote;
    const win = vote === 'yes';
    return (
      <button onClick={() => onVote(vote)} style={{ position: 'relative', flex: 1, overflow: 'hidden', height: 40, borderRadius: 11, border: `1.5px solid ${sel ? (win ? c.accent : c.danger) : c.border}`, background: c.surfaceAlt, cursor: 'pointer', display: 'flex', alignItems: 'center', padding: '0 12px', gap: 7, WebkitTapHighlightColor: 'transparent' }}>
        <span style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: pct + '%', background: win ? c.accentDim : (c.danger + '1F'), transition: 'width .25s' }} />
        <span style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 6, flex: 1 }}>
          {win ? <FrCIcon name="check" size={14} color={grn} sw={2.4} /> : <FrIcon name="close" size={14} color={c.danger} sw={2.4} />}
          <span style={{ fontFamily: CMF, fontSize: 13, fontWeight: 700, color: c.text, letterSpacing: -0.2 }}>{label}</span>
          {sel && <span style={{ fontFamily: CMF, fontSize: 10, fontWeight: 800, color: win ? grn : c.danger }}>✓</span>}
        </span>
        <span style={{ position: 'relative', fontFamily: CMF, fontSize: 12.5, fontWeight: 700, color: c.sub, fontVariantNumeric: 'tabular-nums' }}>{count}</span>
      </button>
    );
  };
  return (
    <div style={{ marginTop: 11, background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: 13, padding: 11 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 9 }}>
        <FrIcon name="users" size={13} color={c.faint} sw={2} />
        <span style={{ fontFamily: CMF, fontSize: 11.5, fontWeight: 700, color: c.sub, letterSpacing: -0.2 }}>이 러닝에 참석하시나요?</span>
        <span style={{ marginLeft: 'auto', fontFamily: CMF, fontSize: 11, color: c.faint }}>{total}명 참여</span>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <Opt vote="yes" label="참석" count={poll.yes} pct={yesPct} ic="check" />
        <Opt vote="no" label="불참" count={poll.no} pct={noPct} ic="close" />
      </div>
    </div>
  );
}

function FrCrewDetail({ c, app, params }) {
  const nav = app.nav;
  const paramCrew = (params && params.crew) || FR_MY_CREWS[0];
  // owner crews are live from app state so edits/announcements persist
  const liveCrew = (app.createdCrews || []).find(x => x.id === paramCrew.id);
  const crew = liveCrew || paramCrew;
  const me = (app && app.displayName) || '지윤';
  // viewAs: preview the crew as a specific manager (permission-scoped). Otherwise normal.
  const viewAs = params && params.viewAs;
  const realOwner = !!crew.owner;
  const managers = crew.managers || [];
  const owner = viewAs ? false : realOwner;
  const manager = viewAs ? true : managers.includes(me);
  const canManage = owner || manager;
  const PERM_FALLBACK = (window.FR_PERM_DEFAULT) || {};
  const perms = viewAs ? ((crew.perms && crew.perms[viewAs]) || PERM_FALLBACK) : null;
  const can = (k) => owner ? true : (viewAs ? !!perms[k] : !!perms_self(k));
  function perms_self(k) { const p = (crew.perms && crew.perms[me]) || PERM_FALLBACK; return !!p[k]; }
  const grn = c.dark ? c.accent : '#3C7A14';
  const [joined, setJoined] = React.useState(true);
  const [composing, setComposing] = React.useState(false);
  const [draft, setDraft] = React.useState('');
  const [pollOn, setPollOn] = React.useState(false);
  const announcements = crew.announcements || [];
  const postAnnouncement = () => {
    const text = draft.trim();
    if (!text) return;
    const an = { id: 'an-' + Date.now(), text, when: '방금 전' };
    if (pollOn) an.poll = { yes: 0, no: 0, myVote: null };
    app.updateCrew(crew.id, { announcements: [an].concat(announcements).slice(0, 6) });
    setDraft(''); setComposing(false); setPollOn(false);
  };
  const votePoll = (anId, vote) => {
    app.updateCrew(crew.id, { announcements: announcements.map(a => {
      if (a.id !== anId || !a.poll) return a;
      const p = { ...a.poll };
      const prev = p.myVote;
      if (prev === vote) { p[vote] = Math.max(0, p[vote] - 1); p.myVote = null; }
      else { if (prev) p[prev] = Math.max(0, p[prev] - 1); p[vote] = p[vote] + 1; p.myVote = vote; }
      return { ...a, poll: p };
    }) });
  };
  const ch = crew.challenge;
  const pct = ch.goal ? Math.round((ch.done / ch.goal) * 100) : 0;
  const ranked = crew.ranking.slice().sort((a, b) => b.km - a.km).slice(0, 10);
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      {/* dark crew header band */}
      <div style={{ position: 'relative', flexShrink: 0, background: '#0C1206', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', inset: 0, opacity: 0.5 }}><FrMiniMap seed={crew.seed} width="100%" height={210} radius={0} hero /></div>
        <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(180deg, rgba(8,12,4,0.6), rgba(8,12,4,0.92))' }} />
        <div style={{ position: 'relative', padding: '54px 16px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <button onClick={() => nav.pop()} aria-label="뒤로" style={{ width: 40, height: 40, borderRadius: 999, border: 'none', background: 'rgba(255,255,255,0.14)', backdropFilter: 'blur(6px)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FrCIcon name="back" size={20} color="#fff" sw={2.2} />
            </button>
            {owner && (
              <button onClick={() => nav.push('crewAdmin', { crewId: crew.id })} aria-label="크루 관리" style={{ display: 'flex', alignItems: 'center', gap: 6, height: 40, padding: '0 14px', borderRadius: 999, border: 'none', background: 'rgba(255,255,255,0.16)', backdropFilter: 'blur(6px)', cursor: 'pointer' }}>
                <FrXIcon name="gear" size={15} color="#fff" sw={1.9} />
                <span style={{ fontFamily: CMF, fontSize: 13, fontWeight: 700, color: '#fff', letterSpacing: -0.2 }}>크루 관리</span>
              </button>
            )}
            {viewAs && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, height: 32, padding: '0 12px', borderRadius: 999, background: 'rgba(124,240,61,0.2)', border: '1px solid rgba(124,240,61,0.45)' }}>
                <FrXIcon name="shield" size={13} color="#7CF03D" sw={1.9} />
                <span style={{ fontFamily: CMF, fontSize: 12, fontWeight: 700, color: '#EAFBDD', letterSpacing: -0.2 }}>운영진 미리보기</span>
              </span>
            )}
          </div>
          <h1 style={{ fontFamily: CMF, fontSize: 24, fontWeight: 700, color: '#fff', letterSpacing: -0.6, margin: '16px 0 0' }}>{crew.name}</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 }}>
            {owner && <span style={{ display: 'flex', alignItems: 'center', gap: 3, fontFamily: CMF, fontSize: 10.5, fontWeight: 800, color: '#0D1A06', background: '#E8B53D', borderRadius: 6, padding: '2px 7px', letterSpacing: 0.2 }}><FrXIcon name="crown" size={11} color="#0D1A06" sw={2} />크루장</span>}
            {viewAs && <span style={{ display: 'flex', alignItems: 'center', gap: 3, fontFamily: CMF, fontSize: 10.5, fontWeight: 800, color: '#0D1A06', background: '#7CF03D', borderRadius: 6, padding: '2px 7px', letterSpacing: 0.2 }}>운영진</span>}
            <FrIcon name="users" size={13} color="rgba(255,255,255,0.7)" sw={2} />
            <span style={{ fontFamily: CMF, fontSize: 13, color: 'rgba(255,255,255,0.78)', letterSpacing: -0.2 }}>{crew.members.toLocaleString()}명 · {crew.area}</span>
          </div>
          {crew.desc && <p style={{ fontFamily: CMF, fontSize: 13.5, lineHeight: 1.5, color: 'rgba(255,255,255,0.88)', letterSpacing: -0.2, margin: '12px 0 0', textWrap: 'pretty' }}>{crew.desc}</p>}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* owner manage bar */}
        {owner && (
          <div style={{ display: 'flex', gap: 9, padding: '16px 20px 0' }}>
            {[['공지 올리기', 'bell', () => setComposing(true)], ['운영진 관리', 'shield', () => nav.push('crewManage', { crewId: crew.id })], ['챌린지 생성', 'trophy', () => nav.push('challengeCreate', { crewId: crew.id })]].map(([lbl, ic, fn]) => (
              <button key={lbl} onClick={fn} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 14, padding: '12px 4px', cursor: 'pointer', boxShadow: c.shadow, WebkitTapHighlightColor: 'transparent' }}>
                <FrXIcon name={ic} size={19} color={grn} sw={1.9} />
                <span style={{ fontFamily: CMF, fontSize: 12, fontWeight: 700, color: c.text, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{lbl}</span>
              </button>
            ))}
          </div>
        )}
        {/* manager (non-owner staff) bar — permission-scoped */}
        {!owner && manager && (() => {
          const acts = [
            can('notice') && ['공지 올리기', 'bell', () => setComposing(true)],
            can('challenge') && ['챌린지 생성', 'trophy', () => nav.push('challengeCreate', { crewId: crew.id })],
            can('invite') && ['멤버 초대', 'plus', () => nav.push('crewInvite', { crewId: crew.id, name: crew.name })],
            can('editInfo') && ['크루 편집', 'gear', () => nav.push('crewEdit', { crewId: crew.id })],
          ].filter(Boolean);
          if (acts.length === 0) return null;
          return (
            <div style={{ display: 'flex', gap: 9, padding: '16px 20px 0' }}>
              {acts.map(([lbl, ic, fn]) => (
                <button key={lbl} onClick={fn} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 14, padding: '12px 4px', cursor: 'pointer', boxShadow: c.shadow, WebkitTapHighlightColor: 'transparent' }}>
                  <FrXIcon name={ic} size={19} color={grn} sw={1.9} />
                  <span style={{ fontFamily: CMF, fontSize: 12, fontWeight: 700, color: c.text, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{lbl}</span>
                </button>
              ))}
            </div>
          );
        })()}

        {/* announcements */}
        {(canManage || announcements.length > 0) && (
          <div style={{ padding: '20px 20px 0' }}>
            <FrCmSectionHead c={c} title="크루 공지" />
            {composing && (
              <div style={{ background: c.surface, border: `1px solid ${c.accent}`, borderRadius: 16, padding: 14, marginBottom: 12, boxShadow: c.shadow }}>
                <textarea autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="크루원에게 전할 공지를 적어주세요" rows={3}
                  style={{ width: '100%', border: 'none', outline: 'none', resize: 'none', background: 'transparent', fontFamily: CMF, fontSize: 14, color: c.text, letterSpacing: -0.2, lineHeight: 1.5 }} />
                {/* attendance poll toggle — only for run-scheduling posts */}
                <button onClick={() => setPollOn(v => !v)} style={{ display: 'flex', alignItems: 'center', gap: 9, width: '100%', textAlign: 'left', background: pollOn ? c.accentDim : c.surfaceAlt, border: `1px solid ${pollOn ? c.accent : c.border}`, borderRadius: 12, padding: '10px 12px', marginTop: 10, cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
                  <span style={{ flexShrink: 0, width: 28, height: 28, borderRadius: 9, background: pollOn ? c.accent : c.surface, border: pollOn ? 'none' : `1px solid ${c.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><FrXIcon name="calendar" size={15} color={pollOn ? c.accentText : c.faint} sw={1.9} /></span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: CMF, fontSize: 13, fontWeight: 700, color: c.text, letterSpacing: -0.2 }}>참석 투표 추가</div>
                    <div style={{ fontFamily: CMF, fontSize: 11.5, color: c.faint, letterSpacing: -0.2, marginTop: 1 }}>러닝 일정이라면 참석 여부를 물어보세요</div>
                  </div>
                  <span style={{ flexShrink: 0, width: 40, height: 24, borderRadius: 999, background: pollOn ? c.accent : c.fieldBorder, position: 'relative', transition: 'background .15s' }}>
                    <span style={{ position: 'absolute', top: 2, left: pollOn ? 18 : 2, width: 20, height: 20, borderRadius: 999, background: '#fff', transition: 'left .15s', boxShadow: '0 1px 3px rgba(0,0,0,0.3)' }} />
                  </span>
                </button>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
                  <button onClick={() => { setComposing(false); setDraft(''); }} style={{ height: 36, padding: '0 14px', borderRadius: 10, border: `1px solid ${c.border}`, background: c.surfaceAlt, color: c.sub, fontFamily: CMF, fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>취소</button>
                  <button onClick={postAnnouncement} disabled={!draft.trim()} style={{ height: 36, padding: '0 16px', borderRadius: 10, border: 'none', background: draft.trim() ? c.accent : c.surfaceAlt, color: draft.trim() ? c.accentText : c.faint, fontFamily: CMF, fontSize: 13, fontWeight: 700, cursor: draft.trim() ? 'pointer' : 'default' }}>게시</button>
                </div>
              </div>
            )}
            {announcements.length === 0 && !composing ? (
              <div style={{ background: c.surfaceAlt, border: `1px dashed ${c.fieldBorder}`, borderRadius: 16, padding: '18px 16px', textAlign: 'center' }}>
                <p style={{ fontFamily: CMF, fontSize: 13, color: c.faint, letterSpacing: -0.2, margin: 0 }}>{can('notice') ? '첫 공지를 올려 크루원에게 소식을 전해보세요.' : '아직 공지가 없어요.'}</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {announcements.map(an => (
                  <div key={an.id} style={{ display: 'flex', gap: 11, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: 14, boxShadow: c.shadow }}>
                    <span style={{ flexShrink: 0, width: 32, height: 32, borderRadius: 10, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><FrXIcon name={an.poll ? 'calendar' : 'bell'} size={16} color={grn} sw={1.9} /></span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ fontFamily: CMF, fontSize: 13.5, lineHeight: 1.5, color: c.text, letterSpacing: -0.2, margin: 0, textWrap: 'pretty' }}>{an.text}</p>
                      <div style={{ fontFamily: CMF, fontSize: 11.5, color: c.faint, marginTop: 5 }}>{an.when}</div>
                      {an.poll && <FrAttendancePoll c={c} poll={an.poll} onVote={(v) => votePoll(an.id, v)} />}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* active challenge — hero */}
        <div style={{ padding: '18px 20px 0' }}>
          <div style={{ position: 'relative', borderRadius: 20, overflow: 'hidden', background: '#0C1206', padding: 18, boxShadow: c.shadow }}>
            <div style={{ position: 'absolute', top: -30, right: -30, width: 120, height: 120, borderRadius: 999, background: '#7CF03D', opacity: 0.14 }} />
            <div style={{ position: 'relative' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(124,240,61,0.18)', border: '1px solid rgba(124,240,61,0.4)', borderRadius: 999, padding: '5px 11px' }}>
                  <FrIcon name="trophy" size={13} color="#7CF03D" sw={1.9} />
                  <span style={{ fontFamily: CMF, fontSize: 11, fontWeight: 700, color: '#EAFBDD', letterSpacing: -0.2, whiteSpace: 'nowrap' }}>진행 중인 챌린지</span>
                </span>
                <span style={{ fontFamily: CMF, fontSize: 11.5, fontWeight: 800, color: '#0D1A06', background: '#7CF03D', borderRadius: 8, padding: '4px 9px', letterSpacing: -0.2, marginLeft: 'auto' }}>D-{ch.days}</span>
              </div>
              <div style={{ fontFamily: CMF, fontSize: 20, fontWeight: 700, color: '#fff', letterSpacing: -0.5, marginTop: 13 }}>{ch.title}</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 14 }}>
                <span style={{ fontFamily: CMF, fontSize: 30, fontWeight: 700, color: '#7CF03D', letterSpacing: -1, fontVariantNumeric: 'tabular-nums' }}>{ch.done}</span>
                <span style={{ fontFamily: CMF, fontSize: 15, fontWeight: 600, color: 'rgba(255,255,255,0.6)' }}>/ {ch.goal}km</span>
                <span style={{ fontFamily: CMF, fontSize: 13, fontWeight: 700, color: '#7CF03D', marginLeft: 'auto' }}>{pct}%</span>
              </div>
              <div style={{ height: 8, borderRadius: 99, background: 'rgba(255,255,255,0.16)', marginTop: 10, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: pct + '%', background: '#7CF03D', borderRadius: 99 }} />
              </div>
            </div>
          </div>
        </div>

        {/* start a crew run (permission-scoped) */}
        {can('crewRun') && (
          <div style={{ padding: '14px 20px 0' }}>
            <button onClick={() => nav.push('tracking', { course: { crewId: crew.id, title: crew.name + ' 크루런', area: crew.area, seed: crew.seed, dist: crew.challenge ? crew.challenge.goal / 10 : 5 } })} style={{ width: '100%', height: 54, borderRadius: 16, border: 'none', background: c.accent, color: c.accentText, fontFamily: CMF, fontSize: 15.5, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, boxShadow: `0 6px 18px ${c.accent}55`, WebkitTapHighlightColor: 'transparent' }}>
              <FrXIcon name="runner" size={20} color={c.accentText} sw={2.2} /> 크루 러닝 시작
            </button>
          </div>
        )}

        {/* crew ranking — motivational core */}
        <div style={{ padding: '24px 20px 0' }}>
          <FrCmSectionHead c={c} title="크루 랭킹" />
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 6, boxShadow: c.shadow, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {ranked.map((r, i) => <FrCrewRankRow key={r.name + i} c={c} r={r} rank={i + 1} role={(owner && r.me) ? 'owner' : (managers.includes(r.name) ? 'manager' : null)} />)}
          </div>
        </div>

        {/* crew run feed — runs done with the crew */}
        <div style={{ padding: '24px 20px 0' }}>
          <FrCmSectionHead c={c} title="크루 러닝 피드" />
          {(crew.feed && crew.feed.length > 0) ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {crew.feed.map(run => (
                <div key={run.id} style={{ display: 'flex', alignItems: 'center', gap: 12, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: 12, boxShadow: c.shadow }}>
                  <div style={{ width: 48, height: 48, borderRadius: 13, overflow: 'hidden', flexShrink: 0 }}><FrMiniMap seed={run.seed || crew.seed} width={48} height={48} radius={13} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <FrAvatar name={run.name} size={18} />
                      <span style={{ fontFamily: CMF, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{run.name}</span>
                      <span style={{ fontFamily: CMF, fontSize: 11.5, color: c.faint, flexShrink: 0, marginLeft: 'auto' }}>{run.when}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 6 }}>
                      <span style={{ fontFamily: CMF, fontSize: 13, fontWeight: 700, color: grn, letterSpacing: -0.2 }}>{run.km}<span style={{ fontSize: 10, color: c.faint, fontWeight: 600 }}> km</span></span>
                      {run.dur && <span style={{ fontFamily: CMF, fontSize: 12.5, fontWeight: 600, color: c.sub }}>{run.dur}</span>}
                      {run.pace && <span style={{ fontFamily: CMF, fontSize: 12.5, fontWeight: 600, color: c.sub }}>{run.pace}/km</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ background: c.surfaceAlt, border: `1px dashed ${c.fieldBorder}`, borderRadius: 16, padding: '20px 16px', textAlign: 'center' }}>
              <p style={{ fontFamily: CMF, fontSize: 13, color: c.faint, letterSpacing: -0.2, margin: 0 }}>{canManage ? '크루 러닝을 시작해 첫 기록을 남겨보세요.' : '아직 크루 러닝 기록이 없어요.'}</p>
            </div>
          )}
        </div>

        <div style={{ padding: '20px 20px 30px' }}>
          {!owner && (
            <button onClick={() => setJoined(j => !j)} style={{ width: '100%', height: 52, borderRadius: 14, border: joined ? `1px solid ${c.border}` : 'none', background: joined ? c.surfaceAlt : c.accent, color: joined ? c.sub : c.accentText, fontFamily: CMF, fontSize: 15.5, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer' }}>{joined ? '크루 나가기' : '크루 가입하기'}</button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Screen 1: main page ────────────────────────────────
function FrCommunity({ c, app, onTab }) {
  const created = (app && app.createdCrews) || [];
  const joinedCrews = FR_MY_CREWS;
  const [tab, setTab] = React.useState('crew');
  const [chip, setChip] = React.useState('전체');
  const [showAll, setShowAll] = React.useState(false);
  const [loc, setLoc] = React.useState({ label: '현재 위치 · 성동구 성수동', region: '성수' });
  const [joined, setJoined] = React.useState({});
  const openCrew = (crew) => app && app.nav && app.nav.push('crewDetail', { crew });
  const discover = () => app && app.nav && app.nav.push('settingStub', { title: '주변 크루 둘러보기' });
  const createCrew = () => { if (app && app.premium) { app.nav.push('crewCreate'); } else { app && app.nav && app.nav.push('premium'); } };
  const premium = !!(app && app.premium);
  const grn = c.dark ? c.accent : '#3C7A14';

  const openChallenges = chip === '전체' ? FR_OPEN_CHALLENGES : FR_OPEN_CHALLENGES.filter(x => x.sport === chip);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg, position: 'relative', overflow: 'hidden' }}>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        <div style={{ padding: '62px 20px 0' }}>
          <h1 style={{ fontFamily: CMF, fontSize: 26, fontWeight: 700, letterSpacing: -0.7, color: c.text, margin: 0 }}>커뮤니티</h1>
          <p style={{ fontFamily: CMF, fontSize: 13.5, color: c.sub, letterSpacing: -0.3, margin: '5px 0 0' }}>내 크루와 함께 목표를 달려요</p>
        </div>

        <FrCmTabs c={c} active={tab} onChange={setTab} tabs={[{ id: 'crew', label: '크루' }, { id: 'discover', label: '둘러보기' }]} />

        {/* ─ 크루 탭 ─ */}
        {tab === 'crew' && (
          <>
            {/* 내가 만든 크루 */}
            <div style={{ padding: '22px 20px 0' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 13 }}>
                <span style={{ fontFamily: CMF, fontSize: 17, fontWeight: 700, color: c.text, letterSpacing: -0.4 }}>내가 만든 크루</span>
                <button onClick={createCrew} style={{ display: 'flex', alignItems: 'center', gap: 4, height: 32, padding: '0 12px 0 9px', borderRadius: 999, border: `1.5px solid ${c.accent}`, background: c.accentDim, cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
                  {premium ? <FrIcon name="plus" size={16} color={grn} sw={2.6} /> : <FrXIcon name="lock" size={13} color={grn} sw={2.1} />}
                  <span style={{ fontFamily: CMF, fontSize: 13, fontWeight: 700, color: grn, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>크루 생성</span>
                </button>
              </div>
              {created.length === 0 ? (
                <button onClick={createCrew} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 12, background: c.surface, border: `1.5px dashed ${c.fieldBorder}`, borderRadius: 18, padding: 16, cursor: 'pointer', textAlign: 'left', WebkitTapHighlightColor: 'transparent' }}>
                  <span style={{ flexShrink: 0, width: 40, height: 40, borderRadius: 12, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><FrIcon name="plus" size={20} color={grn} sw={2.4} /></span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontFamily: CMF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>직접 크루 만들기</span>
                      {!premium && <FrLockChip c={c} />}
                    </div>
                    <div style={{ fontFamily: CMF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, marginTop: 2 }}>{premium ? '크루장이 돼서 공지·챌린지를 관리해보세요' : '프리미엄에서 나만의 크루를 만들어보세요'}</div>
                  </div>
                </button>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
                  {created.map(crew => <FrCrewCard key={crew.id} c={c} crew={crew} onOpen={openCrew} />)}
                </div>
              )}
            </div>

            {/* 즐겨찾는 크루 */}
            {(() => {
              const isFav = (id) => app && app.isFavCrew && app.isFavCrew(id);
              const favList = joinedCrews.filter(cr => isFav(cr.id));
              const restList = joinedCrews.filter(cr => !isFav(cr.id));
              const onFav = (id) => app && app.toggleFavCrew && app.toggleFavCrew(id);
              return (
                <>
                  {favList.length > 0 && (
                    <div style={{ padding: '24px 20px 0' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 13 }}>
                        <FrXIcon name="star" size={16} color="#E8B53D" fill="#E8B53D" sw={1.9} />
                        <span style={{ fontFamily: CMF, fontSize: 17, fontWeight: 700, color: c.text, letterSpacing: -0.4 }}>즐겨찾는 크루</span>
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
                        {favList.map(crew => <FrCrewCard key={crew.id} c={c} crew={crew} onOpen={openCrew} fav onFav={onFav} />)}
                      </div>
                    </div>
                  )}

                  {/* 참여한 크루 */}
                  <div style={{ padding: '24px 20px 0' }}>
                    <div style={{ marginBottom: 13 }}>
                      <span style={{ fontFamily: CMF, fontSize: 17, fontWeight: 700, color: c.text, letterSpacing: -0.4 }}>참여한 크루</span>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
                      {restList.map(crew => <FrCrewCard key={crew.id} c={c} crew={crew} onOpen={openCrew} fav={false} onFav={onFav} />)}
                    </div>
                  </div>
                </>
              );
            })()}

            <div style={{ height: 18 }} />
          </>
        )}

        {/* ─ 둘러보기 탭 ─ */}
        {tab === 'discover' && (
          <>
            <div style={{ padding: '20px 20px 0' }}>
              <button onClick={() => app && app.nav && app.nav.push('locationPicker', { onSelect: (label, key) => setLoc({ label, region: (key && (key.dong || key.gu)) || label }) })} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 14, padding: '12px 14px', cursor: 'pointer', textAlign: 'left', boxShadow: c.shadow, WebkitTapHighlightColor: 'transparent' }}>
                <span style={{ flexShrink: 0, width: 34, height: 34, borderRadius: 11, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><FrIcon name="pin" size={17} color={grn} sw={2} /></span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: CMF, fontSize: 10.5, fontWeight: 700, letterSpacing: 0.4, color: c.faint, textTransform: 'uppercase' }}>검색 위치</div>
                  <div style={{ fontFamily: CMF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{loc.label}</div>
                </div>
                <FrCIcon name="chevdown" size={16} color={c.sub} sw={2.2} />
              </button>
            </div>
            {(() => {
              const list = FR_NEARBY_CREWS.filter(n => showAll || n.members < n.max);
              return (
                <>
                  {/* hide-full toggle + count */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 22px 4px' }}>
                    <span style={{ fontFamily: CMF, fontSize: 12.5, color: c.faint, fontWeight: 600 }}>{list.length}개 크루</span>
                    <button onClick={() => setShowAll(v => !v)} style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', padding: '4px 0', cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
                      <span style={{ fontFamily: CMF, fontSize: 13, fontWeight: 700, color: showAll ? grn : c.sub, letterSpacing: -0.2 }}>{showAll ? '가입 가능한 크루만 보기' : '모집 마감 크루도 보기'}</span>
                      <span style={{ width: 40, height: 24, borderRadius: 999, background: showAll ? c.accent : c.fieldBorder, position: 'relative', transition: 'background .15s' }}>
                        <span style={{ position: 'absolute', top: 2, left: showAll ? 18 : 2, width: 20, height: 20, borderRadius: 999, background: '#fff', transition: 'left .15s', boxShadow: '0 1px 3px rgba(0,0,0,0.3)' }} />
                      </span>
                    </button>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '12px 20px 28px' }}>
                    {list.length === 0 ? (
                      <div style={{ textAlign: 'center', padding: '36px 24px' }}>
                        <p style={{ fontFamily: CMF, fontSize: 14, color: c.faint, letterSpacing: -0.2, margin: 0 }}>조건에 맞는 크루가 없어요.</p>
                      </div>
                    ) : list.map(nb => {
                      const full = nb.members >= nb.max;
                      return (
                        <button key={nb.id} onClick={() => !full && app && app.nav && app.nav.push('settingStub', { title: nb.name })} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 13, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 13, cursor: full ? 'default' : 'pointer', boxShadow: c.shadow, opacity: full ? 0.66 : 1, WebkitTapHighlightColor: 'transparent' }}>
                          <div style={{ width: 54, height: 54, borderRadius: 15, overflow: 'hidden', flexShrink: 0 }}><FrMiniMap seed={nb.seed} width={54} height={54} radius={15} /></div>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontFamily: CMF, fontSize: 15.5, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{nb.name}</div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 3 }}>
                              <FrIcon name="users" size={12} color={c.faint} sw={2} />
                              <span style={{ fontFamily: CMF, fontSize: 12, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{nb.members}/{nb.max}명 · {nb.area} · {nb.dist}</span>
                            </div>
                            <div style={{ display: 'flex', gap: 5, marginTop: 8 }}>
                              {nb.tags.map(t => <span key={t} style={{ fontFamily: CMF, fontSize: 10.5, fontWeight: 700, color: c.sub, background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: 6, padding: '2px 7px' }}>{t}</span>)}
                            </div>
                          </div>
                          <span style={{ flexShrink: 0, height: 32, padding: '0 14px', borderRadius: 999, background: full ? c.surfaceAlt : c.accent, color: full ? c.faint : c.accentText, border: full ? `1px solid ${c.border}` : 'none', fontFamily: CMF, fontSize: 12.5, fontWeight: 700, letterSpacing: -0.2, display: 'flex', alignItems: 'center' }}>{full ? '모집 마감' : '가입'}</span>
                        </button>
                      );
                    })}
                  </div>
                </>
              );
            })()}
          </>
        )}
      </div>
      <FrTabBar c={c} active="community" onTab={onTab} />
    </div>
  );
}

// ── staff management (운영진 관리) — owner promotes/demotes members ──
function FrCrewManage({ c, app, params }) {
  const nav = app.nav;
  const crewId = params && params.crewId;
  const crew = (app.createdCrews || []).find(x => x.id === crewId);
  const me = (app && app.displayName) || '지윤';
  const grn = c.dark ? c.accent : '#3C7A14';
  if (!crew) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
        <FrAppBar c={c} title="운영진 관리" onBack={() => nav.pop()} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <p style={{ fontFamily: CMF, fontSize: 14, color: c.faint }}>크루를 찾을 수 없어요.</p>
        </div>
      </div>
    );
  }
  const managers = crew.managers || [];
  const members = (crew.ranking || []).filter(r => r.name !== me);
  const toggle = (name) => {
    const next = managers.includes(name) ? managers.filter(x => x !== name) : managers.concat([name]);
    app.updateCrew(crew.id, { managers: next });
  };
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="운영진 관리" onBack={() => nav.pop()} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        <div style={{ padding: '16px 20px 0' }}>
          <div style={{ display: 'flex', gap: 11, background: c.accentDim, border: `1px solid ${c.accent}33`, borderRadius: 16, padding: 14 }}>
            <FrXIcon name="shield" size={18} color={grn} sw={1.9} />
            <p style={{ fontFamily: CMF, fontSize: 13, lineHeight: 1.55, color: c.dark ? c.text : '#214210', letterSpacing: -0.2, margin: 0, textWrap: 'pretty' }}>운영진은 <b>공지 작성</b>과 <b>크루 편집</b>을 할 수 있어요. 크루원을 운영진으로 지정해 함께 크루를 관리하세요.</p>
          </div>
        </div>

        {/* owner row (fixed) */}
        <div style={{ padding: '20px 20px 0' }}>
          <div style={{ fontFamily: CMF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '0 4px 8px' }}>크루장</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: '12px 14px', boxShadow: c.shadow }}>
            <FrAvatar name={me} size={40} ring={c.accent} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontFamily: CMF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>{me}</span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 2, fontFamily: CMF, fontSize: 10, fontWeight: 800, color: '#0D1A06', background: '#E8B53D', borderRadius: 5, padding: '1px 5px' }}><FrXIcon name="crown" size={9} color="#0D1A06" sw={2} />크루장</span>
              </div>
              <div style={{ fontFamily: CMF, fontSize: 12, color: c.faint, marginTop: 2 }}>나 · 모든 권한</div>
            </div>
          </div>
        </div>

        {/* members */}
        <div style={{ padding: '22px 20px 28px' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', padding: '0 4px 8px' }}>
            <span style={{ fontFamily: CMF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase' }}>크루원</span>
            <span style={{ fontFamily: CMF, fontSize: 12, fontWeight: 600, color: c.faint }}>운영진 {managers.length}명</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {members.map((m, i) => {
              const isMgr = managers.includes(m.name);
              return (
                <div key={m.name + i} style={{ display: 'flex', alignItems: 'center', gap: 12, background: c.surface, border: `1px solid ${isMgr ? c.accent + '88' : c.border}`, borderRadius: 16, padding: '11px 14px', boxShadow: c.shadow }}>
                  <FrAvatar name={m.name} size={40} ring={isMgr ? c.accent : c.border} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontFamily: CMF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.name}</span>
                      {isMgr && <span style={{ fontFamily: CMF, fontSize: 10, fontWeight: 800, color: grn, background: c.accentDim, borderRadius: 5, padding: '1px 5px', flexShrink: 0 }}>운영진</span>}
                    </div>
                    <div style={{ fontFamily: CMF, fontSize: 12, color: c.faint, marginTop: 2 }}>{isMgr ? '공지·편집 권한' : '크루원'}</div>
                  </div>
                  {isMgr && <button onClick={() => nav.push('crewPerms', { crewId: crew.id, name: m.name })} aria-label="권한 설정" style={{ flexShrink: 0, width: 34, height: 34, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', WebkitTapHighlightColor: 'transparent' }}><FrXIcon name="gear" size={17} color={c.sub} sw={1.8} /></button>}
                  <button onClick={() => toggle(m.name)} style={{ flexShrink: 0, height: 34, padding: '0 14px', borderRadius: 999, border: isMgr ? `1px solid ${c.border}` : 'none', background: isMgr ? c.surfaceAlt : c.accent, color: isMgr ? c.sub : c.accentText, fontFamily: CMF, fontSize: 12.5, fontWeight: 700, letterSpacing: -0.2, cursor: 'pointer', whiteSpace: 'nowrap', WebkitTapHighlightColor: 'transparent' }}>{isMgr ? '운영진 해제' : '운영진 지정'}</button>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 크루 관리 hub (owner dashboard) ──
function FrCrewAdmin({ c, app, params }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3C7A14';
  const crewId = params && params.crewId;
  const crew = (app.createdCrews || []).find(x => x.id === crewId);
  if (!crew) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
        <FrAppBar c={c} title="크루 관리" onBack={() => nav.pop()} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <p style={{ fontFamily: CMF, fontSize: 14, color: c.faint }}>크루를 찾을 수 없어요.</p>
        </div>
      </div>
    );
  }
  const managers = crew.managers || [];
  const approval = crew.privacy === '승인제';
  const pending = (crew.requests || []).length;
  const announce = (crew.announcements || []).length;
  const stats = [[String(crew.members), '크루원'], [String(managers.length + 1), '운영진'], approval ? [String(pending), '가입 요청'] : [`${crew.members}/${crew.maxMembers || crew.members}`, '정원']];
  const rows = [
    ['bell', '공지 관리', `공지 ${announce}개`, () => nav.push('crewNotices', { crewId: crew.id })],
    ['shield', '운영진 관리', `운영진 ${managers.length}명`, () => nav.push('crewManage', { crewId: crew.id })],
    ['users', '크루원 관리', `${crew.members}명`, () => nav.push('crewInvite', { crewId: crew.id, name: crew.name })],
    ...(approval ? [['plus', '가입 요청', pending > 0 ? `${pending}건 대기 중` : '대기 없음', () => nav.push('crewRequests', { crewId: crew.id }), pending > 0]] : []),
    ['trophy', '챌린지 관리', crew.challenge && !crew.challenge.none ? crew.challenge.title : '챌린지 없음', () => nav.push('challengeCreate', { crewId: crew.id })],
    ['gear', '크루 정보 편집', '이름·지역·공개 범위', () => nav.push('crewEdit', { crewId: crew.id })],
  ];
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="크루 관리" onBack={() => nav.pop()} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* crew identity + stats */}
        <div style={{ padding: '16px 20px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 13, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 16, boxShadow: c.shadow }}>
            <div style={{ width: 52, height: 52, borderRadius: 15, background: crew.color || c.accent, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <FrIcon name="users" size={26} color="#0D1A06" sw={2} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontFamily: CMF, fontSize: 16.5, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{crew.name}</span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 2, fontFamily: CMF, fontSize: 10, fontWeight: 800, color: '#0D1A06', background: '#E8B53D', borderRadius: 5, padding: '1px 5px', flexShrink: 0 }}><FrXIcon name="crown" size={9} color="#0D1A06" sw={2} />크루장</span>
              </div>
              <div style={{ fontFamily: CMF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, marginTop: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{crew.area}</div>
            </div>
          </div>
          <div style={{ display: 'flex', marginTop: 12, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: '14px 0', boxShadow: c.shadow }}>
            {stats.map((s, i) => (
              <div key={i} style={{ flex: 1, textAlign: 'center', borderLeft: i ? `1px solid ${c.border}` : 'none' }}>
                <div style={{ fontFamily: CMF, fontSize: 19, fontWeight: 800, color: c.text, letterSpacing: -0.5 }}>{s[0]}</div>
                <div style={{ fontFamily: CMF, fontSize: 11, color: c.faint, marginTop: 3 }}>{s[1]}</div>
              </div>
            ))}
          </div>
        </div>

        {/* management rows */}
        <div style={{ padding: '22px 20px 0' }}>
          <div style={{ fontFamily: CMF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '0 4px 8px' }}>관리</div>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: '4px 16px', boxShadow: c.shadow }}>
            {rows.map(([ic, label, sub, fn, dot], i, arr) => (
              <div key={label}>
                <button onClick={fn} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 13, background: 'transparent', border: 'none', padding: '13px 0', cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
                  <span style={{ flexShrink: 0, width: 38, height: 38, borderRadius: 12, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
                    <FrXIcon name={ic} size={19} color={grn} sw={1.8} />
                    {dot && <span style={{ position: 'absolute', top: -2, right: -2, width: 9, height: 9, borderRadius: 99, background: c.danger, border: `1.5px solid ${c.surface}` }} />}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: CMF, fontSize: 15, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{label}</div>
                    <div style={{ fontFamily: CMF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 1 }}>{sub}</div>
                  </div>
                  <FrIcon name="chevron" size={17} color={c.faint} sw={2} />
                </button>
                {i < arr.length - 1 && <div style={{ height: 1, background: c.border, margin: '0 -16px' }} />}
              </div>
            ))}
          </div>
        </div>

        {/* danger */}
        <div style={{ padding: '22px 20px 30px' }}>
          <button onClick={() => nav.push('crewDelete', { crewId: crew.id, name: crew.name })} style={{ width: '100%', height: 52, borderRadius: 14, border: `1px solid ${c.danger}44`, background: 'transparent', color: c.danger, fontFamily: CMF, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
            <FrXIcon name="logout" size={17} color={c.danger} sw={1.9} /> 크루 삭제
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 공지 관리 (Manage Notices) — full list + delete, max 6 ──
function FrCrewNotices({ c, app, params }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3C7A14';
  const crewId = params && params.crewId;
  const crew = (app.createdCrews || []).find(x => x.id === crewId);
  const me = (app && app.displayName) || '지윤';
  const canManage = !!(crew && (crew.owner || (crew.managers || []).includes(me)));
  if (!crew) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
        <FrAppBar c={c} title="공지 관리" onBack={() => nav.pop()} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <p style={{ fontFamily: CMF, fontSize: 14, color: c.faint }}>크루를 찾을 수 없어요.</p>
        </div>
      </div>
    );
  }
  const list = crew.announcements || [];
  const del = (id) => app.updateCrew(crew.id, { announcements: list.filter(a => a.id !== id) });
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="공지 관리" onBack={() => nav.pop()} right={<span style={{ fontFamily: CMF, fontSize: 12.5, fontWeight: 700, color: list.length >= 6 ? c.danger : c.faint, whiteSpace: 'nowrap' }}>{list.length}/6</span>} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', padding: '16px 20px 28px' }}>
        <div style={{ display: 'flex', gap: 11, background: c.accentDim, border: `1px solid ${c.accent}33`, borderRadius: 14, padding: 13, marginBottom: 16 }}>
          <FrXIcon name="bell" size={17} color={grn} sw={1.9} />
          <p style={{ fontFamily: CMF, fontSize: 12.5, lineHeight: 1.5, color: c.dark ? c.text : '#214210', letterSpacing: -0.2, margin: 0, textWrap: 'pretty' }}>공지는 최대 6개까지 유지돼요. 새 공지를 올리면 가장 오래된 공지가 자동으로 사라져요.</p>
        </div>
        {list.length === 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 13, padding: '40px 24px' }}>
            <span style={{ width: 52, height: 52, borderRadius: 16, background: c.surfaceAlt, border: `1px solid ${c.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FrXIcon name="bell" size={24} color={c.faint} sw={1.7} />
            </span>
            <p style={{ fontFamily: CMF, fontSize: 14, color: c.sub, letterSpacing: -0.2, margin: 0 }}>아직 공지가 없어요.</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {list.map((an, i) => (
              <div key={an.id} style={{ display: 'flex', gap: 11, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: 14, boxShadow: c.shadow }}>
                <span style={{ flexShrink: 0, width: 32, height: 32, borderRadius: 10, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><FrXIcon name={an.poll ? 'calendar' : 'bell'} size={16} color={grn} sw={1.9} /></span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontFamily: CMF, fontSize: 13.5, lineHeight: 1.5, color: c.text, letterSpacing: -0.2, margin: 0, textWrap: 'pretty' }}>{an.text}</p>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 5 }}>
                    <span style={{ fontFamily: CMF, fontSize: 11.5, color: c.faint }}>{an.when}</span>
                    {an.poll && <span style={{ fontFamily: CMF, fontSize: 10.5, fontWeight: 700, color: grn, background: c.accentDim, borderRadius: 5, padding: '1px 6px' }}>참석 투표</span>}
                    {i === list.length - 1 && list.length >= 6 && <span style={{ fontFamily: CMF, fontSize: 10.5, fontWeight: 700, color: c.faint }}>다음 공지 시 삭제</span>}
                  </div>
                </div>
                {canManage && (
                  <button onClick={() => del(an.id)} aria-label="삭제" style={{ flexShrink: 0, width: 34, height: 34, borderRadius: 999, border: 'none', background: 'transparent', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', WebkitTapHighlightColor: 'transparent' }}>
                    <FrXIcon name="trash" size={17} color={c.danger} sw={1.9} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 가입 요청 (Join requests) — accept / decline pending members ──
function FrCrewRequests({ c, app, params }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3C7A14';
  const crewId = params && params.crewId;
  const crew = (app.createdCrews || []).find(x => x.id === crewId);
  if (!crew) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
        <FrAppBar c={c} title="가입 요청" onBack={() => nav.pop()} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <p style={{ fontFamily: CMF, fontSize: 14, color: c.faint }}>크루를 찾을 수 없어요.</p>
        </div>
      </div>
    );
  }
  const reqs = crew.requests || [];
  const accept = (r) => {
    app.updateCrew(crew.id, {
      requests: reqs.filter(x => x.id !== r.id),
      members: (crew.members || 0) + 1,
      ranking: (crew.ranking || []).concat([{ name: r.name, km: 0 }]),
    });
  };
  const decline = (r) => app.updateCrew(crew.id, { requests: reqs.filter(x => x.id !== r.id) });
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="가입 요청" onBack={() => nav.pop()} right={reqs.length > 0 ? <span style={{ fontFamily: CMF, fontSize: 12, fontWeight: 800, color: c.accentText, background: c.danger, borderRadius: 999, padding: '2px 8px', whiteSpace: 'nowrap' }}>{reqs.length}</span> : null} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', padding: '16px 20px 28px' }}>
        {reqs.length === 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 13, padding: '44px 24px' }}>
            <span style={{ width: 54, height: 54, borderRadius: 16, background: c.surfaceAlt, border: `1px solid ${c.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FrCIcon name="check" size={26} color={c.faint} sw={2} />
            </span>
            <p style={{ fontFamily: CMF, fontSize: 14, color: c.sub, letterSpacing: -0.2, margin: 0 }}>대기 중인 가입 요청이 없어요.</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {reqs.map(r => (
              <div key={r.id} style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 15, boxShadow: c.shadow }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <FrAvatar name={r.name} size={44} ring={c.border} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                      <span style={{ fontFamily: CMF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.name}</span>
                      <span style={{ fontFamily: CMF, fontSize: 11.5, color: c.faint, flexShrink: 0 }}>{r.when}</span>
                    </div>
                    <div style={{ fontFamily: CMF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.sub}</div>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 9, marginTop: 13 }}>
                  <button onClick={() => accept(r)} style={{ flex: 1, height: 42, borderRadius: 12, border: 'none', background: c.accent, color: c.accentText, fontFamily: CMF, fontSize: 14, fontWeight: 700, letterSpacing: -0.2, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, WebkitTapHighlightColor: 'transparent' }}>
                    <FrCIcon name="check" size={15} color={c.accentText} sw={2.6} /> 수락
                  </button>
                  <button onClick={() => decline(r)} style={{ flex: 1, height: 42, borderRadius: 12, border: `1px solid ${c.border}`, background: c.surfaceAlt, color: c.sub, fontFamily: CMF, fontSize: 14, fontWeight: 700, letterSpacing: -0.2, cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>거절</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 운영진 권한 설정 (per-manager permissions) ──
const FR_PERM_DEFS = [
  { key: 'notice', label: '공지 올리기', desc: '크루 공지를 작성하고 관리해요', danger: false },
  { key: 'challenge', label: '챌린지 생성·수정', desc: '크루 챌린지를 만들고 교체해요', danger: false },
  { key: 'invite', label: '멤버 초대', desc: '새 크루원을 초대하고 링크를 공유해요', danger: false },
  { key: 'crewRun', label: '크루 러닝 시작', desc: '크루 러닝을 시작해 챌린지에 반영해요', danger: false },
  { key: 'editInfo', label: '크루 정보 수정', desc: '이름·지역·소개·공개 범위를 변경해요', danger: false },
  { key: 'kick', label: '멤버 추방', desc: '크루원을 내보낼 수 있어요', danger: true },
  { key: 'appoint', label: '다른 운영진 임명', desc: '크루원을 운영진으로 지정·해제해요', danger: true },
];
const FR_PERM_DEFAULT = { notice: true, challenge: true, invite: true, crewRun: true, editInfo: false, kick: false, appoint: false };

function FrCrewPerms({ c, app, params }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3C7A14';
  const crewId = params && params.crewId;
  const name = params && params.name;
  const crew = (app.createdCrews || []).find(x => x.id === crewId);
  const saved = (crew && crew.perms && crew.perms[name]) || FR_PERM_DEFAULT;
  const [perms, setPerms] = React.useState(saved);
  const [flash, setFlash] = React.useState(false);
  if (!crew || !name) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
        <FrAppBar c={c} title="운영진 권한 설정" onBack={() => nav.pop()} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <p style={{ fontFamily: CMF, fontSize: 14, color: c.faint }}>운영진을 찾을 수 없어요.</p>
        </div>
      </div>
    );
  }
  const t = (k) => setPerms(p => ({ ...p, [k]: !p[k] }));
  const save = () => {
    const next = { ...(crew.perms || {}), [name]: perms };
    app.updateCrew(crew.id, { perms: next });
    if (navigator.vibrate) navigator.vibrate(12);
    setFlash(true); setTimeout(() => nav.pop(), 700);
  };
  const Row = ({ d }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 0' }}>
      <span style={{ flexShrink: 0, width: 34, height: 34, borderRadius: 10, background: d.danger ? c.danger + '1A' : c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <FrXIcon name={d.danger ? 'shield' : 'check'} size={17} color={d.danger ? c.danger : grn} sw={1.9} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontFamily: CMF, fontSize: 14.5, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{d.label}</span>
          {d.danger && <span style={{ fontFamily: CMF, fontSize: 9.5, fontWeight: 800, color: c.danger, background: c.danger + '1A', borderRadius: 5, padding: '1px 5px', letterSpacing: 0.2 }}>주의</span>}
        </div>
        <div style={{ fontFamily: CMF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 2 }}>{d.desc}</div>
      </div>
      <FrToggle c={c} on={!!perms[d.key]} onChange={() => t(d.key)} />
    </div>
  );
  const safe = FR_PERM_DEFS.filter(d => !d.danger);
  const danger = FR_PERM_DEFS.filter(d => d.danger);
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="운영진 권한 설정" onBack={() => nav.pop()} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* target manager */}
        <div style={{ padding: '16px 20px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 13, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 15, boxShadow: c.shadow }}>
            <FrAvatar name={name} size={48} ring={c.accent} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontFamily: CMF, fontSize: 16, fontWeight: 700, color: c.text, letterSpacing: -0.4 }}>{name}</span>
                <span style={{ fontFamily: CMF, fontSize: 10, fontWeight: 800, color: grn, background: c.accentDim, borderRadius: 5, padding: '1px 6px' }}>운영진</span>
              </div>
              <div style={{ fontFamily: CMF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, marginTop: 3 }}>{crew.name}</div>
            </div>
          </div>
        </div>

        {/* general permissions */}
        <div style={{ padding: '0 20px' }}>
          <div style={{ fontFamily: CMF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 4px' }}>일반 권한</div>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: '4px 16px', boxShadow: c.shadow }}>
            {safe.map((d, i) => (
              <div key={d.key}>
                <Row d={d} />
                {i < safe.length - 1 && <div style={{ height: 1, background: c.border, margin: '0 -16px' }} />}
              </div>
            ))}
          </div>
        </div>

        {/* dangerous permissions */}
        <div style={{ padding: '0 20px 24px' }}>
          <div style={{ fontFamily: CMF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.danger, textTransform: 'uppercase', padding: '22px 4px 4px' }}>주의가 필요한 권한</div>
          <div style={{ background: c.surface, border: `1.5px solid ${c.danger}44`, borderRadius: 18, padding: '4px 16px', boxShadow: c.shadow }}>
            {danger.map((d, i) => (
              <div key={d.key}>
                <Row d={d} />
                {i < danger.length - 1 && <div style={{ height: 1, background: c.border, margin: '0 -16px' }} />}
              </div>
            ))}
          </div>
          <p style={{ fontFamily: CMF, fontSize: 12, lineHeight: 1.5, color: c.faint, letterSpacing: -0.2, margin: '9px 4px 0', textWrap: 'pretty' }}>이 권한들은 크루 구성에 큰 영향을 줄 수 있어요. 신뢰하는 운영진에게만 부여하세요.</p>
        </div>
      </div>

      <div style={{ flexShrink: 0, padding: '14px 20px 26px', borderTop: `1px solid ${c.border}`, background: c.bg }}>
        <button onClick={save} style={{ width: '100%', height: 56, borderRadius: 16, border: 'none', background: flash ? c.surfaceAlt : c.accent, color: flash ? grn : c.accentText, fontFamily: CMF, fontSize: 16.5, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, boxShadow: flash ? 'none' : `0 6px 18px ${c.accent}55` }}>
          {flash ? <><FrCheck color={grn} w={19} /> 저장됨</> : '저장'}
        </button>
      </div>
    </div>
  );
}

Object.assign(window, { FrCommunity, FrCrewDetail, FrCrewManage, FrCrewAdmin, FrCrewNotices, FrCrewRequests, FrCrewPerms, FR_MY_CREWS });
