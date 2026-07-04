// FreshRun — Profile tab (stats + premium + settings list) and its sub-screens.
const PF = window.FR_FONT;

function FrToggle({ c, on, onChange }) {
  return (
    <button onClick={() => onChange(!on)} style={{ width: 46, height: 28, borderRadius: 999, border: 'none', background: on ? c.accent : c.fieldBorder, cursor: 'pointer', position: 'relative', transition: 'background .18s', flexShrink: 0, padding: 0 }}>
      <span style={{ position: 'absolute', top: 3, left: on ? 21 : 3, width: 22, height: 22, borderRadius: 999, background: '#fff', transition: 'left .18s', boxShadow: '0 1px 3px rgba(0,0,0,0.3)' }} />
    </button>
  );
}

function FrSettingRow({ c, icon, iconBg, label, value, badge, onClick, danger, locked }) {
  return (
    <button onClick={onClick} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 13, background: 'transparent', border: 'none', padding: '12px 4px', cursor: onClick ? 'pointer' : 'default', WebkitTapHighlightColor: 'transparent' }}>
      <span style={{ flexShrink: 0, width: 38, height: 38, borderRadius: 12, background: iconBg || c.surfaceAlt, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontFamily: PF, fontSize: 15, fontWeight: 600, letterSpacing: -0.3, color: danger ? c.danger : c.text }}>{label}</span>
          {badge && <span style={{ fontFamily: PF, fontSize: 10, fontWeight: 700, letterSpacing: 0.4, color: c.dark ? c.accent : '#3F8E14', background: c.accentDim, borderRadius: 6, padding: '2px 6px', textTransform: 'uppercase' }}>{badge}</span>}
        </div>
        {value && <div style={{ fontFamily: PF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, marginTop: 2 }}>{value}</div>}
      </div>
      {locked ? <FrXIcon name="lock" size={17} color={c.faint} sw={2} /> : (onClick && !danger && <FrIcon name="chevron" size={17} color={c.faint} sw={2} />)}
    </button>
  );
}

