// FreshRun — extended icon set for the merged app (bell, share, settings, charts…).
// Reuses FR_FONT. Stroke icons on 24-grid. Single component to keep imports light.
function FrXIcon({ name, size = 20, color, fill = 'none', sw = 1.8 }) {
  const p = {
    bell: <path d="M6 9a6 6 0 0112 0c0 5 2 6 2 6H4s2-1 2-6zM9.5 20a2.5 2.5 0 005 0" strokeLinecap="round" strokeLinejoin="round" />,
    share: <><circle cx="6" cy="12" r="2.6" /><circle cx="17.5" cy="6" r="2.6" /><circle cx="17.5" cy="18" r="2.6" /><path d="M8.3 10.8l7-3.6M8.3 13.2l7 3.6" strokeLinecap="round" /></>,
    gear: <><circle cx="12" cy="12" r="3.2" /><path d="M12 2.6l1.4 2.2 2.6-.5.6 2.6 2.4 1-1 2.4 1 2.4-2.4 1-.6 2.6-2.6-.5L12 21.4l-1.4-2.2-2.6.5-.6-2.6-2.4-1 1-2.4-1-2.4 2.4-1 .6-2.6 2.6.5z" strokeLinejoin="round" /></>,
    bolt: <path d="M13 2L4 14h6l-1 8 9-12h-6z" strokeLinejoin="round" />,
    chart: <path d="M5 21V10M12 21V4M19 21v-7M3.5 21h17" strokeLinecap="round" />,
    moon: <path d="M20 14.5A8 8 0 119.5 4 6.4 6.4 0 0020 14.5z" strokeLinejoin="round" />,
    file: <><path d="M7 3h7l4 4v14H7z" strokeLinejoin="round" /><path d="M14 3v4h4M9.5 12h6M9.5 15.5h6" strokeLinecap="round" /></>,
    logout: <path d="M14 4H6a1 1 0 00-1 1v14a1 1 0 001 1h8M15 8l4 4-4 4M9 12h10" strokeLinecap="round" strokeLinejoin="round" />,
    headset: <path d="M4 13v-1a8 8 0 0116 0v1M4 13h2a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1zM20 13h-2a1 1 0 00-1 1v4a1 1 0 001 1h1a1 1 0 001-1z" strokeLinejoin="round" />,
    link: <path d="M9 15l6-6M8.5 11l-1.5 1.5a3.5 3.5 0 005 5L13.5 16M15.5 13l1.5-1.5a3.5 3.5 0 00-5-5L10.5 8" strokeLinecap="round" strokeLinejoin="round" />,
    lock: <><rect x="4.5" y="10.5" width="15" height="10" rx="2.2" /><path d="M8 10.5V8a4 4 0 018 0v2.5" strokeLinecap="round" /></>,
    crown: <path d="M4 18h16M4 18l-1.5-9 5 3.5L12 5l4.5 7.5 5-3.5L20 18" strokeLinejoin="round" strokeLinecap="round" />,
    medal: <><circle cx="12" cy="14.5" r="5" /><path d="M9 10L7 3h10l-2 7M12 12.5l.9 1.8 2 .3-1.4 1.4.3 2-1.8-1-1.8 1 .3-2L9.4 14.6l2-.3z" strokeLinejoin="round" /></>,
    star: <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 17l-5.2 2.6 1-5.8L3.5 9.7l5.9-.9z" strokeLinejoin="round" />,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 7.6h.01" strokeLinecap="round" /></>,
    speaker: <path d="M5 9.5v5h3l4.5 3.5v-12L8 9.5zM16 9a4 4 0 010 6M18.5 6.5a8 8 0 010 11" strokeLinecap="round" strokeLinejoin="round" />,
    skipnext: <><path d="M6 5l9 7-9 7z" fill={color} stroke="none" /><rect x="16.5" y="5" width="2.6" height="14" rx="1" fill={color} stroke="none" /></>,
    edit: <path d="M4 20l.7-3.7L15 6l3 3L7.7 19.3 4 20zM13.5 7.5l3 3" strokeLinejoin="round" strokeLinecap="round" />,
    trash: <path d="M5 7h14M10 7V5h4v2M6 7l1 13h10l1-13M10 11v6M14 11v6" strokeLinecap="round" strokeLinejoin="round" />,
    search: <><circle cx="11" cy="11" r="7" /><path d="M16.5 16.5L21 21" strokeLinecap="round" /></>,
    calendar: <><rect x="4" y="5.5" width="16" height="15" rx="2.4" /><path d="M4 10h16M8 3.5v4M16 3.5v4" strokeLinecap="round" /></>,
    flame: <path d="M12 3c1 3-1 4-1 6a3 3 0 006 0c0 4-2 7-5 7s-6-3-6-7c0-2 1-3 2-4 0 1 1 2 2 2 1-3 2-5 2-7z" strokeLinejoin="round" />,
    trending: <path d="M3 17l6-6 4 4 8-8M15 7h6v6" strokeLinecap="round" strokeLinejoin="round" />,
    seal: <><path d="M12 2.5l2.2 1.6 2.7-.2 1 2.5 2.3 1.4-.7 2.6 1.2 2.4-2 1.8.1 2.7-2.6.7-1.4 2.3-2.6-.7L12 21.5l-2.2-1.6-2.7.7-1.4-2.3-2.6-.7.1-2.7-2-1.8L2.5 11l-.7-2.6 2.3-1.4 1-2.5 2.7.2z" strokeLinejoin="round" /><path d="M8.5 12l2.4 2.4 4.6-4.8" strokeLinecap="round" strokeLinejoin="round" /></>,
    shield: <><path d="M12 3l7 2.5v5.5c0 4.6-3 7.8-7 9-4-1.2-7-4.4-7-9V5.5z" strokeLinejoin="round" /><path d="M8.8 12l2.2 2.2 4.2-4.4" strokeLinecap="round" strokeLinejoin="round" /></>,
    ruler: <path d="M3 8l5-5 13 13-5 5zM8 8l1.6 1.6M11 5l2 2M5 11l2 2" strokeLinecap="round" strokeLinejoin="round" />,
    runner: <><circle cx="14.5" cy="4.6" r="1.9" /><path d="M13 8l-3 2 1 4-3 5M13 8l3 1 3-1M13 8l-1 3 3 2 1 4" strokeLinecap="round" strokeLinejoin="round" /></>,
    health: <path d="M12 20.5l-1.6-1.45C5.4 14.5 2.5 11.9 2.5 8.6 2.5 6.1 4.5 4.1 7 4.1c1.5 0 2.9.7 3.8 1.8.9-1.1 2.3-1.8 3.8-1.8 2.5 0 4.5 2 4.5 4.5 0 3.3-2.9 5.9-7.9 10.45L12 20.5z" />,
    target: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4" /><circle cx="12" cy="12" r="1" fill={color} stroke="none" /></>,
    cloud: <path d="M7 18a4 4 0 01-.4-8A5.5 5.5 0 0117.7 9 3.8 3.8 0 0117 18z" strokeLinejoin="round" />,
    chevright: <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />,
    pace: <><circle cx="12" cy="13" r="7.5" /><path d="M12 13l3-3M12 5.5V3.5M9.5 3.5h5" strokeLinecap="round" strokeLinejoin="round" /></>,
    map: <path d="M9 4L3.5 6v14L9 18l6 2 5.5-2V4L15 6 9 4zM9 4v14M15 6v14" strokeLinejoin="round" strokeLinecap="round" />,
  }[name];
  return <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={color} strokeWidth={sw}>{p}</svg>;
}

