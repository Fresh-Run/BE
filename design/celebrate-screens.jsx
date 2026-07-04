// FreshRun — celebration modals (Challenge Completed, New Personal Best) + Premium upgrade.
const CEF = window.FR_FONT;

// confetti burst — a handful of falling squares (CSS keyframe frconfetti)
function FrConfetti({ c }) {
  const cols = [c.accent, '#3D8BFF', '#E0A52E', '#E0703D', c.accent];
  const bits = [];
  const rnd = frHash('confetti-seed');
  for (let i = 0; i < 16; i++) {
    const left = rnd() * 100, delay = rnd() * 0.5, dur = 1.4 + rnd() * 1.1, size = 6 + rnd() * 6, rot = rnd() * 360;
    bits.push(<span key={i} style={{ position: 'absolute', top: -16, left: left + '%', width: size, height: size, borderRadius: 2, background: cols[i % cols.length], transform: `rotate(${rot}deg)`, animation: `frconfetti ${dur}s ${delay}s ease-in forwards`, opacity: 0.9 }} />);
  }
  return <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }}>{bits}</div>;
}

function FrModalShell({ c, children }) {
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 90, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 18px' }}>
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)', animation: 'frfadein .2s' }} />
      <div style={{ position: 'relative', animation: 'frpop .34s cubic-bezier(.34,1.5,.5,1)' }}>{children}</div>
    </div>
  );
}

