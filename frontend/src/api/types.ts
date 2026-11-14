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
  tts_voice: 'FEMALE' | 'MALE' // 어르신께 들려 드리는 목소리 (D74)
  device_input_mode: 'VOICE' | 'BUTTON'
  status: string
  is_owner: boolean
  // 가족 홈 '시작 3단계'·어르신 바꾸기 판 (D70). 사진 수는 기기 링크 조건(사진 3장)과 같은 셈
  photo_count: number
  member_count: number
  device_connected: boolean
  device_last_seen_at: string | null // 어르신 폰이 마지막으로 서버에 온 때 (5분마다 갱신)
}
/** PATCH /api/rooms/{room_id}/settings (방장만). 보낸 칸만 바뀐다. 추억 시간은 정각만, 말 속도는 글자로 */
export type RoomSettingsIn = {
  memory_time?: string
  diary_time?: string
  font_size?: 'L' | 'XL' | 'XXL'
  tts_speed?: '0.80' | '0.90' | '1.00' // D74 (전 0.70·0.85·1.00)
  tts_voice?: 'FEMALE' | 'MALE'
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
  settings: {
    font_size: 'L' | 'XL' | 'XXL'
    tts_speed: string | number
    input_mode: 'VOICE' | 'BUTTON'
    tts_voice: 'FEMALE' | 'MALE' // 고정 안내 mp3 도 이 목소리로 (D74)
  }
}

export type SttOut = { transcript: string; confidence: number }

// ---- 알림 (backend/app/schemas/notifications.py)
export type NotificationOut = { notification_id: number; room_id: number; kind: string; title: string; body: string | null; link_screen: string | null; sent_at: string; read_at: string | null } // read_at이 null이면 안 읽음
export type NotificationListOut = { notifications: NotificationOut[]; unread: number } // 최신 순 최대 50개, unread는 안 읽은 전체 수
// ---- 주간 이야기 (backend/app/schemas/weekly.py · ai/weekly.py)
// 질문·답 카드 한 장 (D62). 질문은 대화 원문, 답은 어르신 말을 전하는 전달형 한 문장. 사진이 지워졌거나 없으면 photo_url null
export type WeeklyCard = {
  photo_id: number | null
  photo_url: string | null
  date: string
  question: string
  answer: string
  session_id: string
  source_turns: number[]
}
export type WeeklyOut = {
  week_start: string // 그 주 월요일 'YYYY-MM-DD'
  memory_days: number // 회상 대화에서 말씀하신 날 수 (0~7)
  diary_days: number // 일기 쓴 날 수 (0~7)
  qa_list: WeeklyCard[] // 주간 요약 AI 의 카드 최대 4장. 아직 안 붙었거나 실패하면 []
  recall_check: Record<string, unknown>
  mood_trend: { date: string; mood: Mood | null }[] // 7칸, 월 → 일
  talk_volume: { words: number; turns: number; avg_words: number }
  diaries: { diary_id: number; date: string; mood: Mood }[]
  notes: { lines: string[] } | null // 안부 한 줄 — 기운 없음·위급 대화가 있던 주 (D62)
}

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
export type PhotoOut = {
  photo_id: number
  url: string
  taken_at: string | null
  caption: string | null
  people_note: string | null
  status: string
  // AI 분류 (D71·D73, 가족방 탭 '올린 사진' GROUP_004). 분류 전이면 analyzed=false, ai_* 는 null
  source: 'FAMILY' | 'ELDER_CAMERA' | 'FAMILY_DIARY'
  analyzed: boolean
  ai_activity: string | null // data/taxonomy.json 의 활동 글자 또는 'none'
  ai_scene: string | null // 보이는 모습 한 줄
  corrected_activity: string | null // 가족이 고친 활동('none' = 맞는 것 없음) — 있으면 이것이 먼저
}
export type PhotoListOut = { photos: PhotoOut[] }
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
  reactions: Reaction[] // 리액션 (D54). 누른 사람마다 1칸 — 가족 이모지는 어르신 일기에, 어르신 좋아요는 가족 일기에
}
// 리액션 한 칸. name = 누른 가족의 별명(없으면 이름), 어르신은 null
// 가족: POST /api/diaries/{id}/reaction { kind, on } · 어르신: POST /api/elder/diaries/{id}/like { on } → 둘 다 DiaryOut
// on 은 '이 상태로 만들어 줘' — 화면은 지금 보이는 상태의 반대를 보낸다(같은 요청이 두 번 가도 결과가 같다)
export type Reaction = {
  by: 'ELDER' | 'FAMILY'
  kind: 'LIKE' | 'HEART' | 'SMILE' | 'CLAP'
  user_id: number | null
  name: string | null
  at: string
}
export type DiaryListOut = { diaries: DiaryOut[] }
// 어르신 가족 소식 GET /api/elder/family-news (D63): 안 들은 가족 일기 + 아직 못 들은 가족 이모지(첫 장 '하트가 왔어요', 받은 순서)
// 첫 장을 읽어 드린 뒤 POST /api/elder/hearts/heard { until: 읽어 드린 마지막 하트의 at } → 204
export type Heart = { diary_id: number; kind: 'HEART' | 'SMILE' | 'CLAP'; name: string | null; at: string }
export type FamilyNewsOut = DiaryListOut & { hearts: Heart[] }
// ---- 가족 일기 동무 (backend/app/schemas/family_diary.py, D58) — FDIARY_002 질문 · FDIARY_003 초안. 서버는 저장하지 않는다
// POST /api/rooms/{room_id}/family-diary/ask · /draft. 여러 가족방에 보내도 고른 방 하나로 한 번만 부른다
export type FamilyAskIn = { text: string } // 가족이 쓴 말 1~200자
export type FamilyAskOut = { question: string } // 질문 1개 (AI 가 실패하면 고정 질문)
export type FamilyDraftIn = { text: string; question?: string; answer?: string } // 답은 비워도 됨 → 쓴 말만으로
export type FamilyDraftOut = { body: string } // 존댓말 1인칭 3~5문장 → 가족이 고친 뒤 POST /rooms/{id}/diaries
