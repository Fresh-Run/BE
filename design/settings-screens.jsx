// FreshRun — functional Profile sub-screens. Real state via app.settings / app.setSetting.
const SETF = window.FR_FONT;

const FR_SETTINGS_DEFAULTS = {
  profile: { name: '지윤', email: 'jiyoon@freshrun.app', birth: '1997', weight: 62, height: 168, gender: '여성' },
  app: { lang: 'ko', haptics: true, autoPause: true, voiceCue: true, keepScreen: false },
  aiCourse: { terrain: 'mixed', defaultDist: 5, scenic: true, avoidHills: false, preferLoop: true, surface: 'any' },
  weather: { avoidDust: true, dustLevel: 80, avoidHeat: true, heatTemp: 28, avoidRain: false },
  health: { steps: true, workouts: true, heartRate: true, sleep: false, vo2: true },
  social: { apple: true, google: false, instagram: true, strava: false, kakao: true },
};

// ── shared sub-components ──────────────────────────────
function FrSetGroup({ c, title, hint, children }) {
  return (
    <div style={{ padding: '0 20px' }}>
      {title && <div style={{ fontFamily: SETF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 8px' }}>{title}</div>}
      <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: '4px 16px', boxShadow: c.shadow, display: 'flex', flexDirection: 'column' }}>
        {React.Children.toArray(children).filter(Boolean).map((ch, i, arr) => (
          <React.Fragment key={i}>
            {ch}
            {i < arr.length - 1 && <div style={{ height: 1, background: c.border, margin: '0 -16px' }} />}
          </React.Fragment>
        ))}
      </div>
      {hint && <div style={{ fontFamily: SETF, fontSize: 12, color: c.faint, letterSpacing: -0.2, lineHeight: 1.5, padding: '9px 6px 0', textWrap: 'pretty' }}>{hint}</div>}
    </div>
  );
}

function FrToggleRow({ c, label, sub, on, onChange }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 0' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontFamily: SETF, fontSize: 14.5, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{label}</div>
        {sub && <div style={{ fontFamily: SETF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 3 }}>{sub}</div>}
      </div>
      <FrToggle c={c} on={on} onChange={onChange} />
    </div>
  );
}

// single-select list rendered as tappable rows inside a card
function FrSelectRow({ c, label, sub, selected, onSelect }) {
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <button onClick={onSelect} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 12, background: 'transparent', border: 'none', padding: '14px 0', cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontFamily: SETF, fontSize: 14.5, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{label}</div>
        {sub && <div style={{ fontFamily: SETF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 3 }}>{sub}</div>}
      </div>
      <span style={{ width: 22, height: 22, borderRadius: 999, border: `2px solid ${selected ? grn : c.fieldBorder}`, background: selected ? grn : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {selected && <FrCheck color="#fff" w={13} />}
      </span>
    </button>
  );
}

function FrField({ c, label, value, onChange, placeholder, type = 'text', suffix }) {
  return (
    <div style={{ padding: '12px 0' }}>
      <label style={{ fontFamily: SETF, fontSize: 12, fontWeight: 600, color: c.faint, letterSpacing: -0.2, display: 'block', marginBottom: 7 }}>{label}</label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: c.surfaceAlt, border: `1px solid ${c.fieldBorder}`, borderRadius: 12, padding: '0 14px', height: 48 }}>
        <input value={value} placeholder={placeholder} type={type} inputMode={type === 'number' ? 'numeric' : undefined}
          onChange={(e) => onChange(e.target.value)}
          style={{ flex: 1, minWidth: 0, border: 'none', outline: 'none', background: 'transparent', fontFamily: SETF, fontSize: 15.5, fontWeight: 600, color: c.text, letterSpacing: -0.3, padding: 0 }} />
        {suffix && <span style={{ fontFamily: SETF, fontSize: 13.5, fontWeight: 600, color: c.faint, flexShrink: 0 }}>{suffix}</span>}
      </div>
    </div>
  );
}

