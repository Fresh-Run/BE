// FreshRun — 크루 생성 (Create Crew). Reuses settings/profile form primitives.
const CCF = window.FR_FONT;

// reusable selectable chip row (single or multi)
function FrCcChip({ c, label, on, onClick }) {
  const grn = c.dark ? c.accent : '#3C7A14';
  return (
    <button onClick={onClick} style={{ flexShrink: 0, height: 38, padding: '0 15px', borderRadius: 999, cursor: 'pointer', background: on ? c.accentDim : c.surface, border: `1.5px solid ${on ? c.accent : c.border}`, fontFamily: CCF, fontSize: 13.5, fontWeight: 700, color: on ? grn : c.sub, letterSpacing: -0.2, whiteSpace: 'nowrap', WebkitTapHighlightColor: 'transparent' }}>{label}</button>
  );
}

const FR_CREW_COLORS = ['#74E827', '#2F8FE8', '#E8703D', '#A24DE8', '#E8B53D'];

function FrCrewCreate({ c, app }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3C7A14';
  const me = (app && app.displayName) || '지윤';
  const [form, setForm] = React.useState({
    name: '', desc: '', area: '성수동 서울숲', radius: 3,
    sport: '러닝', level: '무관', maxMembers: 30, privacy: '공개',
    days: ['화', '목'], time: '오전 6:30',
    challengeOn: true, goal: 50, period: 7, color: '#74E827',
  });
  const f = (k, v) => setForm(s => ({ ...s, [k]: v }));
  const toggleDay = (d) => setForm(s => ({ ...s, days: s.days.includes(d) ? s.days.filter(x => x !== d) : s.days.concat([d]) }));
  const valid = form.name.trim().length >= 2;
  const submit = () => {
    if (!valid) return;
    const crew = {
      id: 'cr-' + Date.now(), type: 'crew', owner: true, name: form.name.trim(), desc: form.desc.trim(),
      members: 6, area: form.area, radius: form.radius, myRank: 1, seed: 'crew-new-' + (Date.now() % 9999), color: form.color,
      sport: form.sport, level: form.level, maxMembers: form.maxMembers, privacy: form.privacy,
      days: form.days, time: form.time,
      challenge: form.challengeOn
        ? { title: '첫 챌린지', done: 0, goal: form.goal, days: form.period }
        : { title: '챌린지 없음', done: 0, goal: form.goal, days: 0, none: true },
      ranking: [
        { name: me, km: 0, me: true },
        { name: '이서연', km: 0 }, { name: '박지호', km: 0 }, { name: '최유진', km: 0 },
        { name: '한소희', km: 0 }, { name: '윤재호', km: 0 },
      ],
      managers: [],
      announcements: [],
      requests: form.privacy === '승인제' ? [
        { id: 'rq1', name: '정민서', sub: '페이스 5\'10" · 주 4회 · 성수', when: '10분 전' },
        { id: 'rq2', name: '강다은', sub: '페이스 6\'00" · 주 2회 · 뚝섬', when: '1시간 전' },
        { id: 'rq3', name: '오세훈', sub: '페이스 4\'45" · 주 5회 · 한강', when: '어제' },
      ] : [],
    };
    app.addCrew(crew);
    nav.push('crewCreated', { name: crew.name, color: crew.color, crew });
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="크루 생성" onBack={() => nav.pop()} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* identity preview */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '16px 20px 4px' }}>
          <div style={{ width: 76, height: 76, borderRadius: 22, background: form.color, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 8px 20px ${form.color}55` }}>
            <FrIcon name="users" size={34} color="#0D1A06" sw={2} />
          </div>
          <div style={{ fontFamily: CCF, fontSize: 16, fontWeight: 700, color: form.name.trim() ? c.text : c.faint, letterSpacing: -0.4, marginTop: 12 }}>{form.name.trim() || '크루 이름'}</div>
        </div>

        {/* 기본 정보 */}
        <FrSetGroup c={c} title="기본 정보">
          <FrField c={c} label="크루 이름" value={form.name} onChange={(v) => f('name', v.slice(0, 20))} placeholder="예: 성수 새벽 크루" />
          <FrField c={c} label="한 줄 소개" value={form.desc} onChange={(v) => f('desc', v.slice(0, 40))} placeholder="크루를 한 문장으로 소개해요" />
        </FrSetGroup>

        {/* 크루 컬러 */}
        <div style={{ padding: '0 20px' }}>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 8px' }}>크루 컬러</div>
          <div style={{ display: 'flex', gap: 12, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 16, boxShadow: c.shadow }}>
            {FR_CREW_COLORS.map(col => {
              const on = form.color === col;
              return <button key={col} onClick={() => f('color', col)} style={{ width: 40, height: 40, borderRadius: 999, background: col, border: on ? `3px solid ${c.text}` : `3px solid transparent`, cursor: 'pointer', boxShadow: on ? `0 4px 12px ${col}66` : 'none', WebkitTapHighlightColor: 'transparent' }} />;
            })}
          </div>
        </div>

        {/* 활동 지역 */}
        <FrSetGroup c={c} title="활동 지역" hint="대표 출발지를 중심으로 활동 반경 안의 러너에게 크루가 추천돼요.">
          <button onClick={() => nav.push('settingStub', { title: '출발지 변경' })} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 12, background: 'transparent', border: 'none', padding: '14px 0', cursor: 'pointer' }}>
            <span style={{ width: 36, height: 36, borderRadius: 11, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}><FrIcon name="pin" size={18} color={grn} sw={2} /></span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: CCF, fontSize: 12, fontWeight: 600, color: c.faint }}>대표 출발지</div>
              <div style={{ fontFamily: CCF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, marginTop: 2 }}>{form.area}</div>
            </div>
            <span style={{ fontFamily: CCF, fontSize: 13, fontWeight: 600, color: grn }}>변경</span>
          </button>
          <div style={{ padding: '6px 0 8px' }}>
            <FrSlider c={c} label="활동 반경" value={form.radius} min={1} max={10} step={1} fmt={(v) => v + ' km'} onChange={(v) => f('radius', v)} />
          </div>
        </FrSetGroup>

        {/* 크루 설정 */}
        <div style={{ padding: '0 20px' }}>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 8px' }}>주 종목</div>
          <div style={{ display: 'flex', gap: 9 }}>
            {['러닝', '라이딩', '워킹'].map(s => <FrCcChip key={s} c={c} label={s} on={form.sport === s} onClick={() => f('sport', s)} />)}
          </div>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '20px 4px 8px' }}>페이스 레벨</div>
          <div style={{ display: 'flex', gap: 9, flexWrap: 'wrap' }}>
            {['입문', '중급', '고급', '무관'].map(s => <FrCcChip key={s} c={c} label={s} on={form.level === s} onClick={() => f('level', s)} />)}
          </div>
        </div>

        <FrSetGroup c={c} title="모집">
          <FrStepperRow c={c} label="최대 인원" value={form.maxMembers} min={5} max={200} step={5} suffix="명" onChange={(v) => f('maxMembers', v)} />
        </FrSetGroup>
        <div style={{ padding: '0 20px' }}>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '20px 4px 8px' }}>공개 범위</div>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: '4px 16px', boxShadow: c.shadow }}>
            {[['공개', '누구나 바로 가입할 수 있어요'], ['승인제', '크루장이 가입 요청을 확인해요'], ['비공개', '초대 링크로만 가입 가능해요']].map(([lbl, sub], i, arr) => (
              <div key={lbl}>
                <FrSelectRow c={c} label={lbl} sub={sub} selected={form.privacy === lbl} onSelect={() => f('privacy', lbl)} />
                {i < arr.length - 1 && <div style={{ height: 1, background: c.border, margin: '0 -16px' }} />}
              </div>
            ))}
          </div>
        </div>

        {/* 정기 러닝 */}
        <div style={{ padding: '0 20px' }}>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 8px' }}>정기 러닝 (선택)</div>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 16, boxShadow: c.shadow }}>
            <div style={{ display: 'flex', gap: 6, justifyContent: 'space-between' }}>
              {['월', '화', '수', '목', '금', '토', '일'].map(d => {
                const on = form.days.includes(d);
                return <button key={d} onClick={() => toggleDay(d)} style={{ width: 38, height: 38, borderRadius: 999, cursor: 'pointer', background: on ? c.accent : c.surfaceAlt, border: `1px solid ${on ? c.accent : c.border}`, fontFamily: CCF, fontSize: 13.5, fontWeight: 700, color: on ? c.accentText : c.sub, WebkitTapHighlightColor: 'transparent' }}>{d}</button>;
              })}
            </div>
            <div style={{ height: 1, background: c.border, margin: '14px 0' }} />
            <FrField c={c} label="시간" value={form.time} onChange={(v) => f('time', v)} placeholder="예: 오전 6:30" />
          </div>
        </div>

        {/* 첫 챌린지 */}
        <div style={{ padding: '0 20px' }}>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 8px' }}>첫 챌린지 (선택)</div>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: '4px 16px', boxShadow: c.shadow }}>
            <FrToggleRow c={c} label="크루 챌린지 시작하기" sub="크루원과 함께 달릴 첫 목표를 만들어요" on={form.challengeOn} onChange={(v) => f('challengeOn', v)} />
            {form.challengeOn && (
              <>
                <div style={{ height: 1, background: c.border, margin: '0 -16px' }} />
                <FrStepperRow c={c} label="목표 거리" value={form.goal} min={10} max={500} step={10} suffix="km" onChange={(v) => f('goal', v)} />
                <div style={{ height: 1, background: c.border, margin: '0 -16px' }} />
                <FrStepperRow c={c} label="기간" value={form.period} min={3} max={60} step={1} suffix="일" onChange={(v) => f('period', v)} />
              </>
            )}
          </div>
        </div>

        <div style={{ height: 18 }} />
      </div>

      {/* sticky create CTA */}
      <div style={{ flexShrink: 0, padding: '14px 20px 26px', borderTop: `1px solid ${c.border}`, background: c.bg }}>
        <button disabled={!valid} onClick={submit}
          style={{ width: '100%', height: 56, borderRadius: 16, border: 'none', background: valid ? c.accent : c.surfaceAlt, color: valid ? c.accentText : c.faint, fontFamily: CCF, fontSize: 16.5, fontWeight: 700, letterSpacing: -0.3, cursor: valid ? 'pointer' : 'default', boxShadow: valid ? `0 6px 18px ${c.accent}55` : 'none' }}>크루 만들기</button>
      </div>
    </div>
  );
}

// success modal
function FrCrewCreated({ c, app, params }) {
  const nav = app.nav;
  const p = params || {};
  const col = p.color || c.accent;
  const crew = p.crew || ((app.createdCrews && app.createdCrews[0]) || null);
  const goCrew = () => { nav.reset(); if (crew) nav.push('crewDetail', { crew }); };
  const goInvite = () => { nav.reset(); if (crew) nav.push('crewDetail', { crew }); nav.push('crewInvite', { crewId: (crew && crew.id) || null, name: p.name }); };
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 92, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 28px' }}>
      <div onClick={() => { nav.pop(); nav.pop(); }} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)', animation: 'frfadein .2s' }} />
      <div style={{ position: 'relative', width: '100%', background: c.surface, borderRadius: 24, padding: '28px 22px 20px', boxShadow: '0 24px 60px rgba(0,0,0,0.4)', animation: 'frpop .32s cubic-bezier(.34,1.5,.5,1)' }}>
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <div style={{ width: 72, height: 72, borderRadius: 22, background: col, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 8px 22px ${col}66` }}>
            <FrIcon name="users" size={34} color="#0D1A06" sw={2} />
          </div>
        </div>
        <h2 style={{ fontFamily: CCF, fontSize: 21, fontWeight: 700, color: c.text, letterSpacing: -0.5, textAlign: 'center', margin: '18px 0 0' }}>크루가 만들어졌어요!</h2>
        <p style={{ fontFamily: CCF, fontSize: 14, lineHeight: 1.5, color: c.sub, textAlign: 'center', letterSpacing: -0.3, margin: '8px 10px 0', textWrap: 'balance' }}><b style={{ color: c.text }}>{p.name || '새 크루'}</b> 크루의 크루장이 되었어요. 친구를 초대해 함께 달려보세요.</p>
        <button onClick={goInvite} style={{ width: '100%', height: 52, borderRadius: 14, border: 'none', background: c.accent, color: c.accentText, fontFamily: CCF, fontSize: 15.5, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 20 }}>크루원 초대하기</button>
        <button onClick={goCrew} style={{ width: '100%', height: 50, borderRadius: 14, border: 'none', background: 'transparent', color: c.sub, fontFamily: CCF, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 6 }}>나중에 하기</button>
      </div>
    </div>
  );
}