// ── Challenge Completed ────────────────────────────────
function FrChallengeDone({ c, app }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <FrModalShell c={c}>
      <FrConfetti c={c} />
      <div style={{ position: 'relative', background: c.surface, borderRadius: 26, padding: '30px 22px 22px', boxShadow: '0 24px 60px rgba(0,0,0,0.4)' }}>
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <div style={{ position: 'relative', width: 110, height: 110, borderRadius: 999, background: `radial-gradient(circle at 50% 38%, ${c.accent}, ${c.accent}99 60%, ${c.accent}22)`, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 0 44px ${c.accent}88` }}>
            <FrIcon name="trophy" size={50} color={c.accentText} sw={1.7} />
          </div>
        </div>
        <h1 style={{ fontFamily: CEF, fontSize: 25, fontWeight: 700, letterSpacing: -0.7, color: c.text, textAlign: 'center', margin: '20px 0 0' }}>챌린지 완료! 🎉</h1>
        <p style={{ fontFamily: CEF, fontSize: 14, lineHeight: 1.5, color: c.sub, textAlign: 'center', letterSpacing: -0.3, margin: '8px 16px 0', textWrap: 'balance' }}>서울 한강 10km 챌린지를 성공적으로 마쳤어요.</p>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, background: c.accentDim, border: `1px solid ${c.accent}44`, borderRadius: 16, padding: 15, marginTop: 20 }}>
          <span style={{ width: 42, height: 42, borderRadius: 999, background: c.surface, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <FrXIcon name="seal" size={22} color={grn} sw={1.8} />
          </span>
          <div>
            <div style={{ fontFamily: CEF, fontSize: 11, fontWeight: 700, letterSpacing: 0.4, color: grn, textTransform: 'uppercase' }}>New Reward</div>
            <div style={{ fontFamily: CEF, fontSize: 15.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, marginTop: 2 }}>디지털 배지 획득</div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
          {[['총 거리', '10.2', 'km'], ['평균 페이스', "5'12\"", ''], ['칼로리', '650', 'kcal']].map((s, i) => (
            <div key={i} style={{ flex: 1, background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: 14, padding: '12px 8px', textAlign: 'center' }}>
              <div style={{ fontFamily: CEF, fontSize: 16, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap' }}>{s[1]}<span style={{ fontSize: 10.5, color: c.faint, fontWeight: 600 }}>{s[2] && ' ' + s[2]}</span></div>
              <div style={{ fontFamily: CEF, fontSize: 10.5, color: c.faint, marginTop: 3 }}>{s[0]}</div>
            </div>
          ))}
        </div>

        <button onClick={() => { nav.reset(); nav.setTab('log'); }} style={{ width: '100%', height: 52, borderRadius: 14, border: 'none', background: c.accent, color: c.accentText, fontFamily: CEF, fontSize: 16, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 18, boxShadow: `0 6px 18px ${c.accent}55` }}>기록 확인하기</button>
        <button onClick={() => nav.push('runShare', {})} style={{ width: '100%', height: 50, borderRadius: 14, border: `1px solid ${c.border}`, background: c.surfaceAlt, color: c.sub, fontFamily: CEF, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
          <FrXIcon name="share" size={17} color={c.sub} sw={1.9} /> 지금 공유하기
        </button>
      </div>
    </FrModalShell>
  );
}

// ── New Personal Best ──────────────────────────────────
function FrPersonalBest({ c, app, params }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3F8E14';
  const prev = (params && params.prev) || "5'30\"", next = (params && params.next) || "5'15\"";
  return (
    <FrModalShell c={c}>
      <FrConfetti c={c} />
      <div style={{ position: 'relative', background: c.surface, borderRadius: 26, padding: '30px 22px 22px', boxShadow: '0 24px 60px rgba(0,0,0,0.4)' }}>
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <div style={{ width: 100, height: 100, borderRadius: 999, background: `radial-gradient(circle at 50% 38%, ${c.accent}, ${c.accent}88 65%, ${c.accent}11)`, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 0 40px ${c.accent}88` }}>
            <FrXIcon name="medal" size={46} color={c.accentText} sw={1.6} />
          </div>
        </div>
        <h1 style={{ fontFamily: CEF, fontSize: 24, fontWeight: 700, letterSpacing: -0.7, color: grn, textAlign: 'center', margin: '18px 0 0' }}>새로운 기록 경신!</h1>
        <p style={{ fontFamily: CEF, fontSize: 14, lineHeight: 1.5, color: c.sub, textAlign: 'center', letterSpacing: -0.3, margin: '8px 14px 0', textWrap: 'balance' }}>5km 구간 역대 최고 페이스를 달성했어요!</p>

        <div style={{ display: 'flex', alignItems: 'stretch', gap: 0, marginTop: 20, border: `1px solid ${c.border}`, borderRadius: 16, overflow: 'hidden' }}>
          <div style={{ flex: 1, background: c.surfaceAlt, padding: '16px 12px', textAlign: 'center' }}>
            <div style={{ fontFamily: CEF, fontSize: 11, fontWeight: 600, letterSpacing: 0.3, color: c.faint, textTransform: 'uppercase' }}>이전</div>
            <div style={{ fontFamily: CEF, fontSize: 24, fontWeight: 700, letterSpacing: -0.8, color: c.sub, marginTop: 6 }}>{prev}</div>
            <div style={{ fontFamily: CEF, fontSize: 11, color: c.faint, marginTop: 1 }}>/km</div>
          </div>
          <div style={{ flex: 1, background: c.accentDim, padding: '16px 12px', textAlign: 'center', position: 'relative' }}>
            <span style={{ position: 'absolute', top: 8, right: 8, fontFamily: CEF, fontSize: 9, fontWeight: 700, letterSpacing: 0.4, color: c.accentText, background: c.accent, borderRadius: 6, padding: '2px 6px' }}>BEST</span>
            <div style={{ fontFamily: CEF, fontSize: 11, fontWeight: 600, letterSpacing: 0.3, color: grn, textTransform: 'uppercase' }}>현재</div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, marginTop: 6 }}>
              <span style={{ fontFamily: CEF, fontSize: 24, fontWeight: 700, letterSpacing: -0.8, color: grn }}>{next}</span>
              <FrXIcon name="trending" size={16} color={grn} sw={2.2} />
            </div>
            <div style={{ fontFamily: CEF, fontSize: 11, color: c.faint, marginTop: 1 }}>/km</div>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 14 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: c.accentDim, borderRadius: 999, padding: '7px 14px' }}>
            <FrXIcon name="bolt" size={14} color={grn} sw={2} />
            <span style={{ fontFamily: CEF, fontSize: 13, fontWeight: 700, color: grn, letterSpacing: -0.2 }}>4.5% 향상</span>
          </span>
        </div>

        <button onClick={() => { nav.pop(); nav.push('activityDetail', { act: (params && params.run) || FR_ACTS[0] }); }} style={{ width: '100%', height: 52, borderRadius: 14, border: 'none', background: c.accent, color: c.accentText, fontFamily: CEF, fontSize: 16, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 18, boxShadow: `0 6px 18px ${c.accent}55` }}>기록 자세히 보기</button>
        <button onClick={() => nav.push('runShare', { run: (params && params.run) || FR_ACTS[0] })} style={{ width: '100%', height: 50, borderRadius: 14, border: 'none', background: 'transparent', color: c.sub, fontFamily: CEF, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
          <FrXIcon name="share" size={17} color={c.sub} sw={1.9} /> 성과 공유하기
        </button>
      </div>
    </FrModalShell>
  );
}

