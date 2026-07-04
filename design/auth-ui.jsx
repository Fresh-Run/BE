// FreshRun — shared auth UI primitives, theme tokens, route motif
// Exports to window. Calm/minimal. Pretendard type. Single green spark accent.

const FR_LIGHT = {
  dark: false,
  bg: '#FAFAF7', surface: '#FFFFFF', surfaceAlt: '#F4F4EF',
  text: '#16171A', sub: '#6B6E74', faint: '#A2A6AC',
  border: '#E7E7E0', field: '#F3F3ED', fieldBorder: '#E4E4DC',
  accent: '#74E827', accentText: '#0D1A06', accentDim: '#EAF8DA',
  danger: '#D8463C',
  appleBg: '#000000', appleFg: '#FFFFFF',
  shadow: '0 1px 2px rgba(20,22,18,0.04), 0 8px 24px rgba(20,22,18,0.05)',
};
const FR_DARK = {
  dark: true,
  bg: '#0E0F12', surface: '#15171C', surfaceAlt: '#1B1E24',
  text: '#F2F3F0', sub: '#9A9EA5', faint: '#6A6F77',
  border: '#24282F', field: '#181B21', fieldBorder: '#2A2F38',
  accent: '#63C23A', accentText: '#0B1505', accentDim: '#18260D',
  danger: '#F0635A',
  appleBg: '#FFFFFF', appleFg: '#000000',
  shadow: '0 1px 2px rgba(0,0,0,0.4), 0 10px 30px rgba(0,0,0,0.35)',
};

const FR_FONT = "'Pretendard', -apple-system, system-ui, sans-serif";

// ── Icons ──────────────────────────────────────────────
function FrEye({ off, color }) {
  return off ? (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <path d="M3 3l18 18" stroke={color} strokeWidth="1.7" strokeLinecap="round"/>
      <path d="M10.6 5.2A9.8 9.8 0 0112 5c5 0 9 4.5 9 7-.4 1-1.3 2.3-2.6 3.4M6.2 6.6C3.9 8 2.4 10 2 12c.6 1.6 4 7 10 7 1.4 0 2.7-.3 3.8-.8" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M9.7 9.8a3 3 0 004.3 4.2" stroke={color} strokeWidth="1.7" strokeLinecap="round"/>
    </svg>
  ) : (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" stroke={color} strokeWidth="1.7" strokeLinejoin="round"/>
      <circle cx="12" cy="12" r="3" stroke={color} strokeWidth="1.7"/>
    </svg>
  );
}
function FrCheck({ color, w = 14 }) {
  return (
    <svg width={w} height={w} viewBox="0 0 24 24" fill="none">
      <path d="M4 12.5l5 5L20 6.5" stroke={color} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}
function FrBack({ color }) {
  return (
    <svg width="11" height="19" viewBox="0 0 12 20" fill="none">
      <path d="M10 2L2 10l8 8" stroke={color} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}
function FrSpinner({ color, size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{ animation: 'frspin 0.7s linear infinite' }}>
      <circle cx="12" cy="12" r="9" stroke={color} strokeOpacity="0.25" strokeWidth="2.6" fill="none"/>
      <path d="M12 3a9 9 0 019 9" stroke={color} strokeWidth="2.6" strokeLinecap="round" fill="none"/>
    </svg>
  );
}

// ── Brand wordmark + route mark ────────────────────────
function FrLogo({ c, size = 22 }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
        <path d="M5 18c2.5 0 3-7 6-7s3.5 4.5 6 4.5" stroke={c.accent} strokeWidth="2.4" strokeLinecap="round"/>
        <circle cx="5" cy="18" r="2.4" fill={c.accent}/>
        <circle cx="17.4" cy="15.2" r="2.1" fill="none" stroke={c.text} strokeWidth="2"/>
      </svg>
      <span style={{ fontFamily: FR_FONT, fontWeight: 700, fontSize: size * 0.85, letterSpacing: -0.6, color: c.text }}>
        Fresh<span style={{ color: c.text, opacity: 0.45 }}>Run</span>
      </span>
    </div>
  );
}

