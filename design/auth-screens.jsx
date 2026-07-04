// FreshRun — auth screens. Consumes primitives from auth-ui.jsx (on window).
// All screens receive: c (colors), app (shared state + handlers).

const FRF = window.FR_FONT;

const frPageStyle = (c) => ({
  height: '100%', boxSizing: 'border-box', background: c.bg,
  display: 'flex', flexDirection: 'column', overflowY: 'auto',
  WebkitOverflowScrolling: 'touch',
});

// ── 1. Welcome / hero ──────────────────────────────────
function FrWelcome({ c, app }) {
  return (
    <div style={{ ...frPageStyle(c), padding: '70px 26px 30px' }}>
      <FrLogo c={c} size={22} />

      <div style={{ marginTop: 38 }}>
        <FrRouteMotif c={c} />
      </div>

      <div style={{ marginTop: 34 }}>
        <h1 style={{
          fontFamily: FRF, fontSize: 31, lineHeight: 1.22, fontWeight: 700,
          letterSpacing: -1, color: c.text, margin: 0, textWrap: 'balance',
        }}>매번 새로운 길로,<br />서울을 달리세요</h1>
        <p style={{
          fontFamily: FRF, fontSize: 15.5, lineHeight: 1.55, color: c.sub,
          margin: '14px 0 0', letterSpacing: -0.3, maxWidth: 300,
        }}>AI가 거리·분위기·경유지에 맞춰 한 번도 달려본 적 없는 코스를 만들어 드려요.</p>
      </div>

      <div style={{ flex: 1, minHeight: 24 }} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <FrPrimaryButton c={c} label="이메일로 시작하기" onClick={() => app.go('signup')} />
        <button onClick={() => app.go('login')}
          style={{
            height: 52, width: '100%', borderRadius: 15, cursor: 'pointer',
            background: 'transparent', border: `1.5px solid ${c.border}`, color: c.text,
            fontFamily: FRF, fontSize: 16, fontWeight: 600, letterSpacing: -0.3,
          }}>로그인</button>
      </div>
    </div>
  );
}

// ── shared header (back + title) ───────────────────────
function FrHeader({ c, app, title, sub }) {
  return (
    <div style={{ paddingTop: 64 }}>
      <FrBackButton c={c} onClick={app.back} />
      <h1 style={{ fontFamily: FRF, fontSize: 27, fontWeight: 700, letterSpacing: -0.8, color: c.text, margin: '22px 0 0' }}>{title}</h1>
      {sub && <p style={{ fontFamily: FRF, fontSize: 14.5, color: c.sub, letterSpacing: -0.3, margin: '8px 0 0', lineHeight: 1.5 }}>{sub}</p>}
    </div>
  );
}

function FrSocialGroup({ c, app }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <FrSocialButton c={c} brand="apple" label="Apple로 계속하기" onClick={() => app.social()} />
      <FrSocialButton c={c} brand="kakao" label="카카오로 계속하기" onClick={() => app.social()} />
      <FrSocialButton c={c} brand="google" label="Google로 계속하기" onClick={() => app.social()} />
    </div>
  );
}

// ── 2. Sign up ─────────────────────────────────────────
function FrSignUp({ c, app }) {
  const f = app.form;
  return (
    <div style={{ ...frPageStyle(c), padding: '0 26px 30px' }}>
      <FrHeader c={c} app={app} title="계정 만들기" sub="이메일과 비밀번호만 있으면 바로 시작할 수 있어요." />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 26 }}>
        <FrField c={c} label="이메일" placeholder="you@example.com" type="email" inputMode="email" autoComplete="email"
          value={f.email} onChange={(v) => app.setField('email', v)} onBlur={() => app.touch('email')}
          error={app.errors.email} />
        <FrPasswordField c={c} label="비밀번호" placeholder="8자 이상 입력하세요"
          value={f.password} onChange={(v) => app.setField('password', v)} onBlur={() => app.touch('password')}
          error={app.errors.password} showStrength />
      </div>

      <div style={{ marginTop: 22 }}>
        <FrPrimaryButton c={c} label="계정 만들기" onClick={() => app.submit()} loading={app.loading} disabled={!app.valid} />
      </div>
      <p style={{ fontFamily: FRF, fontSize: 12, lineHeight: 1.5, color: c.faint, letterSpacing: -0.2, textAlign: 'center', margin: '14px 6px 0' }}>
        계속하면 <span style={{ color: c.sub, textDecoration: 'underline' }}>서비스 약관</span> 및 <span style={{ color: c.sub, textDecoration: 'underline' }}>개인정보처리방침</span>에 동의하게 됩니다.
      </p>

      <div style={{ margin: '22px 0 18px' }}><FrDivider c={c} label="또는" /></div>
      <FrSocialGroup c={c} app={app} />

      <div style={{ flex: 1, minHeight: 18 }} />
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 5, fontFamily: FRF, fontSize: 14, letterSpacing: -0.3, marginTop: 18 }}>
        <span style={{ color: c.sub, whiteSpace: 'nowrap' }}>이미 계정이 있으신가요?</span>
        <button onClick={() => app.go('login', -1)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: c.text, fontWeight: 700, fontFamily: FRF, fontSize: 14, whiteSpace: 'nowrap', padding: 0 }}>로그인</button>
      </div>
    </div>
  );
}