function FrStepperRow({ c, label, value, min, max, step, suffix, onChange }) {
  const btn = (txt, fn, dis) => (
    <button onClick={fn} disabled={dis} style={{ width: 36, height: 36, borderRadius: 10, border: `1px solid ${c.border}`, background: dis ? c.surfaceAlt : c.surface, color: dis ? c.faint : c.text, fontFamily: SETF, fontSize: 20, fontWeight: 600, cursor: dis ? 'default' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}>{txt}</button>
  );
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 0' }}>
      <div style={{ flex: 1, fontFamily: SETF, fontSize: 14.5, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {btn('−', () => onChange(Math.max(min, +(value - step).toFixed(2))), value <= min)}
        <span style={{ fontFamily: SETF, fontSize: 15.5, fontWeight: 700, color: c.text, minWidth: 56, textAlign: 'center', letterSpacing: -0.3, fontVariantNumeric: 'tabular-nums' }}>{`${value}${suffix}`}</span>
        {btn('+', () => onChange(Math.min(max, +(value + step).toFixed(2))), value >= max)}
      </div>
    </div>
  );
}

function FrSaveBar({ c, onSave, label = '저장', saved }) {
  return (
    <div style={{ padding: '8px 20px 26px' }}>
      <button onClick={onSave} style={{ width: '100%', height: 54, borderRadius: 15, border: 'none', background: saved ? c.surfaceAlt : c.accent, color: saved ? (c.dark ? c.accent : '#3F8E14') : c.accentText, fontFamily: SETF, fontSize: 16, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, transition: 'background .2s', boxShadow: saved ? 'none' : `0 6px 18px ${c.accent}44` }}>
        {saved ? <><FrCheck color={c.dark ? c.accent : '#3F8E14'} w={18} /> 저장됨</> : label}
      </button>
    </div>
  );
}

function useSaved() {
  const [saved, setSaved] = React.useState(false);
  const flash = () => { setSaved(true); setTimeout(() => setSaved(false), 1600); };
  return [saved, flash];
}

const sc = (c) => ({ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg });
const scroll = { flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' };

// ── 1. Settings hub (gear) ─────────────────────────────
function FrSettingsHub({ c, app }) {
  const nav = app.nav, s = app.settings.app, set = (k, v) => app.setSetting('app', k, v);
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title="설정" onBack={() => nav.pop()} />
      <div style={scroll}>
        <FrSetGroup c={c} title="앱 환경">
          <FrSettingRow c={c} icon={<FrXIcon name="ruler" size={19} color={c.sub} sw={1.8} />} label="단위" value={app.units === 'mi' ? 'mi · 마일' : 'km · 킬로미터'} onClick={() => nav.push('units')} />
          <FrSettingRow c={c} icon={<FrXIcon name="moon" size={19} color={c.sub} sw={1.8} />} label="테마" value={app.theme === 'dark' ? '다크' : '라이트'} onClick={() => nav.push('theme')} />
          <FrSettingRow c={c} icon={<FrXIcon name="link" size={19} color={c.sub} sw={1.8} />} label="언어" value={s.lang === 'ko' ? '한국어' : 'English'} onClick={() => set('lang', s.lang === 'ko' ? 'en' : 'ko')} />
        </FrSetGroup>
        <FrSetGroup c={c} title="러닝 동작" hint="자동 일시정지는 GPS 속도가 멈추면 러닝을 자동으로 멈춰요.">
          <FrToggleRow c={c} label="자동 일시정지" sub="멈추면 자동으로 기록 정지" on={s.autoPause} onChange={(v) => set('autoPause', v)} />
          <FrToggleRow c={c} label="음성 안내" sub="구간마다 음성 피드백" on={s.voiceCue} onChange={(v) => set('voiceCue', v)} />
          <FrToggleRow c={c} label="햅틱 피드백" sub="목표 달성 시 진동" on={s.haptics} onChange={(v) => set('haptics', v)} />
          <FrToggleRow c={c} label="화면 항상 켜기" sub="러닝 중 화면 유지" on={s.keepScreen} onChange={(v) => set('keepScreen', v)} />
        </FrSetGroup>
        <FrSetGroup c={c} title="알림 & 데이터">
          <FrSettingRow c={c} icon={<FrXIcon name="bell" size={19} color={c.sub} sw={1.8} />} label="알림 센터" onClick={() => nav.push('notifications')} />
          <FrSettingRow c={c} icon={<FrXIcon name="health" size={19} color={c.danger} fill={c.danger} sw={0} />} label="건강 데이터" onClick={() => nav.push('healthConnect')} />
        </FrSetGroup>
        <div style={{ height: 26 }} />
      </div>
    </div>
  );
}

// ── 2. Subscription management ─────────────────────────
function FrSubscription({ c, app }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3F8E14';
  const bills = [['2026년 6월 1일', '₩79,000', '연간 플랜'], ['2025년 6월 1일', '₩79,000', '연간 플랜'], ['2024년 11월 1일', '₩9,900', '월간 플랜']];
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title="구독 관리" onBack={() => nav.pop()} />
      <div style={scroll}>
        <div style={{ padding: '12px 20px 0' }}>
          <div style={{ background: c.dark ? '#11150E' : c.text, border: c.dark ? `1px solid ${c.border}` : 'none', borderRadius: 20, padding: 20, position: 'relative', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', top: -24, right: -24, width: 120, height: 120, borderRadius: 999, background: c.accent, opacity: 0.16 }} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <FrXIcon name="crown" size={20} color={c.accent} sw={1.9} />
              <span style={{ fontFamily: SETF, fontSize: 12, fontWeight: 700, letterSpacing: 0.4, color: c.accent, textTransform: 'uppercase' }}>Premium · 활성</span>
            </div>
            <div style={{ fontFamily: SETF, fontSize: 22, fontWeight: 700, letterSpacing: -0.6, color: '#fff', marginTop: 12 }}>연간 플랜</div>
            <div style={{ fontFamily: SETF, fontSize: 13.5, color: 'rgba(255,255,255,0.6)', marginTop: 4 }}>₩79,000 / 년 · 2026년 10월 1일 갱신</div>
          </div>
        </div>
        <FrSetGroup c={c} title="플랜">
          <FrSettingRow c={c} icon={<FrXIcon name="bolt" size={19} color={grn} sw={1.8} />} label="플랜 변경" value="월간으로 전환" onClick={() => nav.push('premium')} />
          <FrSettingRow c={c} icon={<FrXIcon name="file" size={19} color={c.sub} sw={1.8} />} label="영수증 보기" onClick={() => nav.push('settingStub', { title: '영수증' })} />
        </FrSetGroup>
        <FrSetGroup c={c} title="결제 내역">
          {bills.map((b, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 0' }}>
              <div>
                <div style={{ fontFamily: SETF, fontSize: 14, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{b[2]}</div>
                <div style={{ fontFamily: SETF, fontSize: 12, color: c.faint, marginTop: 2 }}>{b[0]}</div>
              </div>
              <span style={{ fontFamily: SETF, fontSize: 14.5, fontWeight: 700, color: c.text }}>{b[1]}</span>
            </div>
          ))}
        </FrSetGroup>
        <div style={{ padding: '20px 20px 30px' }}>
          <button onClick={() => nav.push('settingStub', { title: '구독 취소' })} style={{ width: '100%', height: 52, borderRadius: 14, border: `1px solid ${c.border}`, background: 'transparent', color: c.danger, fontFamily: SETF, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer' }}>구독 취소</button>
        </div>
      </div>
    </div>
  );
}

// ── 3. Personal info (editable) ────────────────────────
function FrPersonalInfo({ c, app }) {
  const nav = app.nav, p = app.settings.profile;
  const [form, setForm] = React.useState(p);
  const [saved, flash] = useSaved();
  const f = (k, v) => setForm(s => ({ ...s, [k]: v }));
  const save = () => { Object.keys(form).forEach(k => app.setSetting('profile', k, form[k])); flash(); };
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title="개인 정보" onBack={() => nav.pop()} />
      <div style={scroll}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '14px 20px 4px' }}>
          <div style={{ position: 'relative' }}>
            <FrAvatar name={form.name || '러너'} size={84} ring={c.accent} />
            <span style={{ position: 'absolute', bottom: 0, right: 0, width: 28, height: 28, borderRadius: 999, background: c.accent, border: `2.5px solid ${c.bg}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FrXIcon name="edit" size={13} color={c.accentText} sw={2.2} />
            </span>
          </div>
        </div>
        <FrSetGroup c={c} title="기본 정보">
          <FrField c={c} label="이름" value={form.name} onChange={(v) => f('name', v)} placeholder="이름" />
          <FrField c={c} label="이메일" value={form.email} onChange={(v) => f('email', v)} type="email" placeholder="you@email.com" />
          <FrField c={c} label="출생 연도" value={form.birth} onChange={(v) => f('birth', v.replace(/\D/g, '').slice(0, 4))} type="number" />
        </FrSetGroup>
        <FrSetGroup c={c} title="신체 정보" hint="신체 정보는 칼로리와 페이스 추정의 정확도를 높여요.">
          <FrStepperRow c={c} label="체중" value={+form.weight} min={30} max={150} step={0.5} suffix=" kg" onChange={(v) => f('weight', v)} />
          <FrStepperRow c={c} label="키" value={+form.height} min={120} max={220} step={1} suffix=" cm" onChange={(v) => f('height', v)} />
        </FrSetGroup>
        <FrSetGroup c={c} title="성별">
          {['여성', '남성', '선택 안 함'].map(g => <FrSelectRow key={g} c={c} label={g} selected={form.gender === g} onSelect={() => f('gender', g)} />)}
        </FrSetGroup>
        <FrSaveBar c={c} onSave={save} saved={saved} />
      </div>
    </div>
  );
}

// ── 4. AI course preferences ───────────────────────────
function FrAICoursePrefs({ c, app }) {
  const nav = app.nav, s = app.settings.aiCourse, set = (k, v) => app.setSetting('aiCourse', k, v);
  const grn = c.dark ? c.accent : '#3F8E14';
  const terrains = [['flat', '평지 우선', '한강·공원 등 평탄한 길'], ['mixed', '균형', '평지와 언덕을 적절히'], ['hill', '언덕 훈련', '오르막 위주의 강한 코스']];
  const surfaces = [['any', '상관 없음'], ['paved', '포장도로'], ['trail', '트레일·흙길']];
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title="AI 코스 선호도" onBack={() => nav.pop()} />
      <div style={scroll}>
        <div style={{ padding: '14px 20px 0' }}>
          <div style={{ display: 'flex', gap: 11, background: c.accentDim, border: `1px solid ${c.accent}33`, borderRadius: 16, padding: 14 }}>
            <FrCIcon name="sparkle" size={18} color={grn} sw={1.9} />
            <p style={{ fontFamily: SETF, fontSize: 13, lineHeight: 1.55, color: c.dark ? c.text : '#274417', letterSpacing: -0.2, margin: 0, textWrap: 'pretty' }}>AI가 새 코스를 추천할 때 이 설정을 기본값으로 사용해요.</p>
          </div>
        </div>
        <FrSetGroup c={c} title="지형">
          {terrains.map(([id, t, d]) => <FrSelectRow key={id} c={c} label={t} sub={d} selected={s.terrain === id} onSelect={() => set('terrain', id)} />)}
        </FrSetGroup>
        <FrSetGroup c={c} title="기본 거리">
          <FrStepperRow c={c} label="추천 거리" value={s.defaultDist} min={1} max={42} step={1} suffix=" km" onChange={(v) => set('defaultDist', v)} />
        </FrSetGroup>
        <FrSetGroup c={c} title="노면">
          {surfaces.map(([id, t]) => <FrSelectRow key={id} c={c} label={t} selected={s.surface === id} onSelect={() => set('surface', id)} />)}
        </FrSetGroup>
        <FrSetGroup c={c} title="선호">
          <FrToggleRow c={c} label="경치 좋은 길 우선" sub="강변·공원·녹지를 우선 경유" on={s.scenic} onChange={(v) => set('scenic', v)} />
          <FrToggleRow c={c} label="순환 코스 선호" sub="출발지로 돌아오는 루프" on={s.preferLoop} onChange={(v) => set('preferLoop', v)} />
          <FrToggleRow c={c} label="급경사 회피" sub="가파른 오르막 제외" on={s.avoidHills} onChange={(v) => set('avoidHills', v)} />
        </FrSetGroup>
        <div style={{ height: 26 }} />
      </div>
    </div>
  );
}

// ── 5. Weather-based routing ───────────────────────────
function FrWeatherRouting({ c, app }) {
  const nav = app.nav, s = app.settings.weather, set = (k, v) => app.setSetting('weather', k, v);
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title="날씨 기반 라우팅" onBack={() => nav.pop()} />
      <div style={scroll}>
        <FrSetGroup c={c} title="미세먼지" hint="설정한 수치를 넘으면 AI가 실내·대체 경로를 제안해요.">
          <FrToggleRow c={c} label="미세먼지 회피" on={s.avoidDust} onChange={(v) => set('avoidDust', v)} />
          {s.avoidDust && (
            <div style={{ padding: '6px 0 8px' }}>
              <FrSlider c={c} label="회피 기준 (PM10)" value={s.dustLevel} min={30} max={150} step={10} fmt={(v) => v + ' ㎍/㎥'} onChange={(v) => set('dustLevel', v)} />
            </div>
          )}
        </FrSetGroup>
        <FrSetGroup c={c} title="더위">
          <FrToggleRow c={c} label="고온 회피" on={s.avoidHeat} onChange={(v) => set('avoidHeat', v)} />
          {s.avoidHeat && (
            <div style={{ padding: '6px 0 8px' }}>
              <FrSlider c={c} label="회피 기준 온도" value={s.heatTemp} min={20} max={38} step={1} fmt={(v) => v + '°C'} onChange={(v) => set('heatTemp', v)} />
            </div>
          )}
        </FrSetGroup>
        <FrSetGroup c={c} title="비">
          <FrToggleRow c={c} label="강수 회피" sub="비 예보 시 그늘·지붕 경로 우선" on={s.avoidRain} onChange={(v) => set('avoidRain', v)} />
        </FrSetGroup>
        <div style={{ height: 26 }} />
      </div>
    </div>
  );
}

// ── 6. Apple Health connect ────────────────────────────
function FrHealthConnect({ c, app }) {
  const nav = app.nav, s = app.settings.health, set = (k, v) => app.setSetting('health', k, v);
  const rows = [['steps', '걸음 수'], ['workouts', '운동 기록'], ['heartRate', '심박수'], ['vo2', 'VO₂ Max'], ['sleep', '수면']];
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title="Apple 건강" onBack={() => nav.pop()} />
      <div style={scroll}>
        <div style={{ padding: '14px 20px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 13, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 16, boxShadow: c.shadow }}>
            <span style={{ width: 44, height: 44, borderRadius: 13, background: c.danger + '1A', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <FrXIcon name="health" size={24} color={c.danger} fill={c.danger} sw={0} />
            </span>
            <div style={{ flex: 1 }}>
              <div style={{ fontFamily: SETF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>Apple 건강 연결됨</div>
              <div style={{ fontFamily: SETF, fontSize: 12.5, color: c.faint, marginTop: 2 }}>마지막 동기화 · 방금 전</div>
            </div>
            <span style={{ width: 9, height: 9, borderRadius: 99, background: c.accent }} />
          </div>
        </div>
        <FrSetGroup c={c} title="동기화 항목">
          {rows.map(([k, lbl]) => <FrToggleRow key={k} c={c} label={lbl} on={s[k]} onChange={(v) => set(k, v)} />)}
        </FrSetGroup>
        <div style={{ padding: '20px 20px 30px' }}>
          <button onClick={() => nav.pop()} style={{ width: '100%', height: 52, borderRadius: 14, border: `1px solid ${c.border}`, background: 'transparent', color: c.danger, fontFamily: SETF, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer' }}>연결 해제</button>
        </div>
      </div>
    </div>
  );
}

// ── 7. Social accounts ─────────────────────────────────
function FrSocialAccounts({ c, app }) {
  const nav = app.nav, s = app.settings.social, set = (k, v) => app.setSetting('social', k, v);
  const grn = c.dark ? c.accent : '#3F8E14';
  const accts = [['apple', 'Apple', '#000', 'health'], ['kakao', '카카오', '#F7CE46', 'link'], ['google', 'Google', '#4285F4', 'link'], ['instagram', 'Instagram', '#C44D8B', 'link'], ['strava', 'Strava', '#FC4C02', 'runner']];
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title="소셜 계정" onBack={() => nav.pop()} />
      <div style={scroll}>
        <FrSetGroup c={c} title="연결된 계정" hint="연결하면 러닝 기록을 자동으로 공유하고 친구를 찾을 수 있어요.">
          {accts.map(([k, lbl, col, ic]) => (
            <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 13, padding: '13px 0' }}>
              <span style={{ width: 38, height: 38, borderRadius: 11, background: col + (col === '#000' ? '' : '22'), display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <FrXIcon name={ic} size={19} color={col === '#000' ? '#fff' : col} fill={ic === 'health' ? '#fff' : 'none'} sw={ic === 'health' ? 0 : 1.8} />
              </span>
              <span style={{ flex: 1, fontFamily: SETF, fontSize: 15, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{lbl}</span>
              <button onClick={() => set(k, !s[k])} style={{ height: 34, padding: '0 16px', borderRadius: 999, border: `1px solid ${s[k] ? 'transparent' : c.border}`, background: s[k] ? c.accentDim : c.surfaceAlt, color: s[k] ? grn : c.sub, fontFamily: SETF, fontSize: 13, fontWeight: 700, letterSpacing: -0.2, cursor: 'pointer' }}>
                {s[k] ? '연결됨' : '연결'}
              </button>
            </div>
          ))}
        </FrSetGroup>
        <div style={{ height: 26 }} />
      </div>
    </div>
  );
}

// ── 8. Units ───────────────────────────────────────────
function FrUnitsScreen({ c, app }) {
  const nav = app.nav;
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title="단위" onBack={() => nav.pop()} />
      <div style={scroll}>
        <FrSetGroup c={c} title="거리 단위" hint="앱 전체의 거리·페이스 표기에 적용돼요.">
          <FrSelectRow c={c} label="킬로미터 (km)" sub="페이스 분/킬로미터" selected={app.units === 'km'} onSelect={() => app.setUnits('km')} />
          <FrSelectRow c={c} label="마일 (mi)" sub="페이스 분/마일" selected={app.units === 'mi'} onSelect={() => app.setUnits('mi')} />
        </FrSetGroup>
        <div style={{ height: 26 }} />
      </div>
    </div>
  );
}

// ── 9. Theme ───────────────────────────────────────────
function FrThemeScreen({ c, app }) {
  const nav = app.nav;
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title="테마" onBack={() => nav.pop()} />
      <div style={scroll}>
        <FrSetGroup c={c} title="화면 테마">
          <FrSelectRow c={c} label="라이트" sub="밝은 배경" selected={app.theme === 'light'} onSelect={() => app.setTheme('light')} />
          <FrSelectRow c={c} label="다크" sub="어두운 배경" selected={app.theme === 'dark'} onSelect={() => app.setTheme('dark')} />
        </FrSetGroup>
        <div style={{ height: 26 }} />
      </div>
    </div>
  );
}

// ── 9b. Language ───────────────────────────
function FrLangScreen({ c, app }) {
  const nav = app.nav;
  const lang = (app.settings && app.settings.app && app.settings.app.lang) || 'ko';
  const set = (v) => app.setSetting && app.setSetting('app', 'lang', v);
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title={lang === 'en' ? 'Language' : '언어'} onBack={() => nav.pop()} />
      <div style={scroll}>
        <FrSetGroup c={c} title={lang === 'en' ? 'App language' : '앱 언어'}>
          <FrSelectRow c={c} label="한국어" sub="Korean" selected={lang === 'ko'} onSelect={() => set('ko')} />
          <FrSelectRow c={c} label="English" sub="영어" selected={lang === 'en'} onSelect={() => set('en')} />
        </FrSetGroup>
        <div style={{ height: 26 }} />
      </div>
    </div>
  );
}

// ── 10. Help center ────────────────────────────────────
const FR_FAQ = [
  ['AI 코스는 어떻게 만들어지나요?', '거리·분위기·경유지 선호도와 실시간 날씨를 분석해 최적의 경로를 생성해요. 선호도는 설정 > AI 코스 선호도에서 조정할 수 있어요.'],
  ['GPS가 부정확해요.', '실외에서 하늘이 트인 곳에서 시작하고, 위치 권한을 "항상 허용"으로 설정하면 정확도가 높아져요.'],
  ['Premium은 어떤 기능을 제공하나요?', 'AI 무제한 코스 생성, 심층 퍼포먼스 분석, 실시간 오디오 코치를 사용할 수 있어요.'],
  ['기록이 Apple 건강에 동기화되지 않아요.', '프로필 > Apple 건강에서 연결 상태와 항목별 동기화를 확인해 주세요.'],
];
function FrHelpCenter({ c, app }) {
  const nav = app.nav;
  const [open, setOpen] = React.useState(-1);
  const grn = c.dark ? c.accent : '#3F8E14';
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title="도움말 센터" onBack={() => nav.pop()} />
      <div style={scroll}>
        <FrSetGroup c={c} title="자주 묻는 질문">
          {FR_FAQ.map(([q, a], i) => (
            <div key={i}>
              <button onClick={() => setOpen(open === i ? -1 : i)} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 12, background: 'transparent', border: 'none', padding: '15px 0', cursor: 'pointer' }}>
                <span style={{ flex: 1, fontFamily: SETF, fontSize: 14.5, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{q}</span>
                <span style={{ transform: open === i ? 'rotate(90deg)' : 'none', transition: 'transform .2s', flexShrink: 0 }}><FrIcon name="chevron" size={17} color={c.faint} sw={2} /></span>
              </button>
              {open === i && <p style={{ fontFamily: SETF, fontSize: 13.5, lineHeight: 1.6, color: c.sub, letterSpacing: -0.2, margin: '0 0 14px', textWrap: 'pretty' }}>{a}</p>}
            </div>
          ))}
        </FrSetGroup>
        <FrSetGroup c={c} title="문의">
          <FrSettingRow c={c} icon={<FrXIcon name="link" size={19} color={c.sub} sw={1.8} />} label="이메일 문의" value="help@freshrun.app" onClick={() => nav.push('settingStub', { title: '이메일 문의' })} />
        </FrSetGroup>
        <div style={{ height: 26 }} />
      </div>
    </div>
  );
}

// ── 11. Terms of service ───────────────────────────────
function FrTerms({ c, app }) {
  const nav = app.nav;
  const secs = [
    ['1. 서비스 이용', 'FreshRun은 AI 기반 러닝 코스 추천과 활동 기록 서비스를 제공합니다. 본 약관에 동의하면 서비스를 이용할 수 있습니다.'],
    ['2. 위치 정보', '코스 생성과 활동 추적을 위해 위치 정보를 수집합니다. 위치 데이터는 서비스 제공 목적으로만 사용되며 동의 없이 제3자에게 제공되지 않습니다.'],
    ['3. 건강 데이터', 'Apple 건강 등과 연동된 데이터는 기기 내에서 처리되며 사용자가 동기화 항목을 직접 제어할 수 있습니다.'],
    ['4. 구독 및 결제', 'Premium 구독은 선택한 주기로 자동 갱신되며 갱신일 24시간 전까지 언제든 해지할 수 있습니다.'],
    ['5. 안전 고지', '러닝 중에는 항상 주변 교통과 환경에 유의하세요. AI 추천 코스는 참고용이며 실제 안전은 사용자 책임입니다.'],
  ];
  return (
    <div style={sc(c)}>
      <FrAppBar c={c} title="서비스 약관" onBack={() => nav.pop()} />
      <div style={scroll}>
        <div style={{ padding: '16px 24px 30px' }}>
          <div style={{ fontFamily: SETF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, marginBottom: 18 }}>최종 업데이트 · 2026년 6월 1일</div>
          {secs.map(([t, body], i) => (
            <div key={i} style={{ marginBottom: 22 }}>
              <h3 style={{ fontFamily: SETF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.4, margin: '0 0 8px' }}>{t}</h3>
              <p style={{ fontFamily: SETF, fontSize: 13.5, lineHeight: 1.65, color: c.sub, letterSpacing: -0.2, margin: 0, textWrap: 'pretty' }}>{body}</p>
            </div>
          ))}
          <div style={{ fontFamily: SETF, fontSize: 12, color: c.faint, textAlign: 'center', paddingTop: 8 }}>© 2026 FreshRun · Made in Seoul</div>
        </div>
      </div>
    </div>
  );
}

// ── 12. Logout confirm (modal) ─────────────────────────
function FrLogout({ c, app }) {
  const nav = app.nav;
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 92, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 28px' }}>
      <div onClick={() => nav.pop()} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)', animation: 'frfadein .2s' }} />
      <div style={{ position: 'relative', width: '100%', background: c.surface, borderRadius: 22, padding: '24px 22px 18px', boxShadow: '0 24px 60px rgba(0,0,0,0.4)', animation: 'frpop .3s cubic-bezier(.34,1.5,.5,1)' }}>
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <span style={{ width: 54, height: 54, borderRadius: 999, background: c.danger + '1A', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <FrXIcon name="logout" size={26} color={c.danger} sw={1.9} />
          </span>
        </div>
        <h2 style={{ fontFamily: SETF, fontSize: 19, fontWeight: 700, color: c.text, letterSpacing: -0.5, textAlign: 'center', margin: '16px 0 0' }}>로그아웃 할까요?</h2>
        <p style={{ fontFamily: SETF, fontSize: 13.5, lineHeight: 1.5, color: c.sub, textAlign: 'center', letterSpacing: -0.3, margin: '8px 8px 0', textWrap: 'balance' }}>다시 로그인하면 모든 기록과 설정이 그대로 유지돼요.</p>
        <button onClick={() => nav.pop()} style={{ width: '100%', height: 52, borderRadius: 14, border: 'none', background: c.danger, color: '#fff', fontFamily: SETF, fontSize: 16, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 20 }}>로그아웃</button>
        <button onClick={() => nav.pop()} style={{ width: '100%', height: 50, borderRadius: 14, border: 'none', background: 'transparent', color: c.sub, fontFamily: SETF, fontSize: 15, fontWeight: 700, letterSpacing: -0.3, cursor: 'pointer', marginTop: 6 }}>취소</button>
      </div>
    </div>
  );
}

Object.assign(window, {
  FR_SETTINGS_DEFAULTS, FrSettingsHub, FrSubscription, FrPersonalInfo, FrAICoursePrefs,
  FrWeatherRouting, FrHealthConnect, FrSocialAccounts, FrUnitsScreen, FrThemeScreen, FrLangScreen,
  FrHelpCenter, FrTerms, FrLogout, FrSetGroup, FrToggleRow, FrSelectRow, FrField, FrStepperRow,
});
