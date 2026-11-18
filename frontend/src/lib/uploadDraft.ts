/**
 * 사진 올리기 UPLOAD_001 → UPLOAD_002 가 고른 사진·요청 번호(D17)·한마디·사진 속 사람을 주고받는 곳.
 * 메모리에 있고, 글 칸(caption·peopleNote)만 sessionStorage 에도 둔다 — 폰이 화면을 새로 열어도 같은 창이면 한마디가 남게.
 * 사진·요청 번호·고른 사람 칩은 남기지 않는다(새로고침하면 사진을 다시 고른다).
 */
import type { PhotoOut } from '../api/types'

/** peopleNote = 사진 속 사람 '직접 쓰기' 칸, peopleIds = 칩으로 고른 구성원 user_id (보낼 때 가족방마다 그 방 호칭으로 바꿈) */
export const uploadDraft: {
  userId: number | null
  files: File[]
  batchId: string
  caption: string
  peopleNote: string
  peopleIds: number[]
} = {
  userId: null, // 고르기 시작한 사람(UPLOAD_001 [다음]) — 남긴 글은 같은 사람에게만 되살린다
  files: [],
  batchId: '',
  caption: '',
  peopleNote: '',
  peopleIds: [],
}

const KEY = 'haru.fam.upload-draft'

type SavedText = { userId: number | null; caption: string; peopleNote: string }

// 페이지를 열 때 한 번 읽어 둔 글 — UPLOAD_001 첫 [다음]이 같은 사람일 때만 되살린다(restoreUploadText).
// sessionStorage 는 탭마다 따로라 다른 탭에서 로그인한 사람에게는 clearUploadDraft 가 닿지 않는다 — 그래서 사람을 본다
// (familyDiaryDraft 와 같은 방법). 추억 올리기 화면(/upload…)에 있다가 새로 열렸을 때만 — 다른 화면에서 열렸으면
// 쓰다 그만둔 글이라 버린다(안 버리면 나중에 고른 다른 사진에 옛 한마디·사진 속 사람이 붙는다)
let saved: SavedText | null = (() => {
  try {
    if (!location.pathname.startsWith('/upload')) {
      sessionStorage.removeItem(KEY)
      return null
    }
    const raw = sessionStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as SavedText) : null
  } catch {
    return null // 사생활 보호 모드·망가진 값 — 남긴 글 없이 시작
  }
})()

/** 페이지를 새로 연 뒤 첫 [다음](UPLOAD_001) — 같은 사람이 쓰던 글이면 되살린다. 다른 계정이면 버린다 */
export function restoreUploadText(userId: number) {
  const s = saved
  saved = null
  if (s?.userId !== userId) return
  uploadDraft.caption = s.caption ?? ''
  uploadDraft.peopleNote = s.peopleNote ?? ''
}

/** 남긴 글만 지운다(메모리는 그대로). UPLOAD_002 에서 한 방이라도 올라가면 부른다 — 새로고침 뒤 같은 글로
 *  이미 받은 방에 또 보내지 않게 (FDIARY 의 forgetFamilyDiaryText 와 같은 이유) */
export function forgetUploadText() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // 사생활 보호 모드 — 남긴 것도 없다
  }
}

/** 한마디·사진 속 사람이 바뀔 때마다 부른다 (UPLOAD_002) */
export function saveUploadText() {
  try {
    const { userId, caption, peopleNote } = uploadDraft
    sessionStorage.setItem(KEY, JSON.stringify({ userId, caption, peopleNote } satisfies SavedText))
  } catch {
    // 사생활 보호 모드 — 메모리에만 남는다
  }
}

/** 사진 자체가 문제일 때 서버가 주는 코드 (routers/photos.py) — 어느 가족방에 보내도 같은 답이라 남은 방에는 보내지 않는다.
 * 추억 올리기 UPLOAD_002 와 가족 일기 FDIARY_003 이 같이 쓴다 */
export const PHOTO_PROBLEMS = ['BAD_IMAGE', 'IMAGE_TOO_LARGE', 'PHOTO_TOO_BIG', 'TOO_MANY_PHOTOS']

/** UPLOAD_002 → UPLOAD_003 이 보낸 결과를 주고받는 곳. 가족방 목록 순서, 성공한 곳은 서버가 준 사진도 같이 담긴다.
 *  text = 한 줄 전체(예 '순자 할머니: 이유'), why = 실패 이유만(성공이면 빈 칸) */
export type UploadRoomResult = { room_id: number; name: string; ok: boolean; text: string; why: string; photos: PhotoOut[] }
export const uploadResult: { batchId: string; rooms: UploadRoomResult[] } = { batchId: '', rooms: [] }

/** 고른 사진·보낸 결과를 비운다 — 다 보냈을 때, 그리고 계정이 바뀔 때(로그인·로그아웃). 앞 사람 것이 다음 사람 화면에 남지 않게. */
export function clearUploadDraft() {
  uploadDraft.userId = null
  saved = null
  uploadDraft.files = []
  uploadDraft.batchId = ''
  uploadDraft.caption = ''
  uploadDraft.peopleNote = ''
  uploadDraft.peopleIds = []
  uploadResult.batchId = ''
  uploadResult.rooms = []
  forgetUploadText()
}
