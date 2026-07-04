// FreshRun — 홈 screens (Layout A + B) + shared sub-components.
const HSF = window.FR_FONT;
const frPage = (c) => ({ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg, position: 'relative', overflow: 'hidden' });

// ── metric tile / inline metric ────────────────────────
function FrMetric({ c, icon, label, value, dotColor }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5, flex: 1, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <FrIcon name={icon} size={14} color={c.faint} sw={1.9} />
        <span style={{ fontFamily: HSF, fontSize: 11.5, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{label}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        {dotColor && <span style={{ width: 7, height: 7, borderRadius: 99, background: dotColor, flexShrink: 0 }} />}
        <span style={{ fontFamily: HSF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>{value}</span>
      </div>
    </div>
  );
}

// ── A: full weather banner ─────────────────────────────
function FrWeatherBanner({ c }) {
  const w = FR_WEATHER, vc = frVerdictColor(c, w.verdict.tone);
  return (
    <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 20, padding: 16, boxShadow: c.shadow }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <FrIcon name="pin" size={13} color={c.faint} sw={1.9} />
            <span style={{ fontFamily: HSF, fontSize: 12.5, color: c.sub, letterSpacing: -0.2, fontWeight: 600 }}>서울 · {w.area}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 9, marginTop: 7 }}>
            <span style={{ fontFamily: HSF, fontSize: 38, fontWeight: 700, color: c.text, letterSpacing: -1.5, lineHeight: 0.9 }}>{w.temp}°</span>
            <span style={{ fontFamily: HSF, fontSize: 13, color: c.sub, letterSpacing: -0.3, marginBottom: 4, whiteSpace: 'nowrap' }}>{w.condition} · 체감 {w.feels}°</span>
          </div>
        </div>
        <div style={{ width: 38, height: 38, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrIcon name="sun" size={30} color="#E8A23D" sw={1.7} />
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 14, background: vc + '1A', border: `1px solid ${vc}44`, borderRadius: 12, padding: '9px 12px' }}>
        <span style={{ width: 8, height: 8, borderRadius: 99, background: vc, flexShrink: 0 }} />
        <span style={{ fontFamily: HSF, fontSize: 13, fontWeight: 600, color: c.sub, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>오늘의 러닝 지수</span>
        <span style={{ fontFamily: HSF, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, marginLeft: 'auto', whiteSpace: 'nowrap' }}>{w.verdict.label}</span>
      </div>

      <div style={{ display: 'flex', gap: 10, marginTop: 14, paddingTop: 14, borderTop: `1px solid ${c.border}` }}>
        <FrMetric c={c} icon="droplet" label="습도" value={`${w.humidity}%`} />
        <FrMetric c={c} icon="haze" label="미세먼지" value={w.pm10.label} dotColor={FR_AQI_COLOR[w.pm10.label]} />
        <FrMetric c={c} icon="haze" label="초미세" value={w.pm25.label} dotColor={FR_AQI_COLOR[w.pm25.label]} />
        <FrMetric c={c} icon="wind" label="바람" value={`${w.wind}㎧`} />
      </div>
    </div>
  );
}

// ── B: compact weather strip (tappable) ────────────────
function FrWeatherStrip({ c, onClick }) {
  const w = FR_WEATHER, vc = frVerdictColor(c, w.verdict.tone);
  return (
    <button onClick={onClick} style={{ width: '100%', textAlign: 'left', background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: '11px 12px 11px 14px', boxShadow: c.shadow, display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
      <FrIcon name="sun" size={26} color="#E8A23D" sw={1.8} />
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ fontFamily: HSF, fontSize: 22, fontWeight: 700, color: c.text, letterSpacing: -0.8 }}>{w.temp}°</span>
        <span style={{ fontFamily: HSF, fontSize: 11.5, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{w.area}</span>
      </div>
      <div style={{ width: 1, height: 26, background: c.border }} />
      <div style={{ display: 'flex', gap: 12, flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <FrIcon name="droplet" size={13} color={c.faint} sw={1.9} />
          <span style={{ fontFamily: HSF, fontSize: 12.5, fontWeight: 600, color: c.text, whiteSpace: 'nowrap' }}>{w.humidity}%</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 6, height: 6, borderRadius: 99, background: FR_AQI_COLOR[w.pm10.label], flexShrink: 0 }} />
          <span style={{ fontFamily: HSF, fontSize: 12.5, fontWeight: 600, color: c.text, whiteSpace: 'nowrap' }}>미세 {w.pm10.label}</span>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, background: vc + '1A', borderRadius: 999, padding: '5px 10px', whiteSpace: 'nowrap' }}>
        <span style={{ width: 7, height: 7, borderRadius: 99, background: vc }} />
        <span style={{ fontFamily: HSF, fontSize: 12, fontWeight: 700, color: c.text, letterSpacing: -0.2 }}>{w.verdict.short}</span>
      </div>
      <span style={{ display: 'flex', marginLeft: 2 }}><FrIcon name="chevron" size={16} color={c.faint} sw={2.2} /></span>
    </button>
  );
}

// ── expanded weather bubble (overlay) ──────────────────
function FrWeatherBubble({ c, onClose }) {
  const w = FR_WEATHER, vc = frVerdictColor(c, w.verdict.tone);
  const tiles = [
    { icon: 'droplet', label: '습도', value: `${w.humidity}%` },
    { icon: 'haze', label: '미세먼지', value: w.pm10.label, sub: `${w.pm10.v}㎍`, dot: FR_AQI_COLOR[w.pm10.label] },
    { icon: 'haze', label: '초미세먼지', value: w.pm25.label, sub: `${w.pm25.v}㎍`, dot: FR_AQI_COLOR[w.pm25.label] },
    { icon: 'wind', label: '바람', value: `${w.wind}㎧` },
    { icon: 'sun', label: '자외선', value: w.uv.label, sub: `지수 ${w.uv.v}` },
    { icon: 'droplet', label: '강수확률', value: `${w.rain}%` },
  ];
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 70 }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.34)', animation: 'frfadein .18s' }} />
      <div style={{ position: 'absolute', top: 104, left: 16, right: 16, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 22, padding: 18, boxShadow: '0 18px 50px rgba(0,0,0,0.28)', transformOrigin: 'top center', animation: 'frbubble .26s cubic-bezier(.34,1.4,.64,1)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <FrIcon name="pin" size={13} color={c.faint} sw={1.9} />
              <span style={{ fontFamily: HSF, fontSize: 12.5, color: c.sub, letterSpacing: -0.2, fontWeight: 600 }}>서울 · {w.area}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 9, marginTop: 8 }}>
              <span style={{ fontFamily: HSF, fontSize: 42, fontWeight: 700, color: c.text, letterSpacing: -1.8, lineHeight: 0.9 }}>{w.temp}°</span>
              <span style={{ fontFamily: HSF, fontSize: 13, color: c.sub, letterSpacing: -0.3, marginBottom: 5, whiteSpace: 'nowrap' }}>{w.condition} · 체감 {w.feels}°</span>
            </div>
          </div>
          <button onClick={onClose} style={{ width: 32, height: 32, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surfaceAlt, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <FrIcon name="close" size={16} color={c.sub} sw={2} />
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 14, background: vc + '1A', border: `1px solid ${vc}44`, borderRadius: 12, padding: '9px 12px' }}>
          <span style={{ width: 8, height: 8, borderRadius: 99, background: vc, flexShrink: 0 }} />
          <span style={{ fontFamily: HSF, fontSize: 13, fontWeight: 600, color: c.sub, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>오늘의 러닝 지수</span>
          <span style={{ fontFamily: HSF, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, marginLeft: 'auto', whiteSpace: 'nowrap' }}>{w.verdict.label}</span>
        </div>

        <p style={{ fontFamily: HSF, fontSize: 13, lineHeight: 1.55, color: c.sub, letterSpacing: -0.3, margin: '12px 2px 0', textWrap: 'pretty' }}>{w.tip}</p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginTop: 16 }}>
          {tiles.map((t, i) => (
            <div key={i} style={{ background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: 14, padding: '11px 12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <FrIcon name={t.icon} size={13} color={c.faint} sw={1.9} />
                <span style={{ fontFamily: HSF, fontSize: 11, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{t.label}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 6 }}>
                {t.dot && <span style={{ width: 7, height: 7, borderRadius: 99, background: t.dot, flexShrink: 0 }} />}
                <span style={{ fontFamily: HSF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>{t.value}</span>
              </div>
              {t.sub && <div style={{ fontFamily: HSF, fontSize: 10.5, color: c.faint, letterSpacing: -0.1, marginTop: 2 }}>{t.sub}</div>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── feed tabs: 친구 / 전체 + location ───────────────────
function FrFeedTabs({ c, tab, setTab }) {
  const seg = (id, label) => (
    <button onClick={() => setTab(id)} style={{ flex: 1, height: 32, borderRadius: 999, border: 'none', cursor: 'pointer', background: tab === id ? c.surface : 'transparent', boxShadow: tab === id ? c.shadow : 'none', fontFamily: HSF, fontSize: 13, fontWeight: 700, letterSpacing: -0.3, color: tab === id ? c.text : c.faint, transition: 'color .15s', whiteSpace: 'nowrap', padding: '0 18px' }}>{label}</button>
  );
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
      <div style={{ display: 'flex', gap: 3, background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: 999, padding: 3 }}>
        {seg('친구', '친구')}
        {seg('전체', '전체')}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}>
        <FrIcon name="pin" size={13} color={c.faint} sw={1.9} />
        <span style={{ fontFamily: HSF, fontSize: 12, color: c.faint, letterSpacing: -0.2, fontWeight: 600 }}>{tab === '전체' ? '성수동 10km 이내' : '성수동'}</span>
      </div>
    </div>
  );
}

// ── interaction row ────────────────────────────────────
function FrAction({ c, icon, label, active, activeColor, onClick, fillWhenActive }) {
  const col = active ? (activeColor || c.accent) : c.sub;
  return (
    <button onClick={(e) => { e.stopPropagation(); onClick && onClick(); }}
      style={{ display: 'flex', alignItems: 'center', gap: 5, background: 'none', border: 'none', cursor: 'pointer', padding: '4px 2px', WebkitTapHighlightColor: 'transparent' }}>
      <span style={{ display: 'flex', transition: 'transform .15s', transform: active ? 'scale(1.08)' : 'none' }}>
        <FrIcon name={icon} size={19} color={col} fill={active && fillWhenActive ? col : 'none'} sw={1.9} />
      </span>
      {label != null && <span style={{ fontFamily: HSF, fontSize: 13, fontWeight: 600, color: col, letterSpacing: -0.2, minWidth: 8 }}>{label}</span>}
    </button>
  );
}

function FrTag({ c, t }) {
  return <span style={{ fontFamily: HSF, fontSize: 11.5, fontWeight: 600, color: c.sub, background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: 999, padding: '3px 9px', whiteSpace: 'nowrap' }}>{t}</span>;
}

// ── A card: map left, content right ────────────────────
function FrRunCardA({ c, item, st, on }) {
  return (
    <div onClick={() => on.open(item)} style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 12, boxShadow: c.shadow, cursor: 'pointer', display: 'flex', gap: 12 }}>
      <FrMiniMap seed={item.seed} width={92} height={92} radius={13} />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <FrAvatar name={item.name} size={22} />
          <span style={{ fontFamily: HSF, fontSize: 12.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>{item.name}</span>
          <span style={{ fontFamily: HSF, fontSize: 11.5, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>· {item.ago}</span>
        </div>
        <span style={{ fontFamily: HSF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.4, marginTop: 5, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.title}</span>
        <div style={{ display: 'flex', gap: 12, marginTop: 6 }}>
          <span style={{ fontFamily: HSF, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>{item.dist}<span style={{ fontSize: 10.5, color: c.faint, fontWeight: 600 }}> km</span></span>
          <span style={{ fontFamily: HSF, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>{item.dur}</span>
          <span style={{ fontFamily: HSF, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>{item.pace}<span style={{ fontSize: 10.5, color: c.faint, fontWeight: 600 }}> /km</span></span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 'auto', paddingTop: 8 }}>
          <FrAction c={c} icon="heart" label={item.kudos + (st.liked ? 1 : 0)} active={st.liked} activeColor={c.danger} fillWhenActive onClick={() => on.like(item.id)} />
          <FrAction c={c} icon="comment" label={item.comments} onClick={() => on.open(item)} />
          <FrAction c={c} icon="bookmark" active={st.saved} fillWhenActive onClick={() => on.save(item)} />
        </div>
      </div>
    </div>
  );
}

// ── B card: full-bleed hero map ────────────────────────
function FrRunCardB({ c, item, st, on, showAway }) {
  return (
    <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 20, boxShadow: c.shadow, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '12px 14px' }}>
        <FrAvatar name={item.name} size={36} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: HSF, fontSize: 14, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>{item.name}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <FrIcon name="pin" size={11} color={c.faint} sw={2} />
            <span style={{ fontFamily: HSF, fontSize: 11.5, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{item.area} · {item.ago}</span>
            {showAway && item.away != null && (
              <span style={{ fontFamily: HSF, fontSize: 11.5, fontWeight: 700, color: c.accent, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>· {item.away}km</span>
            )}
          </div>
        </div>
        <button onClick={() => on.save(item)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
          <FrIcon name="bookmark" size={20} color={st.saved ? c.accent : c.faint} fill={st.saved ? c.accent : 'none'} sw={1.9} />
        </button>
      </div>
      <div onClick={() => on.open(item)} style={{ position: 'relative', cursor: 'pointer', margin: '0 0 0 0' }}>
        <FrMiniMap seed={item.seed} width="100%" height={172} radius={0} hero />
        <div style={{ position: 'absolute', left: 12, bottom: 12, display: 'flex', gap: 7 }}>
          {item.tags.map(t => (
            <span key={t} style={{ fontFamily: HSF, fontSize: 11.5, fontWeight: 700, color: '#fff', background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(6px)', borderRadius: 999, padding: '4px 10px', whiteSpace: 'nowrap' }}>{t}</span>
          ))}
        </div>
      </div>
      <div onClick={() => on.open(item)} style={{ padding: '12px 14px 4px', cursor: 'pointer' }}>
        <div style={{ fontFamily: HSF, fontSize: 15.5, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.title}</div>
        <div style={{ display: 'flex', gap: 18, marginTop: 9 }}>
          {[[item.dist, 'km', '거리'], [item.dur, '', '시간'], [item.pace, '/km', '페이스']].map((m, i) => (
            <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span style={{ fontFamily: HSF, fontSize: 16, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap' }}>{m[0]}<span style={{ fontSize: 11, color: c.faint, fontWeight: 600 }}>{m[1] ? ' ' + m[1] : ''}</span></span>
              <span style={{ fontFamily: HSF, fontSize: 10.5, color: c.faint, letterSpacing: -0.1 }}>{m[2]}</span>
            </div>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 18, padding: '8px 14px 12px', margin: '6px 0 0', borderTop: `1px solid ${c.border}` }}>
        <FrAction c={c} icon="heart" label={item.kudos + (st.liked ? 1 : 0)} active={st.liked} activeColor={c.danger} fillWhenActive onClick={() => on.like(item.id)} />
        <FrAction c={c} icon="comment" label={item.comments} onClick={() => on.open(item)} />
        <button onClick={(e) => { e.stopPropagation(); on.run(item); }} style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, background: c.accentDim, border: `1px solid ${c.accent}`, borderRadius: 999, padding: '6px 13px', cursor: 'pointer' }}>
          <FrIcon name="route" size={15} color={c.dark ? c.accent : '#3F8E14'} sw={2} />
          <span style={{ fontFamily: HSF, fontSize: 12.5, fontWeight: 700, color: c.dark ? c.accent : '#3F8E14', letterSpacing: -0.2, whiteSpace: 'nowrap' }}>이 코스 달리기</span>
        </button>
      </div>
    </div>
  );
}

// ── tab bar (floating pill — option 1) ─────────────────
function FrTabBar({ c, active = 'home', onTab }) {
  const tabs = [['home', 'home', '홈'], ['users', 'community', '커뮤니티'], ['plus', 'course', '뛰러 가기'], ['list', 'log', '기록'], ['person', 'profile', '프로필']];
  const floatShadow = c.dark ? '0 12px 32px rgba(0,0,0,0.55), 0 2px 8px rgba(0,0,0,0.4)' : '0 12px 30px rgba(20,22,18,0.16), 0 2px 8px rgba(20,22,18,0.07)';
  return (
    <div style={{ flexShrink: 0, position: 'relative', background: c.bg, paddingTop: 8 }}>
      <div style={{ position: 'absolute', left: 0, right: 0, top: -26, height: 26, background: `linear-gradient(180deg, ${c.bg}00, ${c.bg})`, pointerEvents: 'none' }} />
      <div style={{ margin: '0 16px 26px', height: 66, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 33, boxShadow: floatShadow, display: 'flex', alignItems: 'center', padding: '0 12px' }}>
        {tabs.map(([icon, id, label]) => {
          const on = active === id;
          if (icon === 'plus') {
            return (
              <button key={id} onClick={() => onTab && onTab(id)} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3, background: 'none', border: 'none', cursor: 'pointer', padding: 0, WebkitTapHighlightColor: 'transparent' }}>
                <div style={{ width: 50, height: 50, borderRadius: 17, marginTop: -10, background: c.accent, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 7px 18px ${c.accent}66` }}>
                  <FrIcon name="plus" size={25} color={c.accentText} sw={2.4} />
                </div>
                <span style={{ fontFamily: HSF, fontSize: 10, fontWeight: on ? 800 : 700, color: on ? (c.dark ? c.accent : '#3F8E14') : c.text, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{label}</span>
              </button>
            );
          }
          return (
            <button key={id} onClick={() => onTab && onTab(id)} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, background: 'none', border: 'none', cursor: 'pointer', padding: 0, WebkitTapHighlightColor: 'transparent' }}>
              <FrIcon name={icon} size={22} color={on ? c.text : c.faint} fill="none" sw={on ? 2.1 : 1.8} />
              <span style={{ fontFamily: HSF, fontSize: 10, fontWeight: on ? 700 : 500, color: on ? c.text : c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── greeting header ────────────────────────────────────
function FrGreeting({ c, compact, name = '지윤', onBell }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontFamily: HSF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, fontWeight: 600 }}>토요일, 6월 16일</div>
        <h1 style={{ fontFamily: HSF, fontSize: compact ? 20 : 23, fontWeight: 700, letterSpacing: -0.7, color: c.text, margin: '3px 0 0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>안녕하세요, {name}님</h1>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        {onBell && (
          <button onClick={onBell} aria-label="알림" style={{ width: 42, height: 42, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative', boxShadow: c.shadow }}>
            {window.FrXIcon ? <window.FrXIcon name="bell" size={20} color={c.text} sw={1.9} /> : null}
            <span style={{ position: 'absolute', top: 9, right: 10, width: 7, height: 7, borderRadius: 99, background: c.danger, border: `1.5px solid ${c.surface}` }} />
          </button>
        )}
        <FrAvatar name={name} size={compact ? 38 : 42} ring={c.border} />
      </div>
    </div>
  );
}

// ── AI recommended-course banner (premium) ────────────
// Solid green promo with white text — distinct from the lime accent pills.
function FrAIBanner({ c, dist = 7.4, mins = 43, vibe = '한적함', locked, onClick }) {
  return (
    <button onClick={onClick} style={{ position: 'relative', width: '100%', textAlign: 'left', overflow: 'hidden', border: 'none', cursor: 'pointer', borderRadius: 22, padding: '20px 20px 22px', background: 'linear-gradient(135deg, #3BC55E, #2BA94F)', boxShadow: '0 10px 26px rgba(43,169,79,0.32)', WebkitTapHighlightColor: 'transparent' }}>
      <span style={{ position: 'absolute', top: -30, right: -24, width: 152, height: 152, borderRadius: 999, background: 'rgba(255,255,255,0.14)' }} />
      <span style={{ position: 'absolute', bottom: -52, right: 36, width: 96, height: 96, borderRadius: 999, background: 'rgba(255,255,255,0.10)' }} />
      <div style={{ position: 'relative' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, background: 'rgba(255,255,255,0.22)', borderRadius: 999, padding: '5px 11px' }}>
          <FrCIcon name={locked ? 'lock' : 'sparkle'} size={13} color="#fff" sw={1.9} fill={locked ? 'none' : '#fff'} />
          <span style={{ fontFamily: HSF, fontSize: 11.5, fontWeight: 800, color: '#fff', letterSpacing: 0.2 }}>AI 추천 코스</span>
        </span>
        <div style={{ fontFamily: HSF, fontSize: 21, fontWeight: 700, color: '#fff', letterSpacing: -0.6, lineHeight: 1.3, marginTop: 13, textWrap: 'balance' }}>{locked ? <>날씨·체력 맞춤 AI 코스를<br />프리미엄에서 만나보세요</> : <>오늘 날씨에 딱 맞는<br />새 코스가 준비됐어요</>}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12 }}>
          <span style={{ fontFamily: HSF, fontSize: 13.5, fontWeight: 600, color: 'rgba(255,255,255,0.92)', letterSpacing: -0.2 }}>{locked ? '프리미엄으로 잠금 해제하기' : `${dist} km · 예상 ${mins}분 · ${vibe}`}</span>
          <span style={{ display: 'inline-flex', transform: 'rotate(-45deg)' }}><FrCIcon name="arrow" size={15} color="#fff" sw={2.4} /></span>
        </div>
      </div>
    </button>
  );
}

function FrFeedLabel({ c }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ fontFamily: HSF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap' }}>친구들의 러닝</span>
      <span style={{ width: 6, height: 6, borderRadius: 99, background: c.accent }} />
      <span style={{ fontFamily: HSF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>최근 활동</span>
    </div>
  );
}

Object.assign(window, { FrWeatherBanner, FrWeatherStrip, FrWeatherBubble, FrFeedTabs, FrRunCardA, FrRunCardB, FrTabBar, FrGreeting, FrFeedLabel, FrAIBanner, FrTag, FrAction, frPage });
