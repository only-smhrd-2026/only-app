/**
 * ELDER_HOME_001 — 어르신 홈 (11/27 팀 회의 시안). 위: 작은 로고·날짜·⚙ 설정 → 말풍선(할 일 말 + 그 일 버튼) + 꼬마심심이
 * → 네모 4칸(오늘 사진·일기 쓰기·가족 소식·사진첩) → 아래 넓은 '내 마음' 띠.
 * 말풍선은 하루 상태 순서로 '지금 할 일'을 말하고, 가리키는 칸은 노란 테두리로 한 번 더 짚는다(글을 못 읽으셔도 어디를 누를지 보이게):
 *   하던 이야기(30분 안, D52 ⑥) → 오늘의 한 장 → 일기(17시부터) → 가족 소식 → 마음 체크(PHQ-9 2주마다) → 사진 없는 날이면 사진첩.
 *   할 일이 없으면 시간대 인사 + 추천 하나(잡담·사진첩·지난 소식·외로움·걱정·기억력 체크·기억력 놀이 중 무작위, 11/27).
 *   문장은 상태마다 여러 개 — 같은 날·상태·시간대면 같은 문장(pickOf).
 * 옛 '오늘의 한 장' 팝업·건너뛰기(ELDER_TODAY_001, D65·D78)는 이 말풍선과 회상 칸으로 합쳤다 — /elder/today 도 이 화면.
 * 마음 체크는 말풍선·'내 마음' 칸으로만 권한다 — 홈 위에 판으로 띄우지 않는다(D97, 홈으로 돌아올 때 화면을 덮음). /elder/mood 도 이 화면.
 * 들어오면 인사(이름 + 말풍선)를 읽어 준다 — 같은 말은 앱을 켠 동안 한 번만.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { ElderHomeOut, ElderWeatherOut, SessionOut } from '../../api/types'
import todayPreview from '../../assets/today-preview.svg?inline' // 미리보기 전용 — 배포 빌드에 파일이 따로 남지 않게
import { Bub } from '../../components/ElderUi'
import Sim from '../../components/Sim'
import { useLive } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { setVoice, speak, stopSpeaking } from '../../lib/audio'
import { setElderFont } from '../../lib/elderFont'
import type { CheckKind } from '../../lib/moodCheck'
import { readPaused, resumePath } from '../../lib/pausedSession'
import { ELDER_PUSH, syncPush } from '../../lib/push'
import './ELDER_HOME_001.css'

const STALE_MS = 30 * 60 * 1000 // 이만큼 넘게 숨어 있다 돌아오면 홈을 다시 읽는다 (FR-ME-006, D45 ④)
const RETRY_MS = 5_000 // 홈 읽기가 실패하면 이만큼 뒤에 다시 — 성공할 때까지
const NOTICE_MS = 4_000
const DIARY_FROM = 17 // 홈 말풍선이 일기를 권하는 시각(한국 시간) — 11/25 사용자
let lastGreet = '' // 앱을 켠 동안 마지막으로 읽어 드린 인사 — 같은 말을 홈에 올 때마다 되풀이하지 않게

type Tile = 'talk' | 'diary' | 'news' | 'album' | 'mind'
type Msg = 'paused' | 'photo' | 'diary' | 'news' | 'mind' | 'nophoto' | 'later' | 'done'
// 할 일 말풍선 — 상태마다 여러 문장 중 하나 (11/27 팀 회의: 문구가 한정적이다). [칸, 말풍선 안 버튼 글]
const HMSG: Record<Exclude<Msg, 'later' | 'done'>, [string[], Tile, string]> = {
  paused: [['하던 이야기가 있어요.\n이어서 해 볼까요?', '아까 하던 이야기,\n마저 들려주세요.'], 'talk', '이어서 하기'],
  photo: [
    ['오늘의 한 장이 왔어요.\n사진 보며 이야기해요.', '가족이 보낸 사진이 있어요.\n같이 볼까요?', '새 사진이 도착했어요.\n어떤 이야기가 있을까요?'],
    'talk',
    '이야기 시작하기',
  ],
  diary: [['오늘 있었던 일을\n일기로 남겨 볼까요?', '오늘 하루 어떠셨어요?\n일기로 들려주세요.', '저녁이에요.\n오늘 일기 같이 써요.'], 'diary', '일기 쓰기'],
  news: [['가족 소식이 왔어요.\n같이 들어 볼까요?', '가족이 마음을 보냈어요.\n어서 열어 보세요.'], 'news', '소식 보기'],
  mind: [['기분 여쭤볼 차례예요.\n잠깐 이야기해 주세요.', '요즘 마음은 어떠세요?\n몇 가지 여쭤볼게요.'], 'mind', '마음 체크 하기'],
  nophoto: [['오늘은 새 사진이 없어요.\n사진첩에서 골라 볼까요?', '새 사진은 아직이에요.\n옛날 사진 같이 볼까요?'], 'album', '사진첩 보기'],
}
// 할 일이 없을 때: 시간대 인사 한 줄 + 추천 한 줄. 마음 체크 중 기분(PHQ-9)은 2주마다 '할 차례'로만,
// 나머지 체크(외로움·걱정·기억력·기억력 놀이)는 여기서 무작위로 권한다 (11/27 사용자)
type Rec = { line: string; label: string; tile: Tile | ''; go: string; kind?: CheckKind }
const RECS: Rec[] = [
  { line: '심심하시면 저랑 이야기해요!', label: '심심이랑 이야기하기', tile: '', go: '/elder/chat' },
  { line: '옛날 사진 같이 볼까요?', label: '사진첩 보기', tile: 'album', go: '/elder/album' },
  { line: '지난 가족 소식 다시 들어 볼까요?', label: '가족 소식 보기', tile: 'news', go: '/elder/family-news' },
  { line: '오늘은 외로움 체크 어떠세요?', label: '외로움 체크 하기', tile: 'mind', go: '/elder/mood-check', kind: 'UCLA3' },
  { line: '요즘 걱정은 없으세요?\n걱정 체크 해 볼까요?', label: '걱정 체크 하기', tile: 'mind', go: '/elder/mood-check', kind: 'GAD7' },
  { line: '기억력 체크 한번 해 볼까요?', label: '기억력 체크 하기', tile: 'mind', go: '/elder/mood-check', kind: 'SMCQ' },
  { line: '기억력 놀이 한 판 할까요?', label: '기억력 놀이 하기', tile: 'mind', go: '/elder/mind/memory-game' },
]
// 한국 시각 → 시간대 인사 (오전에 '일기는 저녁 5시부터'만 되풀이하지 않게, 11/27)
const TIME_LINES: [number, string[]][] = [
  [5, ['오늘도 좋은 하루 보내세요.', '하루 잘 마무리하세요.', '편안한 밤 보내세요.']], // 0~4시
  [11, ['좋은 아침이에요!', '아침은 든든히 드셨어요?', '오늘도 힘차게 시작해요.']],
  [14, ['점심은 맛있게 드셨어요?', '오늘 날씨는 어떤가요?', '잠깐 쉬어 가요.']],
  [17, ['오후도 편안하게 보내세요.', '물 한 잔 드셨어요?', '오늘은 무얼 하셨어요?']],
  [21, ['저녁은 드셨어요?', '오늘 하루도 고생 많으셨어요.', '저녁 시간이 참 좋아요.']],
  [24, ['오늘 하루도 고생 많으셨어요.', '푹 주무세요.', '편안한 밤 보내세요.']],
]
/** 같은 날·같은 상태·같은 시간대면 같은 문장 — 홈에 올 때마다 말이 바뀌지 않게, 날·상태가 바뀌면 다른 문장 */
function pickOf<T>(list: T[], seed: string): T {
  let h = 0
  for (const c of seed) h = (h * 31 + c.charCodeAt(0)) | 0
  return list[Math.abs(h) % list.length]
}

