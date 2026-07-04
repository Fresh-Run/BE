// FreshRun — Activity Detail (pushed screen): stat tiles, pace+elevation chart,
// heart-rate zones, AI performance insight, recovery advice.
const ADF = window.FR_FONT;

// pace+elevation chart. paces = sec/km (lower = faster), elev = m gain per km.
function FrPaceChart({ c, paces, elev }) {
  const W = 320, H = 150, padL = 6, padR = 6, padT = 12, padB = 22;
  const n = paces.length;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const bw = innerW / n;
  const pMin = Math.min(...paces), pMax = Math.max(...paces);
  const pRange = Math.max(1, pMax - pMin);
  // bar height: faster (lower sec) → taller. Normalize 0.35..1
  const barH = (p) => { const fast = 1 - (p - pMin) / pRange; return innerH * (0.4 + fast * 0.6); };
  const eMax = Math.max(...elev, 1);
  const ePts = elev.map((e, i) => [padL + bw * (i + 0.5), padT + innerH - (e / eMax) * innerH * 0.72]);
  let eD = '';
  ePts.forEach((p, i) => {
    if (i === 0) { eD = `M ${p[0].toFixed(1)} ${p[1].toFixed(1)}`; return; }
    const prev = ePts[i - 1];
    const mx = (prev[0] + p[0]) / 2;
    eD += ` C ${mx.toFixed(1)} ${prev[1].toFixed(1)}, ${mx.toFixed(1)} ${p[1].toFixed(1)}, ${p[0].toFixed(1)} ${p[1].toFixed(1)}`;
  });
  const accent = c.dark ? c.accent : '#5FBF26';
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{ overflow: 'visible' }}>
        {/* gridlines */}
        {[0.25, 0.5, 0.75].map((g) => (
          <line key={g} x1={padL} y1={padT + innerH * g} x2={W - padR} y2={padT + innerH * g} stroke={c.border} strokeWidth="1" strokeDasharray="2 6" />
        ))}
        {/* pace bars */}
        {paces.map((p, i) => {
          const h = barH(p), x = padL + bw * i + bw * 0.16, w = bw * 0.68, y = padT + innerH - h;
          return <rect key={i} x={x} y={y} width={w} height={h} rx={Math.min(6, w / 2)} fill={accent} opacity={0.5 + 0.5 * (1 - (p - pMin) / pRange)} />;
        })}
        {/* elevation line */}
        <path d={eD} fill="none" stroke={c.faint} strokeWidth="2.2" strokeDasharray="5 4" strokeLinecap="round" />
        {ePts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r="2.4" fill={c.sub} />)}
        {/* x labels */}
        {paces.map((p, i) => (
          <text key={i} x={padL + bw * (i + 0.5)} y={H - 6} textAnchor="middle" fontFamily={ADF} fontSize="10" fontWeight="600" fill={c.faint}>{i + 1}km</text>
        ))}
      </svg>
      <div style={{ display: 'flex', gap: 16, marginTop: 6, paddingLeft: 2 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: ADF, fontSize: 12, color: c.sub, fontWeight: 600 }}>
          <span style={{ width: 11, height: 11, borderRadius: 3, background: accent }} /> 페이스
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: ADF, fontSize: 12, color: c.sub, fontWeight: 600 }}>
          <span style={{ width: 14, height: 0, borderTop: `2.2px dashed ${c.faint}` }} /> 고도
        </span>
      </div>
    </div>
  );
}

function FrZoneBar({ c, z, maxSec }) {
  const pct = Math.round((z.sec / maxSec) * 100);
  const col = FR_ZONE_COLORS[z.tone];
  const m = Math.floor(z.sec / 60), s = z.sec % 60;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <div style={{ width: 116, flexShrink: 0 }}>
        <div style={{ fontFamily: ADF, fontSize: 13, fontWeight: 700, color: c.text, letterSpacing: -0.2 }}>{z.name}</div>
        <div style={{ fontFamily: ADF, fontSize: 11, color: c.faint, marginTop: 1 }}>{z.range} bpm</div>
      </div>
      <div style={{ flex: 1, height: 9, borderRadius: 99, background: c.surfaceAlt, overflow: 'hidden' }}>
        <div style={{ width: Math.max(4, pct) + '%', height: '100%', borderRadius: 99, background: col }} />
      </div>
      <div style={{ fontFamily: ADF, fontSize: 12.5, fontWeight: 700, color: c.sub, width: 46, textAlign: 'right', flexShrink: 0 }}>{m}:{String(s).padStart(2, '0')}</div>
    </div>
  );
}

