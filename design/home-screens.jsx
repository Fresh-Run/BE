// FreshRun — run detail bottom sheet + composed home screens (A & B).
const DSF = window.FR_FONT;

// ── run detail / comments bottom sheet ─────────────────
function FrRunDetailSheet({ c, item, st, on, onClose }) {
  const [draft, setDraft] = React.useState('');
  const [extra, setExtra] = React.useState([]);
  if (!item) return null;
  const base = FR_COMMENTS[item.id] || [];
  const all = base.concat(extra);
  const send = () => { const t = draft.trim(); if (!t) return; setExtra((x) => x.concat([['지윤', t]])); setDraft(''); };
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 80, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.42)', animation: 'frfadein .2s' }} />
      <div style={{ position: 'relative', background: c.bg, borderRadius: '26px 26px 0 0', maxHeight: '88%', display: 'flex', flexDirection: 'column', boxShadow: '0 -10px 40px rgba(0,0,0,0.25)', animation: 'frsheetup .3s cubic-bezier(.22,.61,.36,1)' }}>
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 10 }}>
          <div style={{ width: 38, height: 5, borderRadius: 99, background: c.fieldBorder }} />
        </div>
        <div style={{ overflowY: 'auto', padding: '8px 20px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0 14px' }}>
            <FrAvatar name={item.name} size={42} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: DSF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>{item.name}</div>
              <div style={{ fontFamily: DSF, fontSize: 12, color: c.faint, letterSpacing: -0.2 }}>{item.area} · {item.ago}</div>
            </div>
            <button onClick={onClose} style={{ width: 34, height: 34, borderRadius: 999, border: `1px solid ${c.border}`, background: c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FrIcon name="close" size={17} color={c.sub} sw={2} />
            </button>
          </div>

          <FrMiniMap seed={item.seed} width="100%" height={188} radius={18} hero />

          <div style={{ fontFamily: DSF, fontSize: 18, fontWeight: 700, color: c.text, letterSpacing: -0.5, margin: '14px 0 0' }}>{item.title}</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 9 }}>
            {item.tags.map(t => <FrTag key={t} c={c} t={t} />)}
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
            {[[item.dist + ' km', '거리'], [item.dur, '시간'], [item.pace + ' /km', '평균 페이스']].map((m, i) => (
              <div key={i} style={{ flex: 1, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 14, padding: '12px 10px', textAlign: 'center' }}>
                <div style={{ fontFamily: DSF, fontSize: 16.5, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap' }}>{m[0]}</div>
                <div style={{ fontFamily: DSF, fontSize: 11, color: c.faint, marginTop: 3 }}>{m[1]}</div>
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <button onClick={() => on.like(item.id)} style={{ flex: 1, height: 46, borderRadius: 13, border: `1px solid ${st.liked ? c.danger : c.border}`, background: st.liked ? c.danger + '14' : c.surface, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7 }}>
              <FrIcon name="heart" size={18} color={st.liked ? c.danger : c.sub} fill={st.liked ? c.danger : 'none'} sw={1.9} />
              <span style={{ fontFamily: DSF, fontSize: 13.5, fontWeight: 700, color: st.liked ? c.danger : c.sub, letterSpacing: -0.2 }}>{item.kudos + (st.liked ? 1 : 0)}</span>
            </button>
            <button onClick={() => { onClose(); on.run(item); }} style={{ flex: 2, height: 46, borderRadius: 13, border: 'none', background: c.accent, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, boxShadow: `0 5px 14px ${c.accent}55` }}>
              <FrIcon name="route" size={17} color={c.accentText} sw={2.1} />
              <span style={{ fontFamily: DSF, fontSize: 14, fontWeight: 700, color: c.accentText, letterSpacing: -0.3, whiteSpace: 'nowrap' }}>이 코스 달리기</span>
            </button>
          </div>

          <div style={{ fontFamily: DSF, fontSize: 13.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, margin: '22px 0 4px' }}>댓글 {all.length}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, paddingBottom: 14 }}>
            {all.length === 0 && <div style={{ fontFamily: DSF, fontSize: 13, color: c.faint, letterSpacing: -0.2, padding: '8px 0' }}>첫 댓글을 남겨보세요.</div>}
            {all.map((cm, i) => (
              <div key={i} style={{ display: 'flex', gap: 9 }}>
                <FrAvatar name={cm[0]} size={30} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ fontFamily: DSF, fontSize: 12.5, fontWeight: 700, color: c.text, letterSpacing: -0.2 }}>{cm[0]}</span>
                  <p style={{ fontFamily: DSF, fontSize: 13.5, color: c.sub, letterSpacing: -0.2, lineHeight: 1.45, margin: '2px 0 0', wordBreak: 'break-word' }}>{cm[1]}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 9, alignItems: 'center', padding: '12px 20px 26px', borderTop: `1px solid ${c.border}`, background: c.surface }}>
          <FrAvatar name="지윤" size={32} />
          <input value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && send()} placeholder="댓글 달기..."
            style={{ flex: 1, minWidth: 0, height: 42, borderRadius: 999, border: `1.5px solid ${c.fieldBorder}`, background: c.field, padding: '0 16px', fontFamily: DSF, fontSize: 14, color: c.text, outline: 'none', letterSpacing: -0.2 }} />
          <button onClick={send} disabled={!draft.trim()} style={{ height: 42, padding: '0 16px', borderRadius: 999, border: 'none', background: draft.trim() ? c.accent : c.fieldBorder, color: draft.trim() ? c.accentText : c.faint, fontFamily: DSF, fontSize: 13.5, fontWeight: 700, letterSpacing: -0.2, cursor: draft.trim() ? 'pointer' : 'default', whiteSpace: 'nowrap' }}>게시</button>
        </div>
      </div>
    </div>
  );
}

