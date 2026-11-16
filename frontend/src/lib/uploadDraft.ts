/**
 * 사진 올리기 UPLOAD_001 → UPLOAD_002 가 고른 사진·요청 번호(D17)·한마디·사진 속 사람을 주고받는 곳.
 * 메모리에만 있어 새로고침하면 비워짐.
 */
import type { PhotoOut } from '../api/types'

/** peopleNote = 사진 속 사람 '직접 쓰기' 칸, peopleIds = 칩으로 고른 구성원 user_id (보낼 때 가족방마다 그 방 호칭으로 바꿈) */
export const uploadDraft: { files: File[]; batchId: string; caption: string; peopleNote: string; peopleIds: number[] } = {
  files: [],
  batchId: '',
  caption: '',
  peopleNote: '',
  peopleIds: [],
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
  uploadDraft.files = []
  uploadDraft.batchId = ''
  uploadDraft.caption = ''
  uploadDraft.peopleNote = ''
  uploadDraft.peopleIds = []
  uploadResult.batchId = ''
  uploadResult.rooms = []
}
