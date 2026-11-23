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
 * 문장을 바꾸면 mp3 를 다시 만든다(audio.ts 의 명령). 서버는 답을 종류(kind)별로 저장한다(routers/mood.py).
 */
import type { MoodKind } from '../api/types'
export const MOOD_PROMPT = {
  moodInvite: '요즘 마음이 어떠세요? 여덟 가지만 여쭤볼게요. 2~3분이면 돼요. 잠이나 입맛처럼 불편하신 점은 가족에게 쉬운 말로 알려요.',
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

/*
 * 11/23 내 마음 (ELDER_MIND_001) — 체크 5가지. 글은 11/23 시안(TESTS)의 것, 보기 칸 수는 각 척도의 원래 칸 수 그대로
 * (자리 = 서버에 보내는 값, 채점은 서버 routers/mood.py). WHO-5·ISI 는 넣지 않는다(사용자 결정).
 *   PHQ-9 9번: 공식 한국어판 '자신이 죽는 것이 더 낫다고 생각하거나 어떤 식으로든 자신을 해칠 것이라고 생각함'을 위와 같은 말투로.
 *   UCLA-3: 공식 1~3점 = 값+1 (서버가 더함). SMCQ: 아니요 0 · 네 1.
 * 이 글들은 mp3 가 없어 서버 목소리로 읽는다(lib/audio.ts say → /api/elder/speech). PHQ-8 문항은 위 MOOD_PROMPT mp3 그대로.
 */
export type CheckKind = Exclude<MoodKind, 'MEMGAME'>
type Check = { name: string; info: string; items: readonly string[]; answers: readonly string[] }

const MOOD9 = '지난 2주 동안 죽는 것이 더 낫다고 생각하거나, 어떤 식으로든 스스로를 해치려고 생각한 날이 얼마나 있었어요?'

export const CHECKS: Record<CheckKind, Check> = {
  PHQ8: { name: '마음 체크', info: '여덟 가지 · 3분', items: MOOD_ITEMS, answers: MOOD_ANSWERS },
  PHQ9: { name: '마음 자세히 체크', info: '아홉 가지 · 3분', items: [...MOOD_ITEMS, MOOD9], answers: MOOD_ANSWERS },
  UCLA3: {
    name: '외로움 체크',
    info: '세 가지 · 1분',
    items: [
      '요즘 곁에 함께할 사람이 없다고 느끼실 때가 얼마나 있어요?',
      '요즘 혼자 남겨졌다고 느끼실 때가 얼마나 있어요?',
      '요즘 다른 사람들과 멀리 떨어져 있다고 느끼실 때가 얼마나 있어요?',
    ],
    answers: ['거의 없어요', '가끔 있어요', '자주 있어요'],
  },
  GAD7: {
    name: '걱정 체크',
    info: '일곱 가지 · 2분',
    items: [
      '지난 2주 동안 초조하거나 불안하거나 조마조마했던 날이 얼마나 있었어요?',
      '지난 2주 동안 걱정을 멈추기 어려웠던 날이 얼마나 있었어요?',
      '지난 2주 동안 여러 가지 일로 걱정을 너무 많이 하신 날이 얼마나 있었어요?',
      '지난 2주 동안 편하게 쉬기 어려웠던 날이 얼마나 있었어요?',
      '지난 2주 동안 안절부절못해서 가만히 있기 힘들었던 날이 얼마나 있었어요?',
      '지난 2주 동안 쉽게 짜증이 나거나 화가 났던 날이 얼마나 있었어요?',
      '지난 2주 동안 끔찍한 일이 생길 것처럼 두려웠던 날이 얼마나 있었어요?',
    ],
    answers: MOOD_ANSWERS,
  },
  SMCQ: {
    name: '기억력 체크',
    info: '열네 가지 · 3분',
    items: [
      '요즘 기억력에 문제가 있다고 느끼세요?',
      '10년 전보다 기억력이 나빠졌다고 느끼세요?',
      '같은 또래보다 기억력이 나쁘다고 느끼세요?',
      '깜빡하는 일 때문에 생활이 불편하세요?',
      '최근에 있었던 일이 잘 기억나지 않으세요?',
      '며칠 전에 나눈 이야기가 잘 기억나지 않으세요?',
      '며칠 전에 한 약속이 잘 기억나지 않으세요?',
      '친한 사람 이름이 잘 떠오르지 않으세요?',
      '물건을 둔 곳이 잘 기억나지 않으세요?',
      '예전보다 물건을 자주 잃어버리세요?',
      '집 근처에서 길을 잃으신 적이 있으세요?',
      '가게에서 사려던 물건 두세 가지가 잘 기억나지 않으세요?',
      '가스불이나 전깃불 끄는 걸 잊으실 때가 있으세요?',
      '자주 거는 전화번호가 잘 기억나지 않으세요?',
    ],
    answers: ['아니요', '네'],
  },
}

/** 주소 ?kind= → 체크 종류. 모르는 값·없으면 PHQ-8 */
export function checkKind(v: string | null): CheckKind {
  return v && Object.hasOwn(CHECKS, v) ? (v as CheckKind) : 'PHQ8'
}

const ORD = ['첫', '두', '세', '네', '다섯', '여섯', '일곱', '여덟', '아홉', '열', '열한', '열두', '열세', '열네']
/** 몇 번째 질문인지 읽어 줄 말 (n = 0 부터) */
export const ordinal = (n: number) => `${ORD[n] ?? n + 1} 번째 질문이에요.`

/*
 * 기억력 놀이 (ELDER_MIND_002) — 낱말 셋을 보고, 잠깐 다른 이야기를 한 뒤, 여섯 개 중에서 고른다.
 * 같은 낱말을 날마다 보면 외워 버리므로 한국 날짜로 하루마다 다음 벌로 바꾼다. 보기 여섯 개는 정답·헷갈리는 것이 섞인 순서.
 */
type Word = readonly [emoji: string, word: string]
export type MemSet = { words: readonly Word[]; choices: readonly Word[] }
const W = (e: string, w: string): Word => [e, w]
export const MEM_SETS: readonly MemSet[] = [
  { words: [W('🍎', '사과'), W('🚂', '기차'), W('🌲', '소나무')], choices: [W('🍐', '배'), W('🚂', '기차'), W('🌸', '꽃'), W('🍎', '사과'), W('🚌', '버스'), W('🌲', '소나무')] },
  { words: [W('🐶', '강아지'), W('☂️', '우산'), W('🌙', '달')], choices: [W('☂️', '우산'), W('🐱', '고양이'), W('⭐', '별'), W('🐶', '강아지'), W('🌙', '달'), W('🧢', '모자')] },
  { words: [W('🍚', '밥'), W('🚲', '자전거'), W('🌻', '해바라기')], choices: [W('🚲', '자전거'), W('🍜', '국수'), W('🌻', '해바라기'), W('🚗', '자동차'), W('🌷', '튤립'), W('🍚', '밥')] },
  { words: [W('⏰', '시계'), W('🐟', '물고기'), W('🏔️', '산')], choices: [W('🐟', '물고기'), W('📻', '라디오'), W('🌊', '바다'), W('⏰', '시계'), W('🏔️', '산'), W('🐦', '새')] },
  { words: [W('🍉', '수박'), W('👟', '운동화'), W('🏠', '집')], choices: [W('🍓', '딸기'), W('🏠', '집'), W('👟', '운동화'), W('🏫', '학교'), W('🍉', '수박'), W('🧦', '양말')] },
  { words: [W('📖', '책'), W('🐄', '소'), W('☀️', '해')], choices: [W('🐄', '소'), W('✏️', '연필'), W('☀️', '해'), W('🐷', '돼지'), W('📖', '책'), W('☁️', '구름')] },
  { words: [W('🥕', '당근'), W('✈️', '비행기'), W('🎈', '풍선')], choices: [W('✈️', '비행기'), W('🎈', '풍선'), W('🥔', '감자'), W('🚢', '배'), W('🥕', '당근'), W('🎁', '선물')] },
]

/** 오늘(한국 날짜)의 낱말 벌 — 이어진 날은 늘 다른 벌 */
export function memSetFor(now = Date.now()): MemSet {
  const day = Math.floor((now + 9 * 3_600_000) / 86_400_000) // KST 날짜 번호
  return MEM_SETS[day % MEM_SETS.length]
}

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
