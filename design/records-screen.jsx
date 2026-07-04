// FreshRun — 기록 (Records) tab: monthly stats, premium AI insight, activity history.
// Shared activity dataset (FR_ACTS) is also consumed by Activity Detail.
const RF = window.FR_FONT;

// ── activity dataset ───────────────────────────────────
// splits = per-km pace in seconds; elev = per-km elevation gain sample (m)
function frPaceStr(sec) { const m = Math.floor(sec / 60), s = Math.round(sec % 60); return `${m}'${String(s).padStart(2, '0')}"`; }

const FR_ACTS = [
  {
    id: 'a1', title: '한강 야경 러닝', area: '뚝섬한강공원', date: '오늘', when: '오늘 · 05:24', dayLabel: 'Today', month: '6월',
    dist: 5.20, dur: '26:14', durSec: 1574, pace: "5'02\"", paceSec: 302, kcal: 312, hrAvg: 162, hrMax: 178, elevGain: 24,
    seed: 'me-hangang-night-1', tags: ['야경', '평지'], best: true,
    splits: [318, 312, 306, 296, 288], elev: [4, 7, 5, 3, 5],
    zones: [
      { name: 'Zone 5 · 최대', range: '171–188', sec: 135, tone: 0 },
      { name: 'Zone 4 · 고강도', range: '153–170', sec: 930, tone: 1 },
      { name: 'Zone 3 · 유산소', range: '135–152', sec: 552, tone: 2 },
      { name: 'Zone 2 · 지방연소', range: '117–134', sec: 108, tone: 3 },
    ],
    insight: '초반 페이스를 잘 조절했고, 후반 1km 구간에서 케이던스가 5% 향상됐어요. 네거티브 스플릿이 완벽했습니다.',
    recovery: '고강도 구간이 많았어요. 가벼운 스트레칭과 충분한 수분 섭취를 권장하며, 다음 러닝까지 24시간 휴식을 추천해요.',
  },
  {
    id: 'a2', title: '강남 저녁 시티런', area: '강남구청 인근', date: '어제', when: '어제 · 20:45', dayLabel: 'Yesterday', month: '6월',
    dist: 3.45, dur: '18:30', durSec: 1110, pace: "5'22\"", paceSec: 322, kcal: 208, hrAvg: 158, hrMax: 172, elevGain: 12,
    seed: 'me-gangnam-evening', tags: ['도심', '평지'],
    splits: [330, 326, 318, 314], elev: [3, 2, 4, 3],
    zones: [
      { name: 'Zone 5 · 최대', range: '171–188', sec: 60, tone: 0 },
      { name: 'Zone 4 · 고강도', range: '153–170', sec: 540, tone: 1 },
      { name: 'Zone 3 · 유산소', range: '135–152', sec: 420, tone: 2 },
      { name: 'Zone 2 · 지방연소', range: '117–134', sec: 90, tone: 3 },
    ],
    insight: '꾸준한 페이스로 안정적인 러닝이었어요. 신호 대기 구간을 제외하면 페이스 편차가 거의 없었습니다.',
    recovery: '중강도 러닝이었어요. 가벼운 폼롤러 마사지로 마무리하면 좋아요.',
  },
  {
    id: 'a3', title: '주말 롱런', area: '남산 둘레길', date: '5월 12일', when: '5월 12일 · 07:15', dayLabel: 'May 12', month: '5월',
    dist: 10.02, dur: '52:45', durSec: 3165, pace: "5'15\"", paceSec: 315, kcal: 640, hrAvg: 165, hrMax: 181, elevGain: 86,
    seed: 'me-namsan-long', tags: ['언덕', '롱런'],
    splits: [300, 308, 322, 330, 318, 312, 320, 326, 314, 305], elev: [6, 12, 18, 14, 8, 6, 10, 16, 9, 5],
    zones: [
      { name: 'Zone 5 · 최대', range: '171–188', sec: 320, tone: 0 },
      { name: 'Zone 4 · 고강도', range: '153–170', sec: 1680, tone: 1 },
      { name: 'Zone 3 · 유산소', range: '135–152', sec: 980, tone: 2 },
      { name: 'Zone 2 · 지방연소', range: '117–134', sec: 185, tone: 3 },
    ],
    insight: '언덕 구간에서 페이스를 잘 유지했어요. 누적 고도 86m를 소화한 의미 있는 롱런입니다.',
    recovery: '장거리 + 언덕 러닝이라 근피로가 누적됐어요. 48시간 회복과 단백질 보충을 추천해요.',
  },
  {
    id: 'a4', title: '리커버리 조깅', area: '성수동 골목길', date: '5월 10일', when: '5월 10일 · 18:30', dayLabel: 'May 10', month: '5월',
    dist: 2.10, dur: '12:20', durSec: 740, pace: "5'52\"", paceSec: 352, kcal: 126, hrAvg: 142, hrMax: 154, elevGain: 6,
    seed: 'me-seongsu-recovery', tags: ['회복', '평지'],
    splits: [356, 352, 348], elev: [2, 3, 2],
    zones: [
      { name: 'Zone 5 · 최대', range: '171–188', sec: 0, tone: 0 },
      { name: 'Zone 4 · 고강도', range: '153–170', sec: 80, tone: 1 },
      { name: 'Zone 3 · 유산소', range: '135–152', sec: 480, tone: 2 },
      { name: 'Zone 2 · 지방연소', range: '117–134', sec: 180, tone: 3 },
    ],
    insight: '심박수를 낮게 유지한 좋은 회복 러닝이에요. 다음 고강도 세션을 위한 완벽한 마무리입니다.',
    recovery: '회복 러닝이라 별도 휴식은 필요 없어요. 가벼운 스트레칭으로 충분합니다.',
  },
  {
    id: 'a5', title: '벚꽃 강변 러닝', area: '여의도 한강공원', date: '4월 21일', when: '4월 21일 · 08:10', dayLabel: 'Apr 21', month: '4월',
    dist: 6.40, dur: '34:08', durSec: 2048, pace: "5'20\"", paceSec: 320, kcal: 388, hrAvg: 156, hrMax: 170, elevGain: 14,
    seed: 'me-yeouido-blossom', tags: ['경치', '평지'],
    splits: [330, 324, 318, 316, 320, 312], elev: [3, 4, 2, 3, 4, 2],
    zones: [
      { name: 'Zone 5 · 최대', range: '171–188', sec: 90, tone: 0 },
      { name: 'Zone 4 · 고강도', range: '153–170', sec: 1100, tone: 1 },
      { name: 'Zone 3 · 유산소', range: '135–152', sec: 720, tone: 2 },
      { name: 'Zone 2 · 지방연소', range: '117–134', sec: 138, tone: 3 },
    ],
    insight: '봄 날씨에 맞춰 편안한 페이스로 거리를 늘렸어요. 후반 페이스가 오히려 빨라진 좋은 러닝입니다.',
    recovery: '무리 없는 강도였어요. 가벼운 스트레칭으로 마무리하세요.',
  },
  {
    id: 'a6', title: '인터벌 트랙', area: '잠실 종합운동장', date: '4월 8일', when: '4월 8일 · 19:40', dayLabel: 'Apr 8', month: '4월',
    dist: 4.00, dur: '20:36', durSec: 1236, pace: "5'09\"", paceSec: 309, kcal: 268, hrAvg: 168, hrMax: 184, elevGain: 4,
    seed: 'me-jamsil-interval', tags: ['인터벌', '트랙'],
    splits: [300, 318, 296, 322], elev: [1, 1, 1, 1],
    zones: [
      { name: 'Zone 5 · 최대', range: '171–188', sec: 280, tone: 0 },
      { name: 'Zone 4 · 고강도', range: '153–170', sec: 620, tone: 1 },
      { name: 'Zone 3 · 유산소', range: '135–152', sec: 280, tone: 2 },
      { name: 'Zone 2 · 지방연소', range: '117–134', sec: 56, tone: 3 },
    ],
    insight: '인터벌 구간에서 목표 페이스를 정확히 지켰어요. 회복 구간 심박 관리도 좋았습니다.',
    recovery: '고강도 인터벌이라 근피로가 커요. 48시간 휴식과 충분한 단백질 섭취를 추천해요.',
  },
];