/* 칸 그림 — 꼬마심심이처럼 도톰하게 (시안 ART) */
const ART = {
  mind: (
    <svg viewBox="0 0 120 110" aria-hidden="true">
      <defs><linearGradient id="gM1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#FFB3C1" /><stop offset="1" stopColor="#EE6A84" /></linearGradient></defs>
      <path d="M60 100C29 80 12 63 12 41a23 23 0 0 1 48-10 23 23 0 0 1 48 10c0 22-17 39-48 59z" fill="url(#gM1)" />
      <path d="M33 42c2-9 9-14 17-13" stroke="#fff" strokeWidth="7" strokeLinecap="round" fill="none" opacity=".75" />
    </svg>
  ),
  gear: (
    <svg viewBox="0 0 120 110" aria-hidden="true">
      <defs><linearGradient id="gG1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#C6D2DF" /><stop offset="1" stopColor="#8697AB" /></linearGradient></defs>
      <g transform="translate(60 55)">
        {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => <rect key={a} x="-9" y="-46" width="18" height="20" rx="5" fill="#97A6B8" transform={`rotate(${a})`} />)}
        <circle r="33" fill="url(#gG1)" />
        <circle r="13" fill="#F7F3EC" />
      </g>
    </svg>
  ),
  diary: (
    <svg viewBox="0 0 120 110" aria-hidden="true">
      <defs>
        <linearGradient id="gD1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#FFB7A1" /><stop offset="1" stopColor="#EE7757" /></linearGradient>
        <linearGradient id="gD2" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#FFE585" /><stop offset="1" stopColor="#F3B21F" /></linearGradient>
      </defs>
      <rect x="18" y="8" width="70" height="92" rx="13" fill="url(#gD1)" />
      <rect x="27" y="15" width="57" height="78" rx="7" fill="#FFFDF8" />
      <path d="M38 34h34M38 49h34M38 64h20" stroke="#EAD9C2" strokeWidth="5" strokeLinecap="round" />
      <g transform="rotate(36 88 62)">
        <rect x="80" y="20" width="17" height="60" rx="4" fill="url(#gD2)" />
        <rect x="80" y="20" width="17" height="13" rx="4" fill="#FF9DAA" />
        <path d="M80 80h17l-8.5 15z" fill="#F6DDB6" />
        <path d="M85.5 89.5h6l-3 5.5z" fill="#3A2416" />
      </g>
    </svg>
  ),
  news: (
    <svg viewBox="0 0 120 110" aria-hidden="true">
      <defs>
        <linearGradient id="gN1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#FFFFFF" /><stop offset="1" stopColor="#F4E7D2" /></linearGradient>
        <linearGradient id="gN2" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#FF8E86" /><stop offset="1" stopColor="#E2463F" /></linearGradient>
      </defs>
      <rect x="12" y="24" width="96" height="68" rx="13" fill="url(#gN1)" />
      <path d="M17 33l43 30 43-30" stroke="#E3D0B3" strokeWidth="4.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M60 86c-15-9.5-23-18-23-27a12 12 0 0 1 23-5 12 12 0 0 1 23 5c0 9-8 17.5-23 27z" fill="url(#gN2)" />
    </svg>
  ),
  album: (
    <svg viewBox="0 0 120 110" aria-hidden="true">
      <defs><linearGradient id="gA1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#A9D4F2" /><stop offset="1" stopColor="#FFE9C2" /></linearGradient></defs>
      <g transform="rotate(-11 56 56)"><rect x="18" y="14" width="66" height="74" rx="7" fill="#fff" /><rect x="25" y="21" width="52" height="46" rx="3" fill="#C9DDEA" /></g>
      <g transform="rotate(7 66 56)">
        <rect x="34" y="18" width="68" height="76" rx="7" fill="#fff" />
        <rect x="41" y="25" width="54" height="48" rx="3" fill="url(#gA1)" />
        <circle cx="80" cy="39" r="7" fill="#FFCB45" />
        <path d="M41 73l17-20 12 12 8-7 17 15z" fill="#6FA85A" />
      </g>
    </svg>
  ),
}
/* 상표 — 꼬마심심이 머리의 꽃 한 송이 */
const MARK = (
  <svg viewBox="0 0 48 48" aria-hidden="true">
    <rect width="48" height="48" rx="14" fill="var(--elder-primary)" />
    <g transform="translate(24 24)" fill="#fff">
      <circle cx="0" cy="-9.4" r="7.4" /><circle cx="8.9" cy="-2.9" r="7.4" /><circle cx="5.5" cy="7.6" r="7.4" />
      <circle cx="-5.5" cy="7.6" r="7.4" /><circle cx="-8.9" cy="-2.9" r="7.4" />
    </g>
    <circle cx="24" cy="24" r="5.2" fill="var(--elder-lip)" />
  </svg>
)

