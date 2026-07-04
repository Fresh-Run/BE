// FreshRun — runtime i18n. When language = English, a MutationObserver walks the
// phone DOM and swaps Korean text/placeholders to English from FR_I18N (ko → en).
// Toggling back to Korean re-renders the React tree (Korean is the source), so we
// just disconnect. Dynamic strings with embedded numbers/names may remain Korean.

const FR_I18N = {
  // ── tab bar / common ──
  '홈': 'Home', '커뮤니티': 'Community', '뛰러 가기': 'Run', '기록': 'Records', '프로필': 'Profile',
  '취소': 'Cancel', '저장': 'Save', '저장됨': 'Saved', '닫기': 'Close', '확인': 'Confirm',
  '더보기': 'More', '전체보기': 'See all', '전체 보기': 'See all', '전체보기 →': 'See all →',
  '참여하기': 'Join', '전체': 'All', '초기화': 'Reset', '필터 초기화': 'Clear filters',
  '방금 저장됨': 'Just saved', '연결됨': 'Connected', '연결': 'Connect', '연결 해제': 'Disconnect',
  '켜짐': 'On', '꺼짐': 'Off', '최신순': 'Recent', '거리순': 'Distance', '시간순': 'Time',

  // ── run choice ──
  '오늘 어떻게 달릴까요?': 'How will you run today?',
  '당신의 컨디션에 맞는 완벽한 코스를 선택하세요.': 'Pick the perfect course for how you feel today.',
  'AI 맞춤 코스로 시작': 'Start with an AI course',
  '현재 위치, 날씨, 개인 체력을 분석하여 가장 쾌적한 최적의 코스를 제안합니다.': 'Analyzes your location, weather, and fitness to suggest the most pleasant optimal route.',
  '추천 코스 보기': 'View recommended course',
  '지금 바로 자유 러닝': 'Free run now',
  '익숙한 나만의 경로를 따라 자유롭게 달리세요. 거리와 시간을 실시간으로 기록합니다.': 'Run freely along your own familiar route. Distance and time are tracked in real time.',
  '트래킹 시작하기': 'Start tracking',
  '주간 누적 거리': 'Weekly distance', '현재 온도': 'Temperature',
  '저장된 코스들': 'Saved courses',
  '피드에서 마음에 드는 코스를 북마크해보세요': 'Bookmark courses you like from the feed',
  '아직 저장된 코스가 없어요. 피드에서 마음에 드는 코스를 북마크해보세요.': 'No saved courses yet. Bookmark courses you like from the feed.',
  '조건에 맞는 코스가 없어요.': 'No courses match these filters.',

  // ── home ──
  '오늘의 추천': "Today's pick", 'AI 추천 코스': 'AI recommended course', 'AI 추천': 'AI pick',
  '날씨': 'Weather', '이 코스 달리기': 'Run this course', '내 코스에 저장됨': 'Saved to my courses',
  '오늘의 러닝': "Today's run", '최근 러닝': 'Recent runs',

  // ── records ──
  '이번 달 총 거리': 'Total distance this month', '총 거리': 'Total distance', '세션': 'Sessions',
  '평균 페이스': 'Avg pace', '총 시간': 'Total time', '활동 내역': 'Activity history',
  '지난달': 'Last month', 'AI 월간 분석': 'AI monthly analysis', '자세한 분석 보기': 'View detailed analysis',
  '오늘의 러닝 시작': "Start today's run", '이번 달 거리': 'Distance this month',
  '기간 선택': 'Select period', '이 해에는 기록이 없어요': 'No records for this year',
  '전체 활동': 'All activities', '누적 거리': 'Cumulative distance', '개 활동': ' activities',
  'AI 월간 분석 — 프리미엄': 'AI monthly analysis — Premium',

  // ── monthly insight ──
  '월간 리포트': 'Monthly report', '이번 달 개인 기록': 'Personal records', '주간 거리': 'Weekly distance',
  '주간 페이스 추이': 'Weekly pace trend', '심박 구간 분포': 'Heart-rate zones', '러닝 패턴': 'Running pattern',
  '지형 분석': 'Terrain', 'AI 코칭 요약': 'AI coaching summary', '6월 추천 플랜': 'June plan',
  '최고 5K': 'Best 5K', '최장 거리': 'Longest', '최고 페이스': 'Best pace', '최장 러닝': 'Longest run',
  '주 활동 시간': 'Active time', '연속 러닝': 'Streak', '6월 목표': 'June goal', '집중 포인트': 'Focus',
  '다음 도전': 'Next challenge', '평지': 'Flat', '언덕': 'Hills', '러닝 횟수': 'Runs',
  '누적 고도': 'Elevation', '소모 칼로리': 'Calories', '평균 심박': 'Avg HR', '월 목표': 'Monthly goal', '회': '',
  // split fragments (label + value)
  '평균': 'Avg', '최대': 'Max', '고도': 'Elevation', '달성': 'done', '목표까지': 'To goal', '리포트': 'Report',
  '체감': 'Feels', '서울': 'Seoul', '· 체감': '· Feels', '° · 서울': '° · Seoul', '지수': 'Index', '명 참여': ' joined', '한적함': 'Calm', '쾌적함': 'Pleasant', '주의': 'Caution',
  '날씨 상세 분석': 'Weather details', '한강': 'Hangang',
  // monthly insight hints + PR subs
  '고강도(Zone 4) 비중이 높아요. 회복 러닝으로 Zone 2를 늘리면 부상 위험이 줄어요.': 'Zone 4 share is high. Adding Zone 2 recovery runs lowers injury risk.',
  '5월 28일 · 한강': 'May 28 · Hangang', '5월 12일 · 남산': 'May 12 · Namsan', '5월 28일 인터벌': 'May 28 Intervals', '5월 12일 롱런': 'May 12 Long run',
  '이번 달 기록한 최고 성과예요. 화살표는 자기 기록 경신을 뜻해요.': 'Your best efforts this month. Arrows mean a new personal best.',
  '아침 (06–09시)': 'Morning (6–9am)',

  // ── profile ──
  '탭하여 개인 정보 편집': 'Tap to edit profile', 'km 누적': 'km total', '러닝': 'runs',
  'AI 코스 · 심층 분석 · 오디오 코치': 'AI courses · deep analysis · audio coach',
  '러닝 & AI': 'Running & AI', '연결': 'Connections', '설정': 'Settings', '러닝 동작': 'Run behavior',
  'AI 코스 선호도': 'AI course preferences', '오디오 코치 설정': 'Audio coach', '날씨 기반 라우팅': 'Weather-based routing',
  'Apple 건강': 'Apple Health', '소셜 계정': 'Social accounts', '알림': 'Notifications',
  '단위': 'Units', '다크 모드': 'Dark mode', '언어': 'Language', '도움말 센터': 'Help center', '서비스 약관': 'Terms of service',
  '자동 일시정지': 'Auto-pause', '음성 안내': 'Voice cues', '햅틱 피드백': 'Haptic feedback', '화면 항상 켜기': 'Keep screen on',
  '로그아웃': 'Log out', '구독': 'Subscription', '연간 플랜 · 10월 갱신': 'Annual · renews Oct',
  '무료 플랜 · 업그레이드': 'Free plan · upgrade', 'Premium 멤버': 'Premium member', '무료 플랜': 'Free plan',
  'km (킬로미터)': 'km (kilometers)', 'mi (마일)': 'mi (miles)',

  // ── language screen ──
  '앱 언어': 'App language', '한국어': 'Korean',

  // ── units / theme ──
  '거리 단위': 'Distance unit', '킬로미터 (km)': 'Kilometers (km)', '마일 (mi)': 'Miles (mi)',
  '페이스 분/킬로미터': 'Pace min/km', '페이스 분/마일': 'Pace min/mi',
  '앱 전체의 거리·페이스 표기에 적용돼요.': 'Applies to distance and pace throughout the app.',
  '화면 테마': 'Theme', '라이트': 'Light', '다크': 'Dark', '밝은 배경': 'Light background', '어두운 배경': 'Dark background',

  // ── crew create form ──
  '크루 이름': 'Crew name', '한 줄 소개': 'One-line intro',
  '예: 성수 새벽 크루': 'e.g. Seongsu Dawn Crew', '크루를 한 문장으로 소개해요': 'Describe your crew in one line',
  '공개 범위': 'Visibility', '공개': 'Public', '승인제': 'Approval', '비공개': 'Private',
  '누구나 바로 가입할 수 있어요': 'Anyone can join instantly', '크루장이 가입 요청을 확인해요': 'Owner reviews join requests', '초대 링크로만 가입 가능해요': 'Join by invite link only',
  '활동 요일 · 시간': 'Days & time', '시간': 'Time', '예: 오전 6:30': 'e.g. 6:30 AM', '오전 6:30': '6:30 AM',
  '월': 'M', '화': 'T', '수': 'W', '목': 'Th', '금': 'F', '토': 'Sa', '일': 'Su',
  '첫 챌린지 (선택)': 'First challenge (optional)', '크루 챌린지 시작하기': 'Start a crew challenge', '크루원과 함께 달릴 첫 목표를 만들어요': 'Set a first goal to run toward together',
  '크루 만들기': 'Create crew', '예: 6월 한강 100K': 'e.g. June Hangang 100K', '이름으로 친구 찾기': 'Find friends by name',
  '러닝': 'Running', '라이딩': 'Cycling', '워킹': 'Walking', '페이스 레벨': 'Pace level', '중급': 'Intermediate', '고급': 'Advanced', '무관': 'Any',
  '활동 반경': 'Activity radius', '최대 인원': 'Max members', '첫 챌린지': 'First challenge', '챌린지 없음': 'No challenge',
  '크루 컬러': 'Crew color', '활동 지역': 'Activity area', '변경': 'Change', '출발지 변경': 'Change start point',
  '대표 출발지를 중심으로 활동 반경 안의 러너에게 크루가 추천돼요.': 'Your crew is recommended to runners within the activity radius around your main start point.',
  '성수동 서울숲': 'Seongsu · Seoul Forest', '대표 출발지': 'Main start point',
  '모집': 'Recruiting', '최대 인원': 'Max members', '명': '', '정기 러닝': 'Regular runs', '정기 러닝 (선택)': 'Regular runs (optional)',
  '목표 거리': 'Goal distance', '기간': 'Period', '목표 & 기간': 'Goal & period', '첫 챌린지 (선택)': 'First challenge (optional)',

  // ── course create form ──
  '새 코스 만들기': 'New course', '조건을 고르면 한 번도 안 달려본 코스를 만들어요.': 'Pick your conditions and get a route you have never run.',
  '원하는 조건을 고르면 AI가 새 코스를 그려드려요.': 'Choose your conditions and AI draws a new route.',
  '출발지 · 코스 형태': 'Start · course type', '코스 형태': 'Course type', '순환': 'Loop', '순환 (제자리)': 'Loop (return)', '편도': 'One-way',
  '분위기': 'Vibe', '여러 개 선택': 'Pick a few', '여러 개 선택 가능': 'Pick a few', '고급 설정': 'Advanced', '난이도 · 경유지 · 회피': 'Difficulty · waypoints · avoid',
  '서울숲역 2번 출구': 'Seoul Forest Stn. Exit 2', '코스 생성하기': 'Generate course', '추천': 'Recommended',
  '경치': 'Scenic', '자연': 'Nature', '언덕': 'Hills', '평지': 'Flat',
  '개인 정보': 'Personal info', '기본 정보': 'Basic info', '이름': 'Name', '이메일': 'Email',
  '출생 연도': 'Birth year', '신체 정보': 'Body info', '체중': 'Weight', '키': 'Height', '성별': 'Gender',
  '여성': 'Female', '남성': 'Male', '선택 안 함': 'Prefer not to say',
  '신체 정보는 칼로리와 페이스 추정의 정확도를 높여요.': 'Body info improves calorie and pace estimates.',

  // ── subscription ──
  '구독 관리': 'Manage subscription', '연간 플랜': 'Annual plan', '플랜': 'Plan', '플랜 변경': 'Change plan',
  '월간으로 전환': 'Switch to monthly', '영수증 보기': 'View receipts', '결제 내역': 'Billing history',
  '구독 취소': 'Cancel subscription', '월간 플랜': 'Monthly plan', 'Premium · 활성': 'Premium · active',

  // ── AI course prefs ──
  '지형': 'Terrain', '평지 우선': 'Prefer flat', '균형': 'Balanced', '언덕 훈련': 'Hill training',
  '한강·공원 등 평탄한 길': 'Flat paths like riverside & parks', '평지와 언덕을 적절히': 'A mix of flat and hills',
  '오르막 위주의 강한 코스': 'Tough, uphill-focused course', '기본 거리': 'Default distance', '추천 거리': 'Suggested distance',
  '노면': 'Surface', '상관 없음': 'No preference', '포장도로': 'Paved', '트레일·흙길': 'Trail / dirt',
  '선호': 'Preferences', '경치 좋은 길 우선': 'Prefer scenic routes', '강변·공원·녹지를 우선 경유': 'Favor rivers, parks, greenery',
  '순환 코스 선호': 'Prefer loop courses', '출발지로 돌아오는 루프': 'A loop back to start',
  '급경사 회피': 'Avoid steep climbs', '가파른 오르막 제외': 'Exclude steep uphills',
  'AI가 새 코스를 추천할 때 이 설정을 기본값으로 사용해요.': 'AI uses these as defaults when recommending new courses.',

  // ── weather routing ──
  '미세먼지': 'Fine dust', '미세먼지 회피': 'Avoid fine dust', '회피 기준 (PM10)': 'Threshold (PM10)',
  '더위': 'Heat', '고온 회피': 'Avoid high heat', '회피 기준 온도': 'Threshold temperature',
  '비': 'Rain', '강수 회피': 'Avoid rain', '비 예보 시 그늘·지붕 경로 우선': 'Favor shaded/covered routes when rain is forecast',
  '설정한 수치를 넘으면 AI가 실내·대체 경로를 제안해요.': 'Above your threshold, AI suggests indoor or alternative routes.',

  // ── health / social ──
  'Apple 건강 연결됨': 'Apple Health connected', '동기화 항목': 'Synced data', '걸음 수': 'Steps',
  '운동 기록': 'Workouts', '심박수': 'Heart rate', '수면': 'Sleep', '마지막 동기화 · 방금 전': 'Last sync · just now',
  '연결된 계정': 'Connected accounts', '카카오': 'Kakao',
  '연결하면 러닝 기록을 자동으로 공유하고 친구를 찾을 수 있어요.': 'Connect to auto-share runs and find friends.',

  // ── audio coach ──
  '오디오 코치': 'Audio coach', '실시간 음성 코칭': 'Live voice coaching',
  '러닝 중 AI가 페이스를 안내해요': 'AI guides your pace while you run', '코치 음성': 'Coach voice',
  '조이': 'Joy', '데이빗': 'David', '활기찬': 'Energetic', '차분한': 'Calm', '톤': 'tone',
  '말하기 속도': 'Speaking rate', '안내 간격': 'Cue interval', '안내 항목': 'Cue items',
  '거리 안내': 'Distance cues', '페이스 안내': 'Pace cues', '칼로리 안내': 'Calorie cues',

  // ── help / terms ──
  '자주 묻는 질문': 'FAQ', '문의': 'Contact', '이메일 문의': 'Email us',
  '최종 업데이트 · 2026년 6월 1일': 'Last updated · June 1, 2026',

  // ── tracking ──
  '경과 시간': 'Elapsed time', '거리': 'Distance', '현재 페이스': 'Current pace', '칼로리': 'Calories',
  '러닝 중': 'Running', '일시정지': 'Paused', 'AI 오디오 코치': 'AI audio coach',
  '길게 눌러 종료': 'Hold to stop', '계속 누르세요…': 'Keep holding…',
  '출발 준비 완료! 가볍게 시작해볼까요?': "Ready to go! Let's ease in.",
  '좋아요! 목표 페이스 유지 중이에요': "Nice! You're holding goal pace",
  '"출발 준비 완료! 가볍게 시작해볼까요?"': '"Ready to go! Let\'s ease in."',
  '"좋아요! 목표 페이스 유지 중이에요"': '"Nice! You\'re holding goal pace"',

  // ── celebrations / share ──
  '새로운 기록 경신!': 'New personal best!', '챌린지 완료! 🎉': 'Challenge complete! 🎉',
  '5km 구간 역대 최고 페이스를 달성했어요!': 'You set an all-time best pace over 5km!',
  '이전': 'Previous', '현재': 'Current', '향상': 'improvement', 'New Reward': 'New Reward',
  '디지털 배지 획득': 'Digital badge earned', '기록 자세히 보기': 'View activity', '성과 공유하기': 'Share',
  '기록 확인하기': 'View record', '지금 공유하기': 'Share now', '공유하기': 'Share',
  '사진에 저장': 'Save to Photos', '이미지 복사': 'Copy image', '파일에 저장': 'Save to Files', '프린트': 'Print',
  '메시지': 'Messages', '카카오톡': 'KakaoTalk', '메일': 'Mail', '스토리': 'Story', '피드': 'Feed', '링크 복사': 'Copy link',

  // ── course preview ──
  '코스 미리보기': 'Course preview', '코스 기준 기록': 'Course reference', '원작자 기준 · 내 기록 아님': "Creator's stats · not yours",
  '예상 시간': 'Est. time', '출발지': 'Start point', '이 코스로 뛰시겠습니까?': 'Run this course?',
  '네, 뛸게요': "Yes, let's run", '추천 코스': 'Recommended course',

  // ── activity detail ──
  '활동 상세': 'Activity', '페이스 & 고도 분석': 'Pace & elevation', '심박수 구간': 'Heart-rate zones',
  '회복 조언': 'Recovery advice', '기록 저장하기': 'Save activity', '소모 칼로리': 'Calories',
  '시간': 'Time',

  // ── community ──
  '내 크루와 함께 목표를 달려요': 'Chase goals with your crew', '크루': 'Crews', '챌린지': 'Challenges',
  '액티브': 'Active', '주변 크루 둘러보기': 'Discover nearby crews', '크루 생성': 'Create crew',
  '내 크루': 'My crews', '참여 가능한 챌린지': 'Available challenges', '진행 중': 'In progress',
  '모집 중': 'Recruiting', '명': ' members', '주변 번개 모임': 'Nearby meetups',
  '진행 중인 챌린지': 'Active challenge', '크루 랭킹': 'Crew ranking', '내 순위': 'My rank', '새 소식': 'New', '읽음': 'Read',
  '내가 만든 크루': 'Crews I created', '참여한 크루': 'Joined crews', '크루장': 'Owner', '크루원': 'Members',
  '직접 크루 만들기': 'Create your own crew', '크루장이 돼서 공지·챌린지를 관리해보세요': 'Become an owner and manage announcements & challenges',
  '프리미엄에서 나만의 크루를 만들어보세요': 'Create your own crew with Premium',
  '공지 올리기': 'Post notice', '크루 편집': 'Edit crew', '크루원 초대': 'Invite members', '크루 공지': 'Crew notices',
  '크루 관리': 'Manage crew', '첫 첼린지': 'First challenge', '챌린지 없음': 'No challenge', '챌린지 생성': 'Create challenge',
  '새 챌린지': 'New challenge', '챌린지 이름': 'Challenge name', '목표 & 기간': 'Goal & period', '챌린지 시작하기': 'Start challenge', '챌린지 교체하기': 'Replace challenge', '주 종목': 'Main sport',
  '새로 생성하시겠습니까?': 'Create a new one?', '새로 생성하기': 'Create new',
  '크루 러닝 시작': 'Start crew run', '크루 러닝 피드': 'Crew run feed', '크루런': 'Crew Run',
  '크루 러닝을 시작해 첫 기록을 남겨보세요.': 'Start a crew run to log the first record.', '아직 크루 러닝 기록이 없어요.': 'No crew runs yet.',
  '둘러보기': 'Discover', '가입': 'Join', '저녁': 'Evening', '새벽': 'Dawn', '점심': 'Lunch', '스피드': 'Speed', '강변': 'Riverside', '훈련': 'Training',
  '모집 마감 숨기기': 'Hide full crews', '모든 크루 보기': 'Show all crews', '모집 마감 크루도 보기': 'Show full crews', '가입 가능한 크루만 보기': 'Show joinable only', '모집 마감': 'Full', '전체 지역': 'All areas', '개 크루': ' crews', '조건에 맞는 크루가 없어요.': 'No crews match these filters.', '야간': 'Night',
  '뚝섬 선셋 러너스': 'Ttukseom Sunset Runners', '서울숲 새벽 크루': 'Seoul Forest Dawn Crew', '한강 페이스메이커': 'Hangang Pacemakers', '성수 점심 런': 'Seongsu Lunch Run', '남산 힐러너스': 'Namsan Hill Runners', '응봉산 모닝 크루': 'Eungbongsan Morning Crew', '여의도 라이트런': 'Yeouido Light Run', '한강 나이트 크루': 'Hangang Night Crew',
  '뚝섬 · 성수': 'Ttukseom · Seongsu', '서울숲 · 성수': 'Seoul Forest · Seongsu', '반포 · 잠원': 'Banpo · Jamwon', '성수동': 'Seongsu-dong', '남산 · 회현': 'Namsan · Hoehyeon', '응봉 · 금호': 'Eungbong · Geumho', '여의도': 'Yeouido', '반포 한강공원': 'Banpo Hangang Park',
  '성수': 'Seongsu', '한강': 'Hangang', '남산': 'Namsan', '응봉': 'Eungbong', '평지': 'Flat', '경치': 'Scenic', '도심': 'Urban', '입문': 'Beginner', '중급': 'Intermediate', '고급': 'Advanced', '무관': 'Any',
  '검색 위치': 'Search area', '현재 위치 사용': 'Use current location', 'GPS로 가까운 동네를 찾아요': 'Find nearby areas via GPS', '자동': 'Auto',
  '시 · 도 선택': 'Select province/city', '시·도 검색': 'Search province/city', '구·군 검색': 'Search district', '동 검색': 'Search neighborhood', '현재 위치 · 성동구 성수동': 'Current · Seongsu, Seongdong-gu',
  '크루원에게 전할 공지를 적어주세요': 'Write a notice for your crew', '게시': 'Post', '방금 전': 'Just now',
  '아직 공지가 없어요.': 'No notices yet.', '첫 공지를 올려 크루원에게 소식을 전해보세요.': 'Post your first notice to update your crew.',
  '크루를 한 문장으로 소개해요': 'Describe your crew in one line', '첫 챌린지': 'First challenge',
  '운영진 관리': 'Manage staff', '운영진': 'Staff', '운영진 지정': 'Make staff', '운영진 해제': 'Remove staff',
  '나 · 모든 권한': 'Me · full access', '공지·편집 권한': 'Notice & edit access', '모든 권한': 'Full access',
  '운영진은': 'Staff can', '공지 작성': 'post notices', '크루 편집': 'edit the crew', '크루를 찾을 수 없어요.': 'Crew not found.',
  '참석 투표 추가': 'Add attendance poll', '러닝 일정이라면 참석 여부를 물어보세요': 'For run schedules, ask who is coming',
  '이 러닝에 참석하시나요?': 'Are you joining this run?', '참석': 'Going', '불참': 'Not going', '명 참여': ' voted',
  '변경사항 저장': 'Save changes', '위험 구역': 'Danger zone', '크루 삭제': 'Delete crew', '크루와 모든 기록이 사라져요': 'The crew and all records are erased',
  '크루를 삭제할까요?': 'Delete this crew?', '삭제하기': 'Delete', '정기 러닝': 'Regular runs', '대표 출발지': 'Main start point',
  '활동 반경': 'Activity radius', '주 종목': 'Main sport', '페이스 레벨': 'Pace level', '최대 인원': 'Max members', '공개 범위': 'Visibility',
  '관리': 'Manage', '공지 관리': 'Manage notices', '크루원 관리': 'Manage members', '가입 요청': 'Join requests', '챌린지 관리': 'Manage challenge',
  '정원': 'Capacity',
  '크루 정보 편집': 'Edit crew info', '이름·지역·공개 범위': 'Name · area · visibility', '건 대기 중': ' pending', '대기 없음': 'None pending',
  '공지는 최대 6개까지 유지돼요. 새 공지를 올리면 가장 오래된 공지가 자동으로 사라져요.': 'Up to 6 notices are kept. Posting a new one auto-removes the oldest.',
  '참석 투표': 'Attendance poll', '다음 공지 시 삭제': 'Removed on next post', '아직 공지가 없어요.': 'No notices yet.',
  '크루원 초대': 'Invite members', '초대 링크 공유': 'Share invite link', '링크로 누구나 크루에 초대할 수 있어요': 'Anyone can join via the link',
  '이름으로 친구 찾기': 'Search friends by name', '최근 함께 달린 친구': 'Recently ran with', '친구': 'Friends', '검색 결과': 'Results',
  '초대': 'Invite', '초대됨': 'Invited', '완료': 'Done', '함께 달린 친구 · 한강': 'Ran together · Hangang',
  '수락': 'Accept', '거절': 'Decline', '대기 중인 가입 요청이 없어요.': 'No pending join requests.', '건 대기 중': ' pending',
  '즐겨찾는 크루': 'Favorite crews',
  '운영진 권한 설정': 'Staff permissions', '일반 권한': 'General permissions', '주의가 필요한 권한': 'Sensitive permissions', '주의': 'Caution',
  '챌린지 생성·수정': 'Create/edit challenges', '멤버 초대': 'Invite members', '크루 러닝 시작': 'Start crew runs', '크루 정보 수정': 'Edit crew info', '멤버 추방': 'Remove members', '다른 운영진 임명': 'Appoint other staff',
  '크루 공지를 작성하고 관리해요': 'Write and manage crew notices', '크루 챌린지를 만들고 교체해요': 'Create and replace crew challenges', '새 크루원을 초대하고 링크를 공유해요': 'Invite members and share links', '크루 러닝을 시작해 챌린지에 반영해요': 'Start crew runs that count toward challenges', '이름·지역·소개·공개 범위를 변경해요': 'Change name, area, intro, visibility', '크루원을 내보낼 수 있어요': 'Can remove crew members', '크루원을 운영진으로 지정·해제해요': 'Promote/demote staff',
  '이 권한들은 크루 구성에 큰 영향을 줄 수 있어요. 신뢰하는 운영진에게만 부여하세요.': 'These permissions can significantly affect the crew. Grant them only to trusted staff.', '운영진을 찾을 수 없어요.': 'Staff member not found.',
  '이 운영진 화면으로 미리보기': 'Preview as this staff', '운영진 미리보기': 'Staff preview', '크루 편집': 'Edit crew',
  '함께 달린 친구 · 성수': 'Ran together · Seongsu', '함께 달린 친구 · 남산': 'Ran together · Namsan',
  '크루 찾기': 'Find crews', '이번 주 활동': 'This week', '나': 'Me',
  '해당 종목의 챌린지가 아직 없어요.': 'No challenges in this category yet.',
  '러닝': 'Running', '라이딩': 'Cycling', '워킹': 'Walking',

  // ── lock / upsell copy ──
  'AI 월간 분석 잠금 해제': 'Unlock AI monthly analysis', '프리미엄으로 더 깊은 인사이트를': 'Deeper insights with Premium',
  '보기': 'View', '프리미엄으로 잠금 해제': 'Unlock with Premium', '프리미엄으로 잠금 해제하기': 'Unlock with Premium',
  '월간 AI 인사이트': 'Monthly AI insight', '고도 최적화': 'Elevation optimization',
  '미세먼지 회피 경로': 'Dust-avoiding routes', '프리미엄 페이스 분석': 'Premium pace analysis',
  'AI 프리미엄 코스 생성': 'AI premium course generation',

  // ── notifications ──
  '모두 읽음': 'Mark all read', '시스템': 'System', '소셜': 'Social',

  // ── logout modal ──
  '로그아웃 할까요?': 'Log out?',
  '다시 로그인하면 모든 기록과 설정이 그대로 유지돼요.': 'Your records and settings stay safe when you log back in.',
  '버전 2.4.1 (842) · Made in Seoul': 'Version 2.4.1 (842) · Made in Seoul',

  // ── people (romanized) ──
  '지윤': 'Jiyoon', '김도현': 'Dohyun Kim', '이서연': 'Seoyeon Lee', '박지호': 'Jiho Park', '최유진': 'Yujin Choi',
  '정민수': 'Minsu Jung', '한도윤': 'Doyun Han', '서지안': 'Jian Seo', '문하늘': 'Haneul Moon', '오세훈': 'Sehoon Oh',
  '정민서': 'Minseo Jung', '한소희': 'Sohee Han', '윤재호': 'Jaeho Yoon', '강다은': 'Daeun Kang', '문가영': 'Gayoung Moon',
  '백승호': 'Seungho Baek', '임도윤': 'Doyun Im', '조하늘': 'Haneul Jo', '신우진': 'Woojin Shin', '권나래': 'Narae Kwon', '홍민재': 'Minjae Hong',

  // ── locations ──
  '한강 · 뚝섬': 'Hangang · Ttukseom', '남산': 'Namsan', '올림픽공원': 'Olympic Park', '양재천': 'Yangjaecheon',
  '서울숲': 'Seoul Forest', '성수동': 'Seongsu', '뚝섬한강공원': 'Ttukseom Hangang Park', '응봉산': 'Eungbongsan',
  '중랑천': 'Jungnangcheon', '한강 전역': 'All of Hangang', '성수 · 뚝섬': 'Seongsu · Ttukseom', '여의도 · 반포': 'Yeouido · Banpo',
  '여의도 한강공원': 'Yeouido Hangang Park', '한강 자전거길': 'Hangang Bike Path', '남산 · 회현': 'Namsan · Hoehyeon',
  '서울숲 공원': 'Seoul Forest Park', '강남구청 인근': 'Near Gangnam', '남산 둘레길': 'Namsan Trail', '성수동 골목길': 'Seongsu Alleys',
  '잠실 종합운동장': 'Jamsil Sports Complex', '현재 위치: 서울숲 공원': 'Location: Seoul Forest Park',

  // ── run / course titles ──
  '한강 야경 러닝': 'Hangang Night Run', '남산 언덕 코스': 'Namsan Hill Course', '올림픽공원 둘레길': 'Olympic Park Loop',
  '양재천 새벽 런': 'Yangjaecheon Dawn Run', '서울숲 인터벌': 'Seoul Forest Intervals', '성수 카페거리 러닝': 'Seongsu Cafe St. Run',
  '뚝섬 강변 5K': 'Ttukseom Riverside 5K', '응봉산 언덕 훈련': 'Eungbongsan Hill Training', '중랑천 LSD': 'Jungnangcheon LSD',
  '강남 저녁 시티런': 'Gangnam Evening City Run', '주말 롱런': 'Weekend Long Run', '리커버리 조깅': 'Recovery Jog',
  '벚꽃 강변 러닝': 'Riverside Blossom Run', '인터벌 트랙': 'Interval Track', '자유 러닝': 'Free Run',

  // ── crews / challenges ──
  '한강 100K 챌린지': 'Hangang 100K Challenge', '성수 새벽 크루': 'Seongsu Dawn Crew', '한강 페이서스': 'Hangang Pacers',
  '6월 한강 100K': 'June Hangang 100K', '주간 50K 릴레이': 'Weekly 50K Relay', '서브4 빌드업': 'Sub-4 Buildup',
  '6월 한강 100K 챌린지': 'June Hangang 100K Challenge',
  '여의도 벚꽃 30K': 'Yeouido Blossom 30K', '성수 새벽 7일 루틴': 'Seongsu 7-Day Dawn Routine',
  '한강 라이딩 200K': 'Hangang Cycling 200K', '남산 둘레길 워킹': 'Namsan Trail Walk',
  '시즌': 'Season', '입문': 'Beginner',

  // ── tags ──
  '야경': 'Night', '도심': 'City', '경치': 'Scenic', '공원': 'Park', '자연': 'Nature', '조용함': 'Quiet',
  '강변': 'Riverside', '회복': 'Recovery', '롱런': 'Long run', '인터벌': 'Interval', '트랙': 'Track',

  // ── weather / zones / misc ──
  '맑음': 'Clear', '좋음': 'Good', '보통': 'Moderate', '나쁨': 'Bad', '매우 나쁨': 'Very bad',
  'Zone 5 · 최대': 'Zone 5 · Max', 'Zone 4 · 고강도': 'Zone 4 · High', 'Zone 3 · 유산소': 'Zone 3 · Aerobic', 'Zone 2 · 지방연소': 'Zone 2 · Fat burn',
  '어제': 'Yesterday', '오늘': 'Today', '내 코스에 저장됨': 'Saved to my courses', '저장된 코스': 'Saved courses',
  '여성': 'Female', '남성': 'Male',
  // split-node fragments (greeting / counts / labels)
  '안녕하세요,': 'Welcome,', '님': '', '미세먼지': 'Fine dust', '친구': 'Friends', '페이스': 'Pace',
  '근처': 'Nearby', '개 크루 활동 중': ' crews', '명 ·': ' members ·', '미세먼지 (AQI)': 'Fine dust (AQI)',
  '초미세 PM2.5': 'Ultrafine PM2.5', '습도': 'Humidity', '바람': 'Wind', '자외선': 'UV', '강수확률': 'Rain chance',
  '미세': 'Dust', '초미세': 'PM2.5', '초미세먼지': 'Ultrafine dust',
  // avatar initials (single-char name monograms → romanized first letter)
  '지': 'J', '김': 'K', '이': 'L', '박': 'P', '최': 'C', '정': 'J', '한': 'H', '서': 'S', '문': 'M', '오': 'O',
  '강': 'K', '백': 'B', '임': 'I', '조': 'J', '신': 'S', '권': 'K', '홍': 'H', '윤': 'Y',
  // weather detail
  '러닝하기 딱 좋아요': 'Great for running', 'AI 러닝 지수': 'AI running index', '최적의 컨디션': 'Optimal conditions',
  '기온과 습도가 러닝에 매우 이상적이에요. 가볍게 한 바퀴 돌기 좋은 날입니다.': 'Temperature and humidity are ideal for running — a great day for an easy lap.',
  'AI 조언': 'AI advice', '미세먼지가 적고 바람이 시원해요. 한강변 5km 러닝은 어떠세요?': 'Low dust and a cool breeze. How about a 5km run along the Hangang?',
  '러닝 시작하기': 'Start run', '회복 조언': 'Recovery advice', '목표': 'Goal', '참여 중': 'Joined', '챌린지 참여하기': 'Join challenge',
  '총 운동 시간': 'Total active time', 'AI 월간 분석:': 'AI monthly analysis:',
  '지난달보다 지구력이 12% 향상됐어요. 현재 페이스를 유지하며 주행 거리를 조금씩 늘려보세요.': 'Your endurance is up 12% from last month. Keep this pace and gradually add distance.',
  // monthly insight coaching + plan
  '5월은 지구력이 눈에 띄게 좋아진 달이에요. 주간 거리를 꾸준히 늘리면서도 평균 페이스가 6초 빨라졌고, 4주 차에 최고 페이스를 경신했습니다. 고강도(Zone 4) 비중이 다소 높으니, 6월에는 회복 러닝을 한 세션 더 넣어 균형을 맞추는 걸 추천해요.': 'May was a clear step up in endurance. You steadily added weekly distance while cutting average pace by 6s, and set a best pace in week 4. High-intensity (Zone 4) share is a bit high, so in June add one more recovery run to balance it out.',
  '월 50km · 회복 러닝 주 1회': 'Monthly 50km · 1 recovery run/week', 'Zone 2 유산소 비중 늘리기': 'Increase Zone 2 aerobic share', '5K 24분 벽 깨기': 'Break the 24-min 5K barrier',
  // activity insight / recovery sentences
  '초반 페이스를 잘 조절했고, 후반 1km 구간에서 케이던스가 5% 향상됐어요. 네거티브 스플릿이 완벽했습니다.': 'You paced the start well and lifted cadence 5% in the final km. A perfect negative split.',
  '고강도 구간이 많았어요. 가벼운 스트레칭과 충분한 수분 섭취를 권장하며, 다음 러닝까지 24시간 휴식을 추천해요.': 'Lots of high-intensity work. Stretch lightly, hydrate well, and rest 24h before your next run.',
  '꾸준한 페이스로 안정적인 러닝이었어요. 신호 대기 구간을 제외하면 페이스 편차가 거의 없었습니다.': 'A steady, stable run. Apart from traffic-light stops, your pace barely varied.',
  '중강도 러닝이었어요. 가벼운 폼롤러 마사지로 마무리하면 좋아요.': 'A moderate-intensity run. Finish with a light foam-roller session.',
  '언덕 구간에서 페이스를 잘 유지했어요. 누적 고도 86m를 소화한 의미 있는 롱런입니다.': 'You held pace well on the hills — a meaningful long run with 86m of climbing.',
  '장거리 + 언덕 러닝이라 근피로가 누적됐어요. 48시간 회복과 단백질 보충을 추천해요.': 'Long run plus hills built up muscle fatigue. Rest 48h and refuel with protein.',
  '심박수를 낮게 유지한 좋은 회복 러닝이에요. 다음 고강도 세션을 위한 완벽한 마무리입니다.': 'A good recovery run with low heart rate — a perfect cap before your next hard session.',
  '회복 러닝이라 별도 휴식은 필요 없어요. 가벼운 스트레칭으로 충분합니다.': 'A recovery run needs no extra rest. Light stretching is enough.',
  '봄 날씨에 맞춰 편안한 페이스로 거리를 늘렸어요. 후반 페이스가 오히려 빨라진 좋은 러닝입니다.': 'You extended distance at an easy spring pace — and even sped up late. Nicely done.',
  '무리 없는 강도였어요. 가벼운 스트레칭으로 마무리하세요.': 'An easy effort. Wrap up with light stretching.',
  '인터벌 구간에서 목표 페이스를 정확히 지켰어요. 회복 구간 심박 관리도 좋았습니다.': 'You hit target pace precisely on the intervals and managed recovery heart rate well.',
  '고강도 인터벌이라 근피로가 커요. 48시간 휴식과 충분한 단백질 섭취를 추천해요.': 'High-intensity intervals cause heavy muscle fatigue. Rest 48h and get plenty of protein.',
  '자유 러닝을 안정적인 페이스로 완주했어요. 후반까지 페이스 저하 없이 잘 유지했습니다.': 'You completed a free run at a steady pace, holding strong with no late fade.',
  '가벼운 스트레칭과 수분 보충으로 마무리하세요. 다음 러닝까지 충분한 휴식을 추천해요.': 'Finish with light stretching and hydration. Rest well before your next run.',
  // home AI banner (split by <br/>)
  '날씨·체력 맞춤 AI 코스를': 'Weather & fitness-matched AI courses', '프리미엄에서 만나보세요': 'Discover with Premium',
  '오늘 날씨에 딱 맞는': "Perfect for today's weather", '새 코스가 준비됐어요': 'a new course is ready', 'AI 추천 코스': 'AI recommended course',
};

