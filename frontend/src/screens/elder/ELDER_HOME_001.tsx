/**
 * ELDER_HOME_001 — 어르신 홈. 오늘의 한 장이 있으면 홈 위에 시트를 띄운다.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { ElderHomeOut, SessionOut } from '../../api/types'
import todayPreview from '../../assets/today-preview.svg?inline' // 미리보기 전용 — 배포 빌드에 파일이 따로 남지 않게
import cameraIcon from '../../assets/elder-home-camera.svg'
import speechIcon from '../../assets/elder-home-speech.svg'
import { useLive } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { speak, stopSpeaking } from '../../lib/audio'
import ELDER_TODAY_001 from './ELDER_TODAY_001'
import './ELDER_HOME_001.css'

let closedPickId: number | null = null
const STALE_MS = 30 * 60 * 1000 // 이만큼 넘게 숨어 있다 돌아오면 홈을 다시 읽는다 (FR-ME-006, D45 ④)
const RETRY_MS = 5_000 // 홈 읽기가 실패하면 이만큼 뒤에 다시 — 성공할 때까지

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
  const [today, setToday] = useState(() => new Date())
  const todayLabel = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', weekday: 'long',
  }).format(today)
  const live = useLive()

  useEffect(() => {
    if (home) document.documentElement.dataset.font = home.settings.font_size
  }, [home])

  useEffect(() => {
    if (serverHome) loadedDate.current = kstDate()
  }, [serverHome])

  // 홈을 다시 읽는다. 날짜 글자도 같이 바꾸고, 앞서 뜬 오류 문장과 대화 번호는 비운다
  // (서버는 30분 지난 대화를 끝난 것으로 봐서, 오래된 번호를 다시 쓰면 들어가자마자 끝난다)
  const refresh = useCallback(() => {
    sessionIds.current.clear()
    setStartError(undefined)
    setToday(new Date())
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
  const date = preview ? '11월 4일 (수) 아침' : todayLabel
  return (
    <main className={`elder elder-home${preview ? ' elder-home--preview' : ''}`}>
      <div className="elder-home-content" inert={showToday} aria-hidden={showToday}>
        <p className="elder-home-date">{date}</p>
        <h1 className="elder-home-greeting">{home.greeting}</h1>
        <div className="elder-home-guide">
          <span className="elder-home-avatar" aria-hidden="true">심심이</span>
          <p className="elder-text elder-home-bubble">사진첩이나 오늘 이야기를 골라 주세요.</p>
        </div>
        <div className="elder-home-tiles">
          <button className="elder-btn elder-home-tile elder-home-tile--secondary" onClick={() => nav('/elder/album', { state: { home } })}><img src={cameraIcon} alt="" /><span>사진첩</span></button>
          <button className="elder-btn elder-home-tile" onClick={() => nav('/elder/diary', { state: { home } })}><img src={speechIcon} alt="" /><span>오늘<br />이야기<wbr />하기</span></button>
        </div>
        <p className={`elder-text elder-home-news elder-home-news--card${home.unread_family_news > 0 ? ' elder-home-news--new' : ''}`}>
          {home.unread_family_news > 0 ? `새로운 가족 소식이 ${home.unread_family_news}개 있어요.` : '오늘은 새 소식이 없어요.'}
        </p>
        {status === 'PENDING' && !showToday && (
          <button className="elder-btn elder-home-pick" onClick={preview ? () => { setStartError(undefined); setDismissedPickId(null) } : startMemory} disabled={busy}>
            {busy ? '잠시만요' : preview ? '팝업 다시 보기' : '오늘 사진 보기'}
          </button>
        )}
        {!pick && <p className="elder-home-news">오늘은 아직 사진이 없어요.</p>}
        {status === 'COMPLETED' && <p className="elder-home-news">오늘 이야기는 다 나눴어요.</p>}
        {status === 'SKIPPED' && <p className="elder-home-news">오늘 사진은 건너뛰었어요.</p>}
        {!showToday && startError && <p className="elder-home-news" role="alert">{startError}</p>}
      </div>
      {showToday && <ELDER_TODAY_001 home={home} busy={busy || skipping} error={startError} onTalk={talkFromToday} onSkip={() => void skipToday()} />}
    </main>
  )
}