/** 오늘 날짜(한국 시간) 글자. 날이 바뀌었는지 볼 때만 쓴다 */
const kstDate = () => new Date().toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul' })
/** '11월 23일 일요일' (한국 시간) */
const todayLabel = () => new Date().toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', weekday: 'long' })

// 백엔드 없이 화면을 확인하기 위한 개발 서버 전용 견본 (/elder?preview=1)
const previewHome: ElderHomeOut = {
  greeting: '순자 어르신, 안녕하세요',
  elder_name: '순자',
  elder_honorific: '어르신',
  today_pick: { pick_id: 1, photo_id: 1, photo_url: todayPreview, status: 'PENDING' },
  unread_family_news: 2,
  settings: { font_size: 'XL', tts_speed: 0.9, input_mode: 'VOICE', tts_voice: 'FEMALE' },
  diary_today: false,
  mood_due: false,
}

export default function ELDER_HOME_001() {
  const nav = useNavigate()
  const { search } = useLocation()
  const preview = import.meta.env.DEV && new URLSearchParams(search).get('preview') === '1'
  const { data: serverHome, error, loading, reload } = useFetch<ElderHomeOut>(preview ? null : '/api/elder/home')
  // 날씨 심심이 (11/26) — 홈과 따로 받아 홈을 기다리게 하지 않는다. 못 받으면 늘 쓰던 인사 그림
  const weather = useFetch<ElderWeatherOut>(preview ? null : '/api/elder/weather')
  const home = preview ? previewHome : serverHome
  const homeError = error && !preview && (!serverHome || error.code === 'DEVICE_REQUIRED')
    ? error.code === 'DEVICE_REQUIRED'
      ? '가족이 보낸 연결 링크를 먼저 열어 주세요.'
      : '연결이 잠깐 끊겼어요. 잠시 뒤에 다시 열어 볼게요.'
    : ''
  const speed = Number(home?.settings.tts_speed) || 0.9
  // 같은 pick 재시도는 같은 id, 날짜가 바뀌어 새 pick 이 오면 새 id 를 쓴다.
  const sessionIds = useRef(new Map<number, string>())
  const hiddenAt = useRef<number | null>(null) // 화면이 숨은 시각
  const loadedDate = useRef<string | null>(null) // 홈을 마지막으로 읽은 날(한국 시간)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('') // 잠깐 말풍선에 띄우는 말(오류·'오늘 이야기는 다 나눴어요')
  const noticeTimer = useRef<number | undefined>(undefined)
  const live = useLive()

  useEffect(() => () => window.clearTimeout(noticeTimer.current), [])

  useEffect(() => {
    if (!home) return
    setElderFont(home.settings.font_size)
    setVoice(home.settings.tts_voice) // 고정 안내 mp3 도 고른 목소리로 (D74)
  }, [home])

  useEffect(() => {
    if (serverHome) loadedDate.current = kstDate()
    if (serverHome) void syncPush(ELDER_PUSH, true) // 알림을 허용해 둔 폰이면 조용히 푸시 구독(화면 변화 없음, lib/push)
  }, [serverHome])

  // 홈을 다시 읽고, 앞서 뜬 말과 대화 번호는 비운다
  // (서버는 30분 지난 대화를 끝난 것으로 봐서, 오래된 번호를 다시 쓰면 들어가자마자 끝난다)
  const refresh = useCallback(() => {
    sessionIds.current.clear()
    setNotice('')
    reload()
  }, [reload])

  useEffect(() => {
    if (preview) return
    const onVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        hiddenAt.current = Date.now()
        return
      }
      const hidden = hiddenAt.current
      hiddenAt.current = null
      // 마지막으로 읽은 날과 오늘이 다르거나(켜 둔 채 자정을 넘긴 경우 포함) 30분 넘게 숨어 있었을 때만 다시 읽는다
      const dayChanged = loadedDate.current !== null && loadedDate.current !== kstDate()
      const longHidden = hidden !== null && Date.now() - hidden >= STALE_MS
      if (dayChanged || longHidden) refresh()
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [preview, refresh])

  // 홈 읽기가 실패하면 성공할 때까지 다시 읽는다 — 폰을 켠 직후에는 망이 아직 안 붙어 있을 때가 있다.
  // 연결이 풀린 기기(401)는 다시 읽어도 같으니 그만둔다
  useEffect(() => {
    if (preview || !error || error.code === 'DEVICE_REQUIRED') return
    const timer = window.setTimeout(reload, RETRY_MS)
    return () => window.clearTimeout(timer)
  }, [preview, error, reload])

  // 홈을 떠나면 읽던 말을 끊는다 — 다음 화면 소리 위로 이어지지 않게
  useEffect(() => () => stopSpeaking(), [])

  useEffect(() => {
    if (!homeError) return
    void speak(homeError, speed)
    return () => stopSpeaking()
  }, [homeError, speed])

  // ---- 하루 상태 → 말풍선 (뒤로 키로 나간 대화는 30분 안이면 '이어서', D52 ⑥)
  const paused = preview ? null : readPaused()
  const pick = home?.today_pick ?? null
  // 일기는 17시부터 권한다 (11/25 실사용: 회상을 마치자마자 일기를 권하면 바빴다). 일기 칸은 언제든 눌린다
  const [hour] = useState(() => (new Date().getUTCHours() + 9) % 24) // 홈을 열 때 시각(한국)
  const diaryTime = hour >= DIARY_FROM
  const msg: Msg = paused ? 'paused'
    : pick?.status === 'PENDING' ? 'photo'
      : home && !home.diary_today && diaryTime ? 'diary'
        : home && home.unread_family_news > 0 ? 'news'
          : home?.mood_due ? 'mind'
            : !pick ? 'nophoto'
              : home && !home.diary_today ? 'later' : 'done'
  const timeIdx = TIME_LINES.findIndex(([until]) => hour < until)
  const seed = `${kstDate()}|${msg}|${timeIdx}`
  // 할 일이 없으면 추천 하나(마음 체크·사진첩·잡담 …), 있으면 그 일
  const rec = msg === 'later' || msg === 'done' ? pickOf(RECS, `${seed}|rec`) : null
  const todo = rec ? null : HMSG[msg as keyof typeof HMSG]
  const [msgText, msgTileRaw, actLabel] = todo
    ? [pickOf(todo[0], seed), todo[1], todo[2]]
    : [`${msg === 'done' && pickOf([0, 1], seed) ? '오늘 할 일을 다 하셨어요.' : pickOf(TIME_LINES[timeIdx][1], seed)}\n${rec!.line}`, rec!.tile, rec!.label]
  const msgTile: Tile | '' = msg === 'paused' && paused?.kind === 'DIARY' ? 'diary' : msgTileRaw
  const who = home ? `${home.elder_name} ${home.elder_honorific}` : ''
  const greeting = `${who}, ${msgText.replace('\n', ' ')}`

  // 들어오면 인사를 읽어 준다(같은 인사는 앱을 켠 동안 한 번). 자동 재생이 막혔으면 첫 터치(손을 뗄 때)에 다시
  useEffect(() => {
    if (!home || homeError || lastGreet === greeting) return
    lastGreet = greeting
    let alive = true
    const retry = (e: Event) => {
      window.removeEventListener('pointerup', retry)
      if (e.target instanceof Element && e.target.closest('button')) return // 누른 버튼이 제 말을 한다
      void speak(greeting, speed)
    }
    void speak(greeting, speed).then((heard) => {
      if (heard || !alive) return
      window.addEventListener('pointerup', retry, { once: true })
    })
    return () => {
      alive = false
      window.removeEventListener('pointerup', retry)
    }
  }, [home, homeError, greeting, speed])

  function flash(message: string) {
    window.clearTimeout(noticeTimer.current)
    setNotice(message)
    noticeTimer.current = window.setTimeout(() => setNotice(''), NOTICE_MS)
    void speak(message, speed)
  }

  async function startMemory() {
    if (!home?.today_pick || busy) return
    if (preview) return flash('미리보기예요. 회상 대화는 서버가 연결되면 볼 수 있어요.')
    setBusy(true)
    setNotice('')
    const { pick_id: pickId, photo_id: photoId, photo_url: photoUrl } = home.today_pick
    let sessionId = sessionIds.current.get(pickId)
    if (!sessionId) {
      sessionId = crypto.randomUUID()
      sessionIds.current.set(pickId, sessionId)
    }
    try {
      const s = await api<SessionOut>('/api/elder/sessions', {
        body: { session_id: sessionId, kind: 'MEMORY', pick_id: pickId, photo_id: photoId },
      })
      if (!live.current) return // 기다리는 동안 다른 칸으로 떠났으면 끌고 가지 않는다
      nav(`/elder/memory/${sessionId}`, { state: { session: s, photoUrl, home } })
    } catch (e) {
      if (!live.current) return
      setBusy(false)
      // 옛 화면에서 눌렀다(켜 둔 채 날이 바뀜) → 서버가 409 로 알려 준다. 홈을 다시 읽어 오늘 것을 보여 준다 (D45 ④)
      if (e instanceof ApiError && (e.code === 'PICK_EXPIRED' || e.code === 'PICK_SKIPPED')) return refresh()
      // 서버 문장이 아닌 오류(응답이 중간에 끊김 등)는 영어라 그대로 보여 주거나 읽지 않는다
      flash(e instanceof ApiError ? e.message : '대화를 시작하지 못했어요. 다시 눌러 주세요.')
    }
  }

  function onTalk() {
    if (!home) return
    const p = preview ? null : readPaused() // 한 번 더 읽는다 — 홈을 켜 둔 사이 30분이 지났을 수 있다
    if (p && p.kind !== 'DIARY') return nav(resumePath(p), { state: { home } })
    if (!pick) return nav('/elder/album', { state: { home } })
    if (pick.status === 'PENDING') return void startMemory()
    flash(pick.status === 'COMPLETED' ? '오늘 이야기는 다 나눴어요.' : pick.status === 'SKIPPED' ? '오늘 사진은 건너뛰었어요.' : '오늘 사진은 지났어요.')
  }
  function onDiary() {
    const p = preview ? null : readPaused()
    nav(p?.kind === 'DIARY' ? resumePath(p) : '/elder/diary', { state: { home } })
  }

  // 읽은 홈이 있으면 다시 읽기에 실패해도 그대로 보여 준다(위에서 5초마다 다시 읽는 중). 연결이 풀린 기기만 안내로 바꾼다
  if (homeError)
    return (
      <main className="elder elder--fit elder-center">
        <Sim face="ask" size={150} className="elder-sim" />
        <p className="elder-text" role="alert">{homeError}</p>
      </main>
    )
  if (!home) return loading ? <main className="elder elder--fit elder-center"><p className="elder-text" role="status">잠시만요…</p></main> : null

  const unread = home.unread_family_news
  // 11/27 팀 회의: 칸 아래 작은 글('사진이 왔어요' 등)은 빼고 그림·이름만 가운데
  const tile = (k: Tile, onClick: () => void, art: ReactNode, name: string, extra?: ReactNode) => (
    <button type="button" className={`ehome-tile${msgTile === k ? ' now' : ''}`} onClick={onClick} disabled={k === 'talk' && busy}>
      <span className="ehome-art">{art}</span>
      <b>{name}</b>
      {extra}
    </button>
  )
  // 말풍선 안 버튼 = 말풍선이 권하는 일을 바로
  function onAct() {
    if (rec) return nav(rec.go, { state: { home, kind: rec.kind } })
    if (msg === 'paused' || msg === 'photo') return paused?.kind === 'DIARY' ? onDiary() : onTalk()
    if (msg === 'diary') return onDiary()
    if (msg === 'news') return nav('/elder/family-news', { state: { home } })
    if (msg === 'mind') return nav('/elder/mood-check', { state: { home, kind: 'PHQ9' } })
    nav('/elder/album', { state: { home } })
  }
  const date = todayLabel()
  const bubble = notice || msgText

  return (
    <main className="elder elder--fit elder-home">
      <div className="ehome-body">
        <h1 className="elder-sr">홈</h1>
        <div className="ehome-top">
          <span className="ehome-logo">{MARK}하루한장</span>
          <span className="ehome-topr">
            <button type="button" className="ehome-date" onClick={() => void speak(`오늘은 ${date}이에요.`, speed)} aria-label={`오늘은 ${date}. 누르면 읽어 드려요`}>
              {date}
            </button>
            {/* 설정은 칸 대신 오른쪽 위 (11/27 팀 회의) */}
            <button type="button" className="ehome-gear" onClick={() => nav('/elder/settings', { state: { home } })} aria-label="설정 · 글자와 목소리">
              {ART.gear}
            </button>
          </span>
        </div>
        <div className="ehome-say" role={notice ? 'status' : undefined}>
          {/* 말풍선 = 할 일 말 + 그 일을 바로 하는 버튼 (11/27 팀 회의 시안). 말을 누르면 다시 읽는다 */}
          <div className="ehome-card elder-bub--down">
            <Bub key={bubble} text={bubble} speed={speed} />
            {!notice && (
              <button type="button" className="elder-btn ehome-go" onClick={onAct} disabled={busy}>
                {busy ? '잠시만요…' : actLabel}
                <span aria-hidden="true">›</span>
              </button>
            )}
          </div>
          {/* 심심이를 누르면 잡담 (D106, 11/25 멘토 아이디어) — 그림만 누를 수 있게 */}
          <button type="button" className="ehome-simbtn" onClick={() => nav('/elder/chat', { state: { home } })} aria-label="꼬마심심이랑 이야기하기">
            <Sim face={weather.data?.look ?? 'hello'} size={230} className="elder-sim" />
          </button>
        </div>
        <div className="ehome-grid">
          {tile('talk', onTalk, pick ? <img src={pick.photo_url} alt="" /> : ART.album, '오늘 사진')}
          {tile('diary', onDiary, ART.diary, '일기 쓰기')}
          {tile('news', () => nav('/elder/family-news', { state: { home } }), ART.news, '가족 소식',
            unread > 0 && <b className="elder-badge" aria-label={`새 소식 ${unread}개`}>{unread}</b>)}
          {tile('album', () => nav('/elder/album', { state: { home } }), ART.album, '사진첩')}
        </div>
        {/* 내 마음 = 아래 넓은 띠 (시안) */}
        <button type="button" className={`ehome-mind${msgTile === 'mind' ? ' now' : ''}`} onClick={() => nav('/elder/mind', { state: { home } })}>
          <span className="ehome-mind-art" aria-hidden="true">{ART.mind}</span>
          <b>내 마음</b>
          <span className="ehome-mind-say">{home.mood_due ? '여쭤볼 차례' : '요즘 마음 보기'}</span>
          <span aria-hidden="true">›</span>
          {home.mood_due && <b className="elder-badge" aria-label="할 차례">!</b>}
        </button>
      </div>
    </main>
  )
}
