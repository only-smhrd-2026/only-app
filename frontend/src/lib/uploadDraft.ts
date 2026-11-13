/**
 * 사진 올리기 UPLOAD_001 → UPLOAD_002 가 고른 사진·요청 번호(D17)·한마디·사진 속 사람을 주고받는 곳.
 * 메모리에만 있어 새로고침하면 비워짐.
 */
export const uploadDraft: { files: File[]; batchId: string; caption: string; peopleNote: string } = {
  files: [],
  batchId: '',
  caption: '',
  peopleNote: '',
}

/** 고른 사진을 비운다 — 다 보냈을 때, 그리고 계정이 바뀔 때(로그인·로그아웃). 앞 사람이 고른 사진이 다음 사람 화면에 남지 않게. */
export function clearUploadDraft() {
  uploadDraft.files = []
  uploadDraft.batchId = ''
  uploadDraft.caption = ''
  uploadDraft.peopleNote = ''
}