// zone tone → on-brand green ramp + a warm peak
const FR_ZONE_COLORS = ['#E0703D', '#2F8F3E', '#62C23A', '#9FDC6E'];

// ── stat tile ──────────────────────────────────────────
function FrBigStat({ c, label, value, unit, accent }) {
  return (
    <div style={{ flex: 1, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: '16px 16px 17px', boxShadow: c.shadow }}>
      <div style={{ fontFamily: RF, fontSize: 11.5, fontWeight: 600, letterSpacing: 0.3, color: c.faint, textTransform: 'uppercase' }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginTop: 9 }}>
        <span style={{ fontFamily: RF, fontSize: 27, fontWeight: 700, letterSpacing: -1, color: accent ? (c.dark ? c.accent : '#3F8E14') : c.text }}>{value}</span>
        {unit && <span style={{ fontFamily: RF, fontSize: 13, fontWeight: 600, color: c.faint }}>{unit}</span>}
      </div>
    </div>
  );
}

// ── premium AI insight dashboard card ──────────────────
function FrInsightCard({ c, locked, onUpgrade, onOpen }) {
  const goalPct = 75, done = 42.8, goal = 60;
  return (
    <button onClick={onOpen} style={{ width: '100%', textAlign: 'left', display: 'block', position: 'relative', background: c.surface, border: `1.5px solid ${c.accent}55`, borderRadius: 20, padding: 18, boxShadow: c.shadow, overflow: 'hidden', cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
      <div style={{ position: 'absolute', top: -30, right: -30, width: 130, height: 130, borderRadius: 999, background: c.accent, opacity: c.dark ? 0.12 : 0.07 }} />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <span style={{ display: 'flex', width: 22, height: 22, borderRadius: 7, background: c.accentDim, alignItems: 'center', justifyContent: 'center' }}>
            <FrCIcon name="sparkle" size={13} color={c.dark ? c.accent : '#3F8E14'} sw={2} />
          </span>
          <span style={{ fontFamily: RF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.4, color: c.dark ? c.accent : '#3F8E14', textTransform: 'uppercase' }}>Premium Insight</span>
        </div>
        <span style={{ fontFamily: RF, fontSize: 12.5, fontWeight: 600, color: c.sub }}>2024 · 5월</span>
      </div>

      <div style={{ display: 'flex', gap: 6, marginTop: 16 }}>
        {[['거리', '42.8', 'km'], ['세션', '12', '회'], ['평균 페이스', "5'18\"", '']].map((s, i) => (
          <div key={i} style={{ flex: 1 }}>
            <div style={{ fontFamily: RF, fontSize: 10.5, fontWeight: 600, letterSpacing: 0.3, color: c.faint, textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{s[0]}</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 3, marginTop: 5 }}>
              <span style={{ fontFamily: RF, fontSize: 19, fontWeight: 700, letterSpacing: -0.6, color: c.text }}>{s[1]}</span>
              <span style={{ fontFamily: RF, fontSize: 11, color: c.faint }}>{s[2]}</span>
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 16 }}>
        <div style={{ height: 8, borderRadius: 99, background: c.surfaceAlt, overflow: 'hidden' }}>
          <div style={{ width: goalPct + '%', height: '100%', borderRadius: 99, background: `linear-gradient(90deg, ${c.accent}, ${c.accent})` }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 7 }}>
          <span style={{ fontFamily: RF, fontSize: 12, color: c.sub }}>월 목표 {goal}km까지 <b style={{ color: c.text }}>{(goal - done).toFixed(1)}km</b></span>
          <span style={{ fontFamily: RF, fontSize: 12, fontWeight: 700, color: c.dark ? c.accent : '#3F8E14' }}>{goalPct}% 달성</span>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginTop: 16, paddingTop: 15, borderTop: `1px solid ${c.border}` }}>
        <FrCIcon name="sparkle" size={16} color={c.dark ? c.accent : '#3F8E14'} sw={1.9} />
        <p style={{ flex: 1, fontFamily: RF, fontSize: 12.5, lineHeight: 1.55, color: c.sub, letterSpacing: -0.2, margin: 0, textWrap: 'pretty' }}>
          <b style={{ color: c.text }}>AI 월간 분석:</b> 지난달보다 지구력이 12% 향상됐어요. 현재 페이스를 유지하며 주행 거리를 조금씩 늘려보세요.
        </p>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, marginTop: 14, paddingTop: 13, borderTop: `1px solid ${c.border}` }}>
        <span style={{ fontFamily: RF, fontSize: 13, fontWeight: 700, color: c.dark ? c.accent : '#3F8E14', letterSpacing: -0.2 }}>자세한 분석 보기</span>
        <FrXIcon name="chevright" size={15} color={c.dark ? c.accent : '#3F8E14'} sw={2.4} />
      </div>
    </button>
  );
}

