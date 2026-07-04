// FreshRun — 코스 생성 shared UI: course icons, full map, stepper, chips, accordion.
// Reuses FR_LIGHT/FR_DARK/FR_FONT (auth-ui) + frHash/FrIcon/FrAvatar (home-ui).
const CF = window.FR_FONT;

// ── course-specific icons ──────────────────────────────
function FrCIcon({ name, size = 20, color, fill = 'none', sw = 1.8 }) {
  const p = {
    gps: <><circle cx="12" cy="12" r="3.4" fill={color} stroke="none" /><circle cx="12" cy="12" r="7.5" /><path d="M12 1.6V4M12 20v2.4M22.4 12H20M4 12H1.6" strokeLinecap="round" /></>,
    target: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4" /><circle cx="12" cy="12" r="1" fill={color} stroke="none" /></>,
    refresh: <path d="M3.5 12a8.5 8.5 0 0114.5-6M20.5 12A8.5 8.5 0 016 18M17 5.5V9h-3.5M7 18.5V15h3.5" strokeLinecap="round" strokeLinejoin="round" />,
    play: <path d="M7 4.5l12 7.5-12 7.5z" strokeLinejoin="round" fill={color} stroke="none" />,
    pause: <><rect x="6.5" y="5" width="3.6" height="14" rx="1.2" fill={color} stroke="none" /><rect x="13.9" y="5" width="3.6" height="14" rx="1.2" fill={color} stroke="none" /></>,
    stop: <rect x="6" y="6" width="12" height="12" rx="2.5" fill={color} stroke="none" />,
    flag: <path d="M6 21V4M6 4h11l-2 3.5L17 11H6" strokeLinecap="round" strokeLinejoin="round" />,
    tune: <path d="M4 7h10M18 7h2M4 17h2M10 17h10M14 4.5v5M8 14.5v5" strokeLinecap="round" />,
    loop: <path d="M17 4l3 3-3 3M20 7H9a5 5 0 000 10h1M7 20l-3-3 3-3M4 17h11a5 5 0 000-10h-1" strokeLinecap="round" strokeLinejoin="round" />,
    arrow: <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />,
    mountain: <path d="M3 19l6-11 4 7 2.5-4L21 19z" strokeLinejoin="round" />,
    leaf: <path d="M4 20C3 12 9 4 20 4c0 11-8 17-16 16zM9 15c3-3 6-4 9-5" strokeLinecap="round" strokeLinejoin="round" />,
    building: <path d="M5 21V5a1 1 0 011-1h6a1 1 0 011 1v16M13 21V9h5a1 1 0 011 1v11M7.5 8h2M7.5 12h2M16 13h.8M16 17h.8" strokeLinecap="round" />,
    eye: <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" strokeLinejoin="round" />,
    wave: <path d="M3 8c2-2 4-2 6 0M3 14c2-2 4-2 6 0M3 20c2-2 4-2 6 0M9 8c2-2 4-2 6 0M9 14c2-2 4-2 6 0M9 20c2-2 4-2 6 0M15 8c2-2 4-2 6 0M15 14c2-2 4-2 6 0" strokeLinecap="round" />,
    store: <path d="M4 9l1-4h14l1 4M5 9v11h14V9M4 9h16M9 20v-5h6v5" strokeLinejoin="round" strokeLinecap="round" />,
    toilet: <path d="M5 5v6a3 3 0 003 3v6M5 8h6M8 5v9M19 5v6a3 3 0 01-3 3v6M16 14h3" strokeLinecap="round" strokeLinejoin="round" />,
    check: <path d="M4 12.5l5 5L20 6.5" strokeLinecap="round" strokeLinejoin="round" />,
    chevdown: <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />,
    sparkle: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" strokeLinejoin="round" />,
    fire: <path d="M12 3c1 3-1 4-1 6a3 3 0 006 0c0 4-2 7-5 7s-6-3-6-7c0-2 1-3 2-4 0 1 1 2 2 2 1-3 2-5 2-7z" strokeLinejoin="round" />,
    heart: <path d="M12 20.5l-1.6-1.45C5.4 14.5 2.5 11.9 2.5 8.6 2.5 6.1 4.5 4.1 7 4.1c1.5 0 2.9.7 3.8 1.8.9-1.1 2.3-1.8 3.8-1.8 2.5 0 4.5 2 4.5 4.5 0 3.3-2.9 5.9-7.9 10.45L12 20.5z" />,
    close: <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />,
    back: <path d="M15 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />,
    clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" strokeLinecap="round" /></>,
    ruler: <path d="M3 8l5-5 13 13-5 5zM8 8l1.5 1.5M11 5l2 2M5 11l2 2" strokeLinecap="round" strokeLinejoin="round" />,
  }[name];
  return <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={color} strokeWidth={sw}>{p}</svg>;
}

