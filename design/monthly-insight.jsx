// FreshRun — Premium 월간 리포트 (detailed monthly insight, pushed screen).
// Tappable from the Premium Insight card on the 기록 tab. Rich logs runners care about.
const MIF = window.FR_FONT;

// months selectable in the report (matches the 기록 tab range)
const MI_MONTHS = [
  { label: '2024 · 6월', year: 2024, mn: 6, distKm: 42.8, sessions: 12, goalKm: 50 },
  { label: '2024 · 5월', year: 2024, mn: 5, distKm: 38.2, sessions: 11, goalKm: 45 },
  { label: '2024 · 4월', year: 2024, mn: 4, distKm: 36.4, sessions: 10, goalKm: 45 },
  { label: '2024 · 3월', year: 2024, mn: 3, distKm: 29.6, sessions: 8, goalKm: 40 },
];

const FR_INSIGHT = {
  month: '2024 · 5월', label: '5월',
  distKm: 42.8, goalKm: 60, sessions: 12, timeH: '6:42', timeSub: '총 운동 시간',
  pace: "5'18\"", paceDeltaSec: -6, elevM: 412, kcal: 3840, hrAvg: 158, hrMax: 184,
  vsLast: { dist: 12, pace: 2, sessions: 1 },
  weeks: [
    { wk: '1주', km: 8.2, pace: "5'26\"" },
    { wk: '2주', km: 12.4, pace: "5'20\"" },
    { wk: '3주', km: 9.6, pace: "5'17\"" },
    { wk: '4주', km: 12.6, pace: "5'11\"" },
  ],
  prs: [
    { label: '최고 5K', value: "24'38\"", sub: '5월 28일 · 한강', up: true },
    { label: '최장 거리', value: '10.0km', sub: '5월 12일 · 남산', up: true },
    { label: '최고 페이스', value: "4'46\"", sub: '5월 28일 인터벌', up: true },
    { label: '최장 러닝', value: '52:45', sub: '5월 12일 롱런', up: false },
  ],
  zones: [
    { name: 'Zone 5 · 최대', range: '171–188', pct: 8, tone: 0 },
    { name: 'Zone 4 · 고강도', range: '153–170', pct: 46, tone: 1 },
    { name: 'Zone 3 · 유산소', range: '135–152', pct: 34, tone: 2 },
    { name: 'Zone 2 · 지방연소', range: '117–134', pct: 12, tone: 3 },
  ],
  weekday: [
    ['월', 1], ['화', 3], ['수', 1], ['목', 2], ['금', 1], ['토', 3], ['일', 1],
  ],
  timeOfDay: '아침 (06–09시)', timeOfDayPct: 58,
  terrain: { flat: 68, hill: 32 },
  streak: 5, consistency: 86,
  coaching: '5월은 지구력이 눈에 띄게 좋아진 달이에요. 주간 거리를 꾸준히 늘리면서도 평균 페이스가 6초 빨라졌고, 4주 차에 최고 페이스를 경신했습니다. 고강도(Zone 4) 비중이 다소 높으니, 6월에는 회복 러닝을 한 세션 더 넣어 균형을 맞추는 걸 추천해요.',
  next: [
    ['target', '6월 목표', '월 50km · 회복 러닝 주 1회'],
    ['flame', '집중 포인트', 'Zone 2 유산소 비중 늘리기'],
    ['trending', '다음 도전', '5K 24분 벽 깨기'],
  ],
};

function FrMiMetric({ c, label, value, unit, delta, deltaGood }) {
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: '13px 14px', boxShadow: c.shadow }}>
      <div style={{ fontFamily: MIF, fontSize: 11, fontWeight: 600, letterSpacing: 0.2, color: c.faint, whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 3, marginTop: 8 }}>
        <span style={{ fontFamily: MIF, fontSize: 20, fontWeight: 800, letterSpacing: -0.5, color: c.text }}>{value}</span>
        {unit && <span style={{ fontFamily: MIF, fontSize: 11.5, fontWeight: 600, color: c.faint }}>{unit}</span>}
      </div>
      {delta != null && (
        <div style={{ fontFamily: MIF, fontSize: 11, fontWeight: 700, color: deltaGood ? grn : c.faint, marginTop: 5, letterSpacing: -0.2 }}>{delta}</div>
      )}
    </div>
  );
}

