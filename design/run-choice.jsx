// FreshRun — "뛰러 가기" choice screen (Screen 1). Entry point of the center tab.
// Two paths: AI 맞춤 코스 (→ course form) and 자유 러닝 (→ live tracking).
const RCF = window.FR_FONT;

function FrChoiceCard({ c, premium, badge, locked, iconEl, title, body, cta, onClick }) {
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <button onClick={onClick} style={{ width: '100%', textAlign: 'left', position: 'relative', overflow: 'hidden', background: c.surface, border: `1.5px solid ${premium ? c.accent + '66' : c.border}`, borderRadius: 22, padding: 20, cursor: 'pointer', boxShadow: c.shadow, WebkitTapHighlightColor: 'transparent' }}>
      {premium && <div style={{ position: 'absolute', top: -34, right: -34, width: 130, height: 130, borderRadius: 999, background: c.accent, opacity: c.dark ? 0.13 : 0.08 }} />}
      {badge && (
        <span style={{ position: 'absolute', top: 16, right: 16, display: 'inline-flex', alignItems: 'center', gap: 4, background: grn, borderRadius: 999, padding: '5px 11px 5px 9px' }}>
          <FrXIcon name="bolt" size={12} color={c.accentText} sw={2.2} fill={c.accentText} />
          <span style={{ fontFamily: RCF, fontSize: 10.5, fontWeight: 800, letterSpacing: 0.6, color: c.accentText }}>PREMIUM</span>
        </span>
      )}
      <div style={{ position: 'relative' }}>
        <span style={{ display: 'flex', width: 54, height: 54, borderRadius: 16, alignItems: 'center', justifyContent: 'center', background: premium ? `linear-gradient(135deg, ${c.accent}, ${c.accent}aa)` : c.accent, boxShadow: `0 6px 16px ${c.accent}44` }}>
          {iconEl}
        </span>
        <div style={{ fontFamily: RCF, fontSize: 18.5, fontWeight: 700, letterSpacing: -0.5, color: c.text, marginTop: 16 }}>{title}</div>
        <p style={{ fontFamily: RCF, fontSize: 13.5, lineHeight: 1.55, color: c.sub, letterSpacing: -0.2, margin: '7px 0 0', textWrap: 'pretty' }}>{body}</p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginTop: 15 }}>
          {locked && <FrXIcon name="lock" size={14} color={grn} sw={2.1} />}
          <span style={{ fontFamily: RCF, fontSize: 14, fontWeight: 700, color: grn, letterSpacing: -0.3 }}>{cta}</span>
          <FrXIcon name="chevright" size={16} color={grn} sw={2.4} />
        </div>
      </div>
    </button>
  );
}

function FrMiniStat({ c, label, valueEl }) {
  return (
    <div style={{ flex: 1, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: '13px 15px', boxShadow: c.shadow }}>
      <div style={{ fontFamily: RCF, fontSize: 11.5, fontWeight: 600, letterSpacing: 0.2, color: c.faint, whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 5, marginTop: 8 }}>{valueEl}</div>
    </div>
  );
}

