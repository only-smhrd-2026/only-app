/** 서버 응답 타입 — backend/app/schemas/*.py 의 거울. 서버 모양이 바뀌면 여기도 같이 (PR 리뷰어 김승희). */

// profile_url = 내 정보에서 올린 프로필 사진(11/27), 없으면 null — PATCH /api/auth/me { name } · PUT/DELETE /api/auth/me/photo → UserOut
export type UserOut = { user_id: number; email: string | null; name: string; login_type: string; created_at: string; profile_url: string | null }
export type PasswordChangeIn = { current_password: string; new_password: string }
/** POST /api/auth/withdraw — 회원 탈퇴. transfers = 내가 방장인 가족방마다 1칸: 방장을 넘길 가족, 혼자인 방은 null(가족방을 지움) */
export type WithdrawIn = { password: string; transfers: { room_id: number; new_owner_user_id: number | null }[] }
// ---- 카카오 로그인 (backend/app/schemas/kakao.py)
export type ProvidersOut = { kakao: boolean } // GET /api/auth/providers — 서버에 카카오 키가 없으면 false('준비 중')
export type KakaoPendingOut = { nickname: string } // GET /api/auth/kakao/signup — 처음 온 카카오 회원의 이름 칸에 미리 넣는다(없으면 '')

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
  weather_region: string | null // 어르신 동네 '서울'·'전남 영광군' — 심심이 날씨 (D106·D111). null = 안 정함
  device_input_mode: 'VOICE' | 'BUTTON'
  status: string
  elder_photo_url: string | null // 어르신 얼굴 사진 (11/27, 방장이 넣음). null = 이름 첫 글자 동그라미
  is_owner: boolean
  // 가족 홈 '시작 3단계'·어르신 바꾸기 판 (D70). 사진 수는 기기 링크 조건(사진 3장)과 같은 셈
  photo_count: number
  member_count: number
  device_connected: boolean
  device_perm_mic: boolean | null
  device_perm_camera: boolean | null
  device_perm_notification: boolean | null
  device_last_seen_at: string | null // 어르신 폰이 마지막으로 서버에 온 때 (5분마다 갱신)
}
/** PATCH /api/rooms/{room_id}/settings (방장만). 보낸 칸만 바뀐다. 추억 시간은 정각만, 말 속도는 글자로 */
export type RoomSettingsIn = {
  memory_time?: string
  diary_time?: string
  font_size?: 'L' | 'XL' | 'XXL'
  tts_speed?: '0.80' | '0.90' | '1.00' // D74 (전 0.70·0.85·1.00)
  tts_voice?: 'FEMALE' | 'MALE'
  weather_region?: string // '서울'·'전남 영광군' (서버 config.PLACES, 목록은 GET /api/rooms/regions — D111)
  device_input_mode?: 'VOICE' | 'BUTTON'
  elder_name?: string // 1~10자
  elder_honorific?: string // 부르는 말 1~20자 (빈 칸은 서버가 거절)
}

