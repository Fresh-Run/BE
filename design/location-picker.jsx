// FreshRun — Korean location picker (시/도 → 구/군 → 동). Pushed screen.
// Returns selection via params.onSelect(label, key). Keeps the data compact but realistic.
const LOCF = window.FR_FONT;

const FR_KR_LOCATIONS = {
  '서울특별시': {
    '성동구': ['성수동1가', '성수동2가', '왕십리동', '행당동', '응봉동', '금호동', '옥수동'],
    '광진구': ['자양동', '구의동', '화양동', '능동', '군자동'],
    '강남구': ['역삼동', '삼성동', '대치동', '논현동', '청담동', '압구정동'],
    '서초구': ['서초동', '반포동', '잠원동', '방배동', '양재동'],
    '송파구': ['잠실동', '신천동', '석촌동', '방이동', '문정동'],
    '용산구': ['이태원동', '한남동', '용산동', '청파동', '효창동'],
    '마포구': ['망원동', '연남동', '합정동', '서교동', '상암동'],
    '영등포구': ['여의도동', '당산동', '문래동', '영등포동'],
  },
  '경기도': {
    '성남시 분당구': ['정자동', '서현동', '수내동', '이매동', '판교동'],
    '수원시 영통구': ['영통동', '매탄동', '원천동', '광교동'],
    '고양시 일산동구': ['장항동', '백석동', '마두동', '정발산동'],
    '용인시 수지구': ['죽전동', '동천동', '풍덕천동', '상현동'],
  },
  '부산광역시': {
    '해운대구': ['우동', '중동', '좌동', '재송동', '반여동'],
    '수영구': ['광안동', '남천동', '민락동', '수영동'],
    '부산진구': ['부전동', '전포동', '양정동', '서면'],
  },
  '인천광역시': {
    '연수구': ['송도동', '연수동', '청학동', '동춘동'],
    '남동구': ['구월동', '논현동', '간석동', '만수동'],
  },
  '대구광역시': {
    '수성구': ['범어동', '만촌동', '황금동', '두산동'],
    '중구': ['삼덕동', '동인동', '대봉동'],
  },
  '광주광역시': { '서구': ['치평동', '화정동', '농성동'], '남구': ['봉선동', '주월동'] },
  '대전광역시': { '유성구': ['봉명동', '도룡동', '지족동'], '서구': ['둔산동', '월평동'] },
  '제주특별자치도': { '제주시': ['노형동', '연동', '이도동', '아라동'], '서귀포시': ['중문동', '대정읍'] },
};

