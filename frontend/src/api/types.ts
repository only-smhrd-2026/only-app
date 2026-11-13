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
  status: string
  is_owner: boolean
}

export type RelationTag = 'CHILD' | 'GRANDCHILD' | 'OTHER'
export type InviteKind = 'FAMILY' | 'ELDER_DEVICE'
export type InviteCreatedOut = { kind: InviteKind; url: string; expires_at: string } // 종류마다 링크 1개 (D38)
export type InviteStatusOut = { kind: InviteKind; elder_name: string; expires_at: string; valid: boolean }

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
}
export type TurnIn = {
  text?: string
  input_type: 'VOICE' | 'CHIP' | 'BUTTON'
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