// compact Lite upsell strip (option 2 — lime tint + 보기 button)
function FrInsightUpsell({ c, onUpgrade }) {
  const grn = c.dark ? c.accent : '#3C7A14';
  return (
    <button onClick={onUpgrade} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 12, background: c.accentDim, border: `1px solid ${c.accent}66`, borderRadius: 16, padding: '12px 13px', cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
      <span style={{ flexShrink: 0, width: 40, height: 40, borderRadius: 12, background: c.surface, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <FrXIcon name="lock" size={19} color={grn} sw={1.9} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontFamily: RF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>AI 월간 분석 잠금 해제</div>
        <div style={{ fontFamily: RF, fontSize: 12, color: c.dark ? c.sub : '#5C7A3C', letterSpacing: -0.2, marginTop: 2 }}>프리미엄으로 더 깊은 인사이트를</div>
      </div>
      <span style={{ flexShrink: 0, height: 34, display: 'flex', alignItems: 'center', padding: '0 14px', borderRadius: 999, background: c.accent, color: c.accentText, fontFamily: RF, fontSize: 13, fontWeight: 800, letterSpacing: -0.2 }}>보기</span>
    </button>
  );
}

// ── activity history row ───────────────────────────────
function FrActivityRow({ c, a, onOpen, units, highlight }) {
  const dist = units === 'mi' ? (a.dist * 0.621371).toFixed(2) : a.dist.toFixed(2);
  const distU = units === 'mi' ? 'mi' : 'km';
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <button onClick={() => onOpen(a)} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 13, background: c.surface, border: highlight ? `1.5px solid ${c.accent}` : `1px solid ${c.border}`, borderRadius: 18, padding: 12, cursor: 'pointer', boxShadow: highlight ? `0 8px 22px ${c.accent}44` : c.shadow, WebkitTapHighlightColor: 'transparent', animation: highlight ? 'frbubble .45s ease-out' : 'none' }}>
      <FrMiniMap seed={a.seed} width={62} height={62} radius={14} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
          <span style={{ fontFamily: RF, fontSize: 15, fontWeight: 700, letterSpacing: -0.4, color: c.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.title}</span>
          {highlight
            ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0, background: c.accentDim, borderRadius: 999, padding: '3px 9px' }}><span style={{ width: 5, height: 5, borderRadius: 99, background: grn }} /><span style={{ fontFamily: RF, fontSize: 10.5, fontWeight: 700, color: grn, letterSpacing: -0.1, whiteSpace: 'nowrap' }}>방금 저장됨</span></span>
            : <span style={{ fontFamily: RF, fontSize: 11.5, color: c.faint, whiteSpace: 'nowrap', flexShrink: 0 }}>{a.date}</span>}
        </div>
        <div style={{ fontFamily: RF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.when}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 13, marginTop: 8 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <FrIcon name="pin" size={13} color={c.dark ? c.accent : '#3F8E14'} sw={2} />
            <span style={{ fontFamily: RF, fontSize: 13, fontWeight: 700, color: c.dark ? c.accent : '#3F8E14', letterSpacing: -0.2 }}>{dist} {distU}</span>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <FrIcon name="clock" size={13} color={c.faint} sw={1.9} />
            <span style={{ fontFamily: RF, fontSize: 13, fontWeight: 600, color: c.sub, letterSpacing: -0.2 }}>{a.dur}</span>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <FrXIcon name="pace" size={13} color={c.faint} sw={1.9} />
            <span style={{ fontFamily: RF, fontSize: 13, fontWeight: 600, color: c.sub, letterSpacing: -0.2 }}>{a.pace}</span>
          </span>
        </div>
      </div>
      <FrIcon name="chevron" size={17} color={c.faint} sw={2} />
    </button>
  );
}

