/**
 * 가족 일기(오늘 한 장) FDIARY_001 → 002 → 003 이 나눠 쓰는 칸 (lib/uploadDraft.ts 와 같은 방법).
 * 메모리에 있고, 글 칸(text·question·answer)과 userId 만 sessionStorage 에도 둔다 — 다른 앱에 갔다 오면 폰이
 * 화면을 새로 열 때가 있어서(특히 아이폰). 같은 창 안에서만 남고, 사진·기분·초안은 남기지 않는다.
 * 서버에는 003 [게시하기] 때 한 번에 보낸다.
 */
import type { Mood, RoomOut } from '../api/types'

const empty = () => ({
  userId: null as number | null, // 쓰기 시작한 사람 — 같은 창에서 다른 계정으로 바뀌면 되살리지 않는다
  photo: null as File | null, // 오늘 찍은 사진 1장 (없으면 사진 없이 쓰기)
  text: '', // 한마디 (200자)
  question: '', // 일기 동무 질문 — 한 편에 한 번만 받는다
  answer: '', // 그 질문에 한 답 (안 써도 됨)
  mood: null as Mood | null,
  draft: '', // 일기 동무가 다듬은 초안 (003 에서 고침)
  room: null as RoomOut | null, // 쓰기 시작할 때 보던 분 — 002 질문·초안을 이 방으로 묻는다
  rooms: [] as RoomOut[], // 내 가족방 전부 — 003 '보낼 분'의 기본값
  // 003 [게시하기] 때 보낸 그대로(번호·글·기분·사진·보낼 분). 한 방이라도 올라간 뒤에는 이걸 고정해, 1·2단계에서 글·사진을
  // 바꾸고 와도 남은 방에 '똑같은 일기'만 다시 보낸다 — 할머니마다 다른 일기를 받지 않게(003 리뷰 1번). 같은 번호라 두 번 눌러도 하나씩만(D17)
  sent: null as null | {
    postId: string // 일기 request_id
    batchId: string // 사진 upload_batch_id
    body: string
    mood: Mood
    photo: File | null
    targets: number[] // 보낼 가족방 번호
  },
  done: [] as number[], // 올라간 가족방 번호 — 하나라도 있으면 003 은 잠긴다
})

export const familyDiaryDraft = empty()

const KEY = 'haru.fam.diary-draft'
type SavedText = { userId: number | null; text: string; question: string; answer: string }

// 페이지를 열 때 한 번 읽어 둔 글 — 1단계 첫 [다음]이 한 번만 되살린다(restoreFamilyDiaryText).
// 가족 일기 화면(/fdiary…)에 있다가 새로 열렸을 때만 — 다른 화면에서 열렸으면 쓰다 그만둔 글이라 버린다
// (안 버리면 나중에 탭으로 새로 쓸 때 옛 글이 붙는다)
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

/** 글 칸이 바뀔 때마다 부른다 (FDIARY_001 [다음] · FDIARY_002 한마디·질문·답) */
export function saveFamilyDiaryText() {
  const { userId, text, question, answer, done } = familyDiaryDraft
  if (done.length > 0) return // 한 방이라도 올라갔으면 남기지 않는다 — 아래 forgetFamilyDiaryText
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ userId, text, question, answer } satisfies SavedText))
  } catch {
    // 사생활 보호 모드 — 메모리에만 남는다
  }
}

/** 페이지를 새로 연 뒤 첫 [다음] — 같은 사람이 쓰던 글이면 되살린다. 다른 계정이면 버린다 */
export function restoreFamilyDiaryText(userId: number) {
  const s = saved
  saved = null
  if (s?.userId !== userId) return
  familyDiaryDraft.text = s.text ?? ''
  familyDiaryDraft.question = s.question ?? ''
  familyDiaryDraft.answer = s.answer ?? ''
}

/**
 * 남긴 글만 지운다(메모리는 그대로). FDIARY_003 에서 한 방이라도 올라가면 부른다 — 새로고침 뒤 '보낸 방' 표시(sent·done)는
 * 사라지는데 글만 돌아오면, 다시 게시할 때 이미 받은 방에 같은 일기가 또 간다
 */
export function forgetFamilyDiaryText() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // 사생활 보호 모드 — 남긴 것도 없다
  }
}

/** 다 쓰고 게시했을 때, 그리고 새로 쓰기 시작할 때 비운다(남긴 글도) — 앞 일기·앞 계정의 글이 남지 않게 */
export function clearFamilyDiaryDraft() {
  Object.assign(familyDiaryDraft, empty())
  forgetFamilyDiaryText()
}