// ── 크루 편집 (Edit Crew) — owner/staff edit an existing crew ──
function FrCrewEdit({ c, app, params }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3C7A14';
  const crewId = params && params.crewId;
  const crew = (app.createdCrews || []).find(x => x.id === crewId);
  const owner = !!(crew && crew.owner);
  const [form, setForm] = React.useState(() => ({
    name: (crew && crew.name) || '', desc: (crew && crew.desc) || '',
    area: (crew && crew.area) || '성수동 서울숲', radius: (crew && crew.radius) || 3,
    sport: (crew && crew.sport) || '러닝', level: (crew && crew.level) || '무관',
    maxMembers: (crew && crew.maxMembers) || 30, privacy: (crew && crew.privacy) || '공개',
    days: (crew && crew.days) || ['화', '목'], time: (crew && crew.time) || '오전 6:30',
    color: (crew && crew.color) || '#74E827',
  }));
  const f = (k, v) => setForm(s => ({ ...s, [k]: v }));
  const toggleDay = (d) => setForm(s => ({ ...s, days: s.days.includes(d) ? s.days.filter(x => x !== d) : s.days.concat([d]) }));
  const valid = form.name.trim().length >= 2;

  if (!crew) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
        <FrAppBar c={c} title="크루 편집" onBack={() => nav.pop()} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <p style={{ fontFamily: CCF, fontSize: 14, color: c.faint }}>크루를 찾을 수 없어요.</p>
        </div>
      </div>
    );
  }
  const save = () => {
    if (!valid) return;
    app.updateCrew(crew.id, { name: form.name.trim(), desc: form.desc.trim(), area: form.area, radius: form.radius, sport: form.sport, level: form.level, maxMembers: form.maxMembers, privacy: form.privacy, days: form.days, time: form.time, color: form.color });
    if (navigator.vibrate) navigator.vibrate(12);
    nav.pop();
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="크루 편집" onBack={() => nav.pop()} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* identity preview */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '16px 20px 4px' }}>
          <div style={{ width: 76, height: 76, borderRadius: 22, background: form.color, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: `0 8px 20px ${form.color}55` }}>
            <FrIcon name="users" size={34} color="#0D1A06" sw={2} />
          </div>
          <div style={{ fontFamily: CCF, fontSize: 16, fontWeight: 700, color: form.name.trim() ? c.text : c.faint, letterSpacing: -0.4, marginTop: 12 }}>{form.name.trim() || '크루 이름'}</div>
        </div>

        <FrSetGroup c={c} title="기본 정보">
          <FrField c={c} label="크루 이름" value={form.name} onChange={(v) => f('name', v.slice(0, 20))} placeholder="예: 성수 새벽 크루" />
          <FrField c={c} label="한 줄 소개" value={form.desc} onChange={(v) => f('desc', v.slice(0, 40))} placeholder="크루를 한 문장으로 소개해요" />
        </FrSetGroup>

        {/* 크루 컬러 */}
        <div style={{ padding: '0 20px' }}>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 8px' }}>크루 컬러</div>
          <div style={{ display: 'flex', gap: 12, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 16, boxShadow: c.shadow }}>
            {FR_CREW_COLORS.map(col => {
              const on = form.color === col;
              return <button key={col} onClick={() => f('color', col)} style={{ width: 40, height: 40, borderRadius: 999, background: col, border: on ? `3px solid ${c.text}` : `3px solid transparent`, cursor: 'pointer', boxShadow: on ? `0 4px 12px ${col}66` : 'none', WebkitTapHighlightColor: 'transparent' }} />;
            })}
          </div>
        </div>

        {/* 활동 지역 */}
        <FrSetGroup c={c} title="활동 지역" hint="대표 출발지를 중심으로 활동 반경 안의 러너에게 크루가 추천돼요.">
          <button onClick={() => nav.push('settingStub', { title: '출발지 변경' })} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 12, background: 'transparent', border: 'none', padding: '14px 0', cursor: 'pointer' }}>
            <span style={{ width: 36, height: 36, borderRadius: 11, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}><FrIcon name="pin" size={18} color={grn} sw={2} /></span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: CCF, fontSize: 12, fontWeight: 600, color: c.faint }}>대표 출발지</div>
              <div style={{ fontFamily: CCF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3, marginTop: 2 }}>{form.area}</div>
            </div>
            <span style={{ fontFamily: CCF, fontSize: 13, fontWeight: 600, color: grn }}>변경</span>
          </button>
          <div style={{ padding: '6px 0 8px' }}>
            <FrSlider c={c} label="활동 반경" value={form.radius} min={1} max={10} step={1} fmt={(v) => v + ' km'} onChange={(v) => f('radius', v)} />
          </div>
        </FrSetGroup>

        {/* 크루 설정 */}
        <div style={{ padding: '0 20px' }}>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 8px' }}>주 종목</div>
          <div style={{ display: 'flex', gap: 9 }}>
            {['러닝', '라이딩', '워킹'].map(s => <FrCcChip key={s} c={c} label={s} on={form.sport === s} onClick={() => f('sport', s)} />)}
          </div>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '20px 4px 8px' }}>페이스 레벨</div>
          <div style={{ display: 'flex', gap: 9, flexWrap: 'wrap' }}>
            {['입문', '중급', '고급', '무관'].map(s => <FrCcChip key={s} c={c} label={s} on={form.level === s} onClick={() => f('level', s)} />)}
          </div>
        </div>

        <FrSetGroup c={c} title="모집">
          <FrStepperRow c={c} label="최대 인원" value={form.maxMembers} min={5} max={200} step={5} suffix="명" onChange={(v) => f('maxMembers', v)} />
        </FrSetGroup>
        <div style={{ padding: '0 20px' }}>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '20px 4px 8px' }}>공개 범위</div>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: '4px 16px', boxShadow: c.shadow }}>
            {[['공개', '누구나 바로 가입할 수 있어요'], ['승인제', '크루장이 가입 요청을 확인해요'], ['비공개', '초대 링크로만 가입 가능해요']].map(([lbl, sub], i, arr) => (
              <div key={lbl}>
                <FrSelectRow c={c} label={lbl} sub={sub} selected={form.privacy === lbl} onSelect={() => f('privacy', lbl)} />
                {i < arr.length - 1 && <div style={{ height: 1, background: c.border, margin: '0 -16px' }} />}
              </div>
            ))}
          </div>
        </div>

        {/* 정기 러닝 */}
        <div style={{ padding: '0 20px' }}>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 8px' }}>정기 러닝</div>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 16, boxShadow: c.shadow }}>
            <div style={{ display: 'flex', gap: 6, justifyContent: 'space-between' }}>
              {['월', '화', '수', '목', '금', '토', '일'].map(d => {
                const on = form.days.includes(d);
                return <button key={d} onClick={() => toggleDay(d)} style={{ width: 38, height: 38, borderRadius: 999, cursor: 'pointer', background: on ? c.accent : c.surfaceAlt, border: `1px solid ${on ? c.accent : c.border}`, fontFamily: CCF, fontSize: 13.5, fontWeight: 700, color: on ? c.accentText : c.sub, WebkitTapHighlightColor: 'transparent' }}>{d}</button>;
              })}
            </div>
            <div style={{ height: 1, background: c.border, margin: '14px 0' }} />
            <FrField c={c} label="시간" value={form.time} onChange={(v) => f('time', v)} placeholder="예: 오전 6:30" />
          </div>
        </div>

        {/* danger zone (owner only) */}
        {owner && (
          <div style={{ padding: '24px 20px 0' }}>
            <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.danger, textTransform: 'uppercase', padding: '0 4px 8px' }}>위험 구역</div>
            <button onClick={() => nav.push('crewDelete', { crewId: crew.id, name: crew.name })} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 12, background: c.surface, border: `1px solid ${c.danger}44`, borderRadius: 16, padding: '14px 16px', cursor: 'pointer', textAlign: 'left', WebkitTapHighlightColor: 'transparent' }}>
              <span style={{ flexShrink: 0, width: 36, height: 36, borderRadius: 11, background: c.danger + '1A', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><FrXIcon name="logout" size={18} color={c.danger} sw={1.9} /></span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontFamily: CCF, fontSize: 14.5, fontWeight: 700, color: c.danger, letterSpacing: -0.3 }}>크루 삭제</div>
                <div style={{ fontFamily: CCF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 2 }}>크루와 모든 기록이 사라져요</div>
              </div>
            </button>
          </div>
        )}

        <div style={{ height: 18 }} />
      </div>

      {/* sticky save CTA */}
      <div style={{ flexShrink: 0, padding: '14px 20px 26px', borderTop: `1px solid ${c.border}`, background: c.bg }}>
        <button disabled={!valid} onClick={save}
          style={{ width: '100%', height: 56, borderRadius: 16, border: 'none', background: valid ? c.accent : c.surfaceAlt, color: valid ? c.accentText : c.faint, fontFamily: CCF, fontSize: 16.5, fontWeight: 700, letterSpacing: -0.3, cursor: valid ? 'pointer' : 'default', boxShadow: valid ? `0 6px 18px ${c.accent}55` : 'none' }}>변경사항 저장</button>
      </div>
    </div>
  );
}