// build a full activity record from a finished free run (compatible with Activity Detail)
function frBuildRun({ km, sec, paceSec }) {
  const n = Math.max(2, Math.round(km));
  const splits = Array.from({ length: n }, (_, i) => paceSec + Math.round(Math.sin(i * 1.3) * 8) + (i === n - 1 ? -6 : 0));
  const elev = Array.from({ length: n }, (_, i) => 2 + Math.round(Math.abs(Math.sin(i * 0.8)) * 8));
  const mm = Math.floor(sec / 60), ss = sec % 60;
  const z5 = Math.round(sec * 0.10), z4 = Math.round(sec * 0.55), z3 = Math.round(sec * 0.27), z2 = Math.max(0, sec - z5 - z4 - z3);
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0'), mn = String(now.getMinutes()).padStart(2, '0');
  return {
    id: 'run-' + Date.now(), title: '자유 러닝', area: '서울숲 공원', date: '오늘', when: `오늘 · ${hh}:${mn}`, dayLabel: 'Today', month: '6월',
    dist: +(+km).toFixed(2), dur: `${mm}:${String(ss).padStart(2, '0')}`, durSec: sec,
    pace: frPaceStr(paceSec), paceSec, kcal: Math.round(km * 62), hrAvg: 154, hrMax: 169, elevGain: elev.reduce((a, b) => a + b, 0),
    seed: 'me-freerun-' + (Date.now() % 9999), tags: ['자유 러닝', '평지'],
    splits, elev,
    zones: [
      { name: 'Zone 5 · 최대', range: '171–188', sec: z5, tone: 0 },
      { name: 'Zone 4 · 고강도', range: '153–170', sec: z4, tone: 1 },
      { name: 'Zone 3 · 유산소', range: '135–152', sec: z3, tone: 2 },
      { name: 'Zone 2 · 지방연소', range: '117–134', sec: z2, tone: 3 },
    ],
    insight: '자유 러닝을 안정적인 페이스로 완주했어요. 후반까지 페이스 저하 없이 잘 유지했습니다.',
    recovery: '가벼운 스트레칭과 수분 보충으로 마무리하세요. 다음 러닝까지 충분한 휴식을 추천해요.',
    fresh: true,
  };
}

