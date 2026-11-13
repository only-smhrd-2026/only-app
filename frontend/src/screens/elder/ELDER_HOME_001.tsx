/**
 * ELDER_HOME_001 — 앱 이름과 큰 상자 4개 홈 (D51, 11/12 멘토링 반영).
 * 오늘의 한 장 팝업과 다시 읽기는 유지하고, 회상 상태는 누를 때 글과 소리로 알린다.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { ElderHomeOut, SessionOut } from '../../api/types'
import todayPreview from '../../assets/today-preview.svg?inline' // 미리보기 전용 — 배포 빌드에 파일이 따로 남지 않게
import { useLive } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { speak, stopSpeaking } from '../../lib/audio'
import ELDER_TODAY_001 from './ELDER_TODAY_001'
import './ELDER_HOME_001.css'

let closedPickId: number | null = null
const STALE_MS = 30 * 60 * 1000 // 이만큼 넘게 숨어 있다 돌아오면 홈을 다시 읽는다 (FR-ME-006, D45 ④)
const RETRY_MS = 5_000 // 홈 읽기가 실패하면 이만큼 뒤에 다시 — 성공할 때까지
const NOTICE_MS = 4_000

function HomeIcon({ children }: { children: ReactNode }) {
  return (
    <svg className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  )
}

/** 오늘 날짜(한국 시간) 글자. 날이 바뀌었는지 볼 때만 쓴다 */
const kstDate = () => new Date().toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul' })

// 백엔드 없이 11/10 화면을 확인하기 위한 개발 서버 전용 데이터.
const previewHome: ElderHomeOut = {
  greeting: '순자 어르신, 안녕하세요',
  elder_name: '순자',
  elder_honorific: '어르신',
  today_pick: { pick_id: 1, photo_id: 1, photo_url: todayPreview, status: 'PENDING' },
  unread_family_news: 0,
  settings: { font_size: 'XL', tts_speed: 0.85, input_mode: 'VOICE' },
}