// 크루 삭제 confirm (modal)
function FrCrewDelete({ c, app, params }) {
  const nav = app.nav;
  const p = params || {};
  const del = () => {
    if (app.removeCrew) app.removeCrew(p.crewId);
    nav.reset();
    nav.setTab('community');
  };
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 93, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 28px' }}>
      <div onClick={() => nav.pop()} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)', animation: 'frfadein .2s' }} />
      <div style={{ position: 'relative', width: '100%', background: c.surface, borderRadius: 22, padding: '24px 22px 18px', boxShadow: '0 24px 60px rgba(0,0,0,0.4)', animation: 'frpop .3s cubic-bezier(.34,1.5,.5,1)' }}>
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <span style={{ width: 54, height: 54, borderRadius: 999, background: c.danger + '1A', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <FrXIcon name="logout" size={26} color={c.danger} sw={1.9} />
          </span>
        </div>
        <h2 style={{ fontFamily: CCF, fontSize: 19, fontWeight: 700, color: c.text, letterSpacing: -0.5, textAlign: 'center', margin: '16px 0 0' }}>크루를 삭제할까요?</h2>
        <p style={{ fontFamily: CCF, fontSize: 13.5, lineHeight: 1.5, color: c.sub, textAlign: 'center', letterSpacing: -0.3, margin: '8px 8px 0', textWrap: 'balance' }}><b style={{ color: c.text }}>{p.name || '이 크루'}</b>와 모든 공지·기록이 영구히 사라져요. 되돌릴 수 없어요.</p>
        <button onClick={del} style={{ width: '100%', height: 52, borderRadius: 14, border: 'none', background: c.danger, color: '#fff', fontFamily: CCF, fontSize: 16, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 20 }}>삭제하기</button>
        <button onClick={() => nav.pop()} style={{ width: '100%', height: 50, borderRadius: 14, border: 'none', background: 'transparent', color: c.sub, fontFamily: CCF, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 6 }}>취소</button>
      </div>
    </div>
  );
}