// shared month/year picker (bottom sheet: year stepper + 3×4 month grid)
function FrMonthPicker({ c, app, params }) {
  const nav = app.nav;
  const p = params || {};
  const enabled = new Set(p.enabled || []);
  const [yr, setYr] = React.useState(p.year || 2024);
  const grn = c.dark ? c.accent : '#3F8E14';
  const yearHasData = (y) => { for (let m = 1; m <= 12; m++) if (enabled.has(`${y}-${m}`)) return true; return false; };
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 92, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
      <div onClick={() => nav.pop()} style={{ position: 'absolute', inset: 0, background: 'rgba(10,12,8,0.34)', animation: 'frfadein .2s' }} />
      <div style={{ position: 'relative', background: c.bg, borderRadius: '24px 24px 0 0', padding: '10px 18px 26px', animation: 'frsheetup .3s cubic-bezier(.22,.61,.36,1)' }}>
        <div style={{ width: 40, height: 5, borderRadius: 99, background: c.fieldBorder, margin: '0 auto 14px' }} />
        <div style={{ fontFamily: RF, fontSize: 16, fontWeight: 800, color: c.text, letterSpacing: -0.4, textAlign: 'center', marginBottom: 16 }}>기간 선택</div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 18, marginBottom: 18 }}>
          <button onClick={() => setYr(y => y - 1)} style={{ width: 34, height: 34, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><FrCIcon name="back" size={18} color={c.text} sw={2.2} /></button>
          <span style={{ fontFamily: RF, fontSize: 17, fontWeight: 800, color: c.text, letterSpacing: -0.4, minWidth: 78, textAlign: 'center' }}>{`${yr}년`}</span>
          <button onClick={() => setYr(y => y + 1)} style={{ width: 34, height: 34, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transform: 'scaleX(-1)' }}><FrCIcon name="back" size={18} color={c.text} sw={2.2} /></button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 9 }}>
          {Array.from({ length: 12 }, (_, i) => i + 1).map(mn => {
            const ok = enabled.has(`${yr}-${mn}`);
            const on = yr === p.year && mn === p.month;
            return (
              <button key={mn} onClick={ok ? () => { p.onSelect && p.onSelect(yr, mn); nav.pop(); } : undefined} disabled={!ok}
                style={{ height: 46, borderRadius: 13, cursor: ok ? 'pointer' : 'default', fontFamily: RF, fontSize: 14, fontWeight: 700, letterSpacing: -0.2,
                  background: on ? c.accent : (ok ? c.surface : c.surfaceAlt), color: on ? c.accentText : (ok ? c.text : c.faint),
                  border: `1px solid ${on ? c.accent : (ok ? c.border : 'transparent')}`, WebkitTapHighlightColor: 'transparent' }}>{`${mn}월`}</button>
            );
          })}
        </div>
        {!yearHasData(yr) && <div style={{ fontFamily: RF, fontSize: 12, color: c.faint, textAlign: 'center', marginTop: 14 }}>이 해에는 기록이 없어요</div>}
      </div>
    </div>
  );
}

