/**
 * 사진 올리기 UPLOAD_001 → UPLOAD_002 가 고른 사진·요청 번호(D17)·한마디·사진 속 사람을 주고받는 곳.
 * 메모리에만 있어 새로고침하면 비워짐.
 */
import type { PhotoOut } from '../api/types'

export const uploadDraft: { files: File[]; batchId: string; caption: string; peopleNote: string } = {
  files: [],
  batchId: '',
  caption: '',
  peopleNote: '',
}

/** UPLOAD_002 → UPLOAD_003 이 보낸 결과를 주고받는 곳. 가족방 목록 순서, 성공한 곳은 서버가 준 사진도 같이 담긴다 */
export type UploadRoomResult = { room_id: number; name: string; ok: boolean; text: string; photos: PhotoOut[] }
export const uploadResult: { batchId: string; rooms: UploadRoomResult[] } = { batchId: '', rooms: [] }

/** 고른 사진·보낸 결과를 비운다 — 다 보냈을 때, 그리고 계정이 바뀔 때(로그인·로그아웃). 앞 사람 것이 다음 사람 화면에 남지 않게. */
export function clearUploadDraft() {
  uploadDraft.files = []
  uploadDraft.batchId = ''
  uploadDraft.caption = ''
  uploadDraft.peopleNote = ''
  uploadResult.batchId = ''
  uploadResult.rooms = []
}