export type RelationTag = 'CHILD' | 'GRANDCHILD' | 'OTHER'
/** GET /api/rooms/{room_id}/members — 내보낸 사람은 빼고 들어온 순서 (#141) */
export type MemberOut = {
  user_id: number
  name: string
  nickname: string | null // 어르신이 부르는 호칭(예: 큰딸)
  profile_url: string | null // 프로필 사진 (11/27), 없으면 null
  relation_tag: RelationTag
  joined_at: string
  is_owner: boolean
}
export type InviteKind = 'FAMILY' | 'ELDER_DEVICE'
export type InviteCreatedOut = { kind: InviteKind; url: string; expires_at: string } // 종류마다 링크 1개 (D38)
export type InviteStatusOut = { kind: InviteKind; elder_name: string; expires_at: string; valid: boolean; inviter_name: string | null } // 11/23 초대한 사람
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
// GET /api/elder/weather — 홈·잡담 심심이 날씨 그림 (11/26). null = 늘 쓰던 그림
export type WeatherLook = 'snow' | 'raincoat' | 'umbrella' | 'winter' | 'hot' | 'wind'
export type ElderWeatherOut = { look: WeatherLook | null }
// GET /api/rooms/regions — '사시는 동네' 시·도 → 시·군 (D111). towns 가 비면 시·도 하나로 고른다
export type RegionOut = { name: string; towns: string[] }
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
  diary_today: boolean // 11/23 오늘 어르신 일기를 올렸나 — 홈 말풍선 순서
  mood_due: boolean // 11/23 마음 체크 할 차례(= GET /elder/mood-check/due) — '내 마음' 칸 ! 표시
}
// 11/23 어르신 설정 화면·처음 연결 글자 단계: PATCH /api/elder/settings (어르신 기기 쿠키). 보낸 칸만 바뀐다
export type ElderSettingsOut = ElderHomeOut['settings']
export type ElderSettingsIn = Partial<Pick<ElderSettingsOut, 'font_size' | 'tts_speed' | 'tts_voice'>>

export type SttOut = { transcript: string; confidence: number }

// ---- 알림 (backend/app/schemas/notifications.py)
export type NotificationOut = { notification_id: number; room_id: number; kind: string; title: string; body: string | null; link_screen: string | null; link_id: number | null; sent_at: string; read_at: string | null } // link_id: 11/23 일기 알림 = diary_id // read_at이 null이면 안 읽음
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
  prev_week_start: string | null // 지난 주 이야기가 있으면 그 주 월요일 — ‹ 로 ?week_start= (목업 ⑤)
  next_week_start: string | null // 다음 주 이야기가 있으면 그 주 월요일 — ›
  memory_days: number // 회상 대화에서 말씀하신 날 수 (0~7)
  diary_days: number // 일기 쓴 날 수 (0~7)
  // 사진 바로잡기 카드(최대 2장, FR-ME-009 — answer 가 "이 사진은 …래요.") + 주간 요약 AI 의 카드 최대 4장. 없으면 []
  qa_list: WeeklyCard[]
  recall_check: Record<string, unknown>
  mood_trend: { date: string; mood: Mood | null }[] // 7칸, 월 → 일
  talk_volume: { words: number; turns: number; avg_words: number }
  // illustration_url = 가족 홈 일기 카드와 같은 사진·그림일기 주소. 그림 없는 일기·지운 일기는 null → 기분 얼굴(MoodIcon)
  diaries: { diary_id: number; date: string; mood: Mood; illustration_url: string | null }[]
  notes: { lines: string[] } | null // 안부 한 줄 — 기운 없음·위급 대화가 있던 주 (D62)
  // '이번 주 달라진 점' (11/18 멘토링) — 그 주를 앞 주들과 견준 변화와 그 주 알림 이력. 문장은 서버가 만든다.
  // tone: calm 평소 · watch 살펴볼 것. 견줄 자료가 모자란 줄은 오지 않는다(다 없으면 [])
  changes: {
    kind: 'TALK_DAYS' | 'TALK_LENGTH' | 'MOOD' | 'RUDE' | 'CHECK' | 'CARE' | 'ALERT' // RUDE 거친 말 횟수 (D112)
    text: string
    tone: 'calm' | 'watch'
  }[]
}

