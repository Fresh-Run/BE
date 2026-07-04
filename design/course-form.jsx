// FreshRun — 코스 생성 form, two variations (A: stacked cards, B: compact).
const FF = window.FR_FONT;

// ── section header ─────────────────────────────────────
function FrSecLabel({ c, children, hint }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 12 }}>
      <span style={{ fontFamily: FF, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>{children}</span>
      {hint && <span style={{ fontFamily: FF, fontSize: 12, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{hint}</span>}
    </div>
  );
}
function FrCard({ c, children, pad = 16 }) {
  return <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: pad, boxShadow: c.shadow }}>{children}</div>;
}

// ── location row ───────────────────────────────────────
function FrLocationRow({ c, mode, setMode, place }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '11px 13px', borderRadius: 13, background: c.field, border: `1px solid ${c.border}` }}>
        <div style={{ width: 34, height: 34, borderRadius: 999, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          <FrCIcon name="gps" size={17} color={c.dark ? c.accent : '#3C7A14'} sw={1.9} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: FF, fontSize: 11.5, color: c.faint, letterSpacing: -0.2, fontWeight: 600 }}>출발지</div>
          <div style={{ fontFamily: FF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{place}</div>
        </div>
        <button style={{ fontFamily: FF, fontSize: 12.5, fontWeight: 700, color: c.sub, letterSpacing: -0.2, background: 'none', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap', padding: 4 }}>변경</button>
      </div>
      <FrSegment c={c} full value={mode} onChange={setMode} options={[['gps', '현재 위치', 'gps'], ['manual', '직접 선택', 'target']]} />
    </div>
  );
}

// ── advanced accordion ─────────────────────────────────
function FrAdvanced({ c, open, setOpen, st, set }) {
  const wpKeys = [['편의점', 'store'], ['화장실', 'toilet'], ['카페', 'sparkle'], ['공원', 'leaf']];
  const diffs = [['easy', '쉬움'], ['normal', '보통'], ['hard', '힘듦']];
  return (
    <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, boxShadow: c.shadow, overflow: 'hidden' }}>
      <button onClick={() => setOpen(!open)} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 11, padding: '15px 16px', background: 'none', border: 'none', cursor: 'pointer' }}>
        <FrCIcon name="tune" size={19} color={c.sub} sw={1.9} />
        <span style={{ fontFamily: FF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>고급 설정</span>
        {!open && <span style={{ fontFamily: FF, fontSize: 12, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>난이도 · 경유지 · 회피</span>}
        <span style={{ marginLeft: 'auto', display: 'flex', transition: 'transform .2s', transform: open ? 'rotate(180deg)' : 'none' }}>
          <FrCIcon name="chevdown" size={20} color={c.faint} sw={2} />
        </span>
      </button>
      {open && (
        <div style={{ padding: '4px 16px 18px', display: 'flex', flexDirection: 'column', gap: 18, borderTop: `1px solid ${c.border}` }}>
          <div style={{ marginTop: 14 }}>
            <FrSecLabel c={c}>난이도</FrSecLabel>
            <FrSegment c={c} full value={st.diff} onChange={(v) => set('diff', v)} options={diffs} />
          </div>
          <div>
            <FrSecLabel c={c}>경유지 키워드</FrSecLabel>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {wpKeys.map(([label, icon]) => {
                const on = st.waypoints.includes(label);
                return (
                  <button key={label} onClick={() => set('waypoints', on ? st.waypoints.filter(w => w !== label) : st.waypoints.concat([label]))}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, height: 38, padding: '0 13px', borderRadius: 999, cursor: 'pointer', background: on ? c.accentDim : c.field, border: `1.5px solid ${on ? c.accent : c.border}` }}>
                    <FrCIcon name={icon} size={15} color={on ? (c.dark ? c.accent : '#3C7A14') : c.sub} sw={1.9} />
                    <span style={{ fontFamily: FF, fontSize: 13, fontWeight: 600, color: on ? (c.dark ? c.accent : '#3C7A14') : c.text, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{label}</span>
                  </button>
                );
              })}
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {[['avoidHills', '언덕 피하기'], ['avoidBusy', '번잡한 길 피하기']].map(([k, label]) => (
              <div key={k} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 0' }}>
                <span style={{ fontFamily: FF, fontSize: 14, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{label}</span>
                <FrSwitch c={c} on={st[k]} onClick={() => set(k, !st[k])} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── generate button ────────────────────────────────────
function FrGenerateButton({ c, onClick }) {
  return (
    <button onClick={onClick} style={{ height: 56, width: '100%', borderRadius: 16, border: 'none', background: c.accent, color: c.accentText, fontFamily: FF, fontSize: 16.5, fontWeight: 700, letterSpacing: -0.3, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9, cursor: 'pointer', boxShadow: `0 6px 20px ${c.accent}66`, whiteSpace: 'nowrap' }}>
      <FrCIcon name="sparkle" size={20} color={c.accentText} sw={2} fill={c.accentText} />
      코스 생성하기
    </button>
  );
}

// ── form header ────────────────────────────────────────
function FrFormHeader({ c, sub }) {
  return (
    <div>
      <h1 style={{ fontFamily: FF, fontSize: 25, fontWeight: 700, letterSpacing: -0.7, color: c.text, margin: 0, whiteSpace: 'nowrap' }}>새 코스 만들기</h1>
      <p style={{ fontFamily: FF, fontSize: 14, color: c.sub, letterSpacing: -0.3, margin: '6px 0 0', lineHeight: 1.5 }}>{sub}</p>
    </div>
  );
}

// ════ VARIATION A — stacked cards ════════════════════
function FrFormA({ c, st, set, adv, setAdv, onGenerate }) {
  return (
    <div style={frPage(c)}>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        <div style={{ padding: '60px 20px 0' }}><FrFormHeader c={c} sub="원하는 조건을 고르면 AI가 새 코스를 그려드려요." /></div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 13, padding: '22px 20px 26px' }}>
          <FrCard c={c} pad={18}>
            <FrSecLabel c={c} hint="1 – 20km">거리</FrSecLabel>
            <div style={{ padding: '6px 0 2px' }}><FrStepper c={c} value={st.dist} setValue={(v) => set('dist', v)} /></div>
          </FrCard>
          <FrCard c={c}>
            <FrSecLabel c={c}>출발지</FrSecLabel>
            <FrLocationRow c={c} mode={st.locMode} setMode={(v) => set('locMode', v)} place="서울 성수동 · 서울숲역 2번 출구" />
          </FrCard>
          <FrCard c={c}>
            <FrSecLabel c={c}>코스 형태</FrSecLabel>
            <FrSegment c={c} full value={st.shape} onChange={(v) => set('shape', v)} options={[['loop', '순환 (제자리)', 'loop'], ['oneway', '편도', 'arrow']]} />
          </FrCard>
          <FrCard c={c}>
            <FrSecLabel c={c} hint="여러 개 선택 가능">분위기</FrSecLabel>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 9 }}>
              {FR_MOODS.map(([label, icon]) => (
                <FrMoodChip key={label} c={c} label={label} icon={icon} active={st.moods.includes(label)}
                  onClick={() => set('moods', st.moods.includes(label) ? st.moods.filter(m => m !== label) : st.moods.concat([label]))} />
              ))}
            </div>
          </FrCard>
          <FrAdvanced c={c} open={adv} setOpen={setAdv} st={st} set={set} />
        </div>
      </div>
      <div style={{ padding: '12px 20px 30px', borderTop: `1px solid ${c.border}`, background: c.bg }}>
        <FrGenerateButton c={c} onClick={onGenerate} />
      </div>
    </div>
  );
}

// ════ VARIATION B — compact hero ═════════════════════
function FrFormB({ c, st, set, adv, setAdv, onGenerate, onBack, tabBar, units = 'km' }) {
  return (
    <div style={frPage(c)}>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* hero distance */}
        <div style={{ background: c.surfaceAlt, borderBottom: `1px solid ${c.border}`, padding: '54px 20px 24px' }}>
          {onBack && (
            <button onClick={onBack} aria-label="뒤로" style={{ width: 40, height: 40, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16, WebkitTapHighlightColor: 'transparent' }}>
              <FrCIcon name="back" size={20} color={c.text} sw={2.2} />
            </button>
          )}
          <FrFormHeader c={c} sub="조건을 고르면 한 번도 안 달려본 코스를 만들어요." />
          <div style={{ marginTop: 22 }}><FrStepper c={c} big value={st.dist} setValue={(v) => set('dist', v)} units={units} /></div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 22, padding: '22px 20px 26px' }}>
          <div>
            <FrSecLabel c={c}>출발지 · 코스 형태</FrSecLabel>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 13px', borderRadius: 13, background: c.field, border: `1px solid ${c.border}` }}>
                <FrCIcon name="gps" size={17} color={c.dark ? c.accent : '#3C7A14'} sw={1.9} />
                <span style={{ fontFamily: FF, fontSize: 14, fontWeight: 600, color: c.text, letterSpacing: -0.3, flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>서울숲역 2번 출구</span>
                <button style={{ fontFamily: FF, fontSize: 12.5, fontWeight: 700, color: c.sub, background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>변경</button>
              </div>
              <FrSegment c={c} full value={st.shape} onChange={(v) => set('shape', v)} options={[['loop', '순환', 'loop'], ['oneway', '편도', 'arrow']]} />
            </div>
          </div>
          <div>
            <FrSecLabel c={c} hint="여러 개 선택">분위기</FrSecLabel>
            <div style={{ display: 'flex', gap: 9, overflowX: 'auto', paddingBottom: 4, margin: '0 -20px', padding: '0 20px 4px' }}>
              {FR_MOODS.map(([label, icon]) => (
                <FrMoodChip key={label} c={c} label={label} icon={icon} active={st.moods.includes(label)}
                  onClick={() => set('moods', st.moods.includes(label) ? st.moods.filter(m => m !== label) : st.moods.concat([label]))} />
              ))}
            </div>
          </div>
          <FrAdvanced c={c} open={adv} setOpen={setAdv} st={st} set={set} />
        </div>
      </div>
      <div style={{ padding: tabBar ? '12px 20px 12px' : '12px 20px 30px', borderTop: `1px solid ${c.border}`, background: c.bg }}>
        <FrGenerateButton c={c} onClick={onGenerate} />
      </div>
      {tabBar}
    </div>
  );
}

Object.assign(window, { FrFormA, FrFormB, FrCard, FrSecLabel, FrGenerateButton });