// saved-course card (someone else's bookmarked route)
function FrSavedCourseCard({ c, item, onOpen, onUnsave }) {
  const s = window.frCourseStats ? window.frCourseStats(item) : item;
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <div onClick={() => onOpen(item)} style={{ position: 'relative', display: 'flex', gap: 13, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 12, boxShadow: c.shadow, cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
      <FrMiniMap seed={item.seed} width={82} height={82} radius={14} />
      <div style={{ flex: 1, minWidth: 0, paddingRight: 26 }}>
        <div style={{ fontFamily: RCF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.title}</div>
        {s.tags && s.tags.length > 0 && (
          <div style={{ fontFamily: RCF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.tags.join(' · ')}</div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
          <span style={{ fontFamily: RCF, fontSize: 13, fontWeight: 700, color: c.text, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{(+s.dist).toFixed(1)}<span style={{ fontSize: 10, color: c.faint, fontWeight: 600 }}> km</span></span>
          <span style={{ width: 3, height: 3, borderRadius: 99, background: c.fieldBorder }} />
          <span style={{ fontFamily: RCF, fontSize: 13, fontWeight: 700, color: c.text, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{s.dur}</span>
          <span style={{ width: 3, height: 3, borderRadius: 99, background: c.fieldBorder }} />
          <span style={{ fontFamily: RCF, fontSize: 13, fontWeight: 700, color: c.text, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{s.pace}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 9 }}>
          <FrAvatar name={s.name || '러너'} size={18} />
          <span style={{ fontFamily: RCF, fontSize: 11.5, color: c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{s.name ? `${s.name} 코스` : '추천 코스'}</span>
        </div>
      </div>
      <button onClick={(e) => { e.stopPropagation(); onUnsave(item); }} aria-label="저장 해제" style={{ position: 'absolute', top: 10, right: 10, width: 30, height: 30, borderRadius: 999, border: 'none', background: 'transparent', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', WebkitTapHighlightColor: 'transparent' }}>
        <FrIcon name="bookmark" size={19} color={grn} fill={grn} sw={1.9} />
      </button>
    </div>
  );
}

function FrSavedEmpty({ c }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 13, background: c.surfaceAlt, border: `1px dashed ${c.fieldBorder}`, borderRadius: 18, padding: '28px 24px' }}>
      <span style={{ width: 52, height: 52, borderRadius: 16, background: c.surface, border: `1px solid ${c.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <FrIcon name="bookmark" size={24} color={c.faint} sw={1.7} />
      </span>
      <p style={{ fontFamily: RCF, fontSize: 13.5, lineHeight: 1.55, color: c.sub, letterSpacing: -0.2, margin: 0, maxWidth: 230, textWrap: 'balance' }}>아직 저장된 코스가 없어요. 피드에서 마음에 드는 코스를 북마크해보세요.</p>
    </div>
  );
}

// filter helpers
const FR_REGION_KEYS = ['한강', '뚝섬', '남산', '올림픽', '양재천', '서울숲', '성수', '응봉', '중랑', '잠실', '반포', '여의도'];
function frRegionOf(item) {
  const a = item.area || '';
  return FR_REGION_KEYS.find(k => a.includes(k)) || a.split(/[ ·]/)[0] || '기타';
}
const FR_DIST_RANGES = [['~5km', 0, 5], ['5–10km', 5, 10], ['10km+', 10, 9999]];

function FrFilterChip({ c, label, active, onClick }) {
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <button onClick={onClick} style={{ flexShrink: 0, height: 34, padding: '0 14px', borderRadius: 999, cursor: 'pointer', background: active ? c.accentDim : c.surface, border: `1.5px solid ${active ? c.accent : c.border}`, fontFamily: RCF, fontSize: 13, fontWeight: 700, color: active ? grn : c.sub, letterSpacing: -0.2, whiteSpace: 'nowrap', WebkitTapHighlightColor: 'transparent' }}>{label}</button>
  );
}

// full saved-courses list with filters (pushed screen)
function FrSavedCourses({ c, app }) {
  const nav = app.nav;
  const all = (app && app.bookmarks) || [];
  const [regions, setRegions] = React.useState([]);
  const [dists, setDists] = React.useState([]);
  const [tags, setTags] = React.useState([]);
  const [sort, setSort] = React.useState('recent');

  const regionOpts = [...new Set(all.map(frRegionOf))];
  const tagOpts = [...new Set(all.flatMap(x => x.tags || []))];
  const toggle = (setter, arr, v) => setter(arr.includes(v) ? arr.filter(x => x !== v) : arr.concat([v]));
  const anyActive = regions.length || dists.length || tags.length;
  const clearAll = () => { setRegions([]); setDists([]); setTags([]); };

  let list = all.filter(item => {
    if (regions.length && !regions.includes(frRegionOf(item))) return false;
    if (dists.length) {
      const d = +item.dist;
      const ok = dists.some(label => { const r = FR_DIST_RANGES.find(x => x[0] === label); return d >= r[1] && d < r[2]; });
      if (!ok) return false;
    }
    if (tags.length && !(item.tags || []).some(t => tags.includes(t))) return false;
    return true;
  });
  if (sort === 'dist') list = list.slice().sort((a, b) => (+a.dist) - (+b.dist));

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="저장된 코스들" onBack={() => nav.pop()} />
      {all.length > 0 && (
        <div style={{ flexShrink: 0, borderBottom: `1px solid ${c.border}`, background: c.bg }}>
          {/* sort + clear */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px 0' }}>
            <div style={{ display: 'flex', gap: 3, background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: 999, padding: 3 }}>
              {[['recent', '최신순'], ['dist', '거리순']].map(([v, l]) => (
                <button key={v} onClick={() => setSort(v)} style={{ height: 28, padding: '0 14px', borderRadius: 999, border: 'none', cursor: 'pointer', background: sort === v ? c.surface : 'transparent', boxShadow: sort === v ? c.shadow : 'none', fontFamily: RCF, fontSize: 12.5, fontWeight: 700, color: sort === v ? c.text : c.faint, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{l}</button>
              ))}
            </div>
            {anyActive ? (
              <button onClick={clearAll} style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'none', border: 'none', padding: 4, cursor: 'pointer', fontFamily: RCF, fontSize: 12.5, fontWeight: 700, color: c.danger, letterSpacing: -0.2 }}>
                <FrIcon name="close" size={14} color={c.danger} sw={2.2} /> 초기화
              </button>
            ) : <span style={{ fontFamily: RCF, fontSize: 12.5, color: c.faint, fontWeight: 600 }}>{list.length}개</span>}
          </div>
          {/* chips */}
          <div style={{ display: 'flex', gap: 8, overflowX: 'auto', padding: '12px 16px 12px', WebkitOverflowScrolling: 'touch' }}>
            {FR_DIST_RANGES.map(([l]) => <FrFilterChip key={l} c={c} label={l} active={dists.includes(l)} onClick={() => toggle(setDists, dists, l)} />)}
            {regionOpts.length > 0 && <span style={{ flexShrink: 0, width: 1, background: c.border, margin: '4px 2px' }} />}
            {regionOpts.map(r => <FrFilterChip key={r} c={c} label={r} active={regions.includes(r)} onClick={() => toggle(setRegions, regions, r)} />)}
            {tagOpts.length > 0 && <span style={{ flexShrink: 0, width: 1, background: c.border, margin: '4px 2px' }} />}
            {tagOpts.map(t => <FrFilterChip key={t} c={c} label={t} active={tags.includes(t)} onClick={() => toggle(setTags, tags, t)} />)}
          </div>
        </div>
      )}
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', padding: '14px 20px 28px' }}>
        {all.length === 0 ? <FrSavedEmpty c={c} />
          : list.length === 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 14, padding: '36px 24px' }}>
              <span style={{ width: 52, height: 52, borderRadius: 16, background: c.surfaceAlt, border: `1px solid ${c.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <FrXIcon name="target" size={24} color={c.faint} sw={1.7} />
              </span>
              <p style={{ fontFamily: RCF, fontSize: 14, color: c.sub, letterSpacing: -0.2, margin: 0 }}>조건에 맞는 코스가 없어요.</p>
              <button onClick={clearAll} style={{ height: 42, padding: '0 20px', borderRadius: 999, border: `1.5px solid ${c.accent}`, background: c.accentDim, color: c.dark ? c.accent : '#3F8E14', fontFamily: RCF, fontSize: 13.5, fontWeight: 700, letterSpacing: -0.2, cursor: 'pointer' }}>필터 초기화</button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {list.map(item => <FrSavedCourseCard key={item.id} c={c} item={item} onOpen={(it) => nav.push('coursePreview', { item: it })} onUnsave={(it) => app.toggleBookmark(it)} />)}
            </div>
          )}
      </div>
    </div>
  );
}

function FrRunChoice({ c, app, onAI, onFree, tabBar }) {
  const grn = c.dark ? c.accent : '#3F8E14';
  const units = (app && app.units) || 'km';
  const premium = !!(app && app.premium);
  // Lite users get a few free AI generations/week; lock only once the limit is hit.
  const locked = !premium && ((app && app.aiGenCount) || 0) >= ((app && app.aiLimit) || 3);
  const aiTap = locked ? () => app.nav.push('premium') : onAI;
  const weekKm = units === 'mi' ? (12.4 * 0.621371).toFixed(1) : '12.4';
  const weekU = units === 'mi' ? 'mi' : 'km';
  return (
    <div style={frPage(c)}>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        <div style={{ padding: '62px 22px 0' }}>
          <h1 style={{ fontFamily: RCF, fontSize: 25, fontWeight: 700, letterSpacing: -0.7, color: c.text, margin: 0, textWrap: 'balance' }}>오늘 어떻게 달릴까요?</h1>
          <p style={{ fontFamily: RCF, fontSize: 14, lineHeight: 1.5, color: c.sub, letterSpacing: -0.3, margin: '8px 0 0', textWrap: 'pretty' }}>당신의 컨디션에 맞는 완벽한 코스를 선택하세요.</p>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, padding: '22px 20px 0' }}>
          <FrChoiceCard c={c} premium badge={premium} locked={locked} onClick={aiTap}
            iconEl={<FrCIcon name="sparkle" size={26} color={c.accentText} sw={2} fill={c.accentText} />}
            title="AI 맞춤 코스로 시작"
            body="현재 위치, 날씨, 개인 체력을 분석하여 가장 쾌적한 최적의 코스를 제안합니다."
            cta={locked ? '프리미엄으로 잠금 해제' : '추천 코스 보기'} />
          <FrChoiceCard c={c} onClick={onFree}
            iconEl={<FrXIcon name="runner" size={26} color={c.accentText} sw={2.2} />}
            title="지금 바로 자유 러닝"
            body="익숙한 나만의 경로를 따라 자유롭게 달리세요. 거리와 시간을 실시간으로 기록합니다."
            cta="트래킹 시작하기" />
        </div>

        <div style={{ display: 'flex', gap: 12, padding: '16px 20px 0' }}>
          <FrMiniStat c={c} label="주간 누적 거리" valueEl={<>
            <span style={{ fontFamily: RCF, fontSize: 22, fontWeight: 700, letterSpacing: -0.7, color: c.text }}>{weekKm}</span>
            <span style={{ fontFamily: RCF, fontSize: 13, fontWeight: 600, color: c.faint }}>{weekU}</span>
          </>} />
          <FrMiniStat c={c} label="현재 온도" valueEl={<>
            <FrIcon name="sun" size={18} color="#E8A23D" sw={1.7} />
            <span style={{ fontFamily: RCF, fontSize: 22, fontWeight: 700, letterSpacing: -0.7, color: c.text }}>18°</span>
          </>} />
        </div>

        <div style={{ padding: '14px 20px 24px' }}>
          <div style={{ position: 'relative', borderRadius: 18, overflow: 'hidden', border: `1px solid ${c.border}`, boxShadow: c.shadow }}>
            <FrCourseMap seed="me-seoulforest-loc" width="100%" height={148} radius={0} loop drawAnim={false} dimGrid />
            <div style={{ position: 'absolute', top: 12, left: 12, display: 'inline-flex', alignItems: 'center', gap: 6, background: c.surface, borderRadius: 999, padding: '7px 13px', boxShadow: '0 2px 10px rgba(0,0,0,0.18)' }}>
              <FrIcon name="pin" size={14} color={grn} sw={2} />
              <span style={{ fontFamily: RCF, fontSize: 12.5, fontWeight: 700, color: c.text, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>현재 위치: 서울숲 공원</span>
            </div>
          </div>
        </div>

        {(() => {
          const saved = (app && app.bookmarks) || [];
          const recent = saved.slice(0, 2).map(x => x.title).join(', ');
          return (
            <div style={{ padding: '4px 20px 28px' }}>
              <button onClick={() => app.nav.push('savedCourses')} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 13, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 15, cursor: 'pointer', boxShadow: c.shadow, WebkitTapHighlightColor: 'transparent' }}>
                <span style={{ flexShrink: 0, width: 44, height: 44, borderRadius: 13, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <FrIcon name="bookmark" size={21} color={grn} fill={saved.length ? grn : 'none'} sw={1.9} />
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: RCF, fontSize: 15.5, fontWeight: 700, color: c.text, letterSpacing: -0.4 }}>저장된 코스들</div>
                  <div style={{ fontFamily: RCF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, marginTop: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {saved.length === 0 ? '피드에서 마음에 드는 코스를 북마크해보세요' : (recent || `${saved.length}개 코스`)}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexShrink: 0 }}>
                  {saved.length > 0 && <span style={{ fontFamily: RCF, fontSize: 12.5, fontWeight: 700, color: grn, letterSpacing: -0.2, background: c.accentDim, borderRadius: 999, padding: '4px 10px', whiteSpace: 'nowrap' }}>{saved.length}개</span>}
                  <FrXIcon name="chevright" size={18} color={c.faint} sw={2.2} />
                </div>
              </button>
            </div>
          );
        })()}
      </div>
      {tabBar}
    </div>
  );
}

Object.assign(window, { FrRunChoice, FrChoiceCard, FrMiniStat, FrSavedCourseCard, FrSavedCourses, FrSavedEmpty });
