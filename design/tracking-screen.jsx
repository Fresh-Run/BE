// FreshRun — Live Tracking + AI audio guide (pushed screen). Counts up, computes pace.
const TF = window.FR_FONT;

// press-and-hold to end the run (prevents accidental taps). Ring fills via CSS over HOLD ms.
function FrHoldStop({ c, onComplete }) {
  const HOLD = 1100;
  const [holding, setHolding] = React.useState(false);
  const timer = React.useRef(0), done = React.useRef(false), cb = React.useRef(onComplete);
  cb.current = onComplete;
  const begin = (e) => { if (e && e.preventDefault) { try { e.preventDefault(); } catch (_) {} } done.current = false; setHolding(true); if (navigator.vibrate) navigator.vibrate(10); clearTimeout(timer.current); timer.current = setTimeout(() => { done.current = true; setHolding(false); if (navigator.vibrate) navigator.vibrate([14, 30, 70]); cb.current && cb.current(); }, HOLD); };
  const cancel = () => { if (done.current) return; clearTimeout(timer.current); setHolding(false); };
  React.useEffect(() => () => clearTimeout(timer.current), []);
  const SZ = 72, R = 33, CIRC = 2 * Math.PI * R;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
      <div style={{ position: 'relative', width: SZ, height: SZ, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <svg width={SZ} height={SZ} viewBox={`0 0 ${SZ} ${SZ}`} style={{ position: 'absolute', transform: 'rotate(-90deg)' }}>
          <circle cx={SZ / 2} cy={SZ / 2} r={R} fill="none" stroke={c.danger + '2A'} strokeWidth="4" />
          <circle cx={SZ / 2} cy={SZ / 2} r={R} fill="none" stroke={c.danger} strokeWidth="4" strokeLinecap="round" strokeDasharray={CIRC} strokeDashoffset={holding ? 0 : CIRC} style={{ transition: holding ? `stroke-dashoffset ${HOLD}ms linear` : 'stroke-dashoffset .25s ease-out' }} />
        </svg>
        <button onPointerDown={begin} onPointerUp={cancel} onPointerLeave={cancel} onPointerCancel={cancel} aria-label="길게 눌러 종료"
          style={{ width: 56, height: 56, borderRadius: 999, border: 'none', background: c.danger, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transform: holding ? 'scale(0.86)' : 'scale(1)', transition: 'transform .14s', boxShadow: `0 6px 16px ${c.danger}55`, touchAction: 'none', WebkitTapHighlightColor: 'transparent' }}>
          <span style={{ width: 18, height: 18, borderRadius: 4, background: '#fff' }} />
        </button>
      </div>
      <span style={{ fontFamily: TF, fontSize: 11, fontWeight: 600, color: holding ? c.danger : c.faint, letterSpacing: -0.2, transition: 'color .15s', whiteSpace: 'nowrap' }}>{holding ? '계속 누르세요…' : '길게 눌러 종료'}</span>
    </div>
  );
}

function FrWaveform({ c, active }) {
  const bars = [10, 18, 26, 14, 22, 30, 16, 12, 24, 20, 28, 14];
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 3, height: 30 }}>
      {bars.map((h, i) => (
        <span key={i} style={{ width: 3, borderRadius: 99, background: c.dark ? c.accent : '#3F8E14', height: h, transformOrigin: 'center', animation: active ? `frwave 0.9s ${i * 0.07}s ease-in-out infinite` : 'none', opacity: active ? 1 : 0.4 }} />
      ))}
    </div>
  );
}

