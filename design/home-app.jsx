// FreshRun — 홈 comparison canvas: Layout A & B in light + dark.
function FrHomeFrame({ dark, Comp }) {
  const c = dark ? FR_DARK : FR_LIGHT;
  return (
    <IOSDevice dark={dark} width={402} height={874}>
      <Comp c={c} />
    </IOSDevice>
  );
}

function FrHomeCanvas() {
  return (
    <DesignCanvas>
      <DCSection id="home" title="홈 — 스트립 + 풀블리드 카드" subtitle="슬림 날씨 스트립 · 지도를 히어로로 쓰는 풀폭 카드 · 친구들의 러닝 피드. 카드를 탭하면 상세 시트가 열려요.">
        <DCArtboard id="home-light" label="라이트" width={402} height={874}><FrHomeFrame dark={false} Comp={FrHomeB} /></DCArtboard>
        <DCArtboard id="home-dark" label="다크" width={402} height={874}><FrHomeFrame dark={true} Comp={FrHomeB} /></DCArtboard>
      </DCSection>
    </DesignCanvas>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<FrHomeCanvas />);
