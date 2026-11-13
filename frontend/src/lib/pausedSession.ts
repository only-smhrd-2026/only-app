/**
 * 뒤로 키로 잠깐 나간 대화 (D52 ⑥). 대화 화면이 적고, 홈의 '이어서'(김승희 새 홈)가 읽는다.
 * 서버도 마지막 턴 뒤 30분까지만 잇는다(SESSION_RESUME_MIN). 앱이 꺼졌다 켜져도 남게 기기(localStorage)에 둔다.
 * 대화 번호만 둔다 — 열려면 어르신 기기 쿠키가 있어야 해서 토큰이 아니다. 저장을 못 하는 기기는 '이어서'만 안 된다.
 */
import type { SessionKind } from '../api/types'

const KEY = 'haru.pausedSession'
const RESUME_MS = 30 * 60_000

export type Paused = { id: string; kind: SessionKind; at: number }

export function savePaused(p: Paused) {
  try {
    localStorage.setItem(KEY, JSON.stringify(p))
  } catch {
    // 사생활 보호 모드 등 — 이어서만 안 된다
  }
}

/** 끝난 대화를 지운다. id 를 주면 그 대화일 때만 (다른 대화를 이어 가는 중이면 그대로) */
export function clearPaused(id?: string) {
  try {
    if (!id || readPaused()?.id === id) localStorage.removeItem(KEY)
  } catch {
    // 위와 같음
  }
}

/** 30분 안에 나간 대화. 홈이 '이어서'를 보일지 정한다 */
export function readPaused(now = Date.now()): Paused | null {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Paused | null
    return p && now - p.at < RESUME_MS ? p : null
  } catch {
    return null
  }
}

/** '이어서'를 누르면 갈 주소 — 대화 화면이 서버에서 지난 말풍선과 지금 질문을 다시 읽는다 */
export function resumePath(p: Paused) {
  return p.kind === 'DIARY' ? `/elder/diary/${p.id}` : `/elder/memory/${p.id}`
}