function FrTracking({ c, app, params }) {
  const nav = app.nav;
  const course = params && params.course;
  const units = (app && app.units) || 'km';
  const grn = c.dark ? c.accent : '#3F8E14';
  const [sec, setSec] = React.useState(0);
  const [paused, setPaused] = React.useState(false);
  React.useEffect(() => {
    if (paused) return;
    const id = setInterval(() => setSec(s => s + 1), 1000);
    return () => clearInterval(id);
  }, [paused]);
  // derive distance from a ~5'08"/km effort
  const km = sec / 308;
  const dist = units === 'mi' ? km * 0.621371 : km;
  const distU = units === 'mi' ? 'mi' : 'km';
  const paceSec = 308 + Math.round(Math.sin(sec / 25) * 6);
  const mm = Math.floor(sec / 60), ss = sec % 60;
  const moving = km >= 0.05 && sec >= 8;
  const paceDisplay = moving ? frPaceStr(paceSec) : "--'--\"";
  const coachMsg = !moving ? '출발 준비 완료! 가볍게 시작해볼까요?' : '좋아요! 목표 페이스 유지 중이에요';
  const targetKm = course && +course.dist ? +course.dist : 5.2;
  const progress = Math.min(0.96, km / targetKm);
  const endRun = React.useCallback(() => {
    const run = (window.frBuildRun ? window.frBuildRun({ km, sec, paceSec }) : null);
    if (run && course) { run.title = course.title || run.title; run.area = course.area || run.area; run.tags = (course.tags && course.tags.length) ? course.tags : run.tags; run.seed = course.seed || run.seed; }
    if (course && course.crewId && app.logCrewRun) { const me = (app && app.displayName) || '지윤'; app.logCrewRun(course.crewId, { name: me, km: +km.toFixed(1), pace: frPaceStr(paceSec), dur: `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`, seed: course.seed }); }
    nav.push('personalBest', { prev: "5'30\"", next: frPaceStr(paceSec), run });
  }, [km, sec, paceSec, nav, course, app]);
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg, position: 'relative' }}>
      {/* map area */}
      <div style={{ position: 'relative', flexShrink: 0 }}>
        <FrCourseMap seed={course && course.seed ? course.seed : 'me-live-track'} width="100%" height={330} radius={0} progress={progress} loop={true} drawAnim={false} />
        <button onClick={() => nav.pop()} style={{ position: 'absolute', top: 12, left: 14, width: 40, height: 40, borderRadius: 999, border: 'none', background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(6px)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrIcon name="close" size={20} color="#fff" sw={2} />
        </button>
        {course && (
          <div style={{ position: 'absolute', top: 14, left: '50%', transform: 'translateX(-50%)', maxWidth: '64%', display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(6px)', borderRadius: 999, padding: '7px 13px' }}>
            <FrIcon name="route" size={13} color="#7CF03D" sw={2.2} />
            <span style={{ fontFamily: TF, fontSize: 12, fontWeight: 700, color: '#fff', letterSpacing: -0.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{course.title}</span>
          </div>
        )}
        <div style={{ position: 'absolute', top: 14, right: 14, display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(6px)', borderRadius: 999, padding: '7px 13px' }}>
          <span style={{ width: 7, height: 7, borderRadius: 99, background: paused ? '#E8A23D' : c.accent, animation: paused ? 'none' : 'frblink 1.4s ease-in-out infinite' }} />
          <span style={{ fontFamily: TF, fontSize: 12.5, fontWeight: 700, color: '#fff', letterSpacing: -0.2 }}>{paused ? '일시정지' : '러닝 중'}</span>
        </div>
      </div>

      {/* metrics panel */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: c.bg, borderRadius: '24px 24px 0 0', marginTop: -22, position: 'relative', zIndex: 2, boxShadow: '0 -8px 24px rgba(0,0,0,0.12)', padding: '8px 20px 0' }}>
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 6 }}>
          <div style={{ width: 38, height: 5, borderRadius: 99, background: c.fieldBorder }} />
        </div>

        {/* primary metric: time */}
        <div style={{ textAlign: 'center', marginTop: 14 }}>
          <div style={{ fontFamily: TF, fontSize: 11.5, fontWeight: 600, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase' }}>경과 시간</div>
          <div style={{ fontFamily: TF, fontSize: 56, fontWeight: 700, letterSpacing: -2.5, color: c.text, lineHeight: 1.05, fontVariantNumeric: 'tabular-nums', marginTop: 4 }}>{mm}:{String(ss).padStart(2, '0')}</div>
        </div>

        <div style={{ display: 'flex', marginTop: 18 }}>
          {[[dist.toFixed(2), distU, '거리'], [paceDisplay, '/' + distU, '현재 페이스'], [Math.round(km * 62), 'kcal', '칼로리']].map((m, i) => (
            <div key={i} style={{ flex: 1, textAlign: 'center', borderLeft: i ? `1px solid ${c.border}` : 'none' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: 3 }}>
                <span style={{ fontFamily: TF, fontSize: 23, fontWeight: 700, letterSpacing: -0.7, color: c.text, fontVariantNumeric: 'tabular-nums' }}>{m[0]}</span>
                <span style={{ fontFamily: TF, fontSize: 11.5, fontWeight: 600, color: c.faint }}>{m[1]}</span>
              </div>
              <div style={{ fontFamily: TF, fontSize: 11, color: c.faint, marginTop: 4 }}>{m[2]}</div>
            </div>
          ))}
        </div>

        {/* AI audio guide */}
        <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 14, marginTop: 18, boxShadow: c.shadow }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 36, height: 36, borderRadius: 11, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <FrCIcon name="sparkle" size={18} color={grn} sw={1.9} />
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: TF, fontSize: 11, fontWeight: 700, letterSpacing: 0.3, color: grn, textTransform: 'uppercase' }}>AI 오디오 코치</div>
              <div style={{ fontFamily: TF, fontSize: 13.5, fontWeight: 600, color: c.text, letterSpacing: -0.3, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>"{coachMsg}"</div>
            </div>
            <FrWaveform c={c} active={!paused} />
          </div>
        </div>

        <div style={{ flex: 1 }} />

        {/* controls */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 26, padding: '18px 0 24px' }}>
          <button style={{ width: 56, height: 56, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: c.shadow }}>
            <FrXIcon name="speaker" size={22} color={c.sub} sw={1.9} />
          </button>
          <button onClick={() => setPaused(p => !p)} style={{ width: 78, height: 78, borderRadius: 999, border: 'none', background: c.accent, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 8px 22px ${c.accent}66` }}>
            <FrCIcon name={paused ? 'play' : 'pause'} size={32} color={c.accentText} />
          </button>
          <FrHoldStop c={c} onComplete={endRun} />
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { FrTracking, FrWaveform, FrHoldStop });