// interpolated patterns (applied when no exact match). [regex, replacement|fn]
var FR_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
var FR_WD = { '월': 'Mon', '화': 'Tue', '수': 'Wed', '목': 'Thu', '금': 'Fri', '토': 'Sat', '일': 'Sun' };
var FR_I18N_RE = [
  [/^평균 (\d+) bpm$/, 'Avg $1 bpm'],
  [/^최대 (\d+) bpm$/, 'Max $1 bpm'],
  [/^평균 (\d+)bpm$/, 'Avg $1 bpm'],
  [/^최대 (\d+)$/, 'Max $1'],
  [/^(\d{4}) · (\d+)월$/, (m, y, mo) => `${y} · ${FR_MONTHS[+mo - 1]}`],
  [/^(\d{4})년$/, '$1'],
  [/^(\d+)월$/, (m, mo) => FR_MONTHS[+mo - 1]],
  [/^(\d+)s 빨라짐$/, '$1s faster'],
  [/^언덕 (\d+)회$/, '$1 hills'],
  [/^\+(\d+)회$/, '+$1'],
  [/^(\d{4}) · (\d+)월 리포트$/, (m, y, mo) => `${y} · ${FR_MONTHS[+mo - 1]} Report`],
  [/^-?(\d+)s 빨라짐$/, '$1s faster'],
  [/^(\d+)% 달성$/, '$1% done'],
  [/^목표까지 ([\d.]+)km$/, 'To goal $1km'],
  [/^4주 동안 꾸준히 늘었어요\. 마지막 주가 가장 길었습니다 \(([\d.]+)km\)\.$/, 'Climbed steadily over 4 weeks; the last week was longest ($1km).'],
  [/^지수 (\d+)$/, 'Index $1'],
  [/^(\d+)명 참여$/, '$1 joined'],
  [/^([\d.]+) km · 예상 (\d+)분 · (.+)$/, (m, d, min, vibe) => `${d} km · ~${min} min · ${FR_I18N[vibe] || vibe}`],
  [/^([월화수목금토일])요일, (\d+)월 (\d+)일$/, (m, wd, mo, d) => `${FR_WD[wd]}, ${FR_MONTHS[+mo - 1]} ${d}`],
  [/^(\d+)시간 전$/, '$1h ago'],
  [/^(\d+)분 전$/, '$1m ago'],
  [/^(\d+)일 전$/, '$1d ago'],
  [/^(\d+)일$/, '$1 days'],
  [/^(\d+)명$/, '$1 members'],
  [/^(\d+)월 (\d+)일 · (.+)$/, (m, mo, d, rest) => `${FR_MONTHS[+mo - 1]} ${d} · ${rest}`],
  [/^(\d+)월 (\d+)일$/, (m, mo, d) => `${FR_MONTHS[+mo - 1]} ${d}`],
  [/^오늘 · (.+)$/, 'Today · $1'],
  [/^어제 · (.+)$/, 'Yesterday · $1'],
  [/^목표 (\d[\d.]*)km$/, 'Goal $1km'],
  [/^근처 (\d+)개 크루 활동 중$/, '$1 crews active nearby'],
  [/^근처 (\d+)개 크루$/, '$1 nearby crews'],
  [/^(\d+)일 연속.*$/, '$1-day streak'],
  [/^(\d+)개 코스$/, '$1 courses'],
  [/^(\d+)개 활동$/, '$1 activities'],
  [/^(\d+)개$/, '$1'],
  [/^안녕하세요, (.+)님$/, (m, nm) => 'Welcome, ' + (FR_I18N[nm] || nm)],
  [/^(\d+)km 완주$/, '$1km done'],
  [/^월 목표 (\d[\d.]*)km까지\s*$/, 'To monthly goal: $1km · '],
  [/^지난달 대비\s*$/, 'vs last month '],
  [/^ · 목표까지 (\d[\d.]*)km$/, ' · $1km to goal'],
  [/^(\d+)% 달성$/, '$1% done'],
  [/^(\d+)일째$/, 'Day $1'],
  [/^주 (\d+)회$/, '$1×/week'],
];

