// FreshRun — Weather Detail (pushed modal): AI running index + air-quality breakdown.
const WDF = window.FR_FONT;

function FrIndexGauge({ c, score }) {
  const grn = c.dark ? c.accent : '#3F8E14';
  const R = 52, CIRC = 2 * Math.PI * R, frac = score / 100;
  return (
    <div style={{ position: 'relative', width: 132, height: 132 }}>
      <svg width="132" height="132" viewBox="0 0 132 132" style={{ transform: 'rotate(-90deg)' }}>
        <circle cx="66" cy="66" r={R} fill="none" stroke={c.surfaceAlt} strokeWidth="11" />
        <circle cx="66" cy="66" r={R} fill="none" stroke={c.accent} strokeWidth="11" strokeLinecap="round" strokeDasharray={CIRC} strokeDashoffset={CIRC * (1 - frac)} />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ fontFamily: WDF, fontSize: 34, fontWeight: 700, letterSpacing: -1.5, color: c.text, lineHeight: 1 }}>{score}</span>
        <span style={{ fontFamily: WDF, fontSize: 11, fontWeight: 600, color: c.faint, marginTop: 2 }}>/ 100</span>
      </div>
    </div>
  );
}

function FrWxTile({ c, icon, label, value, sub, tone }) {
  return (
    <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: '13px 14px', boxShadow: c.shadow }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {icon}
        <span style={{ fontFamily: WDF, fontSize: 12, fontWeight: 600, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{label}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 9 }}>
        <span style={{ fontFamily: WDF, fontSize: 19, fontWeight: 700, letterSpacing: -0.5, color: c.text }}>{value}</span>
        {sub && <span style={{ fontFamily: WDF, fontSize: 12, fontWeight: 700, color: tone || c.faint }}>{sub}</span>}
      </div>
    </div>
  );
}

function FrWeatherDetail({ c, app }) {
  const nav = app.nav;
  const w = FR_WEATHER;
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="날씨 상세 분석" onClose={() => nav.pop()} right={<button onClick={() => nav.push('share')} style={{ background: 'none', border: 'none', padding: 6, cursor: 'pointer' }}><FrXIcon name="share" size={19} color={c.text} sw={1.9} /></button>} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', display: 'flex', flexDirection: 'column' }}>
        {/* hero condition */}
        <div style={{ textAlign: 'center', padding: '20px 20px 4px' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: c.accentDim, border: `1px solid ${c.accent}44`, borderRadius: 999, padding: '6px 14px' }}>
            <span style={{ width: 7, height: 7, borderRadius: 99, background: c.accent }} />
            <span style={{ fontFamily: WDF, fontSize: 12, fontWeight: 700, letterSpacing: 0.2, color: grn, textTransform: 'uppercase' }}>러닝하기 딱 좋아요</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 14, marginTop: 16 }}>
            <span style={{ fontFamily: WDF, fontSize: 62, fontWeight: 300, letterSpacing: -3, color: c.text, lineHeight: 1 }}>{w.temp}°</span>
            <FrIcon name="sun" size={48} color="#E8A23D" sw={1.6} />
          </div>
          <div style={{ fontFamily: WDF, fontSize: 14.5, color: c.sub, letterSpacing: -0.3, marginTop: 10 }}>{w.condition} · 체감 {w.feels}° · 서울 {w.area}</div>
        </div>

        {/* AI running index */}
        <div style={{ padding: '20px 20px 0' }}>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 20, padding: 18, boxShadow: c.shadow, display: 'flex', alignItems: 'center', gap: 16 }}>
            <FrIndexGauge c={c} score={92} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <FrCIcon name="sparkle" size={15} color={grn} sw={2} />
                <span style={{ fontFamily: WDF, fontSize: 12.5, fontWeight: 700, letterSpacing: 0.2, color: grn, textTransform: 'uppercase' }}>AI 러닝 지수</span>
              </div>
              <div style={{ fontFamily: WDF, fontSize: 18, fontWeight: 700, letterSpacing: -0.5, color: c.text, marginTop: 6 }}>최적의 컨디션</div>
              <p style={{ fontFamily: WDF, fontSize: 12.5, lineHeight: 1.5, color: c.sub, letterSpacing: -0.2, margin: '6px 0 0', textWrap: 'pretty' }}>기온과 습도가 러닝에 매우 이상적이에요. 가볍게 한 바퀴 돌기 좋은 날입니다.</p>
            </div>
          </div>
        </div>

        {/* air quality / metrics grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 11, padding: '16px 20px 0' }}>
          <FrWxTile c={c} icon={<FrIcon name="droplet" size={15} color={c.faint} sw={1.9} />} label="습도" value={`${w.humidity}%`} />
          <FrWxTile c={c} icon={<FrIcon name="haze" size={15} color={c.faint} sw={1.9} />} label="미세먼지 (AQI)" value={w.pm10.v} sub={w.pm10.label} tone={FR_AQI_COLOR[w.pm10.label]} />
          <FrWxTile c={c} icon={<FrIcon name="haze" size={15} color={c.faint} sw={1.9} />} label="초미세 PM2.5" value={`${w.pm25.v}`} sub={w.pm25.label} tone={FR_AQI_COLOR[w.pm25.label]} />
          <FrWxTile c={c} icon={<FrIcon name="wind" size={15} color={c.faint} sw={1.9} />} label="바람" value={`${w.wind}`} sub="㎧" tone={c.faint} />
          <FrWxTile c={c} icon={<FrIcon name="sun" size={15} color={c.faint} sw={1.9} />} label="자외선" value={w.uv.label} sub={`지수 ${w.uv.v}`} tone={c.faint} />
          <FrWxTile c={c} icon={<FrXIcon name="cloud" size={15} color={c.faint} sw={1.9} />} label="강수확률" value={`${w.rain}%`} />
        </div>

        {/* AI advice */}
        <div style={{ padding: '16px 20px 0' }}>
          <div style={{ display: 'flex', gap: 12, background: '#3D8BFF14', border: '1px solid #3D8BFF33', borderRadius: 16, padding: 15 }}>
            <span style={{ flexShrink: 0, width: 36, height: 36, borderRadius: 11, background: '#3D8BFF22', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FrCIcon name="sparkle" size={18} color="#3D8BFF" sw={1.9} />
            </span>
            <div>
              <div style={{ fontFamily: WDF, fontSize: 12, fontWeight: 700, letterSpacing: 0.3, color: '#3D8BFF', textTransform: 'uppercase' }}>AI 조언</div>
              <p style={{ fontFamily: WDF, fontSize: 13.5, lineHeight: 1.55, color: c.text, letterSpacing: -0.2, margin: '5px 0 0', textWrap: 'pretty' }}>미세먼지가 적고 바람이 시원해요. 한강변 5km 러닝은 어떠세요?</p>
            </div>
          </div>
        </div>

        <div style={{ flex: 1 }} />
        <div style={{ padding: '18px 20px 26px' }}>
          <button onClick={() => { nav.pop(); nav.push('tracking'); }} style={{ width: '100%', height: 56, borderRadius: 16, border: 'none', background: c.accent, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9, boxShadow: `0 6px 18px ${c.accent}55` }}>
            <FrCIcon name="play" size={18} color={c.accentText} />
            <span style={{ fontFamily: WDF, fontSize: 16, fontWeight: 700, letterSpacing: -0.3, color: c.accentText }}>러닝 시작하기</span>
          </button>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { FrWeatherDetail, FrIndexGauge });
