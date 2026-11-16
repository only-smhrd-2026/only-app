/**
 * 가족 일기(오늘 한 장) FDIARY_001 → 002 → 003 이 나눠 쓰는 칸 (lib/uploadDraft.ts 와 같은 방법).
 * 메모리에만 있어 새로고침하면 비워진다. 서버에는 003 [게시하기] 때 한 번에 보낸다.
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
})

export const familyDiaryDraft = empty()

/** 다 쓰고 게시했을 때, 그리고 새로 쓰기 시작할 때 비운다 — 앞 일기·앞 계정의 글이 남지 않게 */
export function clearFamilyDiaryDraft() {
  Object.assign(familyDiaryDraft, empty())
}
