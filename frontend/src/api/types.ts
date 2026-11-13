/** 서버 응답 타입 — backend/app/schemas/*.py 의 거울. 서버 모양이 바뀌면 여기도 같이 (PR 리뷰어 김승희). */

export type UserOut = { user_id: number; email: string | null; name: string; login_type: string; created_at: string }

export type RoomOut = {
  room_id: number
  elder_name: string
  elder_honorific: string
  owner_user_id: number
  memory_time: string
  diary_time: string
  font_size: 'L' | 'XL' | 'XXL'
  tts_speed: string | number
  device_input_mode: 'VOICE' | 'BUTTON'
  status: string
  is_owner: boolean
}
/** PATCH /api/rooms/{room_id}/settings (방장만). 보낸 칸만 바뀐다. 추억 시간은 정각만, 말 속도는 글자로 */
export type RoomSettingsIn = {
  memory_time?: string
  diary_time?: string
  font_size?: 'L' | 'XL' | 'XXL'
  tts_speed?: '0.70' | '0.85' | '1.00'
  device_input_mode?: 'VOICE' | 'BUTTON'
}

export type RelationTag = 'CHILD' | 'GRANDCHILD' | 'OTHER'
export type InviteKind = 'FAMILY' | 'ELDER_DEVICE'
export type InviteCreatedOut = { kind: InviteKind; url: string; expires_at: string } // 종류마다 링크 1개 (D38)
export type InviteStatusOut = { kind: InviteKind; elder_name: string; expires_at: string; valid: boolean }
export type InviteOut = { kind: InviteKind; expires_at: string }

export type DeviceOut = {
  room_id: number
  elder_name: string
  elder_honorific: string
  perm_mic: boolean
  perm_camera: boolean
  perm_notification: boolean
  input_mode: 'VOICE' | 'BUTTON'
}

export type TodayPickOut = { pick_id: number; photo_id: number; photo_url: string; status: string }
export type ElderHomeOut = {
  greeting: string
  elder_name: string
  elder_honorific: string
  today_pick: TodayPickOut | null
  unread_family_news: number
  settings: { font_size: 'L' | 'XL' | 'XXL'; tts_speed: string | number; input_mode: 'VOICE' | 'BUTTON' }
}

export type SttOut = { transcript: string; confidence: number }

// ---- 알림 (backend/app/schemas/notifications.py)
export type NotificationOut = { notification_id: number; room_id: number; kind: string; title: string; body: string | null; link_screen: string | null; sent_at: string; read_at: string | null } // read_at이 null이면 안 읽음
export type NotificationListOut = { notifications: NotificationOut[]; unread: number } // 최신 순 최대 50개, unread는 안 읽은 전체 수

export type AiOut = {
  text: string
  audio_b64: string | null
  suggestions: string[]
  choice_mode: 'CHIPS' | 'TWO_BUTTONS'
  question_type: 'RECALL' | 'REMEMBER' | 'KNOWHOW' | 'THEN_NOW' | 'COMMON' | 'RECHECK' | 'CLOSING' | 'NONE'
}
export type SessionState = 'CONTINUE' | 'ENDED'
export type EndReason = 'COMPLETED' | 'USER_STOP' | 'NO_RESPONSE' | 'ERROR' | 'LIMIT'
export type SessionKind = 'MEMORY' | 'ALBUM' | 'DIARY'
export type SessionOut = {
  session_id: string
  kind: SessionKind
  photo_url: string | null
  ai: AiOut
  state: SessionState
  end_reason: EndReason | null
  turn_no: number
  input_locked: boolean
}
export type SessionGetOut = {
  session_id: string
  kind: SessionKind
  photo_url: string | null
  state: SessionState
  end_reason: EndReason | null
  last_ai: AiOut | null
  turn_no: number
  input_locked: boolean
  turns: TurnOut[] // 지난 말 (오래된 것 → 마지막 질문). 이어서 할 때 말풍선으로 다시 보인다 (D52 ⑥)
}
export type TurnOut = { speaker: 'AI' | 'ELDER'; text: string }
export type TurnIn = {
  text?: string
  input_type: 'VOICE' | 'CHIP' | 'BUTTON' | 'TEXT' // TEXT = 글로 쓰기 (D52 ⑤)
  stt_confidence?: number
  retried?: boolean
  event?: 'NO_RESPONSE'
}

