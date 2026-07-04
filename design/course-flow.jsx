// FreshRun — 코스 생성 flow: generating, map result, running, result + feedback.
const GF = window.FR_FONT;
const flowPage = (c) => ({ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg, position: 'relative', overflow: 'hidden' });

// ── 2. Generating (skeleton card preview) ──────────────
function FrGenerating({ c, st, onDone }) {
  const steps = [
    { t: '출발지 주변을 살펴보는 중', r: 2.5 },
    { t: '한 번도 안 달려본 길 찾는 중', r: 3.0 },
    { t: '분위기·경유지 반영하는 중', r: 3.5 },
    { t: '코스를 그리는 중', r: 4.0 },
  ];
  const [i, setI] = React.useState(0);
  React.useEffect(() => {
    const timers = steps.map((_, idx) => setTimeout(() => setI(idx), idx * 1000));
    const done = setTimeout(onDone, steps.length * 1000 + 800);
    return () => { timers.forEach(clearTimeout); clearTimeout(done); };
  }, []);
  const shimMid = c.dark ? '#272c35' : '#e8e8e1';
  const shim = { background: `linear-gradient(100deg, ${c.surfaceAlt} 30%, ${shimMid} 50%, ${c.surfaceAlt} 70%)`, backgroundSize: '200% 100%', animation: 'frshim 1.4s linear infinite' };
  const pct = Math.round(((i + 1) / steps.length) * 100);
  return (
    <div style={flowPage(c)}>
      {/* header */}
      <div style={{ padding: '62px 22px 0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: c.accentDim, border: `1px solid ${c.dark ? 'rgba(124,240,61,0.34)' : c.accent}`, borderRadius: 999, padding: '8px 15px' }}>
          <FrCIcon name="sparkle" size={15} color={c.dark ? '#7CF03D' : '#3C7A14'} sw={2} fill={c.dark ? '#7CF03D' : '#3C7A14'} />
          <span style={{ fontFamily: GF, fontSize: 13, fontWeight: 700, color: c.dark ? '#EAFBDD' : '#3C7A14', letterSpacing: -0.2, whiteSpace: 'nowrap' }}>AI가 코스를 만드는 중</span>
        </div>
        <FrSpinner color={c.accent} size={22} />
      </div>

      {/* status */}
      <div style={{ padding: '24px 22px 0' }}>
        <div style={{ fontFamily: GF, fontSize: 23, fontWeight: 700, color: c.text, letterSpacing: -0.6, whiteSpace: 'nowrap' }}>{steps[i].t}<span className="frdots" /></div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 9 }}>
          <span style={{ fontFamily: GF, fontSize: 13.5, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>탐색 반경 {steps[i].r.toFixed(1)}km</span>
          <span style={{ width: 3, height: 3, borderRadius: 99, background: c.faint }} />
          <span style={{ fontFamily: GF, fontSize: 13.5, fontWeight: 700, color: c.accent, letterSpacing: -0.2, fontVariantNumeric: 'tabular-nums' }}>{pct}%</span>
        </div>
        {/* progress bar */}
        <div style={{ height: 5, borderRadius: 99, background: c.field, marginTop: 14, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: c.accent, borderRadius: 99, transition: 'width .5s cubic-bezier(.4,0,.2,1)' }} />
        </div>
      </div>

      {/* skeleton result card assembling */}
      <div style={{ margin: '22px 22px 0', background: c.surface, border: `1px solid ${c.border}`, borderRadius: 22, overflow: 'hidden', boxShadow: c.shadow }}>
        <div style={{ height: 176, ...shim, position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrCIcon name="route" size={36} color={c.faint} sw={1.5} />
        </div>
        <div style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ height: 19, width: '64%', borderRadius: 6, ...shim }} />
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ height: 25, width: 58, borderRadius: 999, ...shim }} />
            <div style={{ height: 25, width: 50, borderRadius: 999, ...shim }} />
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 2 }}>
            {[0, 1, 2].map(k => <div key={k} style={{ flex: 1, height: 62, borderRadius: 14, ...shim }} />)}
          </div>
        </div>
      </div>

      <div style={{ flex: 1 }} />
      {/* step dots */}
      <div style={{ padding: '0 22px 40px', display: 'flex', justifyContent: 'center', gap: 6 }}>
        {steps.map((_, k) => <span key={k} style={{ width: k === i ? 24 : 7, height: 7, borderRadius: 99, background: k <= i ? c.accent : c.fieldBorder, transition: 'all .3s' }} />)}
      </div>
    </div>
  );
}