export default function ELDER_HOME_001() {
  const nav = useNavigate()
  const { search } = useLocation()
  const preview = import.meta.env.DEV && new URLSearchParams(search).get('preview') === '1'
  const { data: serverHome, error, loading, reload } = useFetch<ElderHomeOut>(preview ? null : '/api/elder/home')
  const home = preview ? previewHome : serverHome
  // 같은 pick 재시도는 같은 id, 날짜가 바뀌어 새 pick 이 오면 새 id 를 쓴다.
  const sessionIds = useRef(new Map<number, string>())
  const hiddenAt = useRef<number | null>(null) // 화면이 숨은 시각
  const loadedDate = useRef<string | null>(null) // 홈을 마지막으로 읽은 날(한국 시간)
  const [busy, setBusy] = useState(false)
  const [startError, setStartError] = useState<string>()
  const [dismissedPickId, setDismissedPickId] = useState<number | null>(null)
  const [skipping, setSkipping] = useState(false)
  const [skippedPickId, setSkippedPickId] = useState<number | null>(null) // 건너뛰기가 저장된 pick → SKIPPED 로 보인다
  const [notice, setNotice] = useState('')
  const noticeTimer = useRef<number | undefined>(undefined)
  const live = useLive()

  useEffect(() => () => window.clearTimeout(noticeTimer.current), [])

  useEffect(() => {
    if (home) document.documentElement.dataset.font = home.settings.font_size
  }, [home])

  useEffect(() => {
    if (serverHome) loadedDate.current = kstDate()
  }, [serverHome])

  // 홈을 다시 읽고, 앞서 뜬 오류 문장과 대화 번호는 비운다
  // (서버는 30분 지난 대화를 끝난 것으로 봐서, 오래된 번호를 다시 쓰면 들어가자마자 끝난다)
  const refresh = useCallback(() => {
    sessionIds.current.clear()
    setStartError(undefined)
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
  // 실패한 채 두면 어제 화면이 오늘 날짜로 남고, 그 팝업의 [건너뛰기]는 오늘 사진을 건너뛴다.
  // 연결이 풀린 기기(401)는 다시 읽어도 같으니 그만둔다
  useEffect(() => {
    if (preview || !error || error.code === 'DEVICE_REQUIRED') return
    const timer = window.setTimeout(reload, RETRY_MS)
    return () => window.clearTimeout(timer)
  }, [preview, error, reload])

  // 홈을 떠나면 읽던 오류 문장을 끊는다 — 다음 화면 소리 위로 이어지지 않게
  useEffect(() => () => stopSpeaking(), [])

  async function startMemory() {
    if (!home?.today_pick || busy) return
    if (preview) {
      setStartError('이 화면은 미리보기예요. 회상 대화는 서버가 연결되면 확인할 수 있어요.')
      return
    }
    setBusy(true)
    setStartError(undefined)
    const pickId = home.today_pick.pick_id
    let sessionId = sessionIds.current.get(pickId)
    if (!sessionId) {
      sessionId = crypto.randomUUID()
      sessionIds.current.set(pickId, sessionId)
    }
    try {
      const s = await api<SessionOut>('/api/elder/sessions', {
        body: {
          session_id: sessionId,
          kind: 'MEMORY',
          pick_id: home.today_pick.pick_id,
          photo_id: home.today_pick.photo_id,
        },
      })
      if (!live.current) return // 기다리는 동안 [오늘 이야기하기]·[사진첩]으로 떠났으면 끌고 가지 않는다
      closedPickId = home.today_pick.pick_id // 뒤로 가기로 돌아와도 팝업을 다시 띄우지 않는다(미리보기는 여기까지 안 옴)
      nav(`/elder/memory/${sessionId}`, { state: { session: s, photoUrl: home.today_pick.photo_url, home } })
    } catch (e) {
      if (!live.current) return
      setBusy(false)
      // 옛 화면에서 눌렀다(켜 둔 채 날이 바뀜·이미 건너뜀) → 서버가 409 로 알려 준다. 홈을 다시 읽어 오늘 것을 보여 준다 (D45 ④)
      if (e instanceof ApiError && (e.code === 'PICK_EXPIRED' || e.code === 'PICK_SKIPPED')) return refresh()
      // 서버 문장이 아닌 오류(응답이 중간에 끊김 등)는 영어라 그대로 보여 주거나 읽지 않는다
      const message = e instanceof ApiError ? e.message : '대화를 시작하지 못했어요. 다시 눌러 주세요.'
      setStartError(message)
      void speak(message, Number(home.settings.tts_speed) || 0.85)
    }
  }

  function closeToday() {
    if (!home?.today_pick) return
    if (!preview) closedPickId = home.today_pick.pick_id
    setDismissedPickId(home.today_pick.pick_id)
    setStartError(undefined)
    stopSpeaking()
  }

  function talkFromToday() {
    stopSpeaking() // 팝업은 닫지 않는다 — 기다리는 동안 '잠시만요'로 잠기고, 실패 문장도 팝업 안에 나온다
    void startMemory()
  }

  async function skipToday() {
    if (!home?.today_pick || skipping) return
    if (preview) {
      closeToday() // 미리보기는 서버를 부르지 않고 닫기만 한다
      return
    }
    const pickId = home.today_pick.pick_id
    stopSpeaking() // 누르는 순간 인사 소리는 멈춘다
    setSkipping(true) // 서버가 저장할 때까지 팝업을 띄운 채 두 버튼을 잠근다
    setStartError(undefined)
    try {
      await api('/api/elder/picks/today/skip', { method: 'POST' })
      if (!live.current) return // 기다리는 동안 떠났으면 손대지 않는다(다음 화면의 소리를 끊지 않게)
      setSkippedPickId(pickId) // 홈을 다시 읽지 않는다 — 읽으면 화면 전체가 '잠시만요…'로 깜빡인다
      closeToday()
    } catch {
      if (!live.current) return
      const message = '건너뛰지 못했어요. 다시 눌러 주세요.'
      setStartError(message) // 저장이 안 됐으니 팝업을 남기고 그 안에 알린다
      void speak(message, Number(home.settings.tts_speed) || 0.85)
    } finally {
      setSkipping(false)
    }
  }

  // 읽은 홈이 있으면 다시 읽기에 실패해도 그대로 보여 준다(위에서 5초마다 다시 읽는 중). 연결이 풀린 기기만 안내로 바꾼다
  if (error && !preview && (!serverHome || error.code === 'DEVICE_REQUIRED'))
    return (
      <main className="elder">
        <p className="elder-text">
          {error.code === 'DEVICE_REQUIRED'
            ? '가족이 보낸 연결 링크를 먼저 열어 주세요.'
            : '연결이 잠깐 끊겼어요. 잠시 뒤에 다시 열어 볼게요.'}
        </p>
      </main>
    )
  if (!home) return loading ? <main className="elder"><p className="elder-text">잠시만요…</p></main> : null

  const pick = home.today_pick
  const status = pick && pick.pick_id === skippedPickId ? 'SKIPPED' : pick?.status
  const showToday = pick?.status === 'PENDING' && pick.pick_id !== closedPickId && pick.pick_id !== dismissedPickId
  function onMemory() {
    if (!home) return
    if (status === 'PENDING') {
      void startMemory()
      return
    }
    const message = !pick ? '오늘은 아직 사진이 없어요.'
      : status === 'COMPLETED' ? '오늘 이야기는 다 나눴어요.'
      : status === 'SKIPPED' ? '오늘 사진은 건너뛰었어요.' : ''
    if (!message) return
    window.clearTimeout(noticeTimer.current)
    setNotice(message)
    noticeTimer.current = window.setTimeout(() => setNotice(''), NOTICE_MS)
    void speak(message, Number(home.settings.tts_speed) || 0.85)
  }

  return (
    <main className="elder elder--fit elder-home">
      <header className="elder-head">
        <svg viewBox="0 0 40 40" aria-hidden="true">
          <g transform="rotate(-8 20 20)">
            <rect x="6" y="9" width="28" height="22" rx="5" fill="currentColor" />
            <circle cx="14.5" cy="16.5" r="3" fill="var(--elder-primary-fg)" />
            <path d="M9 27l8-7 5 4.5 4-3 5 5.5z" fill="var(--elder-primary-fg)" />
          </g>
        </svg>
        <span>하루한장</span>
      </header>
      <div className="elder-tiles" inert={showToday} aria-hidden={showToday}>
        <button type="button" className={`elder-tile elder-tile--1${status === 'PENDING' ? ' elder-tile--new' : ''}`} onClick={onMemory} disabled={busy}>
          <HomeIcon>
            <rect x="3" y="5" width="18" height="14" rx="2.5" />
            <circle cx="8.5" cy="10" r="1.6" />
            <path d="M21 16l-5-5-7.5 8" />
          </HomeIcon>
          <span>{busy ? '잠시만요' : '회상'}</span>
          {status === 'PENDING' && <span className="elder-badge">새 사진</span>}
        </button>
        <button type="button" className="elder-tile elder-tile--2" onClick={() => nav('/elder/diary', { state: { home } })}>
          <HomeIcon>
            <path d="M6 3h11a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" />
            <path d="M8.5 8h6M8.5 12h6M8.5 16h3.5" />
          </HomeIcon>
          <span>일기 쓰기</span>
        </button>
        <button type="button" className="elder-tile elder-tile--3" onClick={() => nav('/elder/family-news', { state: { home } })}>
          <HomeIcon>
            <circle cx="8.5" cy="8" r="3" />
            <path d="M2.5 20a6 6 0 0 1 12 0" />
            <circle cx="17" cy="9.5" r="2.4" />
            <path d="M16 14.3a5 5 0 0 1 5.5 5.2" />
          </HomeIcon>
          <span>가족 소식</span>
          {home.unread_family_news > 0 && <span className="elder-badge">{home.unread_family_news}</span>}
        </button>
        <button type="button" className="elder-tile elder-tile--4" onClick={() => nav('/elder/album', { state: { home } })}>
          <HomeIcon>
            <rect x="7" y="7" width="14" height="14" rx="2.5" />
            <path d="M3 16V5.5A2.5 2.5 0 0 1 5.5 3H16" />
            <path d="M21 17l-3.5-3.5L12 19" />
          </HomeIcon>
          <span>사진첩</span>
        </button>
      </div>
      {!showToday && startError
        ? <p className="elder-text elder-home-note" role="alert">{startError}</p>
        : notice && <p className="elder-text elder-home-note" role="status">{notice}</p>}
      {showToday && <ELDER_TODAY_001 home={home} busy={busy || skipping} error={startError} onTalk={talkFromToday} onSkip={() => void skipToday()} />}
    </main>
  )
}