export type AlbumOut = { photos: { photo_id: number; url: string; taken_at: string | null; caption: string | null }[] }
// ---- 사진 올리기 (backend/app/schemas/photos.py, D17)
export type PhotoOut = { photo_id: number; url: string; taken_at: string | null; caption: string | null; people_note: string | null; status: string }
export type PhotoBatchOut = { upload_batch_id: string; photos: PhotoOut[] }

// ---- 일기 (backend/app/schemas/diaries.py, D36)
export type Mood = 'SUNNY' | 'CLOUDY' | 'RAINY' | 'MOON'
/** 기분 날씨 표시 이름 (일기 대화 마지막 칩과 같은 글자) */
export const MOOD_LABEL: Record<Mood, string> = { SUNNY: '맑음', CLOUDY: '구름', RAINY: '비', MOON: '달' }

// ---- 가족 홈 마음 카드 (backend/app/schemas/mood.py)
export type MoodDayOut = { date: string; talked: boolean; diary_mood: Mood | null; low: boolean }
export type MoodCheckOut = { check_date: string; level: 'USUAL' | 'DOWN' | 'HARD' } // 마음 체크 마지막 결과. 점수는 오지 않음
export type MoodWeekOut = { days: MoodDayOut[]; talked_days: number; low_days: number; last_check: MoodCheckOut | null } // days 는 7칸, 오래된 날 → 오늘
export type MoodCheckDueOut = { due: boolean } // 어르신 홈 마음 체크 초대 (D56)
export type MoodCheckIn = { answers: number[] } // 8칸, 문항 순서대로 0~3
export type IllustrationType = 'PHOTO' | 'AI_DRAWING' | 'NONE'
export type DraftOut = {
  session_id: string
  body: string
  mood: Mood
  photo_id: number | null
  illustration_type: IllustrationType
  illustration_url: string | null // PHOTO 면 /api/media/{key}
  illustration_b64: string | null // AI_DRAWING 이면 JPEG base64 (올리기 전이라 URL 없음)
  audio_b64: string | null // 본문 + "이대로 올릴까요?" TTS. null 이면 speechSynthesis
}
export type DiaryOut = {
  diary_id: number
  room_id: number
  author_type: 'ELDER' | 'FAMILY'
  author_name: string | null
  author_nickname: string | null // 가족방 별명(예: 큰딸). 가족 일기에만, 없으면 null — 어르신 가족 소식이 '큰딸 ○○'로 읽는다
  body: string
  mood: Mood
  illustration_type: IllustrationType
  illustration_url: string | null
  posted_at: string
  read_by_elder: boolean
  read_by_me: boolean // false 면 가족 홈 '새 일기'
}
export type DiaryListOut = { diaries: DiaryOut[] }
// ---- 가족 일기 동무 (backend/app/schemas/family_diary.py, D58) — FDIARY_002 질문 · FDIARY_003 초안. 서버는 저장하지 않는다
// POST /api/rooms/{room_id}/family-diary/ask · /draft. 여러 가족방에 보내도 고른 방 하나로 한 번만 부른다
export type FamilyAskIn = { text: string } // 가족이 쓴 말 1~200자
export type FamilyAskOut = { question: string } // 질문 1개 (AI 가 실패하면 고정 질문)
export type FamilyDraftIn = { text: string; question?: string; answer?: string } // 답은 비워도 됨 → 쓴 말만으로
export type FamilyDraftOut = { body: string } // 존댓말 1인칭 3~5문장 → 가족이 고친 뒤 POST /rooms/{id}/diaries