(function () {
  let busy = false;
  function walk(node, dict) {
    if (node.nodeType === 3) {
      const raw = node.nodeValue;
      if (!raw) return;
      const key = raw.trim();
      if (!key) return;
      if (key in dict) { node.nodeValue = raw.replace(key, dict[key]); return; }
      for (let i = 0; i < FR_I18N_RE.length; i++) {
        const rule = FR_I18N_RE[i];
        if (rule[0].test(key)) { node.nodeValue = raw.replace(key, key.replace(rule[0], rule[1])); return; }
      }
    } else if (node.nodeType === 1) {
      const tag = node.nodeName;
      if ((tag === 'INPUT' || tag === 'TEXTAREA') && node.placeholder && dict[node.placeholder]) node.placeholder = dict[node.placeholder];
      if (tag === 'INPUT' && node !== document.activeElement && node.value && dict[node.value]) node.value = dict[node.value];
      for (let ch = node.firstChild; ch; ch = ch.nextSibling) walk(ch, dict);
    }
  }
  window.frTranslateTree = function (root, dict) { if (root) walk(root, dict); };
  window.frInstallTranslator = function (root, dict) {
    if (!root) return null;
    const apply = () => { if (busy) return; busy = true; try { walk(root, dict); } finally { busy = false; } };
    apply();
    const obs = new MutationObserver(() => { window.requestAnimationFrame(apply); });
    obs.observe(root, { childList: true, subtree: true, characterData: true });
    return obs;
  };
  window.FR_I18N = FR_I18N;
})();