// ── Hero route motif — animated winding course ─────────
function FrRouteMotif({ c }) {
  const path = "M14 150 C 40 150, 46 96, 74 96 S 118 142, 150 132 S 188 70, 214 78 S 252 120, 286 92";
  return (
    <div style={{ position: 'relative', width: '100%', height: 188 }}>
      <svg viewBox="0 0 300 188" width="100%" height="188" fill="none" style={{ overflow: 'visible' }}>
        {/* faint guide contours */}
        {[40, 80, 120, 160].map((y) => (
          <line key={y} x1="0" y1={y} x2="300" y2={y} stroke={c.border} strokeWidth="1" strokeDasharray="2 9" />
        ))}
        {/* route base glow */}
        <path d={path} stroke={c.accent} strokeOpacity="0.18" strokeWidth="10" strokeLinecap="round" />
        {/* route line */}
        <path d={path} stroke={c.accent} strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" />
        {/* start marker */}
        <circle cx="14" cy="150" r="6.5" fill={c.surface} stroke={c.accent} strokeWidth="3" />
        {/* end marker w/ pulse */}
        <circle cx="286" cy="92" r="13" fill={c.accent} fillOpacity="0.16" style={{ animation: 'frpulse 2.2s ease-out infinite', transformOrigin: '286px 92px' }} />
        <circle cx="286" cy="92" r="6.5" fill={c.accent} />
      </svg>
      {/* floating stat chip */}
      <div style={{
        position: 'absolute', top: 44, right: 6, display: 'flex', alignItems: 'center', gap: 7,
        background: c.surface, border: `1px solid ${c.border}`, borderRadius: 999,
        padding: '7px 12px', boxShadow: c.shadow,
      }}>
        <span style={{ width: 7, height: 7, borderRadius: 99, background: c.accent }} />
        <span style={{ fontFamily: FR_FONT, fontSize: 12.5, fontWeight: 600, color: c.text, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>5.2 km · 28분</span>
      </div>
    </div>
  );
}

// ── Text field ─────────────────────────────────────────
function FrField({ c, label, value, onChange, onBlur, type = 'text', placeholder, error, autoComplete, inputMode, trailing, hint }) {
  const [focus, setFocus] = React.useState(false);
  const borderCol = error ? c.danger : (focus ? c.accent : c.fieldBorder);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
      <label style={{ fontFamily: FR_FONT, fontSize: 13, fontWeight: 600, color: c.sub, letterSpacing: -0.2, paddingLeft: 2 }}>{label}</label>
      <div style={{
        display: 'flex', alignItems: 'center', height: 54, borderRadius: 14,
        background: c.field, border: `1.5px solid ${borderCol}`,
        boxShadow: focus && !error ? `0 0 0 3px ${c.accent}22` : 'none',
        transition: 'border-color .15s, box-shadow .15s', padding: '0 14px',
      }}>
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setFocus(true)}
          onBlur={() => { setFocus(false); onBlur && onBlur(); }}
          type={type} placeholder={placeholder} autoComplete={autoComplete} inputMode={inputMode}
          style={{
            flex: 1, minWidth: 0, border: 'none', outline: 'none', background: 'transparent',
            fontFamily: FR_FONT, fontSize: 16, color: c.text, letterSpacing: -0.2,
          }}
        />
        {trailing}
      </div>
      {error ? (
        <span style={{ fontFamily: FR_FONT, fontSize: 12.5, color: c.danger, paddingLeft: 2 }}>{error}</span>
      ) : hint ? (
        <span style={{ fontFamily: FR_FONT, fontSize: 12.5, color: c.faint, paddingLeft: 2 }}>{hint}</span>
      ) : null}
    </div>
  );
}

function FrPasswordField({ c, label, value, onChange, onBlur, error, placeholder, showStrength }) {
  const [show, setShow] = React.useState(false);
  const ok = value.length >= 8;
  return (
    <FrField
      c={c} label={label} value={value} onChange={onChange} onBlur={onBlur}
      type={show ? 'text' : 'password'} placeholder={placeholder} autoComplete="off" error={error}
      hint={showStrength && !error ? null : undefined}
      trailing={
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {showStrength && value.length > 0 && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontFamily: FR_FONT, fontSize: 12, fontWeight: 600, color: ok ? c.accent : c.faint, whiteSpace: 'nowrap' }}>
              {ok && <FrCheck color={c.accent} w={13} />}8자+
            </span>
          )}
          <button onClick={() => setShow((s) => !s)} aria-label="비밀번호 표시"
            style={{ border: 'none', background: 'transparent', padding: 4, cursor: 'pointer', display: 'flex' }}>
            <FrEye off={!show} color={c.faint} />
          </button>
        </div>
      }
    />
  );
}

