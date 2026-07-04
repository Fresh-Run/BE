// FreshRun — 코스 생성 prototype root. Full flow + A/B form variant toggle.
// Two synced phones (light + dark) like auth, plus a variant switcher in the chrome.

// frMakeSeed is provided globally by course-flow.jsx
const FR_FORMS = { A: FrFormA, B: FrFormB };

function FrCourseFlow({ c, variant, st, set, adv, setAdv, screen, nav }) {
  if (screen === 'form') {
    const Form = FR_FORMS[variant];
    return <Form c={c} st={st} set={set} adv={adv} setAdv={setAdv} onGenerate={() => nav('generating')} />;
  }
  if (screen === 'generating') return <FrGenerating c={c} st={st} onDone={() => nav('result')} />;
  if (screen === 'result') return <FrMapResult c={c} st={st} onRun={() => nav('running')} onRegen={() => { set('seed', frMakeSeed()); nav('generating'); }} onBack={() => nav('form')} />;
  if (screen === 'running') return <FrRunning c={c} st={st} onFinish={() => nav('runresult')} />;
  if (screen === 'runresult') return <FrRunResult c={c} st={st} onSkip={() => nav('form')} onSave={() => nav('saved')} />;
  if (screen === 'saved') return <FrRunSaved c={c} st={st} verdict="good" onHome={() => nav('form')} onViewLog={() => nav('form')} />;
  return null;
}

function FrPhone({ c, dir, screenKey, children }) {
  return (
    <IOSDevice dark={c.dark} width={402} height={874}>
      <div key={screenKey} className="fr-screen" style={{ height: '100%', animationName: dir >= 0 ? 'frInR' : 'frInL' }}>
        {children}
      </div>
    </IOSDevice>
  );
}

function FrLabel({ children }) {
  return <div style={{ fontFamily: FR_FONT, fontSize: 13, fontWeight: 600, letterSpacing: 0.2, color: '#8B8F96', textTransform: 'uppercase', textAlign: 'center', marginBottom: 16 }}>{children}</div>;
}

function FrVariantToggle({ variant, setVariant }) {
  return (
    <div style={{ display: 'inline-flex', gap: 3, background: '#fff', border: '1px solid #E3E3DC', borderRadius: 999, padding: 4, boxShadow: '0 2px 10px rgba(0,0,0,0.06)' }}>
      {[['A', '변형 A · 스택 카드'], ['B', '변형 B · 컴팩트']].map(([id, label]) => {
        const on = variant === id;
        return (
          <button key={id} onClick={() => setVariant(id)} style={{ height: 36, padding: '0 18px', borderRadius: 999, border: 'none', cursor: 'pointer', background: on ? '#16171A' : 'transparent', color: on ? '#fff' : '#6B6E74', fontFamily: FR_FONT, fontSize: 13.5, fontWeight: 700, letterSpacing: -0.3, whiteSpace: 'nowrap', transition: 'background .15s' }}>{label}</button>
        );
      })}
    </div>
  );
}

function FrCourseApp() {
  const [variant, setVariant] = React.useState('B');
  const [screen, setScreen] = React.useState('form');
  const [dir, setDir] = React.useState(1);
  const [adv, setAdv] = React.useState(false);
  const [scale, setScale] = React.useState(1);
  const [st, setSt] = React.useState({
    dist: 5.0, locMode: 'gps', shape: 'loop', moods: ['경치'],
    diff: 'normal', waypoints: [], avoidHills: false, avoidBusy: false,
    seed: frMakeSeed(),
  });
  const set = (k, v) => setSt(s => ({ ...s, [k]: v }));
  const order = ['form', 'generating', 'result', 'running', 'runresult', 'saved'];
  const nav = (next) => {
    setDir(order.indexOf(next) >= order.indexOf(screen) ? 1 : -1);
    if (next === 'generating') set('seed', st.seed); // keep seed unless regen
    setScreen(next);
  };

  React.useEffect(() => {
    const CW = 402 * 2 + 72, CH = 874 + 44;
    const fit = () => setScale(Math.min((window.innerWidth - 64) / CW, (window.innerHeight - 168) / CH, 1));
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, []);

  // reset flow to form when switching variant (so you always see the form variation)
  const switchVariant = (v) => { setVariant(v); setScreen('form'); setDir(-1); };

  const screenKey = screen + (screen === 'form' ? variant : '');

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <div style={{ textAlign: 'center', padding: '22px 20px 4px' }}>
        <div style={{ fontFamily: FR_FONT, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, color: '#1A1C20' }}>FreshRun — 코스 생성</div>
        <div style={{ fontFamily: FR_FONT, fontSize: 12.5, color: '#9A9DA3', marginTop: 3 }}>폼 → 생성 → 지도 → 러닝 → 결과 · 폼은 두 가지 변형을 비교하세요</div>
      </div>
      <div style={{ padding: '8px 0 14px' }}><FrVariantToggle variant={variant} setVariant={switchVariant} /></div>
      <div style={{ height: (874 + 44) * scale + 16, position: 'relative', width: '100%' }}>
        <div style={{ position: 'absolute', top: 0, left: '50%', transform: `translateX(-50%) scale(${scale})`, transformOrigin: 'top center', display: 'flex', gap: 72 }}>
          {[FR_LIGHT, FR_DARK].map((c, i) => (
            <div key={i}>
              <FrLabel>{c.dark ? '다크' : '라이트'}{screen === 'form' ? ` · 변형 ${variant}` : ''}</FrLabel>
              <FrPhone c={c} dir={dir} screenKey={screenKey}>
                <FrCourseFlow c={c} variant={variant} st={st} set={set} adv={adv} setAdv={setAdv} screen={screen} nav={nav} />
              </FrPhone>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<FrCourseApp />);