// ── 3. Log in ──────────────────────────────────────────
function FrLogin({ c, app }) {
  const f = app.form;
  return (
    <div style={{ ...frPageStyle(c), padding: '0 26px 30px' }}>
      <FrHeader c={c} app={app} title="다시 오셨네요" sub="계정에 로그인하고 새 코스를 받아보세요." />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 26 }}>
        <FrField c={c} label="이메일" placeholder="you@example.com" type="email" inputMode="email" autoComplete="email"
          value={f.email} onChange={(v) => app.setField('email', v)} onBlur={() => app.touch('email')}
          error={app.errors.email} />
        <FrPasswordField c={c} label="비밀번호" placeholder="비밀번호 입력"
          value={f.password} onChange={(v) => app.setField('password', v)} onBlur={() => app.touch('password')}
          error={app.errors.password} />
      </div>

      <div style={{ textAlign: 'right', marginTop: 12 }}>
        <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: c.sub, fontWeight: 600, fontFamily: FRF, fontSize: 13.5, letterSpacing: -0.2, whiteSpace: 'nowrap', padding: 0 }}>비밀번호를 잊으셨나요?</button>
      </div>

      <div style={{ marginTop: 18 }}>
        <FrPrimaryButton c={c} label="로그인" onClick={() => app.submit()} loading={app.loading} disabled={!app.valid} />
      </div>

      <div style={{ margin: '22px 0 18px' }}><FrDivider c={c} label="또는" /></div>
      <FrSocialGroup c={c} app={app} />

      <div style={{ flex: 1, minHeight: 18 }} />
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 5, fontFamily: FRF, fontSize: 14, letterSpacing: -0.3, marginTop: 18 }}>
        <span style={{ color: c.sub, whiteSpace: 'nowrap' }}>계정이 없으신가요?</span>
        <button onClick={() => app.go('signup', -1)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: c.text, fontWeight: 700, fontFamily: FRF, fontSize: 14, whiteSpace: 'nowrap', padding: 0 }}>회원가입</button>
      </div>
    </div>
  );
}