// ── 3. Map result ──────────────────────────────────────
function FrMapResult({ c, st, onRun, onRegen, onBack }) {
  const wps = st.waypoints && st.waypoints.length ? st.waypoints.slice(0, 3).map((w, i) => ({ t: 0.25 + i * 0.25, label: w })) : [];
  const est = Math.round(st.dist * 6.4);
  const diffLabel = { easy: '쉬움', normal: '보통', hard: '힘듦' }[st.diff] || '보통';
  return (
    <div style={flowPage(c)}>
      <div style={{ position: 'absolute', inset: 0 }}>
        <FrCourseMap seed={st.seed} width="100%" height="100%" loop={st.shape === 'loop'} waypoints={wps} />
      </div>
      {/* top bar */}
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '58px 18px 0' }}>
        <button onClick={onBack} style={{ width: 42, height: 42, borderRadius: 999, border: 'none', background: 'rgba(20,22,26,0.7)', backdropFilter: 'blur(8px)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrCIcon name="back" size={20} color="#fff" sw={2.2} />
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(20,22,26,0.7)', backdropFilter: 'blur(8px)', borderRadius: 999, padding: '8px 14px' }}>
          <FrCIcon name="sparkle" size={14} color="#7CF03D" sw={2} fill="#7CF03D" />
          <span style={{ fontFamily: GF, fontSize: 12.5, fontWeight: 700, color: '#fff', letterSpacing: -0.2, whiteSpace: 'nowrap' }}>새로 생성된 코스</span>
        </div>
        <button onClick={onRegen} style={{ width: 42, height: 42, borderRadius: 999, border: 'none', background: 'rgba(20,22,26,0.7)', backdropFilter: 'blur(8px)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrCIcon name="refresh" size={19} color="#fff" sw={2} />
        </button>
      </div>
      <div style={{ flex: 1 }} />
      {/* bottom sheet */}
      <div style={{ position: 'relative', background: c.bg, borderRadius: '24px 24px 0 0', padding: '18px 20px 30px', boxShadow: '0 -8px 30px rgba(0,0,0,0.18)' }}>
        <div style={{ fontFamily: GF, fontSize: 19, fontWeight: 700, color: c.text, letterSpacing: -0.5 }}>성수동 {st.dist.toFixed(1)}km {st.shape === 'loop' ? '순환' : '편도'} 코스</div>
        <div style={{ display: 'flex', gap: 7, marginTop: 9, flexWrap: 'wrap' }}>
          {st.moods.length ? st.moods.map(m => <FrTag key={m} c={c} t={m} />) : <FrTag c={c} t="추천" />}
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
          {[['ruler', `${st.dist.toFixed(1)} km`, '거리'], ['clock', `약 ${est}분`, '예상 시간'], ['mountain', diffLabel, '난이도']].map((m, i) => (
            <div key={i} style={{ flex: 1, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 14, padding: '13px 8px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <FrCIcon name={m[0]} size={18} color={c.sub} sw={1.9} />
              <span style={{ fontFamily: GF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>{m[1]}</span>
              <span style={{ fontFamily: GF, fontSize: 11, color: c.faint, letterSpacing: -0.1 }}>{m[2]}</span>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
          <button onClick={onRegen} style={{ width: 56, height: 56, borderRadius: 16, border: `1.5px solid ${c.border}`, background: c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <FrCIcon name="refresh" size={22} color={c.sub} sw={2} />
          </button>
          <button onClick={onRun} style={{ flex: 1, height: 56, borderRadius: 16, border: 'none', background: c.accent, color: c.accentText, fontFamily: GF, fontSize: 16.5, fontWeight: 700, letterSpacing: -0.3, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9, cursor: 'pointer', boxShadow: `0 6px 20px ${c.accent}66`, whiteSpace: 'nowrap' }}>
            <FrCIcon name="play" size={19} color={c.accentText} sw={2} fill={c.accentText} />
            달리기 시작
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 4. Running (live tracking) ─────────────────────────
function FrRunning({ c, st, onFinish }) {
  const [sec, setSec] = React.useState(0);
  const [paused, setPaused] = React.useState(false);
  React.useEffect(() => {
    if (paused) return;
    const id = setInterval(() => setSec(s => s + 1), 1000);
    return () => clearInterval(id);
  }, [paused]);
  const totalSec = Math.round(st.dist * 384); // ~6:24/km
  const progress = Math.min(1, sec / totalSec);
  const distNow = (st.dist * progress).toFixed(2);
  const mm = String(Math.floor(sec / 60)).padStart(2, '0'), ss = String(sec % 60).padStart(2, '0');
  const wps = st.waypoints && st.waypoints.length ? st.waypoints.slice(0, 3).map((w, i) => ({ t: 0.25 + i * 0.25, label: w })) : [];
  return (
    <div style={flowPage(c)}>
      <div style={{ position: 'absolute', inset: 0 }}>
        <FrCourseMap seed={st.seed} width="100%" height="100%" loop={st.shape === 'loop'} waypoints={wps} progress={progress} />
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 140, background: 'linear-gradient(180deg, rgba(10,13,18,0.6), transparent)' }} />
      </div>
      <div style={{ position: 'relative', padding: '56px 20px 0', display: 'flex', justifyContent: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(20,22,26,0.72)', backdropFilter: 'blur(8px)', borderRadius: 999, padding: '8px 16px' }}>
          <span style={{ width: 8, height: 8, borderRadius: 99, background: '#7CF03D', animation: 'frblink 1.4s ease-in-out infinite' }} />
          <span style={{ fontFamily: GF, fontSize: 13, fontWeight: 700, color: '#fff', letterSpacing: -0.2, whiteSpace: 'nowrap' }}>기록 중 · {st.dist.toFixed(1)}km 코스</span>
        </div>
      </div>
      <div style={{ flex: 1 }} />
      <div style={{ position: 'relative', background: c.bg, borderRadius: '24px 24px 0 0', padding: '22px 22px 30px', boxShadow: '0 -8px 30px rgba(0,0,0,0.2)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontFamily: GF, fontSize: 12.5, color: c.faint, fontWeight: 600, letterSpacing: -0.2 }}>거리</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
              <span style={{ fontFamily: GF, fontSize: 52, fontWeight: 700, color: c.text, letterSpacing: -2.5, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{distNow}</span>
              <span style={{ fontFamily: GF, fontSize: 17, fontWeight: 600, color: c.sub }}>km</span>
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: GF, fontSize: 12.5, color: c.faint, fontWeight: 600, letterSpacing: -0.2 }}>남은 거리</div>
            <div style={{ fontFamily: GF, fontSize: 20, fontWeight: 700, color: c.sub, letterSpacing: -0.5, fontVariantNumeric: 'tabular-nums' }}>{(st.dist - distNow).toFixed(2)}km</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 18 }}>
          {[[`${mm}:${ss}`, '시간'], ["6'24\"", '평균 페이스'], [`${Math.round(distNow * 62)}`, 'kcal']].map((m, i) => (
            <div key={i} style={{ flex: 1, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 14, padding: '12px 8px', textAlign: 'center' }}>
              <div style={{ fontFamily: GF, fontSize: 17, fontWeight: 700, color: c.text, letterSpacing: -0.4, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>{m[0]}</div>
              <div style={{ fontFamily: GF, fontSize: 11, color: c.faint, marginTop: 3 }}>{m[1]}</div>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 12, marginTop: 18, alignItems: 'center' }}>
          <button onClick={() => setPaused(p => !p)} style={{ flex: 1, height: 56, borderRadius: 16, border: `1.5px solid ${c.border}`, background: c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, fontFamily: GF, fontSize: 15.5, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>
            <FrCIcon name={paused ? 'play' : 'pause'} size={18} color={c.text} sw={2} fill={c.text} />
            {paused ? '계속' : '일시정지'}
          </button>
          <button onClick={onFinish} style={{ width: 64, height: 56, borderRadius: 16, border: 'none', background: c.danger, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 5px 16px ${c.danger}55` }}>
            <FrCIcon name="stop" size={22} color="#fff" sw={2} fill="#fff" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 5. Run result + 2-tap feedback ─────────────────────
const FR_FB_GOOD = ['조용함', '경치', '공원', '편함', '안전'];
const FR_FB_BAD = ['언덕', '사람많음', '신호등', '좁은 인도', '차량', '지루함'];
function FrRunResult({ c, st, onSkip, onSave }) {
  const [verdict, setVerdict] = React.useState(null);
  const [tags, setTags] = React.useState([]);
  const est = Math.round(st.dist * 6.4);
  const toggle = (t) => setTags(x => x.includes(t) ? x.filter(y => y !== t) : x.concat([t]));
  const pool = verdict === 'good' ? FR_FB_GOOD : FR_FB_BAD;
  return (
    <div style={flowPage(c)}>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* hero */}
        <div style={{ position: 'relative', height: 240 }}>
          <FrCourseMap seed={st.seed} width="100%" height={240} loop={st.shape === 'loop'} progress={1} />
          <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(180deg, rgba(10,13,18,0.5), rgba(10,13,18,0.1) 40%, var(--frbg))', '--frbg': c.bg }} />
          <div style={{ position: 'absolute', left: 20, bottom: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, background: 'rgba(124,240,61,0.2)', border: '1px solid rgba(124,240,61,0.45)', borderRadius: 999, padding: '6px 12px', width: 'fit-content' }}>
              <FrCIcon name="check" size={14} color="#7CF03D" sw={2.6} />
              <span style={{ fontFamily: GF, fontSize: 12.5, fontWeight: 700, color: '#EAFBDD', letterSpacing: -0.2, whiteSpace: 'nowrap' }}>러닝 완료!</span>
            </div>
          </div>
        </div>
        <div style={{ padding: '6px 20px 0' }}>
          <h1 style={{ fontFamily: GF, fontSize: 24, fontWeight: 700, color: c.text, letterSpacing: -0.6, margin: 0 }}>수고했어요, 지윤러너님</h1>
          <p style={{ fontFamily: GF, fontSize: 14, color: c.sub, letterSpacing: -0.3, margin: '6px 0 0' }}>성수동 {st.dist.toFixed(1)}km {st.shape === 'loop' ? '순환' : '편도'} 코스</p>
          {/* stats */}
          <div style={{ display: 'flex', gap: 10, marginTop: 18 }}>
            {[[`${st.dist.toFixed(2)}`, 'km', '거리'], [`${est}:0${0}`.slice(0, 5), '', '시간'], ["6'24\"", '/km', '페이스'], [`${Math.round(st.dist * 62)}`, 'kcal', '칼로리']].map((m, i) => (
              <div key={i} style={{ flex: 1, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 14, padding: '13px 6px', textAlign: 'center' }}>
                <div style={{ fontFamily: GF, fontSize: 16, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>{m[0]}<span style={{ fontSize: 9.5, color: c.faint, fontWeight: 600 }}>{m[1] ? ' ' + m[1] : ''}</span></div>
                <div style={{ fontFamily: GF, fontSize: 10.5, color: c.faint, marginTop: 3 }}>{m[2]}</div>
              </div>
            ))}
          </div>
          {/* feedback */}
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 18, marginTop: 18, boxShadow: c.shadow }}>
            <div style={{ fontFamily: GF, fontSize: 15.5, fontWeight: 700, color: c.text, letterSpacing: -0.4, textAlign: 'center' }}>이 코스 어땠나요?</div>
            <div style={{ fontFamily: GF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, textAlign: 'center', margin: '5px 0 0' }}>다음 추천이 더 좋아져요</div>
            <div style={{ display: 'flex', gap: 11, marginTop: 16 }}>
              <button onClick={() => { setVerdict('good'); setTags([]); }} style={{ flex: 1, height: 56, borderRadius: 14, cursor: 'pointer', border: `1.5px solid ${verdict === 'good' ? c.accent : c.border}`, background: verdict === 'good' ? c.accentDim : c.field, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                <FrCIcon name="heart" size={20} color={verdict === 'good' ? (c.dark ? c.accent : '#3C7A14') : c.sub} sw={1.9} fill={verdict === 'good' ? (c.dark ? c.accent : '#3C7A14') : 'none'} />
                <span style={{ fontFamily: GF, fontSize: 15, fontWeight: 700, color: verdict === 'good' ? (c.dark ? c.accent : '#3C7A14') : c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>좋았어요</span>
              </button>
              <button onClick={() => { setVerdict('bad'); setTags([]); }} style={{ flex: 1, height: 56, borderRadius: 14, cursor: 'pointer', border: `1.5px solid ${verdict === 'bad' ? c.danger : c.border}`, background: verdict === 'bad' ? c.danger + '14' : c.field, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                <span style={{ display: 'inline-flex', transform: 'rotate(180deg)' }}><FrCIcon name="heart" size={20} color={verdict === 'bad' ? c.danger : c.sub} sw={1.9} /></span>
                <span style={{ fontFamily: GF, fontSize: 15, fontWeight: 700, color: verdict === 'bad' ? c.danger : c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>별로였어요</span>
              </button>
            </div>
            {verdict && (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontFamily: GF, fontSize: 12.5, color: c.sub, letterSpacing: -0.2, marginBottom: 10, fontWeight: 600 }}>{verdict === 'good' ? '무엇이 좋았나요?' : '무엇이 별로였나요?'}</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {pool.map(t => {
                    const on = tags.includes(t);
                    const col = verdict === 'good' ? c.accent : c.danger;
                    return <button key={t} onClick={() => toggle(t)} style={{ height: 38, padding: '0 14px', borderRadius: 999, cursor: 'pointer', background: on ? (verdict === 'good' ? c.accentDim : c.danger + '14') : c.field, border: `1.5px solid ${on ? col : c.border}`, fontFamily: GF, fontSize: 13, fontWeight: 600, color: on ? (verdict === 'good' ? (c.dark ? c.accent : '#3C7A14') : c.danger) : c.text, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{t}</button>;
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
      <div style={{ padding: '12px 20px 30px', borderTop: `1px solid ${c.border}`, background: c.bg, display: 'flex', gap: 10 }}>
        <button onClick={onSkip} style={{ flex: 1, height: 54, borderRadius: 15, border: `1.5px solid ${c.border}`, background: c.surface, cursor: 'pointer', fontFamily: GF, fontSize: 15.5, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>홈으로</button>
        <button onClick={() => onSave(verdict, tags)} disabled={!verdict} style={{ flex: 2, height: 54, borderRadius: 15, border: 'none', background: c.accent, color: c.accentText, cursor: verdict ? 'pointer' : 'default', opacity: verdict ? 1 : 0.4, fontFamily: GF, fontSize: 15.5, fontWeight: 700, letterSpacing: -0.3, boxShadow: verdict ? `0 5px 16px ${c.accent}55` : 'none' }}>저장하고 완료</button>
      </div>
    </div>
  );
}

// ── 6. Run saved confirmation ──────────────────────────
function FrRunSaved({ c, st, verdict, onHome, onViewLog }) {
  const est = Math.round(st.dist * 6.4);
  return (
    <div style={flowPage(c)}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '0 28px', textAlign: 'center' }}>
        <div style={{ width: 88, height: 88, borderRadius: 999, background: c.accent, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 12px 34px ${c.accent}55`, animation: 'frpop 0.5s cubic-bezier(.34,1.56,.64,1)' }}>
          <FrCIcon name="check" size={42} color={c.accentText} sw={3} />
        </div>
        <h1 style={{ fontFamily: GF, fontSize: 26, fontWeight: 700, color: c.text, letterSpacing: -0.7, margin: '26px 0 0', whiteSpace: 'nowrap' }}>기록에 저장됐어요</h1>
        <p style={{ fontFamily: GF, fontSize: 14.5, lineHeight: 1.55, color: c.sub, letterSpacing: -0.3, margin: '10px 0 0', maxWidth: 280, textWrap: 'balance' }}>이 코스가 내 기록과 코스 목록에 추가됐어요. 다음 추천이 더 정확해져요.</p>

        {/* summary card */}
        <div style={{ width: '100%', marginTop: 30, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 20, padding: 16, boxShadow: c.shadow, display: 'flex', alignItems: 'center', gap: 14, textAlign: 'left' }}>
          <FrMiniMap seed={st.seed} width={72} height={72} radius={14} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: GF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap' }}>성수동 {st.dist.toFixed(1)}km {st.shape === 'loop' ? '순환' : '편도'}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 5 }}>
              <FrCIcon name="clock" size={12} color={c.faint} sw={2} />
              <span style={{ fontFamily: GF, fontSize: 12.5, color: c.sub, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>오늘 오전 9:41 · {est}분</span>
            </div>
            {verdict && (
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: 5, marginTop: 9, background: verdict === 'good' ? c.accentDim : c.danger + '14', borderRadius: 999, padding: '4px 10px' }}>
                <span style={{ display: 'inline-flex', transform: verdict === 'good' ? 'none' : 'rotate(180deg)' }}><FrCIcon name="heart" size={12} color={verdict === 'good' ? (c.dark ? c.accent : '#3C7A14') : c.danger} sw={2} fill={verdict === 'good' ? (c.dark ? c.accent : '#3C7A14') : 'none'} /></span>
                <span style={{ fontFamily: GF, fontSize: 11.5, fontWeight: 700, color: verdict === 'good' ? (c.dark ? c.accent : '#3C7A14') : c.danger, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{verdict === 'good' ? '좋았어요' : '별로였어요'} 피드백 반영됨</span>
              </div>
            )}
          </div>
        </div>
      </div>
      <div style={{ padding: '12px 20px 30px', display: 'flex', gap: 10 }}>
        <button onClick={onViewLog} style={{ flex: 1, height: 54, borderRadius: 15, border: `1.5px solid ${c.border}`, background: c.surface, cursor: 'pointer', fontFamily: GF, fontSize: 15.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>기록 보기</button>
        <button onClick={onHome} style={{ flex: 1, height: 54, borderRadius: 15, border: 'none', background: c.accent, color: c.accentText, cursor: 'pointer', fontFamily: GF, fontSize: 15.5, fontWeight: 700, letterSpacing: -0.3, boxShadow: `0 5px 16px ${c.accent}55`, whiteSpace: 'nowrap' }}>홈으로</button>
      </div>
    </div>
  );
}

// ── course tab container (form B + flow) for the merged app ──
function frMakeSeed() { return 'course-' + Math.floor(Math.random() * 1e9).toString(36); }

function FrCourseTab({ c, app, onTab }) {
  const [screen, setScreen] = React.useState('choice');
  const [adv, setAdv] = React.useState(false);
  const [fb, setFb] = React.useState(null);
  const [st, setSt] = React.useState({
    dist: 5.0, locMode: 'gps', shape: 'loop', moods: ['경치'],
    diff: 'normal', waypoints: [], avoidHills: false, avoidBusy: false, seed: frMakeSeed(),
  });
  const set = (k, v) => setSt(s => ({ ...s, [k]: v }));
  const tabBar = <FrTabBar c={c} active="course" onTab={onTab} />;
  const genStart = () => { if (app && !app.premium && app.incAiGen) app.incAiGen(); setScreen('generating'); };
  if (screen === 'choice') return <FrRunChoice c={c} app={app} onAI={() => setScreen('form')} onFree={() => app && app.nav && app.nav.push('tracking')} tabBar={tabBar} />;
  if (screen === 'form') return <FrFormB c={c} st={st} set={set} adv={adv} setAdv={setAdv} units={app && app.units} onBack={() => setScreen('choice')} onGenerate={genStart} tabBar={tabBar} />;
  if (screen === 'generating') return <FrGenerating c={c} st={st} onDone={() => setScreen('result')} />;
  if (screen === 'result') return <FrMapResult c={c} st={st} onRun={() => setScreen('running')} onRegen={() => { set('seed', frMakeSeed()); setScreen('generating'); }} onBack={() => setScreen('form')} />;
  if (screen === 'running') return <FrRunning c={c} st={st} onFinish={() => setScreen('runresult')} />;
  if (screen === 'runresult') return <FrRunResult c={c} st={st} onSkip={() => { setScreen('choice'); onTab('home'); }} onSave={(verdict) => { setFb(verdict); setScreen('saved'); }} />;
  if (screen === 'saved') return <FrRunSaved c={c} st={st} verdict={fb} onHome={() => { setScreen('choice'); onTab('home'); }} onViewLog={() => { setScreen('choice'); onTab('log'); }} />;
  return null;
}

Object.assign(window, { FrGenerating, FrMapResult, FrRunning, FrRunResult, FrRunSaved, FrCourseTab, frMakeSeed });