// ── shared feed state hook ─────────────────────────────
function useFrFeed(app) {
  const nav = app && app.nav;
  const [likes, setLikes] = React.useState({});
  const [open, setOpen] = React.useState(null);
  const on = {
    like: (id) => setLikes((s) => ({ ...s, [id]: !s[id] })),
    save: (item) => app && app.toggleBookmark && app.toggleBookmark(item),
    open: (item) => setOpen(item),
    run: (item) => nav && nav.push('coursePreview', { item }),
  };
  const stFor = (id) => ({ liked: !!likes[id], saved: !!(app && app.isBookmarked && app.isBookmarked(id)) });
  return { on, stFor, open, setOpen };
}

// ── Layout A ───────────────────────────────────────────
function FrHomeA({ c, app }) {
  const f = useFrFeed(app);
  const userName = (app && app.displayName && app.displayName.trim()) || '지윤';
  return (
    <div style={frPage(c)}>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        <div style={{ padding: '62px 20px 0' }}><FrGreeting c={c} name={userName} /></div>
        <div style={{ padding: '16px 20px 0' }}><FrWeatherBanner c={c} /></div>
        <div style={{ padding: '22px 20px 8px' }}><FrFeedLabel c={c} /></div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '4px 20px 24px' }}>
          {FR_FEED.map(item => <FrRunCardA key={item.id} c={c} item={item} st={f.stFor(item.id)} on={f.on} />)}
        </div>
      </div>
      <FrTabBar c={c} />
      {f.open && <FrRunDetailSheet c={c} item={f.open} st={f.stFor(f.open.id)} on={f.on} onClose={() => f.setOpen(null)} />}
    </div>
  );
}

// ── Layout B ───────────────────────────────────────────
function FrHomeB({ c, app, onTab }) {
  const f = useFrFeed(app);
  const [wxOpen, setWxOpen] = React.useState(false);
  const [tab, setTab] = React.useState('친구');
  const userName = (app && app.displayName && app.displayName.trim()) || '지윤';
  const list = tab === '전체'
    ? FR_NEARBY.concat(FR_FEED).slice().sort((a, b) => a.away - b.away)
    : FR_FEED;
  return (
    <div style={frPage(c)}>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        <div style={{ padding: '62px 20px 0' }}><FrGreeting c={c} compact name={userName} onBell={app && app.nav ? () => app.nav.push('notifications') : undefined} /></div>
        <div style={{ padding: '14px 20px 0' }}><FrWeatherStrip c={c} onClick={() => app && app.nav ? app.nav.push('weatherDetail') : setWxOpen(true)} /></div>
        <div style={{ padding: '22px 20px 12px' }}><FrFeedTabs c={c} tab={tab} setTab={setTab} /></div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '2px 20px 24px' }}>
          {list.map(item => <FrRunCardB key={item.id} c={c} item={item} st={f.stFor(item.id)} on={f.on} showAway={tab === '전체'} />)}
        </div>
        {app && app.premium ? (
          <div style={{ padding: '0 20px 26px' }}>
            <FrAIBanner c={c} onClick={() => app.nav && app.nav.push('coursePreview', { item: { id: 'ai-rec', title: '오늘의 AI 추천 코스', dist: 7.4, dur: '43:00', pace: "5'48\"", area: '한강 · 한적한 코스', tags: ['한적함', '평지'], seed: 'ai-rec-today', name: 'FreshRun AI' } })} />
          </div>
        ) : (
          <div style={{ padding: '0 20px 26px' }}>
            <FrAIBanner c={c} locked onClick={() => app && app.nav && app.nav.push('premium')} />
          </div>
        )}
      </div>
      <FrTabBar c={c} active="home" onTab={onTab} />
      {wxOpen && <FrWeatherBubble c={c} onClose={() => setWxOpen(false)} />}
      {f.open && <FrRunDetailSheet c={c} item={f.open} st={f.stFor(f.open.id)} on={f.on} onClose={() => f.setOpen(null)} />}
    </div>
  );
}

Object.assign(window, { FrRunDetailSheet, useFrFeed, FrHomeA, FrHomeB });