function FrDetailStat({ c, label, value, unit, icon }) {
  return (
    <div style={{ flex: 1, minWidth: 0, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: '13px 14px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        {icon}
        <span style={{ fontFamily: ADF, fontSize: 11, fontWeight: 600, letterSpacing: 0.2, color: c.faint, textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{label}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 3, marginTop: 7 }}>
        <span style={{ fontFamily: ADF, fontSize: 21, fontWeight: 700, letterSpacing: -0.6, color: c.text }}>{value}</span>
        {unit && <span style={{ fontFamily: ADF, fontSize: 12, color: c.faint, fontWeight: 600 }}>{unit}</span>}
      </div>
    </div>
  );
}

function FrActivityDetail({ c, app, params }) {
  const nav = app.nav;
  const a = (params && params.act) || FR_ACTS[0];
  const units = (app && app.units) || 'km';
  const dist = units === 'mi' ? (a.dist * 0.621371).toFixed(2) : a.dist.toFixed(2);
  const distU = units === 'mi' ? 'mi' : 'km';
  const zMax = Math.max(...a.zones.map(z => z.sec));
  const grn = c.dark ? c.accent : '#3F8E14';
  const saved = !!(app.savedRuns && app.savedRuns.some(r => r.id === a.id));
  const canSave = a.fresh && !saved;
  const onSave = () => { app.saveRun && app.saveRun(a); nav.setTab('log'); };
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="활동 상세" onBack={() => nav.pop()} right={<button onClick={() => nav.push('runShare', { run: a })} style={{ background: 'none', border: 'none', padding: 6, cursor: 'pointer' }}><FrXIcon name="share" size={19} color={c.text} sw={1.9} /></button>} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        <FrMiniMap seed={a.seed} width="100%" height={190} radius={0} hero />
        <div style={{ padding: '18px 20px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{ width: 8, height: 8, borderRadius: 99, background: grn }} />
            <span style={{ fontFamily: ADF, fontSize: 12.5, fontWeight: 600, color: c.sub, letterSpacing: -0.2 }}>{a.when}</span>
          </div>
          <h1 style={{ fontFamily: ADF, fontSize: 23, fontWeight: 700, letterSpacing: -0.7, color: c.text, margin: '8px 0 0' }}>{a.title}</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 6 }}>
            <FrIcon name="pin" size={14} color={c.faint} sw={1.9} />
            <span style={{ fontFamily: ADF, fontSize: 13, color: c.faint, letterSpacing: -0.2 }}>{a.area}</span>
          </div>
        </div>

        {/* stat grid */}
        <div style={{ display: 'flex', gap: 10, padding: '16px 20px 0' }}>
          <FrDetailStat c={c} label="거리" value={dist} unit={distU} icon={<FrIcon name="pin" size={13} color={grn} sw={2} />} />
          <FrDetailStat c={c} label="시간" value={a.dur} icon={<FrIcon name="clock" size={13} color={c.faint} sw={1.9} />} />
        </div>
        <div style={{ display: 'flex', gap: 10, padding: '10px 20px 0' }}>
          <FrDetailStat c={c} label="평균 페이스" value={a.pace} icon={<FrXIcon name="pace" size={13} color={c.faint} sw={1.9} />} />
          <FrDetailStat c={c} label="소모 칼로리" value={a.kcal} unit="kcal" icon={<FrXIcon name="flame" size={13} color="#E0703D" sw={1.9} />} />
        </div>

        {/* AI insight */}
        <div style={{ padding: '16px 20px 0' }}>
          <div style={{ background: c.accentDim, border: `1px solid ${c.accent}44`, borderRadius: 16, padding: 15 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 8 }}>
              <FrCIcon name="sparkle" size={15} color={grn} sw={2} />
              <span style={{ fontFamily: ADF, fontSize: 12, fontWeight: 700, letterSpacing: 0.3, color: grn, textTransform: 'uppercase' }}>AI Performance Insight</span>
            </div>
            <p style={{ fontFamily: ADF, fontSize: 13.5, lineHeight: 1.6, color: c.dark ? c.text : '#274417', letterSpacing: -0.2, margin: 0, textWrap: 'pretty' }}>{a.insight}</p>
          </div>
        </div>

        {/* pace + elevation chart */}
        <div style={{ padding: '24px 20px 0' }}>
          <FrSectionTitle c={c}>페이스 &amp; 고도 분석</FrSectionTitle>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: '16px 14px 12px', marginTop: 12, boxShadow: c.shadow }}>
            <FrPaceChart c={c} paces={a.splits} elev={a.elev} />
          </div>
        </div>

        {/* HR zones */}
        <div style={{ padding: '24px 20px 0' }}>
          <FrSectionTitle c={c}>심박수 구간</FrSectionTitle>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 16, marginTop: 12, boxShadow: c.shadow, display: 'flex', flexDirection: 'column', gap: 15 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', paddingBottom: 4 }}>
              <span style={{ fontFamily: ADF, fontSize: 13, color: c.sub, fontWeight: 600 }}>평균 {a.hrAvg} bpm</span>
              <span style={{ fontFamily: ADF, fontSize: 13, color: c.sub, fontWeight: 600 }}>최대 {a.hrMax} bpm</span>
            </div>
            {a.zones.map((z, i) => <FrZoneBar key={i} c={c} z={z} maxSec={zMax} />)}
          </div>
        </div>

        {/* recovery advice */}
        <div style={{ padding: '18px 20px 30px' }}>
          <div style={{ display: 'flex', gap: 12, background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: 16, padding: 15 }}>
            <span style={{ flexShrink: 0, width: 34, height: 34, borderRadius: 11, background: c.surface, border: `1px solid ${c.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FrCIcon name="leaf" size={18} color={grn} sw={1.9} />
            </span>
            <div>
              <div style={{ fontFamily: ADF, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>회복 조언</div>
              <p style={{ fontFamily: ADF, fontSize: 13, lineHeight: 1.55, color: c.sub, letterSpacing: -0.2, margin: '5px 0 0', textWrap: 'pretty' }}>{a.recovery}</p>
            </div>
          </div>
        </div>
      </div>
      {canSave && (
        <div style={{ flexShrink: 0, padding: '12px 20px 26px', borderTop: `1px solid ${c.border}`, background: c.bg }}>
          <button onClick={onSave} style={{ width: '100%', height: 56, borderRadius: 16, border: 'none', background: c.accent, color: c.accentText, fontFamily: ADF, fontSize: 16.5, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9, boxShadow: `0 6px 18px ${c.accent}55` }}>
            <FrCheck color={c.accentText} w={20} /> 기록 저장하기
          </button>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { FrActivityDetail, FrPaceChart, FrZoneBar });