function FrLocationPicker({ c, app, params }) {
  const nav = app.nav;
  const grn = c.dark ? c.accent : '#3C7A14';
  const p = params || {};
  const [city, setCity] = React.useState(null);
  const [gu, setGu] = React.useState(null);
  const [q, setQ] = React.useState('');

  const level = !city ? 'city' : !gu ? 'gu' : 'dong';
  const title = level === 'city' ? '시 · 도 선택' : level === 'gu' ? city : `${gu}`;

  let items = [];
  if (level === 'city') items = Object.keys(FR_KR_LOCATIONS);
  else if (level === 'gu') items = Object.keys(FR_KR_LOCATIONS[city]);
  else items = FR_KR_LOCATIONS[city][gu];
  const filtered = q ? items.filter(x => x.includes(q)) : items;

  const back = () => { if (level === 'dong') setGu(null); else if (level === 'gu') setCity(null); else nav.pop(); };
  const pick = (v) => {
    if (level === 'city') { setCity(v); setQ(''); }
    else if (level === 'gu') { setGu(v); setQ(''); }
    else { const label = `${city.split(' ')[0]} ${gu.split(' ').pop()} ${v}`; p.onSelect && p.onSelect(label, { city, gu, dong: v }); nav.pop(); }
  };
  const useCurrent = () => { p.onSelect && p.onSelect('현재 위치 · 성동구 성수동', { city: '서울특별시', gu: '성동구', dong: '성수동2가', current: true }); nav.pop(); };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: c.bg }}>
      <FrAppBar c={c} title={title} onBack={back} />
      {/* breadcrumb */}
      {(city || gu) && (
        <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: 5, padding: '0 20px 10px', flexWrap: 'wrap' }}>
          <button onClick={() => { setCity(null); setGu(null); }} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontFamily: LOCF, fontSize: 12.5, fontWeight: 700, color: grn, letterSpacing: -0.2 }}>{city}</button>
          {gu && <><FrIcon name="chevron" size={13} color={c.faint} sw={2.2} /><span style={{ fontFamily: LOCF, fontSize: 12.5, fontWeight: 700, color: c.sub, letterSpacing: -0.2 }}>{gu.split(' ').pop()}</span></>}
        </div>
      )}
      {/* current location (only on first level) */}
      {level === 'city' && (
        <div style={{ flexShrink: 0, padding: '0 20px 12px' }}>
          <button onClick={useCurrent} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 11, background: c.accentDim, border: `1px solid ${c.accent}44`, borderRadius: 14, padding: '13px 14px', cursor: 'pointer', textAlign: 'left', WebkitTapHighlightColor: 'transparent' }}>
            <span style={{ flexShrink: 0, width: 36, height: 36, borderRadius: 11, background: c.surface, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><FrIcon name="pin" size={18} color={grn} sw={2} /></span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: LOCF, fontSize: 14.5, fontWeight: 700, color: c.text, letterSpacing: -0.3 }}>현재 위치 사용</div>
              <div style={{ fontFamily: LOCF, fontSize: 12, color: c.faint, letterSpacing: -0.2, marginTop: 1 }}>GPS로 가까운 동네를 찾아요</div>
            </div>
            <span style={{ fontFamily: LOCF, fontSize: 12.5, fontWeight: 700, color: grn }}>자동</span>
          </button>
        </div>
      )}
      {/* search */}
      <div style={{ flexShrink: 0, padding: '0 20px 12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, background: c.surfaceAlt, border: `1px solid ${c.fieldBorder}`, borderRadius: 12, padding: '0 14px', height: 46 }}>
          <FrIcon name="search" size={17} color={c.faint} sw={2} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={level === 'city' ? '시·도 검색' : level === 'gu' ? '구·군 검색' : '동 검색'} style={{ flex: 1, minWidth: 0, border: 'none', outline: 'none', background: 'transparent', fontFamily: LOCF, fontSize: 14.5, fontWeight: 600, color: c.text, letterSpacing: -0.3 }} />
        </div>
      </div>
      {/* list */}
      <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch', padding: '0 20px 28px' }}>
        <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, padding: '4px 16px', boxShadow: c.shadow }}>
          {filtered.length === 0 ? (
            <div style={{ padding: '24px 0', textAlign: 'center' }}><span style={{ fontFamily: LOCF, fontSize: 13.5, color: c.faint }}>'{q}' 검색 결과가 없어요.</span></div>
          ) : filtered.map((v, i, arr) => (
            <div key={v}>
              <button onClick={() => pick(v)} style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 10, background: 'transparent', border: 'none', padding: '14px 0', cursor: 'pointer', WebkitTapHighlightColor: 'transparent' }}>
                <span style={{ flex: 1, fontFamily: LOCF, fontSize: 15, fontWeight: 600, color: c.text, letterSpacing: -0.3 }}>{v}</span>
                {level !== 'dong' ? <FrIcon name="chevron" size={17} color={c.faint} sw={2} /> : <FrXIcon name="chevright" size={16} color={grn} sw={2.2} />}
              </button>
              {i < arr.length - 1 && <div style={{ height: 1, background: c.border, margin: '0 -16px' }} />}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { FR_KR_LOCATIONS, FrLocationPicker });