// weekly distance bars + pace line overlay
function FrWeeklyVolume({ c }) {
  const w = FR_INSIGHT.weeks, max = Math.max(...w.map(x => x.km));
  const grn = c.dark ? c.accent : '#34B85A';
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, height: 132, padding: '4px 2px 0' }}>
      {w.map((x, i) => {
        const h = Math.round((x.km / max) * 96) + 8;
        return (
          <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 7 }}>
            <span style={{ fontFamily: MIF, fontSize: 11.5, fontWeight: 700, color: c.text }}>{x.km}</span>
            <div style={{ width: '100%', maxWidth: 40, height: h, borderRadius: 9, background: i === w.length - 1 ? c.accent : c.accentDim, border: i === w.length - 1 ? 'none' : `1px solid ${c.accent}44` }} />
            <span style={{ fontFamily: MIF, fontSize: 11, color: c.faint }}>{x.wk}</span>
          </div>
        );
      })}
    </div>
  );
}

function FrZoneRow({ c, z }) {
  const col = (window.FR_ZONE_COLORS || ['#E0703D', '#2F8F3E', '#62C23A', '#9FDC6E'])[z.tone];
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <div style={{ width: 110, flexShrink: 0 }}>
        <div style={{ fontFamily: MIF, fontSize: 12.5, fontWeight: 700, color: c.text, letterSpacing: -0.2 }}>{z.name}</div>
        <div style={{ fontFamily: MIF, fontSize: 10.5, color: c.faint, marginTop: 1 }}>{z.range} bpm</div>
      </div>
      <div style={{ flex: 1, height: 9, borderRadius: 99, background: c.surfaceAlt, overflow: 'hidden' }}>
        <div style={{ width: z.pct + '%', height: '100%', borderRadius: 99, background: col }} />
      </div>
      <div style={{ fontFamily: MIF, fontSize: 12.5, fontWeight: 700, color: c.sub, width: 34, textAlign: 'right' }}>{z.pct}%</div>
    </div>
  );
}

function FrMiCard({ c, title, hint, children, action, onAction }) {
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <div style={{ padding: '24px 20px 0' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', padding: '0 2px 12px' }}>
        <h2 style={{ fontFamily: MIF, fontSize: 16.5, fontWeight: 800, letterSpacing: -0.4, color: c.text, margin: 0 }}>{title}</h2>
        {action && <span style={{ fontFamily: MIF, fontSize: 12, fontWeight: 600, color: grn, letterSpacing: -0.2 }}>{action}</span>}
      </div>
      <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 16, boxShadow: c.shadow }}>{children}</div>
      {hint && <div style={{ fontFamily: MIF, fontSize: 11.5, color: c.faint, letterSpacing: -0.2, padding: '9px 6px 0', lineHeight: 1.5 }}>{hint}</div>}
    </div>
  );
}