// shared section header used across the new screens
function FrSectionTitle({ c, children, action, onAction }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', padding: '0 2px' }}>
      <h2 style={{ fontFamily: FR_FONT, fontSize: 17.5, fontWeight: 700, letterSpacing: -0.5, color: c.text, margin: 0 }}>{children}</h2>
      {action && (
        <button onClick={onAction} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontFamily: FR_FONT, fontSize: 13, fontWeight: 600, color: c.accent === '#74E827' ? '#3F8E14' : c.accent, letterSpacing: -0.2, display: 'flex', alignItems: 'center', gap: 2 }}>{action}</button>
      )}
    </div>
  );
}

// in-phone top app bar for stacked (pushed) screens
function FrAppBar({ c, title, onBack, onClose, right, transparent }) {
  return (
    <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10, padding: '52px 14px 10px', background: transparent ? 'transparent' : c.surface, borderBottom: transparent ? 'none' : `1px solid ${c.border}` }}>
      {onBack && (
        <button onClick={onBack} aria-label="뒤로" style={{ width: 38, height: 38, borderRadius: 999, border: 'none', background: 'transparent', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrCIcon name="back" size={22} color={c.text} sw={2} />
        </button>
      )}
      {onClose && (
        <button onClick={onClose} aria-label="닫기" style={{ width: 38, height: 38, borderRadius: 999, border: 'none', background: 'transparent', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrIcon name="close" size={21} color={c.text} sw={2} />
        </button>
      )}
      <div style={{ flex: 1, fontFamily: FR_FONT, fontSize: 16.5, fontWeight: 700, letterSpacing: -0.4, color: c.text, textAlign: 'center' }}>{title}</div>
      <div style={{ width: 38, height: 38, display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>{right}</div>
    </div>
  );
}

// ── premium lock affordances ───────────────────────────
// small "Premium" pill with a lock glyph
function FrLockChip({ c, label = 'Premium', light }) {
  const grn = c.dark ? c.accent : '#3C7A14';
  const fg = light ? '#0D1A06' : grn;
  const bg = light ? 'rgba(255,255,255,0.92)' : c.accentDim;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: bg, borderRadius: 999, padding: '4px 9px 4px 7px' }}>
      <FrXIcon name="lock" size={12} color={fg} sw={2} />
      <span style={{ fontFamily: FR_FONT, fontSize: 10.5, fontWeight: 800, color: fg, letterSpacing: 0.2, textTransform: 'uppercase' }}>{label}</span>
    </span>
  );
}

// frosted overlay that covers premium-only content in Lite mode
function FrLockedOverlay({ c, onUnlock, label = '프리미엄 전용', cta = '잠금 해제하기', radius = 20 }) {
  return (
    <button onClick={onUnlock} style={{ position: 'absolute', inset: 0, zIndex: 3, borderRadius: radius, border: 'none', cursor: 'pointer', background: c.dark ? 'rgba(14,15,18,0.62)' : 'rgba(250,250,247,0.62)', backdropFilter: 'blur(7px)', WebkitBackdropFilter: 'blur(7px)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10, WebkitTapHighlightColor: 'transparent' }}>
      <span style={{ width: 46, height: 46, borderRadius: 999, background: c.accent, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 6px 16px ${c.accent}55` }}>
        <FrXIcon name="lock" size={22} color={c.accentText} sw={2.1} />
      </span>
      <span style={{ fontFamily: FR_FONT, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>{label}</span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontFamily: FR_FONT, fontSize: 12.5, fontWeight: 700, color: c.dark ? c.accent : '#3C7A14', letterSpacing: -0.2 }}>{cta} <FrXIcon name="chevright" size={14} color={c.dark ? c.accent : '#3C7A14'} sw={2.4} /></span>
    </button>
  );
}

Object.assign(window, { FrXIcon, FrSectionTitle, FrAppBar, FrLockChip, FrLockedOverlay });