// ── Premium upgrade ────────────────────────────────────
function FrPremium({ c, app }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3F8E14';
  const [plan, setPlan] = React.useState('year');
  const feats = [
    ['target', 'AI 맞춤 코스 생성', '거리·분위기·경유지에 최적화된 무제한 코스'],
    ['chart', '심층 퍼포먼스 분석', '페이스·고도·심박 구간 + 회복 조언'],
    ['speaker', 'AI 오디오 코치', '러닝 중 실시간 음성 페이스 안내'],
  ];
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="" onClose={() => nav.pop()} transparent />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', display: 'flex', flexDirection: 'column', padding: '0 22px 26px' }}>
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 4 }}>
          <div style={{ width: 72, height: 72, borderRadius: 22, background: c.text, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <FrXIcon name="crown" size={36} color={c.accent} sw={1.8} />
          </div>
        </div>
        <h1 style={{ fontFamily: CEF, fontSize: 27, fontWeight: 700, letterSpacing: -0.9, color: c.text, textAlign: 'center', margin: '18px 0 0', textWrap: 'balance' }}>FreshRun Premium</h1>
        <p style={{ fontFamily: CEF, fontSize: 14.5, lineHeight: 1.5, color: c.sub, textAlign: 'center', letterSpacing: -0.3, margin: '8px 10px 0', textWrap: 'balance' }}>프로 러너를 위한 AI 코칭과 심층 분석을 잠금 해제하세요.</p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 24 }}>
          {feats.map(([ic, t, d]) => (
            <div key={t} style={{ display: 'flex', gap: 13, alignItems: 'center' }}>
              <span style={{ flexShrink: 0, width: 40, height: 40, borderRadius: 12, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <FrXIcon name={ic} size={20} color={grn} sw={1.8} />
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ fontFamily: CEF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>{t}</div>
                <div style={{ fontFamily: CEF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, marginTop: 2 }}>{d}</div>
              </div>
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 11, marginTop: 26 }}>
          {[['month', '월간', '₩9,900', '/월'], ['year', '연간', '₩79,000', '/년']].map(([id, nm, price, per]) => {
            const sel = plan === id;
            return (
              <button key={id} onClick={() => setPlan(id)} style={{ flex: 1, textAlign: 'left', position: 'relative', background: sel ? c.accentDim : c.surface, border: `1.5px solid ${sel ? c.accent : c.border}`, borderRadius: 16, padding: '14px 14px 15px', cursor: 'pointer' }}>
                {id === 'year' && <span style={{ position: 'absolute', top: -9, right: 12, fontFamily: CEF, fontSize: 9.5, fontWeight: 700, letterSpacing: 0.3, color: c.accentText, background: c.accent, borderRadius: 7, padding: '3px 8px' }}>33% 할인</span>}
                <div style={{ fontFamily: CEF, fontSize: 13, fontWeight: 700, color: sel ? grn : c.sub, letterSpacing: -0.2 }}>{nm}</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 2, marginTop: 6 }}>
                  <span style={{ fontFamily: CEF, fontSize: 21, fontWeight: 700, color: c.text, letterSpacing: -0.6 }}>{price}</span>
                  <span style={{ fontFamily: CEF, fontSize: 12, color: c.faint }}>{per}</span>
                </div>
              </button>
            );
          })}
        </div>

        <div style={{ flex: 1, minHeight: 12 }} />
        <button onClick={() => nav.pop()} style={{ width: '100%', height: 56, borderRadius: 16, border: 'none', background: c.accent, color: c.accentText, fontFamily: CEF, fontSize: 16.5, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 22, boxShadow: `0 6px 18px ${c.accent}55` }}>7일 무료 체험 시작</button>
        <p style={{ fontFamily: CEF, fontSize: 11.5, color: c.faint, textAlign: 'center', letterSpacing: -0.2, margin: '12px 0 0' }}>{plan === 'year' ? '연 ₩79,000' : '월 ₩9,900'} · 언제든 해지 가능</p>
      </div>
    </div>
  );
}