// ── 4. Email verification (email signup only) ─
function FrEmailVerify({ c, app }) {
  const [code, setCode] = React.useState('');
  const [err, setErr] = React.useState(false);
  const [secs, setSecs] = React.useState(30);
  React.useEffect(() => {
    const t = setInterval(() => setSecs((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, []);
  const attempt = (val) => {
    const cc = val != null ? val : code;
    if (cc.length < 6) return;
    if (cc === app.DEMO_CODE) { setErr(false); app.verifyOk(); }
    else { setErr(true); setTimeout(() => { setErr(false); setCode(''); }, 700); }
  };
  const resend = () => { if (secs > 0) return; setSecs(30); setCode(''); setErr(false); };
  const mm = `0:${String(secs).padStart(2, '0')}`;
  const email = (app.form && app.form.email) || 'you@example.com';
  return (
    <div style={{ ...frPageStyle(c), padding: '0 26px 30px' }}>
      <FrHeader c={c} app={app} title="이메일을 확인해 주세요" />
      <p style={{ fontFamily: FRF, fontSize: 14.5, color: c.sub, letterSpacing: -0.3, margin: '8px 0 0', lineHeight: 1.55 }}>
        <strong style={{ color: c.text, fontWeight: 700 }}>{email}</strong>으로 보낸<br />6자리 인증 코드를 입력해 주세요.
      </p>

      <div style={{ marginTop: 28 }}>
        <FrOtp c={c} value={code} error={err} onChange={(v) => { setCode(v); if (err) setErr(false); }} onComplete={(v) => attempt(v)} />
        <div style={{ minHeight: 18, marginTop: 11 }}>
          {err && <span style={{ fontFamily: FRF, fontSize: 12.5, color: c.danger, letterSpacing: -0.2 }}>코드가 올바르지 않아요. 다시 확인해 주세요.</span>}
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
        <span style={{ fontFamily: FRF, fontSize: 13.5, color: c.sub, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>코드를 못 받으셨나요?</span>
        <button onClick={resend} disabled={secs > 0}
          style={{ background: 'none', border: 'none', cursor: secs > 0 ? 'default' : 'pointer', padding: 0,
            fontFamily: FRF, fontSize: 13.5, fontWeight: 700, letterSpacing: -0.2, color: secs > 0 ? c.faint : c.text, whiteSpace: 'nowrap' }}>
          {secs > 0 ? `재전송 ${mm}` : '코드 재전송'}
        </button>
      </div>

      <div style={{ marginTop: 20 }}>
        <FrPrimaryButton c={c} label="인증하고 계속하기" onClick={() => attempt()} loading={app.loading} disabled={code.length < 6} />
      </div>
      <button onClick={app.back} style={{ display: 'block', margin: '16px auto 0', background: 'none', border: 'none', cursor: 'pointer', fontFamily: FRF, fontSize: 13.5, fontWeight: 600, color: c.sub, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>이메일 주소 수정</button>

      <div style={{ flex: 1, minHeight: 16 }} />
      <div style={{ textAlign: 'center', fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 11.5, color: c.faint, letterSpacing: 0.3 }}>데모 코드 · 123456</div>
    </div>
  );
}

// ── 5. Choose display name (new users, uniqueness check) ─
function FrDisplayName({ c, app }) {
  const [focus, setFocus] = React.useState(false);
  const st = app.nameStatus;
  const danger = st === 'taken' || st === 'invalid' || st === 'profane';
  const okk = st === 'ok';
  const borderCol = danger ? c.danger : (okk || focus ? c.accent : c.fieldBorder);
  const msg = {
    idle: '2~20자 · 한글, 영문, 숫자, _ 사용 가능',
    short: '2자 이상 입력해 주세요',
    invalid: '한글, 영문, 숫자, _만 사용할 수 있어요',
    profane: '사용할 수 없는 이름이에요',
    checking: '사용 가능 여부 확인 중…',
    taken: '이미 사용 중인 이름이에요',
    ok: '사용할 수 있는 이름이에요',
  }[st];
  const msgColor = okk ? c.accent : (danger ? c.danger : c.faint);

  const trailing = st === 'checking' ? <FrSpinner color={c.faint} size={18} />
    : okk ? <FrCheck color={c.accent} w={16} />
    : danger ? <svg width="16" height="16" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" stroke={c.danger} strokeWidth="2.4" strokeLinecap="round" /></svg>
    : null;

  const chip = {
    height: 36, padding: '0 14px', borderRadius: 999, cursor: 'pointer',
    background: c.surfaceAlt, border: `1px solid ${c.border}`, color: c.text,
    fontFamily: FRF, fontSize: 13.5, fontWeight: 600, letterSpacing: -0.2, whiteSpace: 'nowrap',
  };

  return (
    <div style={{ ...frPageStyle(c), padding: '0 26px 30px' }}>
      <FrHeader c={c} app={app} title="어떻게 불러드릴까요?" sub="다른 러너에게 보여질 이름이에요. 언제든 바꿀 수 있어요." />

      <div style={{ marginTop: 26, display: 'flex', flexDirection: 'column', gap: 7 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingLeft: 2 }}>
          <label style={{ fontFamily: FRF, fontSize: 13, fontWeight: 600, color: c.sub, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>표시 이름</label>
          <span style={{ fontFamily: FRF, fontSize: 12, color: c.faint, whiteSpace: 'nowrap' }}>{app.displayName.length}/20</span>
        </div>
        <div style={{
          display: 'flex', alignItems: 'center', height: 54, borderRadius: 14,
          background: c.field, border: `1.5px solid ${borderCol}`,
          boxShadow: focus && !danger ? `0 0 0 3px ${c.accent}22` : 'none',
          transition: 'border-color .15s', padding: '0 14px',
        }}>
          <input value={app.displayName} maxLength={20} autoComplete="off" placeholder="예: 한강러너"
            onChange={(e) => app.setName(e.target.value)} onFocus={() => setFocus(true)} onBlur={() => setFocus(false)}
            style={{ flex: 1, minWidth: 0, border: 'none', outline: 'none', background: 'transparent', fontFamily: FRF, fontSize: 16, color: c.text, letterSpacing: -0.2 }} />
          <span style={{ display: 'flex', marginLeft: 8 }}>{trailing}</span>
        </div>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontFamily: FRF, fontSize: 12.5, color: msgColor, letterSpacing: -0.2, paddingLeft: 2, minHeight: 16 }}>
          {okk && <FrCheck color={c.accent} w={12} />}{msg}
        </span>

        {st === 'taken' && app.nameSuggestions.length > 0 && (
          <div style={{ marginTop: 6 }}>
            <div style={{ fontFamily: FRF, fontSize: 12.5, color: c.sub, letterSpacing: -0.2, paddingLeft: 2, marginBottom: 8 }}>이건 어때요?</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {app.nameSuggestions.map((s) => (
                <button key={s} onClick={() => app.applySuggestion(s)} style={chip}>{s}</button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div style={{ flex: 1, minHeight: 24 }} />
      <FrPrimaryButton c={c} label="시작하기" onClick={() => app.finishName()} loading={app.loading} disabled={!okk} />
    </div>
  );
}

// ── 5. Success ─────────────────────────────────────────
function FrSuccess({ c, app }) {
  const name = app.displayName && app.displayName.trim();
  return (
    <div style={{ ...frPageStyle(c), padding: '70px 30px 34px', alignItems: 'center', textAlign: 'center', justifyContent: 'center' }}>
      <div style={{ flex: 1 }} />
      <div style={{
        width: 92, height: 92, borderRadius: 999, background: c.accent,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        boxShadow: `0 12px 30px ${c.accent}66`, animation: 'frpop 0.5s cubic-bezier(.34,1.56,.64,1)',
      }}>
        <FrCheck color={c.accentText} w={42} />
      </div>
      <h1 style={{ fontFamily: FRF, fontSize: 28, fontWeight: 700, letterSpacing: -0.8, color: c.text, margin: '28px 0 0', textWrap: 'balance', maxWidth: 300 }}>
        {name ? `반가워요, ${name}님!` : '환영합니다!'}
      </h1>
      <p style={{ fontFamily: FRF, fontSize: 15.5, lineHeight: 1.55, color: c.sub, letterSpacing: -0.3, margin: '12px 0 0', maxWidth: 260 }}>
        계정이 만들어졌어요.<br />이제 첫 번째 새로운 코스를 만들 준비가 됐어요.
      </p>
      <div style={{ flex: 1 }} />
      <div style={{ width: '100%' }}>
        <FrPrimaryButton c={c} label="달리러 가기" onClick={() => app.go('home')} />
      </div>
    </div>
  );
}

// ── 5. Home placeholder (where auth lands) ─────────────
function FrHome({ c }) {
  const tabs = [['홈', true], ['코스 생성', false], ['기록', false], ['프로필', false]];
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg, overflow: 'hidden' }}>
      <div style={{ padding: '70px 26px 0' }}>
        <p style={{ fontFamily: FRF, fontSize: 14, color: c.sub, margin: 0, letterSpacing: -0.2 }}>좋은 아침이에요</p>
        <h1 style={{ fontFamily: FRF, fontSize: 26, fontWeight: 700, letterSpacing: -0.7, color: c.text, margin: '4px 0 0' }}>오늘은 어디를 달릴까요?</h1>
      </div>
      {/* striped placeholder for the next phase */}
      <div style={{ flex: 1, margin: '22px 20px', borderRadius: 22, border: `1.5px dashed ${c.fieldBorder}`,
        background: `repeating-linear-gradient(135deg, ${c.surfaceAlt} 0 11px, ${c.bg} 11px 22px)`,
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
        <span style={{ fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 12, color: c.faint, letterSpacing: 0, whiteSpace: 'nowrap' }}>[ 코스 생성 · Phase 2 ]</span>
        <span style={{ fontFamily: FRF, fontSize: 13.5, color: c.sub, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>인증 완료 후 도착하는 화면</span>
      </div>
      {/* bottom tab bar placeholder */}
      <div style={{ display: 'flex', borderTop: `1px solid ${c.border}`, background: c.surface, padding: '10px 8px 30px' }}>
        {tabs.map(([label, active]) => (
          <div key={label} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 22, height: 22, borderRadius: 7, background: active ? c.accent : c.fieldBorder }} />
            <span style={{ fontFamily: FRF, fontSize: 10.5, fontWeight: active ? 700 : 500, color: active ? c.text : c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { FrWelcome, FrSignUp, FrLogin, FrEmailVerify, FrDisplayName, FrSuccess, FrHome });
