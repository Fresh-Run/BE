// FreshRun — 홈 shared UI: weather, mini-map, feed cards, detail sheet, tab bar.
// Reuses FR_LIGHT / FR_DARK / FR_FONT from auth-ui.jsx (on window).
const HF = window.FR_FONT;

// ── deterministic PRNG from a string seed ──────────────
function frHash(str) { let h = 1779033703 ^ str.length; for (let i = 0; i < str.length; i++) { h = Math.imul(h ^ str.charCodeAt(i), 3432918353); h = (h << 13) | (h >>> 19); } return () => { h = Math.imul(h ^ (h >>> 16), 2246822507); h = Math.imul(h ^ (h >>> 13), 3266489909); h ^= h >>> 16; return (h >>> 0) / 4294967296; }; }

// ── mini map tile w/ generated route (always dark = Naver dark map) ──
function FrMiniMap({ seed, width = 96, height = 96, radius = 14, hero = false }) {
  const rnd = frHash(seed);
  const W = 300, H = 300, pad = 46;
  // route points
  const n = 5 + Math.floor(rnd() * 3);
  const pts = [];
  for (let i = 0; i < n; i++) pts.push([pad + rnd() * (W - 2 * pad), pad + rnd() * (H - 2 * pad)]);
  // smooth path (catmull-rom -> bezier)
  let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  const start = pts[0], end = pts[pts.length - 1];
  // faint roads
  const roads = [];
  for (let i = 0; i < 4; i++) { const horiz = rnd() > 0.5; const o = 40 + rnd() * 220; roads.push(horiz ? [0, o, W, o] : [o, 0, o, H]); }
  const hasRiver = rnd() > 0.45;
  const accent = '#7CF03D';
  return (
    <div style={{ width, height, borderRadius: radius, overflow: 'hidden', position: 'relative', background: '#0C0F14', flexShrink: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" preserveAspectRatio="xMidYMid slice">
        <rect width={W} height={H} fill="#0C0F14" />
        {hasRiver && <path d={`M -10 ${60 + rnd() * 60} C 90 ${120 + rnd() * 40}, 180 ${40 + rnd() * 40}, ${W + 10} ${150 + rnd() * 60}`} stroke="#15364A" strokeWidth={26} fill="none" strokeOpacity="0.7" strokeLinecap="round" />}
        {roads.map((r, i) => <line key={i} x1={r[0]} y1={r[1]} x2={r[2]} y2={r[3]} stroke="#1C2230" strokeWidth={i % 2 ? 5 : 8} />)}
        <path d={d} stroke={accent} strokeOpacity="0.22" strokeWidth={hero ? 13 : 16} strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <path d={d} stroke={accent} strokeWidth={hero ? 5 : 7} strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <circle cx={start[0]} cy={start[1]} r={hero ? 7 : 9} fill="#0C0F14" stroke={accent} strokeWidth={hero ? 4 : 5} />
        <circle cx={end[0]} cy={end[1]} r={hero ? 8 : 10} fill={accent} />
      </svg>
    </div>
  );
}

// ── avatar (initial chip) ──────────────────────────────
const FR_AVA = ['#E8703D', '#3D8BFF', '#1F9E63', '#C44 D0', '#E0A52E', '#6C5CE7', '#D8463C', '#0FA3A3'].map(s => s.replace(' ', ''));
function FrAvatar({ name, size = 38, ring }) {
  const rnd = frHash(name);
  const col = FR_AVA[Math.floor(rnd() * FR_AVA.length)];
  return (
    <div style={{ width: size, height: size, borderRadius: 999, background: col, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: ring ? `0 0 0 2px ${ring}` : 'none' }}>
      <span style={{ fontFamily: HF, fontWeight: 700, fontSize: size * 0.42, color: '#fff', letterSpacing: -0.3 }}>{name[0]}</span>
    </div>
  );
}

// ── small icons ────────────────────────────────────────
function FrIcon({ name, size = 20, color, fill = 'none', sw = 1.8 }) {
  const p = {
    heart: <path d="M12 20.5l-1.6-1.45C5.4 14.5 2.5 11.9 2.5 8.6 2.5 6.1 4.5 4.1 7 4.1c1.5 0 2.9.7 3.8 1.8.9-1.1 2.3-1.8 3.8-1.8 2.5 0 4.5 2 4.5 4.5 0 3.3-2.9 5.9-7.9 10.45L12 20.5z" />,
    comment: <path d="M21 11.5a8.4 8.4 0 01-11.9 7.6L3 21l1.9-6.1A8.4 8.4 0 1121 11.5z" strokeLinejoin="round" />,
    bookmark: <path d="M6 4h12v16l-6-4.2L6 20V4z" strokeLinejoin="round" />,
    pin: <><path d="M12 21s7-5.7 7-11a7 7 0 10-14 0c0 5.3 7 11 7 11z" strokeLinejoin="round" /><circle cx="12" cy="10" r="2.4" /></>,
    droplet: <path d="M12 3.5s6 6.1 6 10a6 6 0 11-12 0c0-3.9 6-10 6-10z" strokeLinejoin="round" />,
    haze: <><path d="M3 15h18M5 18.5h14M7 11.5h10" strokeLinecap="round" /><circle cx="12" cy="7" r="3" /></>,
    wind: <path d="M3 9h11a2.5 2.5 0 10-2.5-2.5M3 14h15a2.5 2.5 0 11-2.5 2.5" strokeLinecap="round" />,
    sun: <><circle cx="12" cy="12" r="4.2" /><path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5.2 5.2l1.7 1.7M17.1 17.1l1.7 1.7M18.8 5.2l-1.7 1.7M6.9 17.1l-1.7 1.7" strokeLinecap="round" /></>,
    chevron: <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />,
    close: <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />,
    clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" strokeLinecap="round" /></>,
    route: <><circle cx="6" cy="18" r="2.6" /><circle cx="18" cy="6" r="2.6" /><path d="M8.4 16.5C14 14 10 8.5 15.6 7" strokeLinecap="round" strokeDasharray="0.1 3.4" /></>,
    home: <path d="M3.5 11L12 4l8.5 7M6 9.5V20h12V9.5" strokeLinejoin="round" strokeLinecap="round" />,
    list: <path d="M8 6h12M8 12h12M8 18h12M3.6 6h.01M3.6 12h.01M3.6 18h.01" strokeLinecap="round" />,
    person: <><circle cx="12" cy="8" r="3.6" /><path d="M5 20c0-3.5 3.1-5.5 7-5.5s7 2 7 5.5" strokeLinecap="round" /></>,
    users: <><circle cx="9" cy="8.5" r="3.1" /><path d="M3.5 19.5c0-3 2.5-4.8 5.5-4.8s5.5 1.8 5.5 4.8" strokeLinecap="round" /><path d="M16 5.4a3 3 0 010 6M18.5 19.5c0-2.4-1-4-2.6-4.8" strokeLinecap="round" /></>,
    trophy: <><path d="M7 4h10v4a5 5 0 01-10 0V4z" strokeLinejoin="round" /><path d="M7 5.5H4.5V7A2.5 2.5 0 007 9.5M17 5.5h2.5V7A2.5 2.5 0 0117 9.5M9.5 13.5h5M12 13v3M8.5 20h7" strokeLinecap="round" /></>,
    plus: <path d="M12 5v14M5 12h14" strokeLinecap="round" />,
  }[name];
  return <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={color} strokeWidth={sw}>{p}</svg>;
}

// ── shared run data ────────────────────────────────────
const FR_FEED = [
  { id: 'r1', name: '김도현', area: '한강 · 뚝섬', title: '한강 야경 러닝', dist: 7.2, dur: '38:24', pace: "5'19\"", tags: ['야경', '도심'], ago: '2시간 전', kudos: 24, comments: 3, seed: 'kim-hangang-night', away: 4.1 },
  { id: 'r2', name: '이서연', area: '남산', title: '남산 언덕 코스', dist: 5.4, dur: '31:50', pace: "5'53\"", tags: ['언덕', '경치'], ago: '5시간 전', kudos: 41, comments: 7, seed: 'lee-namsan-hill', away: 5.8 },
  { id: 'r3', name: '박지호', area: '올림픽공원', title: '올림픽공원 둘레길', dist: 6.8, dur: '34:58', pace: "5'08\"", tags: ['공원', '평지'], ago: '어제', kudos: 18, comments: 1, seed: 'park-olympic-loop', away: 8.7 },
  { id: 'r4', name: '최유진', area: '양재천', title: '양재천 새벽 런', dist: 8.1, dur: '44:06', pace: "5'26\"", tags: ['자연', '조용함'], ago: '어제', kudos: 33, comments: 5, seed: 'choi-yangjae-dawn', away: 9.2 },
  { id: 'r5', name: '정민수', area: '서울숲', title: '서울숲 인터벌', dist: 4.2, dur: '21:58', pace: "5'14\"", tags: ['공원'], ago: '2일 전', kudos: 12, comments: 0, seed: 'jung-seoulsup-int', away: 2.4 },
];
// nearby non-friend runs (전체 피드, 10km 이내)
const FR_NEARBY = [
  { id: 'n1', name: '한도윤', area: '성수동', title: '성수 카페거리 러닝', dist: 3.6, dur: '19:40', pace: "5'28\"", tags: ['도심'], ago: '1시간 전', kudos: 6, comments: 2, seed: 'han-seongsu-cafe', away: 0.6 },
  { id: 'n2', name: '서지안', area: '뚝섬한강공원', title: '뚝섬 강변 5K', dist: 5.0, dur: '27:30', pace: "5'30\"", tags: ['강변', '평지'], ago: '2시간 전', kudos: 9, comments: 0, seed: 'seo-ttukseom-5k', away: 1.3 },
  { id: 'n3', name: '문하늘', area: '응봉산', title: '응봉산 언덕 훈련', dist: 6.1, dur: '35:50', pace: "5'52\"", tags: ['언덕'], ago: '3시간 전', kudos: 21, comments: 3, seed: 'moon-eungbong', away: 3.0 },
  { id: 'n4', name: '오세훈', area: '중랑천', title: '중랑천 LSD', dist: 9.4, dur: '52:18', pace: "5'34\"", tags: ['강변', '평지'], ago: '5시간 전', kudos: 14, comments: 1, seed: 'oh-jungnang-lsd', away: 4.7 },
];
const FR_COMMENTS = {
  r1: [['이서연', '야경 미쳤다 🔥 나도 담에 같이 가요'], ['박지호', '페이스 좋네요!'], ['최유진', '뚝섬 코스 저장!']],
  r2: [['김도현', '언덕 구간 힘들었죠 ㅋㅋ'], ['정민수', '경치값 함']],
  r3: [['최유진', '평지라 기록 잘 나오는 코스']],
  r5: [],
};

// ── weather data + helpers ─────────────────────────────
const FR_WEATHER = {
  area: '성수동', condition: '맑음', temp: 18, feels: 16,
  humidity: 45, pm10: { v: 28, label: '좋음' }, pm25: { v: 19, label: '보통' }, wind: 2.1,
  uv: { v: 4, label: '보통' }, rain: 10, sunset: '19:48',
  verdict: { label: '러닝하기 좋아요', short: '좋음', tone: 'good' },
  tip: '미세먼지가 적고 바람이 약해 야외 러닝에 좋은 날이에요. 해 지기 전 가볍게 한 바퀴 어때요?',
};
const FR_AQI_COLOR = { '좋음': '#3BA7FF', '보통': '#2FA866', '나쁨': '#E8922E', '매우나쁨': '#D8463C' };
function frVerdictColor(c, tone) { return tone === 'good' ? c.accent : tone === 'ok' ? '#E8A23D' : c.danger; }

Object.assign(window, { FrMiniMap, FrAvatar, FrIcon, FR_FEED, FR_NEARBY, FR_COMMENTS, FR_WEATHER, FR_AQI_COLOR, frVerdictColor, frHash });
