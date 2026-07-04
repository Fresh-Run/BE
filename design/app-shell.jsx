// FreshRun — main tabbed shell (merged app). Lands here after auth.
// Switches between 홈 / 코스 생성 / 기록 / 프로필 with a shared tab bar.

function FrTabPlaceholder({ c, app, active, onTab, title, sub }) {
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <div style={{ padding: '70px 22px 0' }}>
        <h1 style={{ fontFamily: FR_FONT, fontSize: 26, fontWeight: 700, letterSpacing: -0.7, color: c.text, margin: 0 }}>{title}</h1>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, padding: '0 40px' }}>
        <div style={{ width: 60, height: 60, borderRadius: 18, background: c.surfaceAlt, border: `1px solid ${c.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrCIcon name={active === 'log' ? 'clock' : 'sparkle'} size={26} color={c.faint} sw={1.8} />
        </div>
        <div style={{ fontFamily: FR_FONT, fontSize: 14.5, color: c.sub, letterSpacing: -0.3, textAlign: 'center', textWrap: 'balance' }}>{sub}</div>
      </div>
      <FrTabBar c={c} active={active} onTab={onTab} />
    </div>
  );
}

function FrMainShell({ c, app }) {
  const [tab, setTab] = React.useState('home');
  if (tab === 'home') return <FrHomeB c={c} app={app} onTab={setTab} />;
  if (tab === 'community') return <FrCommunity c={c} app={app} onTab={setTab} />;
  if (tab === 'course') return <FrCourseTab c={c} app={app} onTab={setTab} />;
  if (tab === 'log') return <FrTabPlaceholder c={c} app={app} active="log" onTab={setTab} title="기록" sub="달린 코스가 여기에 쌓여요. 곧 추가될 화면이에요." />;
  return <FrTabPlaceholder c={c} app={app} active="profile" onTab={setTab} title="프로필" sub="러닝 통계와 설정. 곧 추가될 화면이에요." />;
}

Object.assign(window, { FrMainShell, FrTabPlaceholder });
