/**
 * 마음 체크 (D56·D66) — 2주에 한 번 홈 위 초대(ELDER_MOOD_001) → 8문항(ELDER_MOOD_002). 글은 이 파일 한 곳에 둔다.
 *
 * 문항·머리말·보기는 PHQ-9 공식 한국어판을 **한 글자도 바꾸지 않고** 옮긴 것이다(띄어쓰기 '2 주일'·'7 일'도 원문 그대로).
 * 9번 문항은 넣지 않는다(D56). 고치지 않는다 — 말투를 바꾸면 검증된 문구가 아니게 된다.
 *   출처: https://www.phqscreeners.com → PHQ-9, Korean for Korea (PHQ9_Korean for Korea.pdf, 11/14 내려받아 확인)
 *   그 문서 아래: 'Pfizer Inc.로부터 교육용 지원금을 받아 Robert L. Spitzer 박사, Janet B.W. Williams 박사, Kurt Kroenke 박사와
 *   동료들에 의해 개발된 것임. 복제, 번역, 전시 또는 배포를 위해 허가가 필요하지 않음.'
 * 초대·끝 인사는 11/12 목업의 글(공식 문구가 아니다).
 *
 * MOOD_PROMPT 는 lib/audio.ts 의 PROMPT 에 펼쳐져 mp3(assets/audio/<키>.mp3)와 이어진다 — 한 줄에 '  키: '문장',' 모양을 지킨다.
 * 문장을 바꾸면 mp3 를 다시 만든다(audio.ts 의 명령). 서버는 답(0~3) 8개만 저장한다(routers/mood.py).
 */
export const MOOD_PROMPT = {
  moodInvite: '요즘 마음이 어떠세요? 여덟 가지만 여쭤볼게요. 2~3분이면 돼요. 답하신 내용은 가족에게 요즘 어떠신지 한 줄로만 알려요.',
  moodStem: '지난 2 주일 동안 당신은 다음의 문제들로 인해서 얼마나 자주 방해를 받았습니까?',
  mood1: '일 또는 여가 활동을 하는 데 흥미나 즐거움을 느끼지 못함',
  mood2: '기분이 가라앉거나, 우울하거나, 희망이 없음',
  mood3: '잠이 들거나 계속 잠을 자는 것이 어려움, 또는 잠을 너무 많이 잠',
  mood4: '피곤하다고 느끼거나 기운이 거의 없음',
  mood5: '입맛이 없거나 과식을 함',
  mood6: '자신을 부정적으로 봄 - 혹은 자신이 실패자라고 느끼거나 자신 또는 가족을 실망시킴',
  mood7: '신문을 읽거나 텔레비전 보는 것과 같은 일에 집중하는 것이 어려움',
  mood8: '다른 사람들이 주목할 정도로 너무 느리게 움직이거나 말을 함. 또는 반대로 평상시보다 많이 움직여서, 너무 안절부절 못하거나 들떠 있음',
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

/** 보기 4개 (공식 한국어판 그대로). 자리 = 서버에 보내는 값 0~3 */
export const MOOD_ANSWERS = ['전혀 방해 받지 않았다', '며칠 동안 방해 받았다', '7 일 이상 방해 받았다', '거의 매일 방해 받았다'] as const

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