export type AiOut = {
  text: string
  audio_b64: string | null
  suggestions: string[]
  choice_mode: 'CHIPS' | 'TWO_BUTTONS'
  question_type: 'RECALL' | 'REMEMBER' | 'KNOWHOW' | 'THEN_NOW' | 'COMMON' | 'RECHECK' | 'CLOSING' | 'NONE'
  care?: boolean // 11/23 힘든 말씀 뒤 위로 중인 턴(D94 바꿈) — 대화는 이어지고, 화면은 전화 버튼 없이 심심이가 위로
  // 잡담(CHAT, D106)만: 이 말에 어울리는 심심이 표정 · 어르신이 가자고 하신 화면(화면이 그리로 데려간다)
  face?: 'hello' | 'joy' | 'smile' | 'curious' | 'ask' | 'thumbs' | null
  go?: ChatGo | null
}
export type ChatGo = 'DIARY' | 'ALBUM' | 'NEWS' | 'MIND'
/** GET /api/elder/sessions?kind=CHAT — '지난 이야기' 목록 한 줄 (D106). 말은 GET /api/elder/sessions/{id} 의 turns */
export type ChatItemOut = { session_id: string; started_at: string; title: string; elder_turns: number }
export type SessionState = 'CONTINUE' | 'ENDED'
export type EndReason = 'COMPLETED' | 'USER_STOP' | 'NO_RESPONSE' | 'ERROR' | 'LIMIT'
export type SessionKind = 'MEMORY' | 'ALBUM' | 'DIARY' | 'CHAT' // CHAT = 심심이 잡담 (D106)
export type SessionOut = {
  session_id: string
  kind: SessionKind
  photo_url: string | null
  ai: AiOut
  state: SessionState
  end_reason: EndReason | null
  turn_no: number
  input_locked: boolean
  urgent?: 'BODY' | null // 몸이 위급하다는 말로 끝난 대화 — 화면이 [119 전화하기]를 띄운다 (11/19 응급)
}
// 가족 홈 긴급 카드 (backend/app/schemas/alerts.py). acked_at 이 null 이면 아직 아무도 [제가 연락했어요]를 안 누름
export type AlertOut = {
  alert_id: number
  kind: 'MOOD' | 'BODY' // MOOD 마음 위급(D55), BODY 몸 위급
  created_at: string
  acked_at: string | null
  acked_by_name: string | null
  acked_by_me: boolean
  missed_at: string | null // 11/23 '안 받으세요' — POST /api/rooms/{id}/alerts/{alert_id}/missed → AlertOut
  missed_by_name: string | null
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

// 11/23 분류 묶음 — 서버가 AI 분류(D76 활동·주제)를 묶는다. 분류 전·없음 = ETC
export type PhotoGroup = 'FAMILY' | 'TRAVEL' | 'FOOD' | 'NATURE' | 'EVENT' | 'ETC'
// 어르신 사진첩 GET /api/elder/album — 11/23 어르신 일기 사진·갤러리 사진(ELDER_CAMERA)도 (D60 바꿈), 새것 먼저
export type AlbumPhoto = {
  photo_id: number
  url: string
  taken_at: string | null
  caption: string | null
  group: PhotoGroup
  source: 'FAMILY' | 'ELDER_CAMERA' | 'FAMILY_DIARY'
  diary_id: number | null // 어르신 일기 사진이면 그 일기
  uploader_name: string | null // 11/25 가족 사진을 올린 사람 '별명 (이름)' — 어르신 사진이면 null
  talks: { at: string; summary: string }[] // 11/27 이 사진으로 나눈 회상 요약(새것 먼저) — 사진 보기에서 보여 드리고 읽어 드림
}
export type AlbumOut = { photos: AlbumPhoto[] }
// POST /api/elder/album (multipart file + request_id) → AlbumPhoto — 어르신이 폰 갤러리에서 고른 사진 1장
// ---- 사진 올리기 (backend/app/schemas/photos.py, D17)
export type PhotoOut = {
  usable: boolean | null // 분류 AI가 본 오늘의 한 장 사용 가능 여부. 분류 전이거나 이름표가 없으면 null
  is_mine: boolean
  photo_id: number
  url: string
  taken_at: string | null
  taken_year: number | null // 11/23 찍은 날이 없을 때 가족이 고른 연도
  caption: string | null
  people_note: string | null
  status: string
  // AI 분류 (D71·D73, 가족방 탭 '올린 사진' GROUP_004). 분류 전이면 analyzed=false, ai_* 는 null
  source: 'FAMILY' | 'ELDER_CAMERA' | 'FAMILY_DIARY'
  analyzed: boolean
  ai_activity: string | null // data/taxonomy.json 의 활동 글자 또는 'none'
  ai_scene: string | null // 보이는 모습 한 줄
  corrected_activity: string | null // 가족이 고친 활동('none' = 맞는 것 없음) — 있으면 이것이 먼저
  elder_note: string | null // 어르신이 대화에서 이 사진을 바로잡아 주신 내용 한 문장 (FR-ME-009)
  group: PhotoGroup // 11/23 사진첩 분류 칩
  uploader_name: string | null // 11/23 올린 사람(가족 별명→이름, 어르신 사진이면 '순자 할머니' 꼴)
  shown: boolean // 11/23 어르신께 보여 드렸나(오늘의 한 장·대화에 나옴). 이 사진 빼기 규칙에만 쓴다(11/25 화면 글자 없앰)
  // 11/25 사진첩 판 — 목록만 채운다
  talked: boolean // 어르신이 이 사진으로 말씀하신 대화가 있다 — 사진 칸 말풍선
  quotes: PhotoQuote[] // 그 이야기의 주간 이야기 카드(질문·전한 말) — 주간 이야기가 나온 뒤에 붙는다
  diary_id: number | null // 이 사진을 쓴 게시 일기(어르신 일기·가족 오늘 소식)
}
export type PhotoQuote = { day: string; question: string; answer: string }
// ?who=ELDER(어르신이 찍은 사진)·FAMILY(가족 추억 사진 + 오늘 소식 사진) 칩 (11/25). waiting_count = 오늘의 한 장으로 남은 사진 수
export type PhotoListOut = { photos: PhotoOut[]; has_more: boolean; waiting_count: number }
export type PhotoBatchOut = { upload_batch_id: string; photos: PhotoOut[] }

// ---- 일기 (backend/app/schemas/diaries.py, D36)
export type Mood = 'GOOD' | 'SO_SO' | 'UPSET' | 'LONELY'
/** 기분 표시 이름 (일기 대화 마지막 칩과 같은 글자, D75). 얼굴 이모지는 components/MoodIcon */
export const MOOD_LABEL: Record<Mood, string> = { GOOD: '좋았어요', SO_SO: '그저 그랬어요', UPSET: '속상했어요', LONELY: '쓸쓸했어요' }

// ---- 가족 홈 마음 카드 (backend/app/schemas/mood.py)
export type MoodDayOut = { date: string; talked: boolean; diary_mood: Mood | null; low: boolean }
export type MoodCheckOut = { check_date: string; level: 'USUAL' | 'DOWN' | 'HARD' } // 마음 체크 마지막 결과. 점수는 오지 않음
export type MoodWeekOut = { days: MoodDayOut[]; talked_days: number; low_days: number; last_check: MoodCheckOut | null; other_checks: MoodOtherOut[]; last_talk_at: string | null } // days 는 7칸, 오래된 날 → 오늘
// 11/23 외로움·걱정·기억력 체크·기억력 놀이 — 종류마다 마지막 결과, 점수 없이 얼굴·말만
export type MoodOtherOut = { kind: 'UCLA3' | 'GAD7' | 'SMCQ' | 'MEMGAME'; check_date: string; face: string; title: string }
export type MoodCheckDueOut = { due: boolean } // 어르신 홈 마음 체크 초대 (D56)
// 11/23 내 마음: 종류 5가지 + 기억력 놀이. 칸 수·값 — PHQ8 8칸 0~3 · PHQ9 9칸 0~3 · UCLA3 3칸 0~2 · GAD7 7칸 0~3 · SMCQ 14칸 0~1 · MEMGAME 1칸 0~3(맞힌 수)
export type MoodKind = 'PHQ8' | 'PHQ9' | 'UCLA3' | 'GAD7' | 'SMCQ' | 'MEMGAME'
export type MoodCheckIn = { kind?: MoodKind; answers: number[] } // kind 없으면 PHQ8
// 마음 체크 저장 응답. say = 어르신께 드리는 끝 인사 한마디('잠이 편치 않은 날이 많으셨군요. …') — null 이면 평소 인사
export type MoodCheckSavedOut = { ok: boolean; say: string | null; face: string; title: string; sub: string; help_call: boolean } // 11/23 결과는 점수 없이 얼굴·말. help_call = 9번 '있었다' → [109 전화] (11/25)
export type MoodHistoryOut = { items: { check_date: string; kind: MoodKind; level: 'USUAL' | 'DOWN' | 'HARD'; face: string; title: string }[] } // GET /api/elder/mood-history 최근 10개
// 가족 홈 돌봄 일지 (backend/app/schemas/care.py, 11/19 돌봄 루프). 문장은 서버가 만든다 — 어르신 말 원문·점수 없음
export type CareDayOut = {
  date: string
  level: 'WATCH' | 'CARE' // 지켜봄 / 주의
  heard: string | null // 들은 것
  did: string | null // 한 일
  reaction: string | null // 어르신 답
  notes: string[] // 그 밖에 달라진 점
}
export type CareOut = { days: CareDayOut[] } // 새 날부터, 최근 7일 가운데 살핀 것이 있는 날만
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
  is_mine: boolean
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
// 가족 한마디 (11/19): kind 'REPLY' + text. 이모지와 따로, 한 사람이 여러 개(11/25), 응답에서는 이모지 칸들 뒤에 남긴 순서로 온다
// POST /api/diaries/{id}/reply { text: 한 줄 1~200자, 11/27 } → DiaryOut (새 칸이 붙음) · DELETE /api/diaries/{id}/reply?at=<칸의 at> → 204 (그 칸 하나)
export type Reaction = {
  by: 'ELDER' | 'FAMILY'
  kind: 'LIKE' | 'HEART' | 'SMILE' | 'CLAP' | 'REPLY'
  user_id: number | null
  name: string | null
  at: string
  text?: string // REPLY 칸에만
  // 가족 목소리 답장 (D99, 11/24): 소리 주소·길이(초). 이때 text 는 받아 적은 자막(빈 글일 수 있음)
  // POST /api/diaries/{id}/voice-reply (form audio, 30초까지) → DiaryOut. 보낼 때마다 새 칸 (11/25)
  // 어르신 답(by ELDER·kind REPLY)도 녹음이 있으면 소리 주소가 붙는다 (11/25) — 가족 화면은 눌러야 튼다
  audio_url?: string
  audio_sec?: number
}
export type DiaryListOut = { diaries: DiaryOut[]; has_more: boolean }
// 회상 카드 (11/27 팀 회의): 회상 대화가 끝나면 AI 가 가족용 한두 줄 요약을 만든다. '가족에게 말하지 마' 대화는 카드가 없다.
// 가족 홈 피드에 일기와 섞여 시각 순으로 — 좋아요(HEART)·댓글(REPLY)은 일기와 같은 모양의 칸
// GET /api/rooms/{room_id}/memories → MemoryListOut (최근 7일, 새것 먼저)
// POST /api/memories/{session_id}/reaction { kind: 'HEART', on } · POST …/reply { text } · PATCH …/reply { at, text } → MemoryCardOut
// DELETE /api/memories/{session_id}/reply?at=<칸의 at> → 204
export type MemoryCardOut = {
  session_id: string
  room_id: number
  photo_url: string | null
  summary: string
  ended_at: string
  reactions: Reaction[]
}
export type MemoryListOut = { memories: MemoryCardOut[] }
// 어르신 가족 소식 GET /api/elder/family-news (D63): 안 들은 가족 일기 + 아직 못 들은 가족 이모지·한마디(첫 장 '하트가 왔어요', 받은 순서)
// 첫 장을 읽어 드린 뒤 POST /api/elder/hearts/heard { until: 읽어 드린 마지막 하트·한마디의 at } → 204
export type Heart = {
  diary_id: number
  kind: 'HEART' | 'SMILE' | 'CLAP' | 'REPLY'
  name: string | null
  at: string
  text?: string
  audio_url?: string // 목소리 답장 (D99) — 가족 소식이 한 장씩 틀어 드린다. text 는 자막
  audio_sec?: number
  diary_body: string // 11/23 어느 일기에 — 일기 글 전체(11/24, 화면이 두 줄로 줄임)
  diary_posted_at: string
  diary_thumb_url: string | null
}
// 11/23 어르신 [말로 답하기] (가족 일기에만, 답장의 답장 없음): 녹음 → POST /api/stt → POST /api/elder/diaries/{id}/reply-draft {transcript} → {text}
// → 어르신 확인 → POST /api/elder/diaries/{id}/voice-reply (form text + audio = 그 녹음, 11/25 저장) → DiaryOut (reactions 에 by ELDER·kind REPLY 한 칸)
//   녹음이 없으면 POST /api/elder/diaries/{id}/reply {text}
export type ElderReplyDraftIn = { transcript: string }
export type ElderReplyDraftOut = { text: string }
export type ElderReplyIn = { text: string }
export type FamilyNewsOut = DiaryListOut & { hearts: Heart[] }
// 11/25 달력 (backend/app/schemas/calendar.py, 인스타 스토리 보관함처럼). 달 = 'YYYY-MM', 날 = 'YYYY-MM-DD'(한국 날짜)
// 가족 일기 달력 HOME_003: GET /api/rooms/{id}/calendar?month= (없으면 일기가 있는 가장 최근 달) · GET …/calendar/{날}
export type CalendarOut = { month: string; days: { date: string; count: number; thumb_url: string | null }[]; prev_month: string | null; next_month: string | null }
export type CalendarDayOut = { date: string; diaries: DiaryOut[]; prev_date: string | null; next_date: string | null } // 올린 시각 순서
// 어르신 '지난 가족 소식' 달력: GET /api/elder/family-news/past?month= — 이미 들은 가족 일기(올린 순서), 일기가 있는 앞·뒤 달
export type PastNewsOut = { month: string; diaries: DiaryOut[]; prev_month: string | null; next_month: string | null }
// ---- 가족 일기 동무 (backend/app/schemas/family_diary.py, D58) — FDIARY_002 질문 · FDIARY_003 초안. 서버는 저장하지 않는다
// POST /api/rooms/{room_id}/family-diary/ask · /draft. 여러 가족방에 보내도 고른 방 하나로 한 번만 부른다
export type FamilyAskIn = { text: string } // 가족이 쓴 말 1~200자
export type FamilyAskOut = { question: string } // 질문 1개 (AI 가 실패하면 고정 질문)
export type FamilyDraftIn = { text: string; question?: string; answer?: string } // 답은 비워도 됨 → 쓴 말만으로
export type FamilyDraftOut = { body: string } // 존댓말 1인칭 3~5문장 → 가족이 고친 뒤 POST /rooms/{id}/diaries
// ---- 웹 푸시 (backend/app/schemas/push.py) — lib/push.ts 가 쓴다
// GET /api/push/key → PushKeyOut. 구독 등록 POST /api/push/subscribe(가족)·/api/elder/push/subscribe(어르신 기기)는
// 브라우저의 PushSubscription.toJSON() 을 그대로 보낸다. 끄기 POST /api/push/unsubscribe { endpoint }. 셋 다 { ok: true }
// 11/23 알림 종류별 끄기 GET·PUT /api/push/prefs — 급한 알림은 끌 수 없다
export type PushGroup = 'DIARY' | 'WEEKLY' | 'CARE'
export type PushPrefs = { muted: PushGroup[] }
export type PushKeyOut = { public_key: string | null } // null = 이 서버는 푸시를 안 쓴다 → 알림 카드를 숨긴다