function FrSettingGroup({ c, title, children }) {
  return (
    <div style={{ padding: '0 20px' }}>
      <div style={{ fontFamily: PF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '20px 4px 4px' }}>{title}</div>
      <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: '4px 12px', boxShadow: c.shadow, display: 'flex', flexDirection: 'column' }}>
        {React.Children.toArray(children).map((ch, i, arr) => (
          <React.Fragment key={i}>
            {ch}
            {i < arr.length - 1 && <div style={{ height: 1, background: c.border, margin: '0 4px' }} />}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

// ── Profile tab ────────────────────────────────────────
function FrProfile({ c, app, onTab }) {
  const nav = app && app.nav;
  const premium = app && app.premium;
  const grn = c.dark ? c.accent : '#3F8E14';
  const name = (app && app.displayName) || '지윤';
  const go = (screen) => nav && nav.push(screen);
  const goPrem = (screen) => nav && nav.push(premium ? screen : 'premium');
  const sApp = (app && app.settings && app.settings.app) || {};
  const setApp = (k, v) => app && app.setSetting && app.setSetting('app', k, v);
  return (
    <div style={frPage(c)}>
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
        {/* header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '60px 20px 0' }}>
          <h1 style={{ fontFamily: PF, fontSize: 26, fontWeight: 700, letterSpacing: -0.8, color: c.text, margin: 0 }}>프로필</h1>
        </div>

        {/* identity card */}
        <div style={{ padding: '18px 20px 0' }}>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 20, padding: 18, boxShadow: c.shadow }}>
            <button onClick={() => go('personalInfo')} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 14, background: 'none', border: 'none', padding: 0, cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
              <div style={{ position: 'relative' }}>
                <FrAvatar name={name} size={62} ring={c.accent} />
                <span style={{ position: 'absolute', bottom: -2, right: -2, width: 24, height: 24, borderRadius: 999, background: c.accent, border: `2.5px solid ${c.surface}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <FrXIcon name="edit" size={12} color={c.accentText} sw={2.2} />
                </span>
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <span style={{ fontFamily: PF, fontSize: 19, fontWeight: 700, letterSpacing: -0.5, color: c.text }}>{name}</span>
                  {premium && (
                    <span role="button" onClick={(e) => { e.stopPropagation(); go('subscription'); }} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: c.accent, borderRadius: 999, padding: '3px 9px 3px 7px', cursor: 'pointer' }}>
                      <FrXIcon name="crown" size={12} color={c.accentText} sw={2} />
                      <span style={{ fontFamily: PF, fontSize: 10.5, fontWeight: 800, color: c.accentText, letterSpacing: 0.2 }}>PREMIUM</span>
                    </span>
                  )}
                </div>
                <div style={{ fontFamily: PF, fontSize: 12.5, color: c.faint, letterSpacing: -0.2, marginTop: 3 }}>탭하여 개인 정보 편집</div>
              </div>
              <FrIcon name="chevron" size={18} color={c.faint} sw={2} />
            </button>
            {/* quick stats */}
            <div style={{ display: 'flex', marginTop: 16, paddingTop: 16, borderTop: `1px solid ${c.border}` }}>
              {[['127.4', 'km 누적'], ['38', '러닝'], ["4'58\"", '최고 페이스']].map((s, i) => (
                <div key={i} style={{ flex: 1, textAlign: 'center', borderLeft: i ? `1px solid ${c.border}` : 'none' }}>
                  <div style={{ fontFamily: PF, fontSize: 18, fontWeight: 700, letterSpacing: -0.5, color: c.text }}>{s[0]}</div>
                  <div style={{ fontFamily: PF, fontSize: 11, color: c.faint, marginTop: 3 }}>{s[1]}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* premium upsell (only when free) */}
        {!premium && (
          <div style={{ padding: '14px 20px 0' }}>
            <button onClick={() => nav.push('premium')} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 12, background: c.text, border: 'none', borderRadius: 18, padding: 16, cursor: 'pointer' }}>
              <FrXIcon name="crown" size={22} color={c.accent} sw={1.9} />
              <div style={{ flex: 1 }}>
                <div style={{ fontFamily: PF, fontSize: 14.5, fontWeight: 700, color: c.bg, letterSpacing: -0.3 }}>FreshRun Premium</div>
                <div style={{ fontFamily: PF, fontSize: 12, color: c.faint, marginTop: 2 }}>AI 코스 · 심층 분석 · 오디오 코치</div>
              </div>
              <FrIcon name="chevron" size={18} color={c.faint} sw={2} />
            </button>
          </div>
        )}

        {/* 구독은 Premium 멤버는 이름 옆 배지로, Lite는 위 배너로 이동 */}

        <FrSettingGroup c={c} title="러닝 & AI">
          <FrSettingRow c={c} icon={<FrCIcon name="sparkle" size={19} color="#3D8BFF" sw={1.8} />} label="AI 코스 선호도" badge="Premium" locked={!premium} onClick={() => goPrem('aiCoursePrefs')} />
          <FrSettingRow c={c} icon={<FrXIcon name="speaker" size={19} color={grn} sw={1.8} />} label="오디오 코치 설정" badge="Premium" locked={!premium} onClick={() => goPrem('audioCoach')} />
        </FrSettingGroup>

        <FrSettingGroup c={c} title="연결">
          <FrSettingRow c={c} icon={<FrXIcon name="health" size={19} color={c.danger} fill={c.danger} sw={0} />} label="Apple 건강" value="연결됨" onClick={() => go('healthConnect')} />
          <FrSettingRow c={c} icon={<FrXIcon name="link" size={19} color={c.sub} sw={1.8} />} label="소셜 계정" onClick={() => go('socialAccounts')} />
          <FrSettingRow c={c} icon={<FrXIcon name="bell" size={19} color={c.sub} sw={1.8} />} label="알림" onClick={() => nav.push('notifications')} />
        </FrSettingGroup>

        <FrSettingGroup c={c} title="러닝 동작">
          {[['autoPause', '자동 일시정지'], ['voiceCue', '음성 안내'], ['haptics', '햅틱 피드백'], ['keepScreen', '화면 항상 켜기']].map(([k, lbl]) => (
            <div key={k} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '13px 0' }}>
              <span style={{ fontFamily: PF, fontSize: 15, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{lbl}</span>
              <FrToggle c={c} on={!!sApp[k]} onChange={(v) => setApp(k, v)} />
            </div>
          ))}
        </FrSettingGroup>

        <FrSettingGroup c={c} title="설정">
          <FrSettingRow c={c} icon={<FrXIcon name="ruler" size={19} color={c.sub} sw={1.8} />} label="단위" value={(app && app.units) === 'mi' ? 'mi (마일)' : 'km (킬로미터)'} onClick={() => go('units')} />
          <FrSettingRow c={c} icon={<FrXIcon name="moon" size={19} color={c.sub} sw={1.8} />} label="다크 모드" value={c.dark ? '켜짐' : '꺼짐'} onClick={() => go('theme')} />
          <FrSettingRow c={c} icon={<FrXIcon name="info" size={19} color={c.sub} sw={1.8} />} label="언어" value={sApp.lang === 'en' ? 'English' : '한국어'} onClick={() => go('lang')} />
          <FrSettingRow c={c} icon={<FrXIcon name="headset" size={19} color={c.sub} sw={1.8} />} label="도움말 센터" onClick={() => go('help')} />
          <FrSettingRow c={c} icon={<FrXIcon name="file" size={19} color={c.sub} sw={1.8} />} label="서비스 약관" onClick={() => go('terms')} />
        </FrSettingGroup>

        <div style={{ padding: '20px 20px 0' }}>
          <FrSettingRow c={c} icon={<FrXIcon name="logout" size={19} color={c.danger} sw={1.9} />} label="로그아웃" danger onClick={() => go('logout')} />
        </div>
        <div style={{ textAlign: 'center', fontFamily: PF, fontSize: 11.5, color: c.faint, padding: '8px 20px 28px' }}>버전 2.4.1 (842) · Made in Seoul</div>
      </div>
      <FrTabBar c={c} active="profile" onTab={onTab} />
    </div>
  );
}

// ── Audio Coach sub-screen ─────────────────────────────
function FrAudioCoach({ c, app }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3F8E14';
  const [on, setOn] = React.useState({ enabled: true, dist: true, pace: true, kcal: false });
  const [voice, setVoice] = React.useState('joy');
  const [rate, setRate] = React.useState(1.0);
  const [cue, setCue] = React.useState(1);
  const t = (k) => setOn(s => ({ ...s, [k]: !s[k] }));
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title="오디오 코치" onBack={() => nav.pop()} />
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', padding: '4px 20px 28px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 13, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: 16, boxShadow: c.shadow, marginTop: 8 }}>
          <span style={{ width: 40, height: 40, borderRadius: 12, background: c.accentDim, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <FrXIcon name="speaker" size={20} color={grn} sw={1.8} />
          </span>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: PF, fontSize: 15, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>실시간 음성 코칭</div>
            <div style={{ fontFamily: PF, fontSize: 12, color: c.faint, marginTop: 2 }}>러닝 중 AI가 페이스를 안내해요</div>
          </div>
          <FrToggle c={c} on={on.enabled} onChange={() => t('enabled')} />
        </div>

        <div style={{ opacity: on.enabled ? 1 : 0.4, pointerEvents: on.enabled ? 'auto' : 'none', transition: 'opacity .2s' }}>
          <div style={{ fontFamily: PF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 8px' }}>코치 음성</div>
          <div style={{ display: 'flex', gap: 10 }}>
            {[['joy', '조이', '활기찬'], ['david', '데이빗', '차분한']].map(([id, nm, desc]) => {
              const sel = voice === id;
              return (
                <button key={id} onClick={() => setVoice(id)} style={{ flex: 1, textAlign: 'left', background: sel ? c.accentDim : c.surface, border: `1.5px solid ${sel ? c.accent : c.border}`, borderRadius: 16, padding: 14, cursor: 'pointer' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontFamily: PF, fontSize: 15, fontWeight: 700, color: c.text }}>{nm}</span>
                    {sel && <FrCheck color={grn} w={15} />}
                  </div>
                  <div style={{ fontFamily: PF, fontSize: 12, color: c.faint, marginTop: 4 }}>{desc} 톤</div>
                </button>
              );
            })}
          </div>

          <div style={{ marginTop: 18, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: '6px 16px', boxShadow: c.shadow }}>
            <FrSlider c={c} label="말하기 속도" value={rate} min={0.6} max={1.6} step={0.1} fmt={(v) => v.toFixed(1) + 'x'} onChange={setRate} />
            <div style={{ height: 1, background: c.border }} />
            <FrSlider c={c} label="안내 간격" value={cue} min={0.5} max={3} step={0.5} fmt={(v) => v + ' km'} onChange={setCue} />
          </div>

          <div style={{ fontFamily: PF, fontSize: 11.5, fontWeight: 700, letterSpacing: 0.6, color: c.faint, textTransform: 'uppercase', padding: '22px 4px 8px' }}>안내 항목</div>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 18, padding: '4px 16px', boxShadow: c.shadow }}>
            {[['dist', '거리'], ['pace', '페이스'], ['kcal', '칼로리']].map(([k, lbl], i, arr) => (
              <div key={k}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '13px 0' }}>
                  <span style={{ fontFamily: PF, fontSize: 14.5, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{lbl} 안내</span>
                  <FrToggle c={c} on={on[k]} onChange={() => t(k)} />
                </div>
                {i < arr.length - 1 && <div style={{ height: 1, background: c.border }} />}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function FrSlider({ c, label, value, min, max, step, fmt, onChange }) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div style={{ padding: '14px 0' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontFamily: PF, fontSize: 14.5, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{label}</span>
        <span style={{ fontFamily: PF, fontSize: 14, fontWeight: 700, color: c.dark ? c.accent : '#3F8E14' }}>{fmt(value)}</span>
      </div>
      <div style={{ position: 'relative', height: 22, display: 'flex', alignItems: 'center' }}>
        <div style={{ position: 'absolute', left: 0, right: 0, height: 6, borderRadius: 99, background: c.surfaceAlt }} />
        <div style={{ position: 'absolute', left: 0, width: pct + '%', height: 6, borderRadius: 99, background: c.accent }} />
        <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(parseFloat(e.target.value))}
          style={{ position: 'absolute', left: 0, right: 0, width: '100%', margin: 0, WebkitAppearance: 'none', appearance: 'none', background: 'transparent', height: 22 }} />
        <div style={{ position: 'absolute', left: `calc(${pct}% - 11px)`, width: 22, height: 22, borderRadius: 999, background: '#fff', border: `2px solid ${c.accent}`, boxShadow: '0 1px 4px rgba(0,0,0,0.2)', pointerEvents: 'none' }} />
      </div>
    </div>
  );
}

// generic placeholder sub-screen for rows without a full build-out
function FrSettingStub({ c, app, params }) {
  const nav = app.nav;
  const title = (params && params.title) || '설정';
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title={title} onBack={() => nav.pop()} />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14, padding: '0 40px' }}>
        <div style={{ width: 60, height: 60, borderRadius: 18, background: c.surfaceAlt, border: `1px solid ${c.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <FrXIcon name="gear" size={26} color={c.faint} sw={1.7} />
        </div>
        <div style={{ fontFamily: PF, fontSize: 14.5, color: c.sub, letterSpacing: -0.3, textAlign: 'center', textWrap: 'balance' }}>'{title}' 화면이에요. 이 흐름에서는 자리표시자로 두었어요.</div>
      </div>
    </div>
  );
}

Object.assign(window, { FrProfile, FrAudioCoach, FrSettingStub, FrToggle, FrSlider, FrSettingRow });
