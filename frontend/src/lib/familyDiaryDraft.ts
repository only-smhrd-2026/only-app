/**
 * 가족 '오늘 소식'(FDIARY_001 한 화면, 11/23 — 옛 3단계 '오늘 한 장'을 합침)의 쓰던 것 (lib/uploadDraft.ts 와 같은 방법).
 * 메모리에 있어 ← 로 나갔다 다시 들어와도 그대로고, 글 칸(text·question·answer)과 userId 만 sessionStorage 에도 둔다 —
 * 다른 앱에 갔다 오면 폰이 화면을 새로 열 때가 있어서(특히 아이폰). 같은 창 안에서만 남고, 사진·기분은 남기지 않는다.
 * 서버에는 [○○께 보내기] 때 한 번에 보낸다.
 */
import type { Mood } from '../api/types'

const empty = () => ({
  userId: null as number | null, // 쓰기 시작한 사람 — 같은 창에서 다른 계정으로 바뀌면 되살리지 않는다
  photo: null as File | null, // 오늘 사진 1장 (안 골라도 됨)
  text: '', // 보낼 글 (200자). 일기 동무가 다듬으면 그 글로 바뀐다
  before: '', // 다듬기 전 글 — [처음 글로]
  question: '', // 일기 동무 질문 — 한 편에 한 번만 받는다
  answer: '', // 그 질문에 한 답 (안 써도 됨)
  mood: 'GOOD' as Mood, // 시안 f-today 처음 값
  // 마지막으로 보낸 그대로(번호·글·기분·사진). 같은 것을 다시 보내면(답을 못 받고 다시 누름) 같은 번호로 — 서버가 한 번만 저장(D17)
  sent: null as null | { postId: string; batchId: string; body: string; mood: Mood; photo: File | null },
})

export const familyDiaryDraft = empty()

const KEY = 'haru.fam.diary-draft'
type SavedText = { userId: number | null; text: string; question: string; answer: string }

// 페이지를 열 때 한 번 읽어 둔 글 — 화면이 같은 사람일 때 한 번만 되살린다(restoreFamilyDiaryText).
// 오늘 소식 화면(/fdiary)에 있다가 새로 열렸을 때만 — 다른 화면에서 열렸으면 쓰다 그만둔 글이라 버린다
let saved: SavedText | null = (() => {
  try {
    if (!location.pathname.startsWith('/fdiary')) {
      sessionStorage.removeItem(KEY)
      return null
    }
    const raw = sessionStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as SavedText) : null
  } catch {
    return null // 사생활 보호 모드·망가진 값 — 남긴 글 없이 시작
  }
})()

/** 글 칸이 바뀔 때마다 부른다 (글·질문·답) */
export function saveFamilyDiaryText() {
  const { userId, text, question, answer } = familyDiaryDraft
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ userId, text, question, answer } satisfies SavedText))
  } catch {
    // 사생활 보호 모드 — 메모리에만 남는다
  }
}

/**
 * 화면을 열 때 — 메모리의 쓰던 것이 다른 사람 것이면 비우고, 페이지를 새로 연 뒤 처음이면 같은 사람이 쓰던 글을 되살린다.
 * 같은 사람이 ← 로 나갔다 온 것이면 그대로 둔다
 */
export function restoreFamilyDiaryText(userId: number) {
  if (familyDiaryDraft.userId !== userId) Object.assign(familyDiaryDraft, empty(), { userId })
  const s = saved
  saved = null
  if (s?.userId !== userId) return
  familyDiaryDraft.text = s.text ?? ''
  familyDiaryDraft.question = s.question ?? ''
  familyDiaryDraft.answer = s.answer ?? ''
}

/** 보냈을 때, 그리고 계정이 바뀔 때(로그인·로그아웃·탈퇴) 비운다(남긴 글도) — 앞 소식·앞 계정의 글이 남지 않게 */
export function clearFamilyDiaryDraft() {
  Object.assign(familyDiaryDraft, empty())
  saved = null
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // 사생활 보호 모드 — 남긴 것도 없다
  }
}
