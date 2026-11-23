/**
 * ELDER_HOME_001 — 어르신 홈 (11/23 시안 e-home). 위: 작은 로고·날짜 → 큰 꼬마심심이 + 말풍선 → 아래 네모 6칸.
 * 말풍선은 하루 상태 순서로 '지금 할 일'을 말하고, 가리키는 칸은 노란 테두리로 한 번 더 짚는다(글을 못 읽으셔도 어디를 누를지 보이게):
 *   하던 이야기(30분 안, D52 ⑥) → 오늘의 한 장 → 일기 → 가족 소식 → 마음 체크 → 다 함(사진 없는 날이면 사진첩 권유).
 * 옛 '오늘의 한 장' 팝업·건너뛰기(ELDER_TODAY_001, D65·D78)는 이 말풍선과 회상 칸으로 합쳤다 — /elder/today 도 이 화면.
 * 마음 체크 초대(ELDER_MOOD_001)는 말풍선이 마음 체크 차례일 때 홈 위에 판으로 뜬다(/elder/mood 도 이 화면).
 * 들어오면 인사(이름 + 말풍선)를 읽어 준다 — 같은 말은 앱을 켠 동안 한 번만.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { ElderHomeOut, SessionOut } from '../../api/types'
import todayPreview from '../../assets/today-preview.svg?inline' // 미리보기 전용 — 배포 빌드에 파일이 따로 남지 않게
import { Bub } from '../../components/ElderUi'
import Sim from '../../components/Sim'
import { useLive } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { setVoice, speak, stopSpeaking } from '../../lib/audio'
import { setElderFont } from '../../lib/elderFont'
import { moodSnoozed, snoozeMood } from '../../lib/moodCheck'
import { readPaused, resumePath } from '../../lib/pausedSession'
import { ELDER_PUSH, syncPush } from '../../lib/push'
import ELDER_MOOD_001 from './ELDER_MOOD_001'
import './ELDER_HOME_001.css'

const STALE_MS = 30 * 60 * 1000 // 이만큼 넘게 숨어 있다 돌아오면 홈을 다시 읽는다 (FR-ME-006, D45 ④)
const RETRY_MS = 5_000 // 홈 읽기가 실패하면 이만큼 뒤에 다시 — 성공할 때까지
const NOTICE_MS = 4_000
let lastGreet = '' // 앱을 켠 동안 마지막으로 읽어 드린 인사 — 같은 말을 홈에 올 때마다 되풀이하지 않게

type Tile = 'talk' | 'diary' | 'news' | 'album' | 'mind' | 'set'
type Msg = 'paused' | 'photo' | 'diary' | 'news' | 'mind' | 'nophoto' | 'done'
const HMSG: Record<Msg, [string, Tile | '']> = {
  paused: ['하던 이야기가 있어요.\n이어서 해 볼까요?', 'talk'],
  photo: ['오늘의 한 장이 왔어요.\n사진 보며 이야기할 시간이에요.', 'talk'],
  diary: ['오늘 있었던 일을\n일기로 남길 시간이에요.', 'diary'],
  news: ['가족 소식이 왔어요.\n눌러서 보세요.', 'news'],
  mind: ['마음 체크할 차례예요.\n내 마음을 눌러 주세요.', 'mind'],
  nophoto: ['오늘은 새 사진이 없어요.\n사진첩에서 골라 볼까요?', 'album'],
  done: ['오늘 할 일을 다 하셨어요.\n편히 쉬세요.', ''],
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
  const [moodClosed, setMoodClosed] = useState(false)
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
  const msg: Msg = paused ? 'paused'
    : pick?.status === 'PENDING' ? 'photo'
      : home && !home.diary_today ? 'diary'
        : home && home.unread_family_news > 0 ? 'news'
          : home?.mood_due ? 'mind'
            : !pick ? 'nophoto' : 'done'
  const [msgText, msgTileRaw] = HMSG[msg]
  const msgTile: Tile | '' = msg === 'paused' && paused?.kind === 'DIARY' ? 'diary' : msgTileRaw
  // 마음 체크 초대 (D56·D66): 말풍선이 마음 체크 차례일 때만. [할게요]·[다음에] 어느 쪽이든 오늘은 다시 권하지 않는다
  const showMood = !!home && msg === 'mind' && !moodClosed && !moodSnoozed()
  const who = home ? `${home.elder_name} ${home.elder_honorific}` : ''
  const greeting = `${who}, ${msgText.replace('\n', ' ')}`

  // 들어오면 인사를 읽어 준다(같은 인사는 앱을 켠 동안 한 번). 자동 재생이 막혔으면 첫 터치(손을 뗄 때)에 다시
  useEffect(() => {
    if (!home || homeError || showMood || lastGreet === greeting) return
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
  }, [home, homeError, showMood, greeting, speed])

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
  function answerMood(start: boolean) {
    snoozeMood() // 어느 쪽을 눌러도 오늘은 다시 권하지 않는다. 다 하면 서버가 2주 뒤에 다시 권한다
    setMoodClosed(true)
    stopSpeaking()
    if (start) nav('/elder/mood-check', { state: { home, kind: 'PHQ8' } })
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

  const resumeMemory = !!paused && paused.kind !== 'DIARY'
  const talkNote = busy ? '잠시만요' : resumeMemory ? '이어서 해요' : !pick ? '사진이 없어요' : pick.status === 'PENDING' ? '사진이 왔어요' : '오늘 했어요'
  const unread = home.unread_family_news
  const tile = (k: Tile, onClick: () => void, art: ReactNode, name: string, note: string, extra?: ReactNode) => (
    <button type="button" className={`ehome-tile${msgTile === k ? ' now' : ''}`} onClick={onClick} disabled={k === 'talk' && busy}>
      <span className="ehome-art">{art}</span>
      <b>{name}</b>
      <small>{note}</small>
      {extra}
    </button>
  )
  const date = todayLabel()
  const bubble = notice || msgText

  return (
    <main className="elder elder--fit elder-home">
      <div className="ehome-body" inert={showMood}>
        <h1 className="elder-sr">홈</h1>
        <div className="ehome-top">
          <span className="ehome-logo">{MARK}하루한장</span>
          <button type="button" className="ehome-date" onClick={() => void speak(`오늘은 ${date}이에요.`, speed)} aria-label={`오늘은 ${date}. 누르면 읽어 드려요`}>
            {date}
          </button>
        </div>
        <div className="ehome-say" role={notice ? 'status' : undefined}>
          <Bub key={bubble} text={bubble} speed={speed} className="elder-bub--down" />
          <Sim face="hello" size={230} className="elder-sim" />
        </div>
        <div className="ehome-grid">
          {tile('talk', onTalk, pick ? <img src={pick.photo_url} alt="" /> : ART.album, '회상', talkNote)}
          {tile('diary', onDiary, ART.diary, '일기 쓰기', paused?.kind === 'DIARY' ? '이어서 해요' : home.diary_today ? '오늘 썼어요' : '오늘 있었던 일')}
          {tile('news', () => nav('/elder/family-news', { state: { home } }), ART.news, '가족 소식', unread > 0 ? `새 소식 ${unread}개` : '다 봤어요',
            unread > 0 && <b className="elder-badge" aria-label={`새 소식 ${unread}개`}>{unread}</b>)}
          {tile('album', () => nav('/elder/album', { state: { home } }), ART.album, '사진첩', '지난 사진')}
          {tile('mind', () => nav('/elder/mind', { state: { home } }), ART.mind, '내 마음', home.mood_due ? '체크할 차례' : '요즘 괜찮아요',
            home.mood_due && <b className="elder-badge" aria-label="할 차례">!</b>)}
          {tile('set', () => nav('/elder/settings', { state: { home } }), ART.gear, '설정', '글자·목소리')}
        </div>
      </div>
      {showMood && <ELDER_MOOD_001 speed={speed} onYes={() => answerMood(true)} onLater={() => answerMood(false)} />}
    </main>
  )
}
