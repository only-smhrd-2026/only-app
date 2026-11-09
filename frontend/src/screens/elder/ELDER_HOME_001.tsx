/**
 * ELDER_HOME_001 — 어르신 홈. 오늘의 한 장이 있으면 홈 위에 시트를 띄운다.
 */
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { ElderHomeOut, SessionOut } from '../../api/types'
import todayPreview from '../../assets/today-preview.svg?inline' // 미리보기 전용 — 배포 빌드에 파일이 따로 남지 않게
import { useLive } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import ELDER_TODAY_001 from './ELDER_TODAY_001'
import './ELDER_HOME_001.css'

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
  const { data: serverHome, error, loading } = useFetch<ElderHomeOut>(preview ? null : '/api/elder/home')
  const home = preview ? previewHome : serverHome
  // 같은 화면에서는 같은 session_id 를 쓴다 → 두 번 눌러도 서버가 멱등으로 세션 하나만 만든다
  const [sessionId] = useState(() => crypto.randomUUID())
  const [busy, setBusy] = useState(false)
  const [startError, setStartError] = useState<string>()
  const [todayDismissed, setTodayDismissed] = useState(false)
  const [todayLabel] = useState(() => new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', weekday: 'long',
  }).format(new Date()))
  const live = useLive()

  useEffect(() => {
    if (home) document.documentElement.dataset.font = home.settings.font_size
  }, [home])

  async function startMemory() {
    if (!home?.today_pick || busy) return
    if (preview) {
      setStartError('이 화면은 미리보기예요. 회상 대화는 서버가 연결되면 확인할 수 있어요.')
      return
    }
    setBusy(true)
    setStartError(undefined)
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
      nav(`/elder/memory/${sessionId}`, { state: { session: s, photoUrl: home.today_pick.photo_url, home } })
    } catch (e) {
      setStartError((e as ApiError).message)
      setBusy(false)
    }
  }

  if (loading && !preview) return <main className="elder"><p className="elder-text">잠시만요…</p></main>
  if (error && !preview)
    return (
      <main className="elder">
        <p className="elder-text">
          {error.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : (error as ApiError).message}
        </p>
      </main>
    )
  if (!home) return null

  const pick = home.today_pick
  const showToday = pick?.status === 'PENDING' && !todayDismissed
  const date = preview ? '11월 4일 (수) 아침' : todayLabel
  return (
    <main className={`elder elder-home${preview ? ' elder-home--preview' : ''}`}>
      <div className="elder-home-content" inert={showToday} aria-hidden={showToday}>
        <p className="elder-home-date">{date}</p>
        <h1 className="elder-home-greeting">{home.greeting}</h1>
        <div className="elder-home-tiles">
          <button className="elder-home-tile elder-home-tile--secondary" onClick={() => nav('/elder/album')}><span>사진첩</span></button>
          <button className="elder-home-tile" onClick={() => nav('/elder/diary', { state: { home } })}><span>오늘<br />이야기<wbr />하기</span></button>
        </div>
        {home.unread_family_news > 0 && <p className="elder-home-news">새로운 가족 소식이 {home.unread_family_news}개 있어요.</p>}
        {pick?.status === 'PENDING' && !showToday && (
          <button className="elder-btn elder-home-pick" onClick={preview ? () => { setStartError(undefined); setTodayDismissed(false) } : startMemory} disabled={busy}>
            {busy ? '잠시만요' : preview ? '팝업 다시 보기' : '오늘 사진 보기'}
          </button>
        )}
        {!pick && <p className="elder-home-news">오늘은 아직 사진이 없어요.</p>}
        {pick && pick.status !== 'PENDING' && <p className="elder-home-news">오늘 이야기는 다 나눴어요.</p>}
        {!showToday && startError && <p className="elder-home-news" role="alert">{startError}</p>}
      </div>
      {showToday && <ELDER_TODAY_001 home={home} busy={busy} error={startError} preview={preview} onTalk={startMemory} onSkip={() => setTodayDismissed(true)} />}
    </main>
  )
}
