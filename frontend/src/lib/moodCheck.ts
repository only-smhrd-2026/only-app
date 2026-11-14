/**
 * 마음 체크 (D56·D66) — 2주에 한 번 홈 위 초대(ELDER_MOOD_001) → 8문항(ELDER_MOOD_002). 글은 이 파일 한 곳에 둔다.
 *
 * 문항은 PHQ-9 공식 한국어판(9번 제외, D56)의 뜻을 그대로 두고 '지난 2주 동안 … 날이 얼마나 있었어요?'로 풀어 쓴 것이다
 * (11/14 사용자 결정 — 공식판 그대로는 머리말만 질문이라 화면마다 같은 질문처럼 보였다). 보기의 점수 0~3 은 그대로.
 *   출처: https://www.phqscreeners.com → PHQ-9, Korean for Korea (PHQ9_Korean for Korea.pdf, 11/14 내려받아 확인)
 *   그 문서 아래: 'Pfizer Inc.로부터 교육용 지원금을 받아 Robert L. Spitzer 박사, Janet B.W. Williams 박사, Kurt Kroenke 박사와
 *   동료들에 의해 개발된 것임. 복제, 번역, 전시 또는 배포를 위해 허가가 필요하지 않음.'
 * 초대·끝 인사는 11/12 목업의 글.
 *
 * MOOD_PROMPT 는 lib/audio.ts 의 PROMPT 에 펼쳐져 mp3(assets/audio/<키>.mp3)와 이어진다 — 한 줄에 '  키: '문장',' 모양을 지킨다.
 * 문장을 바꾸면 mp3 를 다시 만든다(audio.ts 의 명령). 서버는 답(0~3) 8개만 저장한다(routers/mood.py).
 */
export const MOOD_PROMPT = {
  moodInvite: '요즘 마음이 어떠세요? 여덟 가지만 여쭤볼게요. 2~3분이면 돼요. 답하신 내용은 가족에게 요즘 어떠신지 한 줄로만 알려요.',
  mood1: '지난 2주 동안 일이나 여가 활동에 흥미나 즐거움을 못 느낀 날이 얼마나 있었어요?',
  mood2: '지난 2주 동안 기분이 가라앉거나 우울하거나 희망이 없던 날이 얼마나 있었어요?',
  mood3: '지난 2주 동안 잠들기 어렵거나 자다가 자주 깼거나, 또는 잠을 너무 많이 잔 날이 얼마나 있었어요?',
  mood4: '지난 2주 동안 피곤하거나 기운이 거의 없던 날이 얼마나 있었어요?',
  mood5: '지난 2주 동안 입맛이 없거나 너무 많이 먹은 날이 얼마나 있었어요?',
  mood6: '지난 2주 동안 스스로가 못났다거나 실패했다고 느끼거나, 자신이나 가족을 실망시켰다고 느낀 날이 얼마나 있었어요?',
  mood7: '지난 2주 동안 신문을 읽거나 텔레비전을 볼 때 집중하기 어려웠던 날이 얼마나 있었어요?',
  mood8: '지난 2주 동안 다른 사람이 알아챌 만큼 몸이나 말이 느려졌거나, 반대로 너무 안절부절못해서 평소보다 많이 움직인 날이 얼마나 있었어요?',
  moodThanks: '말씀해 주셔서 고마워요. 오늘도 좋은 하루 보내세요.',
} as const

/** 문항 순서 = 서버 answers 의 순서 */
export const MOOD_ITEMS = [
  MOOD_PROMPT.mood1,
  MOOD_PROMPT.mood2,
  MOOD_PROMPT.mood3,
  MOOD_PROMPT.mood4,
  MOOD_PROMPT.mood5,
  MOOD_PROMPT.mood6,
  MOOD_PROMPT.mood7,
  MOOD_PROMPT.mood8,
] as const

/** 보기 4개. 자리 = 서버에 보내는 값 0~3 (공식판 '전혀 방해 받지 않았다 · 며칠 동안 · 7 일 이상 · 거의 매일'과 같은 칸) */
export const MOOD_ANSWERS = ['없었어요', '며칠 있었어요', '절반 넘게 있었어요', '거의 매일이었어요'] as const

// [다음에]를 누르거나 하다가 나가면 그날은 다시 권하지 않고 다음 날 다시 권한다 (D66). 서버는 기억하지 않는다
const KEY = 'haru.moodLater'
const kstToday = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' }) // 2026-11-14

/** 오늘은 그만 권한다 */
export function snoozeMood() {
  try {
    localStorage.setItem(KEY, kstToday())
  } catch {
    // 사생활 보호 모드 등 — 기억만 못 한다(홈을 새로 열 때 다시 권함)
  }
}

/** 오늘 이미 권했는지 */
export function moodSnoozed() {
  try {
    return localStorage.getItem(KEY) === kstToday()
  } catch {
    return false
  }
}
