// FreshRun — auth prototype root. Two synced iPhones (light + dark), shared state.

const FR_SCREENS = { welcome: FrWelcome, signup: FrSignUp, login: FrLogin, verify: FrEmailVerify, name: FrDisplayName, success: FrSuccess, home: FrMainShell };
const validEmail = (e) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e.trim());
// simulated "taken" registry for the uniqueness check
const FR_TAKEN = ['runner', 'seoul', 'hong', 'freshrun', 'run', 'admin', 'test', 'nike', '러너', '김러너', '달리기', '서울러너'];
// profanity blocklist — display names containing any of these are rejected
const FR_PROFANITY = [
  'fuck', 'shit', 'bitch', 'asshole', 'dick', 'pussy', 'cunt', 'bastard', 'slut', 'whore', 'nigger', 'faggot', 'retard',
  '시발', '씨발', '씨톱', '시팔', '씨팔', '병신', '새끼', '개새끼', '지랴', '좌', '존나', '닥쳐', '엿먹', '씬', '창년', '보지', '자지', '걸레', '꺼져', '좋나'];

function FrPhone({ c, screen, dir, app }) {
  const Screen = FR_SCREENS[screen];
  return (
    <IOSDevice dark={c.dark} width={402} height={872}>
      <div key={screen} className="fr-screen" style={{ height: '100%', animationName: dir >= 0 ? 'frInR' : 'frInL' }}>
        <Screen c={c} app={app} />
      </div>
    </IOSDevice>
  );
}

function FrLabel({ children }) {
  return (
    <div style={{ fontFamily: FR_FONT, fontSize: 13, fontWeight: 600, letterSpacing: 0.2, color: '#8B8F96', textTransform: 'uppercase', textAlign: 'center', marginBottom: 16 }}>{children}</div>
  );
}

function FrApp() {
  const [screen, setScreen] = React.useState('welcome');
  const [dir, setDir] = React.useState(1);
  const [form, setForm] = React.useState({ email: '', password: '' });
  const [touched, setTouched] = React.useState({});
  const [submitted, setSubmitted] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [scale, setScale] = React.useState(1);
  const [name, setName] = React.useState('');
  const [nameStatus, setNameStatus] = React.useState('idle');
  const [nameSuggestions, setNameSuggestions] = React.useState([]);
  const nameTimer = React.useRef();
  const histRef = React.useRef(['welcome']);

  // validation (login is lenient on password length; signup needs 8+)
  const needsStrong = screen === 'signup';
  const errors = {};
  if ((touched.email || submitted) && form.email && !validEmail(form.email)) errors.email = '올바른 이메일 주소를 입력해 주세요.';
  if ((touched.email || submitted) && !form.email) errors.email = '이메일을 입력해 주세요.';
  if ((touched.password || submitted) && needsStrong && form.password.length > 0 && form.password.length < 8) errors.password = '비밀번호는 8자 이상이어야 해요.';
  if ((touched.password || submitted) && !form.password) errors.password = '비밀번호를 입력해 주세요.';
  const valid = validEmail(form.email) && form.password.length >= (needsStrong ? 8 : 1);

  const resetForm = () => { setForm({ email: '', password: '' }); setTouched({}); setSubmitted(false); };

  const app = {
    form, errors, valid, loading,
    setField: (k, v) => setForm((s) => ({ ...s, [k]: v })),
    touch: (k) => setTouched((s) => ({ ...s, [k]: true })),
    go: (next, direction = 1) => {
      setDir(direction);
      if (next === 'signup' || next === 'login') resetForm();
      histRef.current.push(next);
      setScreen(next);
    },
    back: () => {
      const h = histRef.current;
      if (h.length > 1) { h.pop(); setDir(-1); setScreen(h[h.length - 1]); }
    },
    submit: () => {
      setSubmitted(true);
      if (!valid) return;
      setLoading(true);
      const fromLogin = screen === 'login';
      setTimeout(() => {
        setLoading(false);
        const next = fromLogin ? 'home' : 'verify';
        setDir(1); histRef.current.push(next); setScreen(next);
      }, 1100);
    },
    // social sign-in — provider already verifies email, so skip the code step
    social: () => {
      const fromLogin = screen === 'login';
      const next = fromLogin ? 'home' : 'name';
      if (next === 'name') { setName(''); setNameStatus('idle'); setNameSuggestions([]); }
      setDir(1); histRef.current.push(next); setScreen(next);
    },
    // email verification
    DEMO_CODE: '123456',
    verifyOk: () => {
      setLoading(true);
      setTimeout(() => {
        setLoading(false);
        setName(''); setNameStatus('idle'); setNameSuggestions([]);
        setDir(1); histRef.current.push('name'); setScreen('name');
      }, 700);
    },
    // display name (new users) — debounced uniqueness check + profanity filter
    displayName: name, nameStatus, nameSuggestions,
    setName: (v) => {
      setName(v);
      clearTimeout(nameTimer.current);
      const t = v.trim();
      if (t.length === 0) { setNameStatus('idle'); setNameSuggestions([]); return; }
      if (!/^[A-Za-z0-9_가-훃]+$/.test(t)) { setNameStatus('invalid'); setNameSuggestions([]); return; }
      const norm = t.toLowerCase().replace(/[\s._-]/g, '');
      if (FR_PROFANITY.some((w) => norm.includes(w))) { setNameStatus('profane'); setNameSuggestions([]); return; }
      if (t.length < 2) { setNameStatus('short'); setNameSuggestions([]); return; }
      setNameStatus('checking'); setNameSuggestions([]);
      nameTimer.current = setTimeout(() => {
        if (FR_TAKEN.includes(t.toLowerCase())) {
          setNameStatus('taken');
          const cands = [t + '_run', t + '2', 'seoul_' + t].filter((x) => !FR_TAKEN.includes(x.toLowerCase()));
          setNameSuggestions(cands.slice(0, 3));
        } else { setNameStatus('ok'); }
      }, 650);
    },
    applySuggestion: (s) => app.setName(s),
    finishName: () => {
      if (nameStatus !== 'ok') return;
      setLoading(true);
      setTimeout(() => { setLoading(false); setDir(1); histRef.current.push('success'); setScreen('success'); }, 700);
    },
  };

  // fit two phones to viewport
  React.useEffect(() => {
    const CW = 402 * 2 + 72, CH = 872 + 44;
    const fit = () => {
      const s = Math.min((window.innerWidth - 64) / CW, (window.innerHeight - 132) / CH, 1);
      setScale(s);
    };
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, []);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <div style={{ textAlign: 'center', padding: '26px 20px 6px' }}>
        <div style={{ fontFamily: FR_FONT, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, color: '#1A1C20' }}>FreshRun — 인증 &amp; 온보딩</div>
        <div style={{ fontFamily: FR_FONT, fontSize: 12.5, color: '#9A9DA3', marginTop: 3 }}>계정 만들기 · 두 테마를 나란히 · 탭하여 체험하세요</div>
      </div>
      <div style={{ height: (872 + 44) * scale + 24, position: 'relative', width: '100%' }}>
        <div style={{ position: 'absolute', top: 0, left: '50%', transform: `translateX(-50%) scale(${scale})`, transformOrigin: 'top center', display: 'flex', gap: 72 }}>
          <div>
            <FrLabel>라이트</FrLabel>
            <FrPhone c={FR_LIGHT} screen={screen} dir={dir} app={app} />
          </div>
          <div>
            <FrLabel>다크</FrLabel>
            <FrPhone c={FR_DARK} screen={screen} dir={dir} app={app} />
          </div>
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<FrApp />);
