// FreshRun — merged-app root. Single phone, bottom tabs, overlay nav stack, Tweaks.
const ROOTF = window.FR_FONT;

const FR_TABS = { home: FrHomeB, community: FrCommunity, course: FrCourseTab, log: FrRecords, profile: FrProfile };
const FR_OVERLAYS = {
  weatherDetail: { comp: FrWeatherDetail, modal: false },
  activityDetail: { comp: FrActivityDetail, modal: false },
  notifications: { comp: FrNotifications, modal: false },
  audioCoach: { comp: FrAudioCoach, modal: false },
  settingStub: { comp: FrSettingStub, modal: false },
  settingsHub: { comp: FrSettingsHub, modal: false },
  subscription: { comp: FrSubscription, modal: false },
  personalInfo: { comp: FrPersonalInfo, modal: false },
  aiCoursePrefs: { comp: FrAICoursePrefs, modal: false },
  weatherRouting: { comp: FrWeatherRouting, modal: false },
  healthConnect: { comp: FrHealthConnect, modal: false },
  socialAccounts: { comp: FrSocialAccounts, modal: false },
  units: { comp: FrUnitsScreen, modal: false },
  theme: { comp: FrThemeScreen, modal: false },
  lang: { comp: FrLangScreen, modal: false },
  help: { comp: FrHelpCenter, modal: false },
  terms: { comp: FrTerms, modal: false },
  logout: { comp: FrLogout, modal: true },
  premium: { comp: FrPremium, modal: false },
  tracking: { comp: FrTracking, modal: false },
  coursePreview: { comp: FrCoursePreview, modal: false },
  crewDetail: { comp: FrCrewDetail, modal: false },
  crewCreate: { comp: FrCrewCreate, modal: false },
  crewManage: { comp: FrCrewManage, modal: false },
  crewAdmin: { comp: FrCrewAdmin, modal: false },
  crewNotices: { comp: FrCrewNotices, modal: false },
  crewInvite: { comp: FrCrewInvite, modal: false },
  crewRequests: { comp: FrCrewRequests, modal: false },
  crewPerms: { comp: FrCrewPerms, modal: false },
  locationPicker: { comp: FrLocationPicker, modal: false },
  crewEdit: { comp: FrCrewEdit, modal: false },
  challengeCreate: { comp: FrChallengeCreate, modal: false },
  crewDelete: { comp: FrCrewDelete, modal: true },
  crewCreated: { comp: FrCrewCreated, modal: true },
  savedCourses: { comp: FrSavedCourses, modal: false },
  allActivities: { comp: FrAllActivities, modal: false },
  monthPicker: { comp: FrMonthPicker, modal: true },
  monthlyInsight: { comp: FrMonthlyInsight, modal: false },
  challengeDone: { comp: FrChallengeDone, modal: true },
  personalBest: { comp: FrPersonalBest, modal: true },
  share: { comp: FrShareSheet, modal: true },
  runShare: { comp: FrRunShareSheet, modal: true },
};

