// FreshRun — Notifications (pushed screen). Tabbed: 전체 / 소셜 / 시스템.
const NF = window.FR_FONT;

const FR_NOTIFS = [
  { id: 'n1', kind: 'ai', cat: '시스템', tag: 'AI 추천', tone: '#3F8E14', ago: '2분 전',
    body: ['오늘 날씨에 딱 맞는 새 코스가 도착했어요! ', { b: '한강 야경 런' }, '을 확인해 보세요.'], cta: '코스 보기', action: 'weatherDetail', map: 'notif-hangang' },
  { id: 'n2', kind: 'social', cat: '소셜', tone: '#3D8BFF', ago: '1시간 전', who: '이서연',
    body: [{ b: '이서연' }, '님이 친구 요청을 보냈어요.'], buttons: true },
  { id: 'n3', kind: 'achv', cat: '시스템', tone: '#E0703D', ago: '3시간 전',
    body: ['축하해요! ', { b: '5일 연속' }, ' 러닝 목표를 달성했어요.'], chips: ['🔥', '👟', '🏆'], xp: '+500 XP', action: 'challengeDone' },
  { id: 'n4', kind: 'crew', cat: '소셜', tone: '#3D8BFF', ago: '5시간 전',
    body: [{ b: '모닝 러너 크루' }, '가 새 그룹 트래킹 세션을 시작했어요.'], live: true },
  { id: 'n5', kind: 'sys', cat: '시스템', tone: '#3F8E14', ago: '어제',
    body: ['새 프리미엄 기능: ', { b: '고급 대사 분석' }, ' 이 지금 사용 가능해요.'], action: 'premium' },
];

function frNotifText(c, parts) {
  return parts.map((p, i) => typeof p === 'string'
    ? <span key={i}>{p}</span>
    : <b key={i} style={{ color: c.text, fontWeight: 700 }}>{p.b}</b>);
}

function FrNotifIcon({ c, n }) {
  const grn = c.dark ? c.accent : '#3F8E14';
  const map = {
    ai: { bg: c.accentDim, el: <FrCIcon name="sparkle" size={19} color={grn} sw={1.9} /> },
    achv: { bg: '#E0703D22', el: <FrIcon name="trophy" size={19} color="#E0703D" sw={1.8} /> },
    crew: { bg: '#3D8BFF22', el: <FrIcon name="users" size={19} color="#3D8BFF" sw={1.8} /> },
    sys: { bg: c.surfaceAlt, el: <FrXIcon name="bolt" size={19} color={grn} sw={1.8} /> },
  }[n.kind];
  if (n.kind === 'social') return <FrAvatar name={n.who} size={42} />;
  return <span style={{ width: 42, height: 42, borderRadius: 13, background: map.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{map.el}</span>;
}

function FrNotifCard({ c, n, nav }) {
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <div style={{ display: 'flex', gap: 12, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 15, boxShadow: c.shadow }}>
      <FrNotifIcon c={c} n={n} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span style={{ fontFamily: NF, fontSize: 12, fontWeight: 700, letterSpacing: 0.2, color: n.tone, textTransform: 'uppercase' }}>{n.tag || n.cat}</span>
          <span style={{ fontFamily: NF, fontSize: 11.5, color: c.faint, whiteSpace: 'nowrap' }}>{n.ago}</span>
        </div>
        <p style={{ fontFamily: NF, fontSize: 13.5, lineHeight: 1.5, color: c.sub, letterSpacing: -0.2, margin: '5px 0 0', textWrap: 'pretty' }}>{frNotifText(c, n.body)}</p>

        {n.map && (
          <button onClick={() => nav.push(n.action)} style={{ position: 'relative', width: '100%', height: 92, borderRadius: 12, border: 'none', marginTop: 11, overflow: 'hidden', cursor: 'pointer', padding: 0 }}>
            <FrMiniMap seed={n.map} width="100%" height={92} radius={12} hero />
            <span style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.18)' }}>
              <span style={{ background: c.surface, borderRadius: 999, padding: '7px 16px', fontFamily: NF, fontSize: 13, fontWeight: 700, color: c.text, letterSpacing: -0.2 }}>{n.cta}</span>
            </span>
          </button>
        )}

        {n.buttons && (
          <div style={{ display: 'flex', gap: 9, marginTop: 11 }}>
            <button onClick={() => nav.pop()} style={{ flex: 1, height: 40, borderRadius: 11, border: 'none', background: c.accent, color: c.accentText, fontFamily: NF, fontSize: 13.5, fontWeight: 700, cursor: 'pointer', letterSpacing: -0.2 }}>수락</button>
            <button style={{ flex: 1, height: 40, borderRadius: 11, border: `1px solid ${c.border}`, background: c.surfaceAlt, color: c.sub, fontFamily: NF, fontSize: 13.5, fontWeight: 700, cursor: 'pointer', letterSpacing: -0.2 }}>거절</button>
          </div>
        )}

        {n.chips && (
          <button onClick={() => nav.push(n.action)} style={{ display: 'flex', alignItems: 'center', gap: 9, marginTop: 11, background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}>
            <div style={{ display: 'flex' }}>
              {n.chips.map((e, i) => <span key={i} style={{ width: 26, height: 26, borderRadius: 999, background: c.surfaceAlt, border: `2px solid ${c.surface}`, marginLeft: i ? -8 : 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13 }}>{e}</span>)}
            </div>
            <span style={{ fontFamily: NF, fontSize: 12.5, fontWeight: 700, color: grn, letterSpacing: -0.2 }}>{n.xp} 획득</span>
          </button>
        )}

        {n.live && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 9 }}>
            <span style={{ width: 7, height: 7, borderRadius: 99, background: c.danger, animation: 'frblink 1.2s ease-in-out infinite' }} />
            <span style={{ fontFamily: NF, fontSize: 12, fontWeight: 700, color: c.danger, letterSpacing: -0.2 }}>실시간 세션</span>
          </div>
        )}
      </div>
    </div>
  );
}

function FrNotifications({ c, app }) {
  const nav = app.nav;
  const [tab, setTab] = React.useState('전체');
  const list = tab === '전체' ? FR_NOTIFS : FR_NOTIFS.filter(n => n.cat === tab);
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="알림" onBack={() => nav.pop()} right={<button style={{ background: 'none', border: 'none', padding: 6, cursor: 'pointer' }}><FrCheck color={c.dark ? c.accent : '#3F8E14'} w={20} /></button>} />
      <div style={{ display: 'flex', gap: 8, padding: '6px 20px 10px', borderBottom: `1px solid ${c.border}` }}>
        {['전체', '소셜', '시스템'].map(t => {
          const on = tab === t;
          return (
            <button key={t} onClick={() => setTab(t)} style={{ background: 'none', border: 'none', padding: '6px 2px', cursor: 'pointer', position: 'relative' }}>
              <span style={{ fontFamily: NF, fontSize: 14, fontWeight: on ? 700 : 600, color: on ? c.text : c.faint, letterSpacing: -0.3 }}>{t}</span>
              {on && <span style={{ position: 'absolute', left: 2, right: 2, bottom: -2, height: 2.5, borderRadius: 99, background: c.accent }} />}
            </button>
          );
        })}
      </div>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', display: 'flex', flexDirection: 'column', gap: 12, padding: '16px 20px 28px' }}>
        {list.map(n => <FrNotifCard key={n.id} c={c} n={n} nav={nav} />)}
      </div>
    </div>
  );
}

Object.assign(window, { FrNotifications, FR_NOTIFS });