// ── monthly records (option 6: full-bleed area graph + hero + month switch) ──
const FR_MONTHLY = [
  { label: '2024 · 6월', year: 2024, mn: 6, distKm: 42.8, sessions: 12, pace: "5'18\"", time: '3:47', weeks: [8.2, 12.4, 9.6, 12.6], delta: 12 },
  { label: '2024 · 5월', year: 2024, mn: 5, distKm: 38.2, sessions: 11, pace: "5'24\"", time: '3:26', weeks: [9.0, 8.0, 11.0, 10.2], delta: 5 },
  { label: '2024 · 4월', year: 2024, mn: 4, distKm: 36.4, sessions: 10, pace: "5'30\"", time: '3:18', weeks: [7.0, 9.0, 10.0, 10.4], delta: -3 },
  { label: '2024 · 3월', year: 2024, mn: 3, distKm: 29.6, sessions: 8, pace: "5'41\"", time: '2:48', weeks: [5.0, 7.6, 8.0, 9.0], delta: 8 },
];

function frAreaPaths(vals, w, h, padB) {
  const max = Math.max(...vals), min = Math.min(...vals), n = vals.length, pad = 4;
  const pts = vals.map((v, i) => [pad + i * ((w - 2 * pad) / (n - 1)), (h - padB) - ((v - min) / (max - min || 1)) * (h - padB - 8)]);
  let line = '';
  pts.forEach((p, i) => { if (i === 0) { line = `M ${p[0].toFixed(1)} ${p[1].toFixed(1)}`; } else { const pr = pts[i - 1], mx = (pr[0] + p[0]) / 2; line += ` C ${mx.toFixed(1)} ${pr[1].toFixed(1)}, ${mx.toFixed(1)} ${p[1].toFixed(1)}, ${p[0].toFixed(1)} ${p[1].toFixed(1)}`; } });
  const area = line + ` L ${pts[n - 1][0].toFixed(1)} ${h} L ${pts[0][0].toFixed(1)} ${h} Z`;
  return { line, area };
}

