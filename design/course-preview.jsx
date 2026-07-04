// FreshRun — 코스 미리보기 (Course preview + confirm). Reached from a feed card's
// "이 코스 달리기". Confirm → live tracking loaded with this course.
const CPF = window.FR_FONT;

// estimate dur/pace when a course card doesn't carry them (e.g. 인기 코스)
function frCourseStats(item) {
  const dist = +item.dist;
  let pace = item.pace, dur = item.dur;
  if (!pace) { const ps = 320; const m = Math.floor(ps / 60), s = ps % 60; pace = `${m}'${String(s).padStart(2, '0')}"`; }
  if (!dur) { const tot = Math.round(dist * 320); const mm = Math.floor(tot / 60), ss = tot % 60; dur = `${mm}:${String(ss).padStart(2, '0')}`; }
  return { dist, pace, dur, area: item.area || '서울', tags: item.tags || [], title: item.title, seed: item.seed, name: item.name };
}

function FrCoursePreview({ c, app, params }) {
  const nav = app.nav;
  const item = (params && params.item) || {};
  const s = frCourseStats(item);
  const grn = c.dark ? c.accent : '#3F8E14';
  const run = () => { nav.pop(); nav.push('tracking', { course: { ...item, ...s } }); };
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* hero map with neon route */}
        <div style={{ position: 'relative' }}>
          <FrCourseMap seed={s.seed} width="100%" height={300} radius={0} loop drawAnim={false} />
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 120, background: 'linear-gradient(180deg, rgba(8,12,4,0.55), transparent)' }} />
          <button onClick={() => nav.pop()} aria-label="뒤로" style={{ position: 'absolute', top: 54, left: 16, width: 42, height: 42, borderRadius: 999, border: 'none', background: 'rgba(12,14,10,0.6)', backdropFilter: 'blur(8px)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <FrCIcon name="back" size={20} color="#fff" sw={2.2} />
          </button>
          <div style={{ position: 'absolute', top: 56, left: '50%', transform: 'translateX(-50%)', display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(12,14,10,0.6)', backdropFilter: 'blur(8px)', borderRadius: 999, padding: '8px 14px' }}>
            <FrIcon name="route" size={14} color="#7CF03D" sw={2.2} />
            <span style={{ fontFamily: CPF, fontSize: 12.5, fontWeight: 700, color: '#fff', letterSpacing: -0.2, whiteSpace: 'nowrap' }}>코스 미리보기</span>
          </div>
          {/* author chip */}
          <div style={{ position: 'absolute', left: 16, bottom: 14, display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(12,14,10,0.55)', backdropFilter: 'blur(8px)', borderRadius: 999, padding: '5px 12px 5px 5px' }}>
            <FrAvatar name={s.name || '러너'} size={26} />
            <span style={{ fontFamily: CPF, fontSize: 12.5, fontWeight: 700, color: '#fff', letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{s.name ? `${s.name}님의 코스` : '추천 코스'}</span>
          </div>
        </div>

        <div style={{ padding: '20px 20px 0' }}>
          <h1 style={{ fontFamily: CPF, fontSize: 24, fontWeight: 700, letterSpacing: -0.7, color: c.text, margin: 0, textWrap: 'balance' }}>{s.title || '추천 코스'}</h1>
          <div style={{ display: 'flex', gap: 7, marginTop: 11, flexWrap: 'wrap' }}>
            {s.tags.map(t => <FrTag key={t} c={c} t={t} />)}
          </div>

          {/* reference stats */}
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', margin: '22px 2px 10px' }}>
            <span style={{ fontFamily: CPF, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>코스 기준 기록</span>
            <span style={{ fontFamily: CPF, fontSize: 11.5, color: c.faint, letterSpacing: -0.2 }}>원작자 기준 · 내 기록 아님</span>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            {[['ruler', s.dist.toFixed ? s.dist.toFixed(1) : s.dist, 'km', '거리'], ['clock', s.dur, '', '예상 시간'], ['pace', s.pace, '/km', '페이스']].map((m, i) => (
              <div key={i} style={{ flex: 1, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: '14px 8px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 7, boxShadow: c.shadow }}>
                {m[0] === 'pace' ? <FrXIcon name="pace" size={17} color={c.sub} sw={1.9} /> : <FrCIcon name={m[0]} size={17} color={c.sub} sw={1.9} />}
                <span style={{ fontFamily: CPF, fontSize: 16.5, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap' }}>{m[1]}<span style={{ fontSize: 10.5, color: c.faint, fontWeight: 600 }}>{m[2] ? ' ' + m[2] : ''}</span></span>
                <span style={{ fontFamily: CPF, fontSize: 11, color: c.faint, letterSpacing: -0.1 }}>{m[3]}</span>
              </div>
            ))}
          </div>

          {/* start point */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12, background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: 16, padding: '13px 15px' }}>
            <span style={{ width: 36, height: 36, borderRadius: 11, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <FrIcon name="pin" size={18} color={grn} sw={2} />
            </span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontFamily: CPF, fontSize: 11.5, fontWeight: 600, color: c.faint, letterSpacing: -0.2 }}>출발지</div>
              <div style={{ fontFamily: CPF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.area}</div>
            </div>
          </div>
        </div>
        <div style={{ height: 18 }} />
      </div>

      {/* confirm */}
      <div style={{ flexShrink: 0, padding: '16px 20px 26px', borderTop: `1px solid ${c.border}`, background: c.bg }}>
        <div style={{ fontFamily: CPF, fontSize: 16, fontWeight: 700, color: c.text, letterSpacing: -0.4, textAlign: 'center', marginBottom: 14 }}>이 코스로 뛰시겠습니까?</div>
        <button onClick={run} style={{ width: '100%', height: 56, borderRadius: 16, border: 'none', background: c.accent, color: c.accentText, fontFamily: CPF, fontSize: 16.5, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9, boxShadow: `0 6px 18px ${c.accent}55` }}>
          <FrCIcon name="play" size={19} color={c.accentText} sw={2} fill={c.accentText} />
          네, 뛸게요
        </button>
        <button onClick={() => nav.pop()} style={{ width: '100%', height: 50, borderRadius: 16, border: 'none', background: 'transparent', color: c.sub, fontFamily: CPF, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 6 }}>취소</button>
      </div>
    </div>
  );
}

Object.assign(window, { FrCoursePreview, frCourseStats });