function FrMonthlyInsight({ c, app }) {
  const nav = app.nav;
  const [idx, setIdx] = React.useState(0);
  const m = MI_MONTHS[idx];
  const d = { ...FR_INSIGHT, distKm: m.distKm, sessions: m.sessions, goalKm: m.goalKm };
  const grn = c.dark ? c.accent : '#3F8E14';
  const goalPct = Math.min(100, Math.round((d.distKm / d.goalKm) * 100));
  const R = 46, CIRC = 2 * Math.PI * R;
  const wdMax = Math.max(...d.weekday.map(x => x[1]));
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="월간 리포트" onBack={() => nav.pop()} right={<button onClick={() => nav.push('share')} style={{ background: 'none', border: 'none', padding: 6, cursor: 'pointer' }}><FrXIcon name="share" size={19} color={c.text} sw={1.9} /></button>} />
      {/* month stepper — same control as the 기록 tab */}
      <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px 14px', borderBottom: `1px solid ${c.border}` }}>
        <button onClick={() => setIdx(i => Math.min(MI_MONTHS.length - 1, i + 1))} disabled={idx >= MI_MONTHS.length - 1} style={{ width: 34, height: 34, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: idx >= MI_MONTHS.length - 1 ? 'default' : 'pointer', opacity: idx >= MI_MONTHS.length - 1 ? 0.4 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrCIcon name="back" size={18} color={c.text} sw={2.2} />
        </button>
        <button onClick={() => nav.push('monthPicker', { year: m.year, month: m.mn, enabled: MI_MONTHS.map(e => `${e.year}-${e.mn}`), onSelect: (y, mm) => { const j = MI_MONTHS.findIndex(e => e.year === y && e.mn === mm); if (j >= 0) setIdx(j); } })} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', padding: '4px 6px', WebkitTapHighlightColor: 'transparent' }}>
          <span style={{ fontFamily: MIF, fontSize: 16, fontWeight: 800, color: c.text, letterSpacing: -0.4 }}>{m.label}</span>
          <FrCIcon name="chevdown" size={16} color={c.sub} sw={2.2} />
        </button>
        <button onClick={() => setIdx(i => Math.max(0, i - 1))} disabled={idx <= 0} style={{ width: 34, height: 34, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: idx <= 0 ? 'default' : 'pointer', opacity: idx <= 0 ? 0.4 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', transform: 'scaleX(-1)' }}>
          <FrCIcon name="back" size={18} color={c.text} sw={2.2} />
        </button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', paddingBottom: 30 }}>

        {/* hero: goal ring + distance + premium tag */}
        <div style={{ padding: '16px 20px 0' }}>
          <div style={{ position: 'relative', overflow: 'hidden', background: c.dark ? '#11150E' : c.text, border: c.dark ? `1px solid ${c.border}` : 'none', borderRadius: 22, padding: '20px 20px 22px' }}>
            <div style={{ position: 'absolute', top: -40, right: -40, width: 150, height: 150, borderRadius: 999, background: c.accent, opacity: 0.16 }} />
            <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 18 }}>
              <div style={{ position: 'relative', width: 108, height: 108, flexShrink: 0 }}>
                <svg width="108" height="108" viewBox="0 0 108 108" style={{ transform: 'rotate(-90deg)' }}>
                  <circle cx="54" cy="54" r={R} fill="none" stroke="rgba(255,255,255,0.16)" strokeWidth="9" />
                  <circle cx="54" cy="54" r={R} fill="none" stroke={c.accent} strokeWidth="9" strokeLinecap="round" strokeDasharray={CIRC} strokeDashoffset={CIRC * (1 - goalPct / 100)} />
                </svg>
                <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ fontFamily: MIF, fontSize: 22, fontWeight: 800, color: '#fff', letterSpacing: -0.6, lineHeight: 1 }}>{goalPct}%</span>
                  <span style={{ fontFamily: MIF, fontSize: 10, color: 'rgba(255,255,255,0.6)', marginTop: 3 }}>월 목표</span>
                </div>
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'rgba(255,255,255,0.12)', borderRadius: 999, padding: '3px 9px', marginBottom: 8 }}>
                  <FrCIcon name="sparkle" size={11} color={c.accent} sw={2} />
                  <span style={{ fontFamily: MIF, fontSize: 10, fontWeight: 700, color: c.accent, letterSpacing: 0.3, textTransform: 'uppercase' }}>{d.month} 리포트</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
                  <span style={{ fontFamily: MIF, fontSize: 34, fontWeight: 800, color: '#fff', letterSpacing: -1.2 }}>{d.distKm}</span>
                  <span style={{ fontFamily: MIF, fontSize: 15, fontWeight: 700, color: 'rgba(255,255,255,0.55)' }}>/ {d.goalKm}km</span>
                </div>
                <div style={{ fontFamily: MIF, fontSize: 12.5, color: 'rgba(255,255,255,0.7)', letterSpacing: -0.2, marginTop: 5 }}>지난달 대비 <b style={{ color: c.accent }}>+{d.vsLast.dist}%</b> · 목표까지 {(d.goalKm - d.distKm).toFixed(1)}km</div>
              </div>
            </div>
          </div>
        </div>

        {/* key metrics grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, padding: '14px 20px 0' }}>
          <FrMiMetric c={c} label="러닝 횟수" value={d.sessions} unit="회" delta={`+${d.vsLast.sessions}회`} deltaGood />
          <FrMiMetric c={c} label="총 시간" value={d.timeH} delta="6:42:18" />
          <FrMiMetric c={c} label="평균 페이스" value={d.pace} unit="/km" delta={`${d.paceDeltaSec}s 빨라짐`} deltaGood />
          <FrMiMetric c={c} label="누적 고도" value={d.elevM} unit="m" delta="언덕 4회" />
          <FrMiMetric c={c} label="소모 칼로리" value={d.kcal.toLocaleString()} unit="kcal" />
          <FrMiMetric c={c} label="평균 심박" value={d.hrAvg} unit="bpm" delta={`최대 ${d.hrMax}`} />
        </div>

        {/* personal records */}
        <FrMiCard c={c} title="이번 달 개인 기록" hint="이번 달 기록한 최고 성과예요. 화살표는 자기 기록 경신을 뜻해요.">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {d.prs.map((p, i) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ fontFamily: MIF, fontSize: 11.5, fontWeight: 600, color: c.faint, letterSpacing: -0.2 }}>{p.label}</span>
                  {p.up && <FrXIcon name="trending" size={12} color={grn} sw={2.4} />}
                </div>
                <span style={{ fontFamily: MIF, fontSize: 20, fontWeight: 800, color: c.text, letterSpacing: -0.6 }}>{p.value}</span>
                <span style={{ fontFamily: MIF, fontSize: 11, color: c.faint, letterSpacing: -0.2 }}>{p.sub}</span>
              </div>
            ))}
          </div>
        </FrMiCard>

        {/* weekly volume */}
        <FrMiCard c={c} title="주간 거리" hint={`4주 동안 꾸준히 늘었어요. 마지막 주가 가장 길었습니다 (${d.weeks[3].km}km).`}>
          <FrWeeklyVolume c={c} />
        </FrMiCard>

        {/* pace progression */}
        <FrMiCard c={c} title="주간 페이스 추이">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
            {d.weeks.map((x, i) => {
              const secs = x.pace.match(/(\d+)'(\d+)/);
              const tot = +secs[1] * 60 + +secs[2];
              const all = d.weeks.map(w => { const m = w.pace.match(/(\d+)'(\d+)/); return +m[1] * 60 + +m[2]; });
              const min = Math.min(...all), max = Math.max(...all);
              const pct = 30 + (1 - (tot - min) / (max - min || 1)) * 70;
              return (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ width: 34, fontFamily: MIF, fontSize: 12, fontWeight: 600, color: c.faint }}>{x.wk}</span>
                  <div style={{ flex: 1, height: 9, borderRadius: 99, background: c.surfaceAlt, overflow: 'hidden' }}>
                    <div style={{ width: pct + '%', height: '100%', borderRadius: 99, background: i === 3 ? c.accent : `${c.accent}99` }} />
                  </div>
                  <span style={{ width: 50, textAlign: 'right', fontFamily: MIF, fontSize: 12.5, fontWeight: 700, color: i === 3 ? grn : c.sub }}>{x.pace}</span>
                </div>
              );
            })}
          </div>
        </FrMiCard>

        {/* running patterns */}
        <FrMiCard c={c} title="러닝 패턴">
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 84 }}>
            {d.weekday.map(([day, n], i) => {
              const h = Math.round((n / wdMax) * 56) + 6;
              const peak = n === wdMax;
              return (
                <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
                  <div style={{ width: '100%', maxWidth: 26, height: h, borderRadius: 7, background: peak ? c.accent : c.accentDim }} />
                  <span style={{ fontFamily: MIF, fontSize: 11, fontWeight: peak ? 700 : 500, color: peak ? c.text : c.faint }}>{day}</span>
                </div>
              );
            })}
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 16, paddingTop: 15, borderTop: `1px solid ${c.border}` }}>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 9 }}>
              <span style={{ width: 34, height: 34, borderRadius: 10, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}><FrCIcon name="sparkle" size={16} color={grn} sw={1.9} /></span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontFamily: MIF, fontSize: 10.5, color: c.faint, fontWeight: 600 }}>주 활동 시간</div>
                <div style={{ fontFamily: MIF, fontSize: 13, fontWeight: 700, color: c.text, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{d.timeOfDay}</div>
              </div>
            </div>
            <div style={{ width: 1, background: c.border }} />
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 9 }}>
              <span style={{ width: 34, height: 34, borderRadius: 10, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}><FrXIcon name="flame" size={16} color={grn} sw={1.9} /></span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontFamily: MIF, fontSize: 10.5, color: c.faint, fontWeight: 600 }}>연속 러닝</div>
                <div style={{ fontFamily: MIF, fontSize: 13, fontWeight: 700, color: c.text, letterSpacing: -0.2 }}>{d.streak}일 · 일관성 {d.consistency}%</div>
              </div>
            </div>
          </div>
        </FrMiCard>

        {/* HR zone distribution */}
        <FrMiCard c={c} title="심박 구간 분포" hint="고강도(Zone 4) 비중이 높아요. 회복 러닝으로 Zone 2를 늘리면 부상 위험이 줄어요.">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {d.zones.map((z, i) => <FrZoneRow key={i} c={c} z={z} />)}
          </div>
        </FrMiCard>

        {/* terrain split */}
        <FrMiCard c={c} title="지형 분석">
          <div style={{ display: 'flex', height: 14, borderRadius: 99, overflow: 'hidden', gap: 3 }}>
            <div style={{ width: d.terrain.flat + '%', background: c.accent, borderRadius: '99px 0 0 99px' }} />
            <div style={{ width: d.terrain.hill + '%', background: c.accentDim, border: `1px solid ${c.accent}55`, borderRadius: '0 99px 99px 0' }} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10 }}>
            <span style={{ fontFamily: MIF, fontSize: 12.5, fontWeight: 700, color: c.text }}>평지 {d.terrain.flat}%</span>
            <span style={{ fontFamily: MIF, fontSize: 12.5, fontWeight: 700, color: c.sub }}>언덕 {d.terrain.hill}%</span>
          </div>
        </FrMiCard>

        {/* AI coaching summary */}
        <div style={{ padding: '24px 20px 0' }}>
          <div style={{ background: c.accentDim, border: `1px solid ${c.accent}44`, borderRadius: 18, padding: 17 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 10 }}>
              <FrCIcon name="sparkle" size={16} color={grn} sw={2} />
              <span style={{ fontFamily: MIF, fontSize: 12, fontWeight: 800, letterSpacing: 0.3, color: grn, textTransform: 'uppercase' }}>AI 코칭 요약</span>
            </div>
            <p style={{ fontFamily: MIF, fontSize: 13.5, lineHeight: 1.65, color: c.dark ? c.text : '#274417', letterSpacing: -0.2, margin: 0, textWrap: 'pretty' }}>{d.coaching}</p>
          </div>
        </div>

        {/* next month plan */}
        <FrMiCard c={c} title="6월 추천 플랜">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {d.next.map(([ic, t, body], i) => (
              <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <span style={{ width: 38, height: 38, borderRadius: 11, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}><FrXIcon name={ic} size={18} color={grn} sw={1.9} /></span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontFamily: MIF, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>{t}</div>
                  <div style={{ fontFamily: MIF, fontSize: 12.5, color: c.sub, letterSpacing: -0.2, marginTop: 2 }}>{body}</div>
                </div>
              </div>
            ))}
          </div>
        </FrMiCard>

      </div>
    </div>
  );
}

Object.assign(window, { FrMonthlyInsight, FR_INSIGHT });
