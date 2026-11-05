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

export type InviteKind = 'FAMILY' | 'ELDER_DEVICE'
export type InviteCreatedOut = { invite_id: number; kind: InviteKind; url: string; expires_at: string }
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

export type AiOut = {
  text: string
  audio_b64: string | null
  suggestions: string[]
  choice_mode: 'CHIPS' | 'TWO_BUTTONS'
  question_type: 'RECALL' | 'REMEMBER' | 'KNOWHOW' | 'THEN_NOW' | 'RECHECK' | 'CLOSING' | 'NONE'
}
export type SessionState = 'CONTINUE' | 'ENDED'
export type EndReason = 'COMPLETED' | 'USER_STOP' | 'NO_RESPONSE' | 'ERROR' | 'LIMIT'
export type SessionOut = {
  session_id: string
  ai: AiOut
  state: SessionState
  end_reason: EndReason | null
  turn_no: number
  input_locked: boolean
}
export type SessionGetOut = {
  session_id: string
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