// run share sheet (slide-up): shareable course card + social outlets + save-as-photo
// iOS system share sheet (UIActivityViewController look). Native-style, not in-app branded.
function FrRunShareSheet({ c, app, params }) {
  const nav = app.nav;
  const run = (params && params.run) || (window.FR_ACTS && FR_ACTS[0]) || {};
  const dark = c.dark;
  const dist = (run.dist != null ? run.dist : 5.2);
  const distStr = dist.toFixed ? dist.toFixed(2) : dist;
  // iOS palette
  const sheet = dark ? '#1C1C1E' : '#F2F2F7';
  const cell = dark ? '#2C2C2E' : '#FFFFFF';
  const txt = dark ? '#FFFFFF' : '#000000';
  const sub = dark ? 'rgba(235,235,245,0.6)' : 'rgba(60,60,67,0.6)';
  const sep = dark ? 'rgba(84,84,88,0.5)' : 'rgba(60,60,67,0.13)';
  const blue = '#0A84FF';
  const SF = '-apple-system, "SF Pro Text", Pretendard, system-ui, sans-serif';

  const apps = [
    { lbl: 'AirDrop', bg: 'linear-gradient(180deg,#3FA7FF,#0A6CFF)', el: <FrCIcon name="sparkle" size={22} color="#fff" sw={2} /> },
    { lbl: '메시지', bg: 'linear-gradient(180deg,#5BF675,#1Fca42)', el: <FrChatGlyph /> },
    { lbl: '카카오톡', bg: '#FEE500', el: <FrXIcon name="chat" size={22} color="#3B1E1E" sw={1.9} /> },
    { lbl: 'Instagram', bg: 'linear-gradient(45deg,#FEDA75,#FA7E1E,#D62976,#962FBF)', el: <FrCameraGlyph /> },
    { lbl: '메일', bg: 'linear-gradient(180deg,#4DA2FF,#0A78FF)', el: <FrMailGlyph /> },
  ];
  const actions = [
    ['사진에 저장', 'photo'],
    ['이미지 복사', 'copy'],
    ['파일에 저장', 'folder'],
    ['프린트', 'print'],
  ];
  const close = () => nav.pop();

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 93, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
      <div onClick={close} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.4)', animation: 'frfadein .2s' }} />
      <div style={{ position: 'relative', margin: 8, background: sheet, borderRadius: 13, overflow: 'hidden', animation: 'frsheetup .32s cubic-bezier(.22,.61,.36,1)', boxShadow: '0 -2px 30px rgba(0,0,0,0.25)' }}>
        {/* header: preview cell + close */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px 14px', borderBottom: `1px solid ${sep}` }}>
          <div style={{ width: 56, height: 56, borderRadius: 11, overflow: 'hidden', flexShrink: 0, background: '#0C1206' }}>
            <FrCourseMap seed={run.seed || 'me-share-course'} width={56} height={56} radius={0} loop drawAnim={false} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: SF, fontSize: 16, fontWeight: 600, color: txt, letterSpacing: -0.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{run.title || '자유 러닝'}</div>
            <div style={{ fontFamily: SF, fontSize: 13, color: sub, letterSpacing: -0.2, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>FreshRun · {distStr}km · {run.dur || '00:00'}</div>
          </div>
          <button onClick={close} aria-label="닫기" style={{ width: 30, height: 30, borderRadius: 999, border: 'none', background: dark ? 'rgba(120,120,128,0.36)' : 'rgba(120,120,128,0.16)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <FrIcon name="close" size={15} color={sub} sw={2.4} />
          </button>
        </div>

        {/* app/AirDrop row */}
        <div style={{ display: 'flex', gap: 16, overflowX: 'auto', padding: '16px 16px 18px', WebkitOverflowScrolling: 'touch', borderBottom: `1px solid ${sep}` }}>
          {apps.map((a, i) => (
            <button key={i} onClick={close} style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 7, flexShrink: 0, width: 60 }}>
              <span style={{ width: 60, height: 60, borderRadius: 15, background: a.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 1px 3px rgba(0,0,0,0.18)' }}>{a.el}</span>
              <span style={{ fontFamily: SF, fontSize: 11, color: txt, letterSpacing: -0.1, textAlign: 'center', lineHeight: 1.2, width: 64 }}>{a.lbl}</span>
            </button>
          ))}
        </div>

        {/* action list */}
        <div style={{ background: cell, margin: 10, borderRadius: 12, overflow: 'hidden' }}>
          {actions.map(([lbl, ic], i) => (
            <button key={i} onClick={close} style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, background: 'none', border: 'none', cursor: 'pointer', padding: '14px 16px', borderTop: i ? `1px solid ${sep}` : 'none', WebkitTapHighlightColor: 'transparent' }}>
              <span style={{ fontFamily: SF, fontSize: 16, color: txt, letterSpacing: -0.3 }}>{lbl}</span>
              <FrIosActionIcon name={ic} color={txt} />
            </button>
          ))}
        </div>

        {/* cancel */}
        <button onClick={close} style={{ width: 'calc(100% - 20px)', margin: '0 10px 10px', height: 52, borderRadius: 12, border: 'none', background: cell, color: blue, fontFamily: SF, fontSize: 17, fontWeight: 600, letterSpacing: -0.3, cursor: 'pointer' }}>취소</button>
        <div style={{ height: 8 }} />
      </div>
    </div>
  );
}

// small glyphs for the iOS app icons
function FrChatGlyph() { return <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M5 5.5h14a1.5 1.5 0 011.5 1.5v8a1.5 1.5 0 01-1.5 1.5H9l-4 3v-3H5A1.5 1.5 0 013.5 15V7A1.5 1.5 0 015 5.5z" fill="#fff" /></svg>; }
function FrCameraGlyph() { return <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2"><rect x="3.5" y="3.5" width="17" height="17" rx="5" /><circle cx="12" cy="12" r="4.2" /><circle cx="17.3" cy="6.7" r="1.1" fill="#fff" stroke="none" /></svg>; }
function FrMailGlyph() { return <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><rect x="3.5" y="6" width="17" height="12" rx="2.4" fill="#fff" /><path d="M4.5 7.5l7.5 5.5 7.5-5.5" stroke="#0A78FF" strokeWidth="1.7" fill="none" strokeLinecap="round" /></svg>; }
function FrIosActionIcon({ name, color }) {
  const p = {
    photo: <><rect x="3.5" y="5.5" width="17" height="13" rx="2.5" /><circle cx="8.5" cy="10" r="1.6" /><path d="M5 17l4.5-4 3 2.5 3-3L19 16" strokeLinecap="round" strokeLinejoin="round" /></>,
    copy: <><rect x="8" y="8" width="11" height="11" rx="2.4" /><path d="M5 14.5V6.5A2 2 0 017 4.5h7" strokeLinecap="round" /></>,
    folder: <path d="M3.5 7a2 2 0 012-2h3.2l2 2.2H18.5a2 2 0 012 2v7.3a2 2 0 01-2 2h-13a2 2 0 01-2-2z" strokeLinejoin="round" />,
    print: <><path d="M7 9V4.5h10V9M7 17H5.5A1.5 1.5 0 014 15.5v-4A1.5 1.5 0 015.5 10h13a1.5 1.5 0 011.5 1.5v4A1.5 1.5 0 0118.5 17H17" strokeLinecap="round" strokeLinejoin="round" /><rect x="7" y="14" width="10" height="5.5" rx="1" /></>,
  }[name];
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.7">{p}</svg>;
}

Object.assign(window, { FrChallengeDone, FrPersonalBest, FrPremium, FrConfetti, FrRunShareSheet });