// ── 크루원 초대 (Invite members) — friends + recently-run-with ──
const FR_INVITE_FRIENDS = [
  { name: '이서연', sub: '함께 달린 친구 · 한강', recent: true },
  { name: '박지호', sub: '함께 달린 친구 · 성수', recent: true },
  { name: '최유진', sub: '함께 달린 친구 · 남산', recent: true },
  { name: '정민서', sub: '친구', recent: false },
  { name: '한소희', sub: '친구', recent: false },
  { name: '윤재호', sub: '친구', recent: false },
  { name: '오세훈', sub: '친구', recent: false },
  { name: '강다은', sub: '친구', recent: false },
];

function FrCrewInvite({ c, app, params }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3C7A14';
  const [sent, setSent] = React.useState({});
  const [q, setQ] = React.useState('');
  const toggle = (name) => setSent(s => ({ ...s, [name]: !s[name] }));
  const recent = FR_INVITE_FRIENDS.filter(f => f.recent);
  const all = FR_INVITE_FRIENDS.filter(f => !q || f.name.includes(q));
  const sentCount = Object.values(sent).filter(Boolean).length;

  const Row = ({ f }) => {
    const on = !!sent[f.name];
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 0' }}>
        <FrAvatar name={f.name} size={42} ring={c.border} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontFamily: CCF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{f.name}</div>
          <div style={{ fontFamily: CCF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{f.sub}</div>
        </div>
        <button onClick={() => toggle(f.name)} style={{ flexShrink: 0, height: 34, padding: '0 15px', borderRadius: 999, border: on ? `1px solid ${c.border}` : 'none', background: on ? c.surfaceAlt : c.accent, color: on ? c.sub : c.accentText, fontFamily: CCF, fontSize: 12.5, fontWeight: 700, letterSpacing: -0.2, cursor: 'pointer', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 5, WebkitTapHighlightColor: 'transparent' }}>
          {on ? <><FrCIcon name="check" size={13} color={grn} sw={2.6} /> 초대됨</> : '초대'}
        </button>
      </div>
    );
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="크루원 초대" onBack={() => nav.pop()} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* invite by link */}
        <div style={{ padding: '14px 20px 0' }}>
          <button onClick={() => nav.push('settingStub', { title: '초대 링크 복사됨' })} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 12, background: c.accentDim, border: `1px solid ${c.accent}44`, borderRadius: 16, padding: 14, cursor: 'pointer', textAlign: 'left', WebkitTapHighlightColor: 'transparent' }}>
            <span style={{ flexShrink: 0, width: 38, height: 38, borderRadius: 11, background: c.surface, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><FrXIcon name="link" size={19} color={grn} sw={1.9} /></span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: CCF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>초대 링크 공유</div>
              <div style={{ fontFamily: CCF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 1 }}>링크로 누구나 크루에 초대할 수 있어요</div>
            </div>
            <FrXIcon name="share" size={18} color={grn} sw={1.9} />
          </button>
        </div>

        {/* search */}
        <div style={{ padding: '16px 20px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, background: c.surfaceAlt, border: `1px solid ${c.fieldBorder}`, borderRadius: 12, padding: '0 14px', height: 46 }}>
            <FrIcon name="search" size={17} color={c.faint} sw={2} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="이름으로 친구 찾기" style={{ flex: 1, minWidth: 0, border: 'none', outline: 'none', background: 'transparent', fontFamily: CCF, fontSize: 14.5, fontWeight: 600, color: c.text, letterSpacing: -0.3 }} />
          </div>
        </div>

        {/* recently run with */}
        {!q && recent.length > 0 && (
          <div style={{ padding: '20px 20px 0' }}>
            <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '0 4px 4px' }}>최근 함께 달린 친구</div>
            <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: '4px 16px', boxShadow: c.shadow }}>
              {recent.map((f, i) => (
                <div key={f.name}>{i > 0 && <div style={{ height: 1, background: c.border, margin: '0 -16px' }} />}<Row f={f} /></div>
              ))}
            </div>
          </div>
        )}

        {/* all friends */}
        <div style={{ padding: '20px 20px 28px' }}>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '0 4px 4px' }}>{q ? '검색 결과' : '친구'}</div>
          {all.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '30px 20px' }}><p style={{ fontFamily: CCF, fontSize: 13.5, color: c.faint, margin: 0 }}>'{q}' 친구를 찾을 수 없어요.</p></div>
          ) : (
            <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: '4px 16px', boxShadow: c.shadow }}>
              {all.map((f, i) => (
                <div key={f.name}>{i > 0 && <div style={{ height: 1, background: c.border, margin: '0 -16px' }} />}<Row f={f} /></div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* sticky done bar */}
      <div style={{ flexShrink: 0, padding: '14px 20px 26px', borderTop: `1px solid ${c.border}`, background: c.bg }}>
        <button onClick={() => nav.pop()} style={{ width: '100%', height: 54, borderRadius: 15, border: 'none', background: c.accent, color: c.accentText, fontFamily: CCF, fontSize: 16, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', boxShadow: `0 6px 18px ${c.accent}55` }}>{sentCount > 0 ? `${sentCount}명 초대 완료` : '완료'}</button>
      </div>
    </div>
  );
}

// ── 챌린지 생성 (Create Challenge) — owner/staff set the crew's active challenge ──
function FrChallengeCreate({ c, app, params }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3C7A14';
  const crewId = params && params.crewId;
  const crew = (app.createdCrews || []).find(x => x.id === crewId);
  const presets = ['이번 달 100K', '주간 50K 릴레이', '서브4 빌드업', '새벽 7일 루틴'];
  const [form, setForm] = React.useState({ title: '', goal: 100, period: 30, sport: '러닝' });
  const f = (k, v) => setForm(s => ({ ...s, [k]: v }));
  const valid = form.title.trim().length >= 2;
  if (!crew) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
        <FrAppBar c={c} title="챌린지 생성" onBack={() => nav.pop()} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <p style={{ fontFamily: CCF, fontSize: 14, color: c.faint }}>크루를 찾을 수 없어요.</p>
        </div>
      </div>
    );
  }
  const hasActive = crew.challenge && !crew.challenge.none;
  const [confirm, setConfirm] = React.useState(false);
  const create = () => {
    if (!valid) return;
    app.updateCrew(crew.id, { challenge: { title: form.title.trim(), done: 0, goal: form.goal, days: form.period } });
    if (navigator.vibrate) navigator.vibrate(12);
    nav.pop();
  };
  const onCta = () => { if (!valid) return; if (hasActive) { setConfirm(true); } else { create(); } };
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="챌린지 생성" onBack={() => nav.pop()} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* hero preview */}
        <div style={{ padding: '16px 20px 0' }}>
          <div style={{ position: 'relative', overflow: 'hidden', background: '#0C1206', borderRadius: 20, padding: 18, boxShadow: c.shadow }}>
            <div style={{ position: 'absolute', top: -30, right: -30, width: 120, height: 120, borderRadius: 999, background: '#7CF03D', opacity: 0.14 }} />
            <svg viewBox="0 0 64 64" width="78" height="78" style={{ position: 'absolute', right: 12, bottom: 10, opacity: 0.9 }} aria-hidden="true">
              <path d="M14 6 V58" stroke="#7CF03D" strokeWidth="3.5" strokeLinecap="round" />
              <g>
                <rect x="14" y="9" width="9" height="7" fill="#7CF03D" />
                <rect x="32" y="9" width="9" height="7" fill="#7CF03D" />
                <rect x="23" y="16" width="9" height="7" fill="#7CF03D" />
                <rect x="41" y="16" width="8" height="7" fill="#7CF03D" />
                <rect x="14" y="23" width="9" height="7" fill="#7CF03D" />
                <rect x="32" y="23" width="9" height="7" fill="#7CF03D" />
                <rect x="14" y="9" width="35" height="21" fill="none" stroke="rgba(124,240,61,0.35)" strokeWidth="1.5" />
              </g>
            </svg>
            <div style={{ position: 'relative' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'rgba(124,240,61,0.18)', border: '1px solid rgba(124,240,61,0.4)', borderRadius: 999, padding: '5px 11px' }}>
                <FrIcon name="trophy" size={13} color="#7CF03D" sw={1.9} />
                <span style={{ fontFamily: CCF, fontSize: 11, fontWeight: 700, color: '#EAFBDD', letterSpacing: -0.2 }}>새 챌린지</span>
              </span>
              <div style={{ fontFamily: CCF, fontSize: 20, fontWeight: 700, color: form.title.trim() ? '#fff' : 'rgba(255,255,255,0.4)', letterSpacing: -0.5, marginTop: 13 }}>{form.title.trim() || '챌린지 이름'}</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 12 }}>
                <span style={{ fontFamily: CCF, fontSize: 28, fontWeight: 700, color: '#7CF03D', letterSpacing: -1 }}>0</span>
                <span style={{ fontFamily: CCF, fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.6)' }}>/ {form.goal}km</span>
                <span style={{ marginLeft: 'auto', fontFamily: CCF, fontSize: 11.5, fontWeight: 800, color: '#0D1A06', background: '#7CF03D', borderRadius: 8, padding: '4px 9px' }}>D-{form.period}</span>
              </div>
            </div>
          </div>
        </div>

        {hasActive && (
          <div style={{ padding: '14px 20px 0' }}>
            <div style={{ display: 'flex', gap: 10, background: '#E8703D1A', border: '1px solid #E8703D44', borderRadius: 14, padding: 13 }}>
              <FrIcon name="info" size={17} color="#E8703D" sw={1.9} />
              <p style={{ fontFamily: CCF, fontSize: 12.5, lineHeight: 1.5, color: c.text, letterSpacing: -0.2, margin: 0, textWrap: 'pretty' }}>진행 중인 <b>{crew.challenge.title}</b> 챌린지가 새 챌린지로 교체돼요.</p>
            </div>
          </div>
        )}

        <FrSetGroup c={c} title="챌린지 이름">
          <FrField c={c} label="이름" value={form.title} onChange={(v) => f('title', v.slice(0, 24))} placeholder="예: 6월 한강 100K" />
        </FrSetGroup>
        <div style={{ padding: '12px 20px 0' }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {presets.map(p => <FrCcChip key={p} c={c} label={p} on={form.title === p} onClick={() => f('title', p)} />)}
          </div>
        </div>

        <div style={{ padding: '0 20px' }}>
          <div style={{ fontFamily: CCF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 8px' }}>주 종목</div>
          <div style={{ display: 'flex', gap: 9 }}>
            {['러닝', '라이딩', '워킹'].map(s => <FrCcChip key={s} c={c} label={s} on={form.sport === s} onClick={() => f('sport', s)} />)}
          </div>
        </div>

        <FrSetGroup c={c} title="목표 & 기간">
          <FrStepperRow c={c} label="목표 거리" value={form.goal} min={10} max={1000} step={10} suffix="km" onChange={(v) => f('goal', v)} />
          <FrStepperRow c={c} label="기간" value={form.period} min={3} max={90} step={1} suffix="일" onChange={(v) => f('period', v)} />
        </FrSetGroup>

        <div style={{ height: 18 }} />
      </div>

      <div style={{ flexShrink: 0, padding: '14px 20px 26px', borderTop: `1px solid ${c.border}`, background: c.bg }}>
        <button disabled={!valid} onClick={onCta}
          style={{ width: '100%', height: 56, borderRadius: 16, border: 'none', background: valid ? c.accent : c.surfaceAlt, color: valid ? c.accentText : c.faint, fontFamily: CCF, fontSize: 16.5, fontWeight: 700, letterSpacing: -0.3, cursor: valid ? 'pointer' : 'default', boxShadow: valid ? `0 6px 18px ${c.accent}55` : 'none' }}>{hasActive ? '챌린지 교체하기' : '챌린지 시작하기'}</button>
      </div>
      {confirm && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 94, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 28px' }}>
          <div onClick={() => setConfirm(false)} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)', animation: 'frfadein .2s' }} />
          <div style={{ position: 'relative', width: '100%', background: c.surface, borderRadius: 22, padding: '24px 22px 18px', boxShadow: '0 24px 60px rgba(0,0,0,0.4)', animation: 'frpop .3s cubic-bezier(.34,1.5,.5,1)' }}>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <span style={{ width: 54, height: 54, borderRadius: 999, background: '#E8703D1A', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <FrIcon name="trophy" size={26} color="#E8703D" sw={1.9} />
              </span>
            </div>
            <h2 style={{ fontFamily: CCF, fontSize: 19, fontWeight: 700, color: c.text, letterSpacing: -0.5, textAlign: 'center', margin: '16px 0 0' }}>새로 생성하시겠습니까?</h2>
            <p style={{ fontFamily: CCF, fontSize: 13.5, lineHeight: 1.5, color: c.sub, textAlign: 'center', letterSpacing: -0.3, margin: '8px 8px 0', textWrap: 'balance' }}>현재 진행 중인 <b style={{ color: c.text }}>{crew.challenge.title}</b> 챌린지가 있습니다. 새 챌린지로 교체하면 기존 진행률은 초기화돼요.</p>
            <button onClick={() => { setConfirm(false); create(); }} style={{ width: '100%', height: 52, borderRadius: 14, border: 'none', background: c.accent, color: c.accentText, fontFamily: CCF, fontSize: 16, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 20 }}>새로 생성하기</button>
            <button onClick={() => setConfirm(false)} style={{ width: '100%', height: 50, borderRadius: 14, border: 'none', background: 'transparent', color: c.sub, fontFamily: CCF, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 6 }}>취소</button>
          </div>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { FrCrewCreate, FrCrewCreated, FrCrewEdit, FrCrewDelete, FrCrewInvite, FrChallengeCreate, FrCcChip });