// ── Primary button ─────────────────────────────────────
function FrPrimaryButton({ c, label, onClick, disabled, loading }) {
  return (
    <button onClick={onClick} disabled={disabled || loading}
      style={{
        height: 54, width: '100%', borderRadius: 15, border: 'none',
        background: c.accent, color: c.accentText,
        fontFamily: FR_FONT, fontSize: 16.5, fontWeight: 700, letterSpacing: -0.3,
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.4 : 1, transition: 'transform .1s',
        boxShadow: disabled ? 'none' : `0 6px 18px ${c.accent}55`,
      }}
      onMouseDown={(e) => !disabled && (e.currentTarget.style.transform = 'scale(0.985)')}
      onMouseUp={(e) => (e.currentTarget.style.transform = 'none')}
      onMouseLeave={(e) => (e.currentTarget.style.transform = 'none')}>
      {loading ? <FrSpinner color={c.accentText} /> : label}
    </button>
  );
}

// ── Divider with label ─────────────────────────────────
function FrDivider({ c, label }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '2px 0' }}>
      <div style={{ flex: 1, height: 1, background: c.border }} />
      <span style={{ fontFamily: FR_FONT, fontSize: 12.5, color: c.faint, letterSpacing: 0 }}>{label}</span>
      <div style={{ flex: 1, height: 1, background: c.border }} />
    </div>
  );
}

// ── Social buttons ─────────────────────────────────────
function FrSocialButton({ c, brand, label, onClick }) {
  const styles = {
    apple: { bg: c.appleBg, fg: c.appleFg, border: 'none' },
    kakao: { bg: '#FEE500', fg: '#1A1100', border: 'none' },
    google: { bg: c.surface, fg: c.text, border: `1.5px solid ${c.fieldBorder}` },
  }[brand];
  const icon = {
    apple: <svg width="18" height="18" viewBox="0 0 24 24" fill={c.appleFg}><path d="M16.36 1.43c0 1.14-.42 2.2-1.12 3-.78.88-2.05 1.56-3.1 1.48-.13-1.1.43-2.27 1.07-2.99.78-.9 2.13-1.55 3.15-1.49zM20.5 17.06c-.55 1.27-.82 1.84-1.53 2.96-.99 1.57-2.39 3.53-4.12 3.54-1.54.02-1.94-1.01-4.03-1-2.09.01-2.53 1.02-4.07 1.01-1.73-.01-3.05-1.78-4.04-3.35-2.77-4.36-3.06-9.11-1.64-11.63 1.01-1.79 2.6-2.92 4.1-2.92 1.53 0 2.49 1.04 4.04 1.04 1.49 0 2.4-1.04 4.18-1.04 1.32 0 2.72.72 3.72 1.96-3.27 1.8-2.74 6.48.4 7.83z"/></svg>,
    kakao: <svg width="18" height="18" viewBox="0 0 24 24" fill="#1A1100"><path d="M12 3.5C6.9 3.5 2.8 6.74 2.8 10.74c0 2.55 1.7 4.79 4.27 6.06-.19.66-.68 2.37-.78 2.74-.12.45.17.45.35.33.14-.09 2.27-1.55 3.2-2.18.7.1 1.42.16 2.16.16 5.1 0 9.2-3.24 9.2-7.11S17.1 3.5 12 3.5z"/></svg>,
    google: <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.08H42V20H24v8h11.3c-1.65 4.66-6.08 8-11.3 8-6.63 0-12-5.37-12-12s5.37-12 12-12c3.06 0 5.84 1.15 7.96 3.04l5.66-5.66C34.05 6.05 29.27 4 24 4 12.95 4 4 12.95 4 24s8.95 20 20 20 20-8.95 20-20c0-1.34-.14-2.65-.4-3.92z"/><path fill="#FF3D00" d="M6.31 14.69l6.57 4.82C14.66 15.11 18.96 12 24 12c3.06 0 5.84 1.15 7.96 3.04l5.66-5.66C34.05 6.05 29.27 4 24 4 16.32 4 9.66 8.34 6.31 14.69z"/><path fill="#4CAF50" d="M24 44c5.17 0 9.86-1.98 13.41-5.19l-6.19-5.24C29.21 35.09 26.72 36 24 36c-5.2 0-9.62-3.32-11.28-7.95l-6.52 5.03C9.51 39.56 16.23 44 24 44z"/><path fill="#1976D2" d="M43.6 20.08H42V20H24v8h11.3c-.79 2.24-2.23 4.17-4.09 5.57l6.19 5.24C36.97 39.2 44 34 44 24c0-1.34-.14-2.65-.4-3.92z"/></svg>,
  }[brand];
  return (
    <button onClick={onClick}
      style={{
        height: 52, width: '100%', borderRadius: 14, background: styles.bg, color: styles.fg,
        border: styles.border, position: 'relative', cursor: 'pointer',
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
        fontFamily: FR_FONT, fontSize: 15.5, fontWeight: 600, letterSpacing: -0.3,
        transition: 'transform .1s, filter .15s',
      }}
      onMouseDown={(e) => (e.currentTarget.style.transform = 'scale(0.99)')}
      onMouseUp={(e) => (e.currentTarget.style.transform = 'none')}
      onMouseLeave={(e) => (e.currentTarget.style.transform = 'none')}>
      <span style={{ position: 'absolute', left: 18, display: 'flex' }}>{icon}</span>
      {label}
    </button>
  );
}