// lightweight share sheet (modal)
function FrShareSheet({ c, app }) {
  const nav = app.nav;
  const items = [['health', 'Apple 건강', c.danger], ['link', 'Instagram', '#C44D8B'], ['users', '크루', '#3D8BFF'], ['link', '링크 복사', c.sub]];
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 92, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
      <div onClick={() => nav.pop()} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.45)', animation: 'frfadein .2s' }} />
      <div style={{ position: 'relative', background: c.bg, borderRadius: '24px 24px 0 0', padding: '12px 20px 28px', animation: 'frsheetup .3s cubic-bezier(.22,.61,.36,1)' }}>
        <div style={{ display: 'flex', justifyContent: 'center', paddingBottom: 12 }}>
          <div style={{ width: 38, height: 5, borderRadius: 99, background: c.fieldBorder }} />
        </div>
        <div style={{ fontFamily: ROOTF, fontSize: 16, fontWeight: 700, color: c.text, letterSpacing: -0.4, textAlign: 'center', marginBottom: 16 }}>공유하기</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12 }}>
          {items.map(([ic, lbl, col], i) => (
            <button key={i} onClick={() => nav.pop()} style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 54, height: 54, borderRadius: 16, background: c.surface, border: `1px solid ${c.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: c.shadow }}>
                <FrXIcon name={ic} size={23} color={col} fill={ic === 'health' ? col : 'none'} sw={ic === 'health' ? 0 : 1.8} />
              </span>
              <span style={{ fontFamily: ROOTF, fontSize: 11.5, color: c.sub, letterSpacing: -0.2, whiteSpace: 'nowrap' }}>{lbl}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function FrOverlayPanel({ c, entry, app, params, z }) {
  const { comp: Comp, modal } = entry;
  if (modal) {
    return <Comp c={c} app={app} params={params} />;
  }
  return (
    <div className="fr-screen" style={{ position: 'absolute', inset: 0, zIndex: z, background: c.bg, animationName: 'frInR' }}>
      <Comp c={c} app={app} params={params} />
    </div>
  );
}

function FrAppRoot() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const c = t.theme === 'dark' ? FR_DARK : FR_LIGHT;
  const [tab, setTab] = React.useState('home');
  const [stack, setStack] = React.useState([]);
  const [scale, setScale] = React.useState(1);
  const [settings, setSettings] = React.useState(FR_SETTINGS_DEFAULTS);
  const setSetting = React.useCallback((group, key, val) => setSettings(s => ({ ...s, [group]: { ...s[group], [key]: val } })), []);
  const [savedRuns, setSavedRuns] = React.useState([]);
  const [justSavedId, setJustSavedId] = React.useState(null);
  const savedTimer = React.useRef(0);
  const saveRun = React.useCallback((run) => {
    const rec = { ...run, fresh: false, saved: true };
    setSavedRuns(r => r.some(x => x.id === rec.id) ? r : [rec, ...r]);
    setJustSavedId(rec.id);
    clearTimeout(savedTimer.current);
    savedTimer.current = setTimeout(() => setJustSavedId(null), 5000);
  }, []);
  const [bookmarks, setBookmarks] = React.useState([]);
  const [createdCrews, setCreatedCrews] = React.useState([]);
  const addCrew = React.useCallback((crew) => { setCreatedCrews(list => [crew, ...list]); }, []);
  const updateCrew = React.useCallback((id, patch) => { setCreatedCrews(list => list.map(x => x.id === id ? { ...x, ...patch } : x)); }, []);
  const logCrewRun = React.useCallback((id, entry) => {
    setCreatedCrews(list => list.map(x => {
      if (x.id !== id) return x;
      const feed = [{ id: 'cf-' + Date.now(), ...entry, when: '방금 전' }].concat(x.feed || []).slice(0, 20);
      const ch = x.challenge ? { ...x.challenge, done: +((x.challenge.done || 0) + (entry.km || 0)).toFixed(1) } : x.challenge;
      const ranking = (x.ranking || []).map(r => r.me ? { ...r, km: +((r.km || 0) + (entry.km || 0)).toFixed(1) } : r);
      return { ...x, feed, challenge: ch, ranking };
    }));
  }, []);
  const removeCrew = React.useCallback((id) => { setCreatedCrews(list => list.filter(x => x.id !== id)); }, []);
  const [favCrews, setFavCrews] = React.useState([]);
  const toggleFavCrew = React.useCallback((id) => { setFavCrews(list => list.includes(id) ? list.filter(x => x !== id) : list.concat([id])); }, []);
  const [aiGenCount, setAiGenCount] = React.useState(0);
  const incAiGen = React.useCallback(() => setAiGenCount(n => n + 1), []);
  const toggleBookmark = React.useCallback((item) => {
    if (!item) return;
    setBookmarks(list => list.some(x => x.id === item.id) ? list.filter(x => x.id !== item.id) : [item, ...list]);
  }, []);

  const nav = React.useMemo(() => ({
    push: (name, params = {}) => setStack(s => [...s, { name, params, key: Date.now() + Math.random() }]),
    pop: () => setStack(s => s.slice(0, -1)),
    reset: () => setStack([]),
    setTab: (id) => { setStack([]); setTab(id); },
  }), []);
  nav.tab = tab;

  const app = { displayName: (settings.profile.name || '').trim() || '지윤', nav, premium: t.premium, units: t.units, theme: t.theme, settings, setSetting, savedRuns, justSavedId, saveRun, bookmarks, toggleBookmark, isBookmarked: (id) => bookmarks.some(x => x.id === id), createdCrews, addCrew, updateCrew, removeCrew, logCrewRun, favCrews, toggleFavCrew, isFavCrew: (id) => favCrews.includes(id), aiGenCount, aiLimit: 3, incAiGen, setUnits: (v) => setTweak('units', v), setTheme: (v) => setTweak('theme', v) };

  const Tab = FR_TABS[tab] || FrHomeB;

  React.useEffect(() => {
    const CW = 402, CH = 872 + 30;
    const fit = () => setScale(Math.min((window.innerWidth - 40) / CW, (window.innerHeight - 92) / CH, 1));
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, []);

  // runtime English translation — observer swaps Korean DOM text when lang = en
  const lang = (settings.app && settings.app.lang) || 'ko';
  React.useEffect(() => {
    if (lang !== 'en' || !window.frInstallTranslator) return;
    const root = document.getElementById('fr-i18n-root');
    const obs = window.frInstallTranslator(root, window.FR_I18N);
    return () => obs && obs.disconnect();
  }, [lang]);
  // translate freshly-mounted screens synchronously before paint (observer lags on tab swaps)
  React.useLayoutEffect(() => {
    if (lang !== 'en' || !window.frTranslateTree) return;
    window.frTranslateTree(document.getElementById('fr-i18n-root'), window.FR_I18N);
  }, [lang, tab, stack.length]);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-start' }}>
      <div style={{ textAlign: 'center', padding: '20px 20px 4px' }}>
        <div style={{ fontFamily: ROOTF, fontSize: 14.5, fontWeight: 700, letterSpacing: -0.3, color: '#1A1C20' }}>FreshRun</div>
        <div style={{ fontFamily: ROOTF, fontSize: 12, color: '#9A9DA3', marginTop: 2 }}>탭을 눌러 화면을 둘러보세요 · 아래에서 버전 전환</div>
        <div style={{ display: 'inline-flex', gap: 3, marginTop: 10, background: '#E4E4DC', borderRadius: 999, padding: 3 }}>
          {[['lite', 'Lite'], ['premium', 'Premium']].map(([v, lbl]) => {
            const on = (v === 'premium') === !!t.premium;
            return (
              <button key={v} onClick={() => setTweak('premium', v === 'premium')} style={{ height: 30, padding: '0 18px', borderRadius: 999, border: 'none', cursor: 'pointer', background: on ? '#fff' : 'transparent', color: on ? '#16171A' : '#7C7F86', fontFamily: ROOTF, fontSize: 12.5, fontWeight: 700, letterSpacing: -0.2, boxShadow: on ? '0 1px 3px rgba(20,22,18,0.14)' : 'none', display: 'flex', alignItems: 'center', gap: 5 }}>
                {v === 'premium' && <span style={{ fontSize: 11 }}>{on ? '⚡' : ''}</span>}{lbl}
              </button>
            );
          })}
        </div>
      </div>
      <div style={{ height: (872 + 30) * scale + 12, position: 'relative', width: '100%' }}>
        <div style={{ position: 'absolute', top: 0, left: '50%', transform: `translateX(-50%) scale(${scale})`, transformOrigin: 'top center' }}>
          <IOSDevice dark={c.dark} width={402} height={872}>
            <div id="fr-i18n-root" key={lang} style={{ position: 'relative', height: '100%', overflow: 'hidden', background: c.bg }}>
              <div key={tab} className="fr-screen" style={{ position: 'absolute', inset: 0, animationName: 'frfadein' }}>
                <Tab c={c} app={app} onTab={(id) => { setStack([]); setTab(id); }} />
              </div>
              {stack.map((s, i) => (
                <FrOverlayPanel key={s.key} c={c} entry={FR_OVERLAYS[s.name]} app={app} params={s.params} z={10 + i} />
              ))}
            </div>
          </IOSDevice>
        </div>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection label="테마 & 버전" />
        <TweakRadio label="테마" value={t.theme} options={[{ value: 'light', label: '라이트' }, { value: 'dark', label: '다크' }]} onChange={(v) => setTweak('theme', v)} />
        <TweakRadio label="앱 버전" value={t.premium ? 'premium' : 'lite'} options={[{ value: 'lite', label: 'Lite' }, { value: 'premium', label: 'Premium' }]} onChange={(v) => setTweak('premium', v === 'premium')} />
        <TweakRadio label="단위" value={t.units} options={[{ value: 'km', label: 'km' }, { value: 'mi', label: 'mi' }]} onChange={(v) => setTweak('units', v)} />
      </TweaksPanel>
    </div>
  );
}

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "light",
  "premium": false,
  "units": "km"
}/*EDITMODE-END*/;

ReactDOM.createRoot(document.getElementById('root')).render(<FrAppRoot />);