// ── full course map (dark Naver-style) ─────────────────
// progress: 0..1 (running). waypoints: [{t:0..1, kind}]. drawAnim: animate route in.
function FrCourseMap({ seed, width = '100%', height = 300, radius = 0, progress = null, waypoints = [], drawAnim = false, loop = true, dimGrid = false }) {
  const data = React.useMemo(() => {
    const rnd = frHash(seed);
    const W = 390, H = 390, pad = 54;
    const n = 7 + Math.floor(rnd() * 3);
    const pts = [];
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 + rnd() * 0.7;
      const r = (loop ? 105 : 70) + rnd() * 70;
      pts.push([195 + Math.cos(a) * r * 0.92, 195 + Math.sin(a) * r]);
    }
    if (loop) pts.push(pts[0]);
    let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
    }
    const roads = [];
    for (let i = 0; i < 7; i++) { const horiz = rnd() > 0.5; const o = 20 + rnd() * 350; roads.push({ horiz, o, major: rnd() > 0.6 }); }
    const blocks = [];
    for (let i = 0; i < 5; i++) blocks.push([rnd() * W, rnd() * H, 30 + rnd() * 50, 30 + rnd() * 50]);
    return { W, H, pts, d, roads, blocks, start: pts[0], end: pts[pts.length - 1], hasRiver: rnd() > 0.4, riverY: 80 + rnd() * 230 };
  }, [seed, loop]);

  const { W, H, d, roads, blocks, start, end, hasRiver, riverY } = data;
  const pathRef = React.useRef(null);
  const [len, setLen] = React.useState(1000);
  const [userPt, setUserPt] = React.useState(null);
  React.useEffect(() => { if (pathRef.current) { const L = pathRef.current.getTotalLength(); setLen(L); } }, [d]);
  React.useEffect(() => {
    if (progress == null || !pathRef.current) { setUserPt(null); return; }
    const L = pathRef.current.getTotalLength();
    const pt = pathRef.current.getPointAtLength(L * Math.max(0, Math.min(1, progress)));
    setUserPt([pt.x, pt.y]);
  }, [progress, d, len]);

  const accent = '#7CF03D';
  const wpPos = (t) => { if (!pathRef.current) return null; const L = pathRef.current.getTotalLength(); const p = pathRef.current.getPointAtLength(L * t); return [p.x, p.y]; };

  return (
    <div style={{ width, height, borderRadius: radius, overflow: 'hidden', position: 'relative', background: '#0A0D12' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" preserveAspectRatio="xMidYMid slice">
        <rect width={W} height={H} fill="#0A0D12" />
        {blocks.map((b, i) => <rect key={'b' + i} x={b[0]} y={b[1]} width={b[2]} height={b[3]} rx="3" fill="#10151D" />)}
        {hasRiver && <path d={`M -10 ${riverY} C 110 ${riverY + 50}, 240 ${riverY - 60}, ${W + 10} ${riverY + 30}`} stroke="#13354A" strokeWidth={34} fill="none" strokeOpacity="0.8" strokeLinecap="round" />}
        {roads.map((r, i) => r.horiz
          ? <line key={'r' + i} x1="0" y1={r.o} x2={W} y2={r.o} stroke={r.major ? '#1E2530' : '#161C25'} strokeWidth={r.major ? 6 : 3} />
          : <line key={'r' + i} x1={r.o} y1="0" x2={r.o} y2={H} stroke={r.major ? '#1E2530' : '#161C25'} strokeWidth={r.major ? 6 : 3} />)}
        {/* route glow */}
        <path d={d} stroke={accent} strokeOpacity="0.16" strokeWidth="15" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        {/* base (dim when running to show remaining) */}
        <path ref={pathRef} d={d} stroke={progress != null ? '#2C5A1E' : accent} strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" fill="none"
          style={drawAnim ? { strokeDasharray: len, strokeDashoffset: len, animation: 'frcdraw 1.8s cubic-bezier(.4,0,.2,1) forwards' } : undefined} />
        {/* progress overlay when running */}
        {progress != null && <path d={d} stroke={accent} strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" fill="none" style={{ strokeDasharray: len, strokeDashoffset: len * (1 - progress), transition: 'stroke-dashoffset .4s linear' }} />}
        {/* waypoint pins */}
        {waypoints.map((w, i) => { const p = wpPos(w.t); if (!p) return null; return (
          <g key={'w' + i}>
            <circle cx={p[0]} cy={p[1]} r="9" fill="#0A0D12" stroke={accent} strokeWidth="2.5" />
            <circle cx={p[0]} cy={p[1]} r="3" fill={accent} />
          </g>
        ); })}
        {/* start */}
        <circle cx={start[0]} cy={start[1]} r="9" fill="#0A0D12" stroke={accent} strokeWidth="5" />
        {/* end (flag) */}
        {!loop && <g><circle cx={end[0]} cy={end[1]} r="11" fill={accent} /></g>}
        {loop && <circle cx={start[0]} cy={start[1]} r="3.5" fill={accent} />}
        {/* user dot */}
        {userPt && <g><circle cx={userPt[0]} cy={userPt[1]} r="14" fill={accent} fillOpacity="0.2" style={{ animation: 'frpulse 2s ease-out infinite', transformOrigin: `${userPt[0]}px ${userPt[1]}px` }} /><circle cx={userPt[0]} cy={userPt[1]} r="7" fill="#fff" /><circle cx={userPt[0]} cy={userPt[1]} r="4.5" fill={accent} /></g>}
      </svg>
    </div>
  );
}

// ── distance stepper (draggable slider, 100m steps) ────
function FrStepper({ c, value, setValue, min = 1, max = 20, step = 0.1, big = false, units = 'km' }) {
  const mi = units === 'mi';
  const dispV = mi ? value * 0.621371 : value;
  const U = mi ? 'mi' : 'km';
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  const round = (v) => Math.max(min, Math.min(max, Math.round(v / step) * step));
  const dec = () => setValue(+round(value - step).toFixed(1));
  const inc = () => setValue(+round(value + step).toFixed(1));
  const fromX = (clientX) => {
    const r = trackRef.current.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
    setValue(+round(min + pct * (max - min)).toFixed(1));
  };
  const onDown = (e) => { setDragging(true); e.currentTarget.setPointerCapture(e.pointerId); fromX(e.clientX); };
  const onMove = (e) => { if (dragging) fromX(e.clientX); };
  const onUp = (e) => { setDragging(false); try { e.currentTarget.releasePointerCapture(e.pointerId); } catch (_) {} };
  const btn = (on, disabled, kids) => (
    <button onClick={on} disabled={disabled} style={{ width: big ? 56 : 46, height: big ? 56 : 46, borderRadius: 999, border: `1.5px solid ${c.border}`, background: c.surface, cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.35 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: c.shadow, flexShrink: 0, touchAction: 'manipulation' }}>{kids}</button>
  );
  const pct = (value - min) / (max - min);
  const trackW = big ? 248 : 200;
  const knob = dragging ? 22 : 18;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: big ? 18 : 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: big ? 22 : 16 }}>
        {btn(dec, value <= min, <svg width="20" height="20" viewBox="0 0 24 24"><path d="M5 12h14" stroke={c.text} strokeWidth="2.4" strokeLinecap="round" /></svg>)}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 5, minWidth: big ? 150 : 120, justifyContent: 'center' }}>
          <span style={{ fontFamily: CF, fontSize: big ? 56 : 40, fontWeight: 700, color: c.text, letterSpacing: -2, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{dispV.toFixed(1)}</span>
          <span style={{ fontFamily: CF, fontSize: big ? 18 : 15, fontWeight: 600, color: c.sub, letterSpacing: -0.3 }}>{U}</span>
        </div>
        {btn(inc, value >= max, <svg width="20" height="20" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" stroke={c.text} strokeWidth="2.4" strokeLinecap="round" /></svg>)}
      </div>
      {/* draggable slider */}
      <div ref={trackRef} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
        style={{ width: trackW, padding: '12px 0', cursor: 'pointer', touchAction: 'none', position: 'relative' }}>
        <div style={{ height: 6, borderRadius: 99, background: c.field, position: 'relative' }}>
          <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${pct * 100}%`, background: c.accent, borderRadius: 99 }} />
          <div style={{ position: 'absolute', left: `calc(${pct * 100}% - ${knob / 2}px)`, top: `calc(50% - ${knob / 2}px)`, width: knob, height: knob, borderRadius: 99, background: c.accent, boxShadow: dragging ? `0 0 0 6px ${c.accent}33, 0 2px 8px ${c.accent}99` : `0 2px 6px ${c.accent}88`, border: `2px solid ${c.surface}`, transition: 'width .12s, height .12s, box-shadow .12s' }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
          <span style={{ fontFamily: CF, fontSize: 11, color: c.faint, letterSpacing: -0.2 }}>{mi ? (min * 0.621371).toFixed(1) : min}{U}</span>
          <span style={{ fontFamily: CF, fontSize: 11, color: c.faint, letterSpacing: -0.2 }}>{mi ? (max * 0.621371).toFixed(1) : max}{U}</span>
        </div>
      </div>
    </div>
  );
}

// ── mood chip ──────────────────────────────────────────
const FR_MOODS = [['경치', 'eye'], ['도심', 'building'], ['자연', 'leaf'], ['언덕', 'mountain'], ['평지', 'wave']];
function FrMoodChip({ c, label, icon, active, onClick }) {
  return (
    <button onClick={onClick} style={{ display: 'flex', alignItems: 'center', gap: 7, height: 42, padding: '0 16px', borderRadius: 999, cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0, background: active ? c.accentDim : c.surface, border: `1.5px solid ${active ? c.accent : c.border}`, transition: 'background .15s, border-color .15s' }}>
      <FrCIcon name={icon} size={17} color={active ? (c.dark ? c.accent : '#3C7A14') : c.sub} sw={1.9} />
      <span style={{ fontFamily: CF, fontSize: 14, fontWeight: 600, color: active ? (c.dark ? c.accent : '#3C7A14') : c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>{label}</span>
    </button>
  );
}

// ── segmented toggle ───────────────────────────────────
function FrSegment({ c, options, value, onChange, full }) {
  return (
    <div style={{ display: 'flex', gap: 3, background: c.field, border: `1px solid ${c.border}`, borderRadius: 12, padding: 3, width: full ? '100%' : 'auto' }}>
      {options.map(([id, label, icon]) => {
        const on = value === id;
        return (
          <button key={id} onClick={() => onChange(id)} style={{ flex: full ? 1 : 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, height: 40, padding: '0 16px', borderRadius: 9, border: 'none', cursor: 'pointer', background: on ? c.surface : 'transparent', boxShadow: on ? c.shadow : 'none', transition: 'background .15s' }}>
            {icon && <FrCIcon name={icon} size={16} color={on ? c.text : c.faint} sw={1.9} />}
            <span style={{ fontFamily: CF, fontSize: 14, fontWeight: on ? 700 : 600, color: on ? c.text : c.faint, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>{label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ── toggle switch ──────────────────────────────────────
function FrSwitch({ c, on, onClick }) {
  return (
    <button onClick={onClick} style={{ width: 48, height: 29, borderRadius: 999, border: 'none', cursor: 'pointer', background: on ? c.accent : c.fieldBorder, position: 'relative', transition: 'background .18s', flexShrink: 0, padding: 0 }}>
      <span style={{ position: 'absolute', top: 3, left: on ? 22 : 3, width: 23, height: 23, borderRadius: 999, background: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,0.3)', transition: 'left .18s' }} />
    </button>
  );
}

Object.assign(window, { FrCIcon, FrCourseMap, FrStepper, FrMoodChip, FrSegment, FrSwitch, FR_MOODS });