// ── Back button (round) ────────────────────────────────
function FrBackButton({ c, onClick }) {
  return (
    <button onClick={onClick} aria-label="뒤로"
      style={{
        width: 42, height: 42, borderRadius: 999, border: `1px solid ${c.border}`,
        background: c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
        boxShadow: c.shadow,
      }}>
      <FrBack color={c.text} />
    </button>
  );
}

// ── OTP / verification code input ────────────────
function FrOtp({ c, length = 6, value, onChange, error, onComplete }) {
  const refs = React.useRef([]);
  const boxes = [];
  for (let i = 0; i < length; i++) {
    const ch = value[i] || '';
    const filled = !!ch;
    boxes.push(
      <input key={i} ref={(el) => (refs.current[i] = el)} value={ch} inputMode="numeric" maxLength={1}
        aria-label={`자릿수 ${i + 1}`}
        onChange={(e) => {
          const raw = e.target.value.replace(/\D/g, '');
          if (!raw) return;
          if (raw.length > 1) {
            const merged = (value.slice(0, i) + raw).slice(0, length);
            onChange(merged);
            const fi = Math.min(merged.length, length - 1);
            setTimeout(() => refs.current[fi] && refs.current[fi].focus(), 0);
            if (merged.length === length) onComplete && onComplete(merged);
            return;
          }
          const nv = (value.slice(0, i) + raw + value.slice(i + 1)).slice(0, length);
          onChange(nv);
          if (i < length - 1) setTimeout(() => refs.current[i + 1] && refs.current[i + 1].focus(), 0);
          if (nv.length === length) onComplete && onComplete(nv);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Backspace') {
            if (value[i]) { onChange(value.slice(0, i) + value.slice(i + 1)); }
            else if (i > 0) { onChange(value.slice(0, i - 1)); setTimeout(() => refs.current[i - 1] && refs.current[i - 1].focus(), 0); }
          }
        }}
        style={{
          width: 46, height: 56, textAlign: 'center', borderRadius: 13, padding: 0,
          background: c.field, border: `1.5px solid ${error ? c.danger : (filled ? c.accent : c.fieldBorder)}`,
          fontFamily: FR_FONT, fontSize: 22, fontWeight: 700, color: error ? c.danger : c.text, outline: 'none',
          transition: 'border-color .15s',
        }} />
    );
  }
  return <div style={{ display: 'flex', gap: 9, justifyContent: 'space-between', animation: error ? 'frshake .4s' : 'none' }}>{boxes}</div>;
}

Object.assign(window, {
  FR_LIGHT, FR_DARK, FR_FONT,
  FrEye, FrCheck, FrBack, FrSpinner, FrLogo, FrRouteMotif,
  FrField, FrPasswordField, FrPrimaryButton, FrDivider, FrSocialButton, FrBackButton, FrOtp,
});
