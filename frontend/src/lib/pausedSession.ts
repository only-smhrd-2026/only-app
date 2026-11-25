/**
 * 뒤로 키로 잠깐 나간 대화 (D52 ⑥). 대화 화면이 적고, 홈의 '이어서'(김승희 새 홈)가 읽는다.
 * 서버도 마지막 턴 뒤 30분까지만 잇는다(SESSION_RESUME_MIN). 앱이 꺼졌다 켜져도 남게 기기(localStorage)에 둔다.
 * 대화 번호만 둔다 — 열려면 어르신 기기 쿠키가 있어야 해서 토큰이 아니다. 저장을 못 하는 기기는 '이어서'만 안 된다.
 * 잡담(D106)은 칸을 따로 둔다 — 홈의 '하던 이야기'는 회상·일기만 보고, 하나뿐인 그 칸의 회상 대화를 지우지 않게.
 * 잡담 화면이 그 칸을 읽어 30분 안이면 같은 잡담을 잇는다 — 사진첩·지난 이야기·홈에 갔다 와도 (D107).
 */
import type { ChatGo, SessionKind } from '../api/types'

const KEY = 'haru.pausedSession'
const CHAT_KEY = 'haru.chatSession'
const RESUME_MS = 30 * 60_000

/** went = 잡담이 데려다 드린 화면 (돌아오면 '사진첩 잘 보셨어요?') */
export type Paused = { id: string; kind: SessionKind; at: number; went?: ChatGo }

/** 이어서 연 대화의 첫마디 — 지금 질문 앞에 붙여 읽는다 (11/23 시안 talkBefore) */
export const RESUME_LEAD = '아까 하던 이야기를 이어서 할게요.'

export function savePaused(p: Paused) {
  try {
    localStorage.setItem(p.kind === 'CHAT' ? CHAT_KEY : KEY, JSON.stringify(p))
  } catch {
    // 사생활 보호 모드 등 — 이어서만 안 된다
  }
}

/** 끝난 대화를 지운다. id 를 주면 그 대화일 때만 (다른 대화를 이어 가는 중이면 그대로) */
export function clearPaused(id?: string) {
  try {
    for (const key of [KEY, CHAT_KEY]) if (!id || read(key)?.id === id) localStorage.removeItem(key)
  } catch {
    // 위와 같음
  }
}

function read(key: string, now = Date.now()): Paused | null {
  try {
    const p = JSON.parse(localStorage.getItem(key) ?? 'null') as Paused | null
    return p && now - p.at < RESUME_MS ? p : null
  } catch {
    return null
  }
}

/** 30분 안에 나간 회상·일기 대화. 홈이 '이어서'를 보일지 정한다 */
export const readPaused = (now = Date.now()) => read(KEY, now)

/** 30분 안에 하던 잡담. 잡담 화면이 새로 열지 이어서 열지 정한다 */
export const readChat = (now = Date.now()) => read(CHAT_KEY, now)

/** '이어서'를 누르면 갈 주소 — 대화 화면이 서버에서 지난 말풍선과 지금 질문을 다시 읽는다 */
export function resumePath(p: Paused) {
  return p.kind === 'DIARY' ? `/elder/diary/${p.id}` : `/elder/memory/${p.id}`
}