function FrMonthlyRecord({ c, app }) {
  const nav = app && app.nav;
  const units = (app && app.units) || 'km';
  const [idx, setIdx] = React.useState(0);
  const m = FR_MONTHLY[idx];
  const grn = c.dark ? c.accent : '#3F8E14';
  const chartCol = c.dark ? c.accent : '#34B85A';
  const distU = units === 'mi' ? 'mi' : 'km';
  const dist = units === 'mi' ? (m.distKm * 0.621371).toFixed(1) : m.distKm.toFixed(1);
  const W = 380, H = 98;
  const { line, area } = frAreaPaths(m.weeks, W, H, 1);
  const gid = 'frmg' + idx;
  const stats = [['총 거리', dist, distU], ['세션', String(m.sessions), '회'], ['평균 페이스', m.pace, ''], ['총 시간', m.time, 'h']];
  return (
    <div style={{ padding: '14px 20px 0' }}>
      {/* month stepper */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <button onClick={() => setIdx(i => Math.min(FR_MONTHLY.length - 1, i + 1))} disabled={idx >= FR_MONTHLY.length - 1} style={{ width: 34, height: 34, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: idx >= FR_MONTHLY.length - 1 ? 'default' : 'pointer', opacity: idx >= FR_MONTHLY.length - 1 ? 0.4 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrCIcon name="back" size={18} color={c.text} sw={2.2} />
        </button>
        <button onClick={() => nav && nav.push('monthPicker', { year: m.year, month: m.mn, enabled: FR_MONTHLY.map(e => `${e.year}-${e.mn}`), onSelect: (y, mm) => { const j = FR_MONTHLY.findIndex(e => e.year === y && e.mn === mm); if (j >= 0) setIdx(j); } })} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', padding: '4px 6px', WebkitTapHighlightColor: 'transparent' }}>
          <span style={{ fontFamily: RF, fontSize: 16, fontWeight: 800, color: c.text, letterSpacing: -0.4 }}>{m.label}</span>
          <FrCIcon name="chevdown" size={16} color={c.sub} sw={2.2} />
        </button>
        <button onClick={() => setIdx(i => Math.max(0, i - 1))} disabled={idx <= 0} style={{ width: 34, height: 34, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: idx <= 0 ? 'default' : 'pointer', opacity: idx <= 0 ? 0.4 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', transform: 'scaleX(-1)' }}>
          <FrCIcon name="back" size={18} color={c.text} sw={2.2} />
        </button>
      </div>

      {/* hero card with full-bleed area graph */}
      <div style={{ position: 'relative', borderRadius: 18, overflow: 'hidden', background: c.surface, border: `1px solid ${c.border}`, padding: '16px 16px 0', boxShadow: c.shadow }}>
        <div style={{ position: 'relative', zIndex: 2 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
            <span style={{ fontFamily: RF, fontSize: 40, fontWeight: 800, letterSpacing: -1.6, color: c.text }}>{dist}</span>
            <span style={{ fontFamily: RF, fontSize: 16, fontWeight: 700, color: c.faint }}>{distU}</span>
            <span style={{ marginLeft: 'auto', fontFamily: RF, fontSize: 12.5, fontWeight: 700, color: m.delta >= 0 ? grn : c.danger, background: m.delta >= 0 ? c.accentDim : c.danger + '1A', borderRadius: 999, padding: '4px 10px' }}>지난달 {m.delta >= 0 ? '+' : ''}{m.delta}%</span>
          </div>
          <div style={{ fontFamily: RF, fontSize: 11.5, fontWeight: 600, letterSpacing: 0.2, color: c.faint, marginTop: 2 }}>이번 달 총 거리</div>
        </div>
        <div style={{ margin: '6px -16px -1px', position: 'relative', zIndex: 1 }}>
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" style={{ display: 'block' }}>
            <defs><linearGradient id={gid} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={chartCol} stopOpacity="0.30" /><stop offset="1" stopColor={chartCol} stopOpacity="0" /></linearGradient></defs>
            <path d={area} fill={`url(#${gid})`} />
            <path d={line} fill="none" stroke={chartCol} strokeWidth="2.6" strokeLinecap="round" />
          </svg>
        </div>
      </div>

      {/* stat row */}
      <div style={{ display: 'flex', marginTop: 14 }}>
        {stats.map((s, i) => (
          <div key={i} style={{ flex: 1, textAlign: 'center', borderLeft: i ? `1px solid ${c.border}` : 'none' }}>
            <div style={{ fontFamily: RF, fontSize: 18, fontWeight: 800, letterSpacing: -0.4, color: c.text }}>{s[1]}<span style={{ fontSize: 11, color: c.faint, fontWeight: 600 }}>{s[2] ? ' ' + s[2] : ''}</span></div>
            <div style={{ fontFamily: RF, fontSize: 11, color: c.faint, marginTop: 4 }}>{s[0]}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Records tab ────────────────────────────────────────
function FrRecords({ c, app, onTab }) {
  const nav = app && app.nav;
  const units = (app && app.units) || 'km';
  const justSavedId = (app && app.justSavedId) || null;
  const acts = ((app && app.savedRuns) || []).concat(FR_ACTS);
  return (
    <div style={frPage(c)}>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '60px 20px 4px' }}>
          <h1 style={{ fontFamily: RF, fontSize: 26, fontWeight: 700, letterSpacing: -0.8, color: c.text, margin: 0 }}>기록</h1>
          <button onClick={() => nav && nav.push('notifications')} style={{ width: 42, height: 42, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative', boxShadow: c.shadow }}>
            <FrXIcon name="bell" size={20} color={c.text} sw={1.9} />
            <span style={{ position: 'absolute', top: 9, right: 10, width: 7, height: 7, borderRadius: 99, background: c.danger, border: `1.5px solid ${c.surface}` }} />
          </button>
        </div>

        <FrMonthlyRecord c={c} app={app} />

        <div style={{ padding: '14px 20px 0' }}>
          {(app && app.premium)
            ? <FrInsightCard c={c} onOpen={() => nav && nav.push('monthlyInsight')} onUpgrade={() => nav && nav.push('premium')} />
            : <FrInsightUpsell c={c} onUpgrade={() => nav && nav.push('premium')} />}
        </div>

        <div style={{ padding: '24px 20px 8px' }}>
          <FrSectionTitle c={c} action="전체보기 →" onAction={() => nav && nav.push('allActivities')}>활동 내역</FrSectionTitle>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '4px 20px 28px' }}>
          {acts.map(a => <FrActivityRow key={a.id} c={c} a={a} units={units} highlight={a.id === justSavedId} onOpen={(x) => nav && nav.push('activityDetail', { act: x })} />)}
        </div>
      </div>
      <FrTabBar c={c} active="log" onTab={onTab} />
    </div>
  );
}

// ── all activities (pushed: month organizer + grouped list) ──────
function FrAllActivities({ c, app }) {
  const nav = app.nav;
  const units = (app && app.units) || 'km';
  const justSavedId = (app && app.justSavedId) || null;
  const base = ((app && app.savedRuns) || []).concat(FR_ACTS);
  // distinct months in data order (newest first)
  const months = base.map(a => a.month || '기타').filter((v, i, arr) => arr.indexOf(v) === i);
  const [idx, setIdx] = React.useState(0);
  const month = months[idx];
  const shown = base.filter(a => (a.month || '기타') === month);
  const grn = c.dark ? c.accent : '#3F8E14';
  const fmtKm = (v) => units === 'mi' ? (v * 0.621371).toFixed(1) : v.toFixed(1);
  const distU = units === 'mi' ? 'mi' : 'km';
  const monthKm = shown.reduce((s, a) => s + a.dist, 0);
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="활동 내역" onBack={() => nav.pop()} />
      {/* month stepper — matches the 이번 달 기록 control */}
      <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px 14px', borderBottom: `1px solid ${c.border}` }}>
        <button onClick={() => setIdx(i => Math.min(months.length - 1, i + 1))} disabled={idx >= months.length - 1} style={{ width: 34, height: 34, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: idx >= months.length - 1 ? 'default' : 'pointer', opacity: idx >= months.length - 1 ? 0.4 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrCIcon name="back" size={18} color={c.text} sw={2.2} />
        </button>
        <button onClick={() => nav.push('monthPicker', { year: 2024, month: parseInt(month, 10), enabled: months.map(mm => `2024-${parseInt(mm, 10)}`), onSelect: (y, mm) => { const j = months.indexOf(`${mm}월`); if (j >= 0) setIdx(j); } })} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', padding: '4px 6px', WebkitTapHighlightColor: 'transparent' }}>
          <span style={{ fontFamily: RF, fontSize: 16, fontWeight: 800, color: c.text, letterSpacing: -0.4 }}>2024 · {month}</span>
          <FrCIcon name="chevdown" size={16} color={c.sub} sw={2.2} />
        </button>
        <button onClick={() => setIdx(i => Math.max(0, i - 1))} disabled={idx <= 0} style={{ width: 34, height: 34, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: idx <= 0 ? 'default' : 'pointer', opacity: idx <= 0 ? 0.4 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', transform: 'scaleX(-1)' }}>
          <FrCIcon name="back" size={18} color={c.text} sw={2.2} />
        </button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', padding: '4px 20px 28px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', padding: '16px 2px 10px' }}>
          <span style={{ fontFamily: RF, fontSize: 13, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>{shown.length}개 활동</span>
          <span style={{ fontFamily: RF, fontSize: 12.5, fontWeight: 600, color: c.faint, letterSpacing: -0.2 }}>누적 {fmtKm(monthKm)} {distU}</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {shown.map(a => <FrActivityRow key={a.id} c={c} a={a} units={units} highlight={a.id === justSavedId} onOpen={(x) => nav.push('activityDetail', { act: x })} />)}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { FR_ACTS, FR_ZONE_COLORS, frPaceStr, frBuildRun, FrRecords, FrActivityRow, FrBigStat, FrInsightCard, FrInsightUpsell, FrMonthlyRecord, FrAllActivities, FrMonthPicker });
