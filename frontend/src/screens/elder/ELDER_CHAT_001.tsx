/**
 * ELDER_CHAT_001 — 심심이랑 이야기 (D106, 11/25 멘토 아이디어). 홈의 큰 꼬마심심이를 누르면 온다.
 * 심심할 때 아무 이야기나·궁금한 것 무엇이든(날씨·요리·날짜). 말하기는 회상·일기와 같은 버튼 방식(VoiceSession 잡담 모양).
 * 왼쪽 위 [뒤로](ElderBackFrame), 오른쪽 위 [지난 이야기](ELDER_CHAT_002). 어르신이 일기·사진첩·가족 소식·마음 체크로
 * 가자고 하시면 그 화면으로 데려간다 — 이 잡담은 끝낸다(다시 오면 새 잡담, 지난 잡담은 '지난 이야기'에서 잇는다).
 * '지난 이야기'에서 [이어서 하기]로 오면 state 에 그 잡담 번호·말이 있다 → 서버가 그 이야기로 첫 말을 연다(resume_of).
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { ChatGo, ElderHomeOut, SessionOut, TurnOut } from '../../api/types'
import { ElderStop, IC } from '../../components/ElderUi'
import VoiceSession from '../../components/VoiceSession/VoiceSession'
import { useLive } from '../../hooks/useElderSession'
import { setVoice } from '../../lib/audio'
import { setElderFont } from '../../lib/elderFont'
import './ELDER_CHAT.css'

/** 이어서 할 때 ELDER_CHAT_002 가 넘기는 것 */
export type ChatNavState = { home?: ElderHomeOut; resumeOf?: string; earlier?: TurnOut[]; earlierLabel?: string }

const GO_PATH: Record<ChatGo, string> = {
  DIARY: '/elder/diary',
  ALBUM: '/elder/album',
  NEWS: '/elder/family-news',
  MIND: '/elder/mind',
}

export default function ELDER_CHAT_001() {
  const nav = useNavigate()
  const loc = useLocation()
  const live = useLive()
  const [start] = useState<ChatNavState>(() => (loc.state ?? {}) as ChatNavState)
  const [home, setHome] = useState<ElderHomeOut | undefined>(start.home)
  const [resume, setResume] = useState(start.resumeOf ? start : undefined) // [새로 이야기하기]면 지난 이야기를 뗀다
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())
  const [session, setSession] = useState<SessionOut>()
  const [error, setError] = useState<string>()

  // 넘겨받은 state 는 위로 옮겼으니 주소에서 지운다 — 새로고침하면 새 잡담
  useEffect(() => {
    if (loc.state) nav(loc.pathname, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 잡담을 연다. 같은 번호의 요청은 한 번만 보낸다 — 개발 모드(StrictMode)는 이 effect 를 곧바로 두 번 돌리는데,
  // 두 요청이 동시에 가면 서버의 '같은 번호면 그대로' 검사를 둘 다 지나 두 번째가 저장 충돌(500)이 난다
  const opening = useRef(new Map<string, Promise<SessionOut>>())
  useEffect(() => {
    let alive = true
    setError(undefined)
    let open = opening.current.get(sessionId)
    if (!open) {
      open = api<SessionOut>('/api/elder/sessions', {
        body: { session_id: sessionId, kind: 'CHAT', ...(resume?.resumeOf ? { resume_of: resume.resumeOf } : {}) },
      })
      opening.current.set(sessionId, open)
    }
    Promise.all([open, home ?? api<ElderHomeOut>('/api/elder/home')])
      .then(([s, h]) => {
        if (!alive) return
        setVoice(h.settings.tts_voice)
        setElderFont(h.settings.font_size)
        setHome(h)
        setSession(s)
      })
      .catch((e) => {
        opening.current.delete(sessionId) // [다시 보기]는 새 번호로 가지만, 같은 번호로 다시 와도 새로 보낸다
        if (!alive) return
        if (e instanceof ApiError && e.code === 'DEVICE_REQUIRED') return nav('/elder', { replace: true })
        setError(e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 눌러 주세요.')
      })
    return () => {
      alive = false
    }
    // 잡담 번호가 바뀔 때만 ([새로 이야기하기]·[다시 해 보기]) — home 은 처음 한 번 받으면 그대로
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  /** 가자고 하신 화면으로 — 이 잡담은 끝낸다(기다리지 않음) */
  function go(to: ChatGo) {
    void api(`/api/elder/sessions/${sessionId}/end`, { body: { reason: 'COMPLETED' } }).catch(() => {})
    if (live.current) nav(GO_PATH[to], { state: { home } })
  }

  function again() {
    setResume(undefined)
    setSession(undefined)
    setSessionId(crypto.randomUUID())
  }

  const past = (
    <button type="button" className="elder-btn elder-btn--secondary elder-btn--sm echat-past" onClick={() => nav('/elder/chat/past', { state: { home } })}>
      {IC.chat}
      <span>지난 이야기</span>
    </button>
  )

  if (error)
    return (
      <main className="elder elder--fit elder-center">
        {past}
        <ElderStop text={error} onRetry={() => setSessionId(crypto.randomUUID())} />
      </main>
    )
  if (!session || !home)
    return (
      <main className="elder elder--fit elder-center">
        <p className="elder-text" role="status">
          잠시만요…
        </p>
      </main>
    )
  return (
    <main className="elder elder--fit">
      {past}
      <VoiceSession
        key={sessionId}
        sessionId={sessionId}
        initial={session}
        speed={Number(home.settings.tts_speed) || 0.9}
        inputMode={home.settings.input_mode}
        who={home.elder_honorific}
        title="심심이랑 이야기"
        onEnded={() => {}}
        onDone={() => nav('/elder', { replace: true })}
        onMore={again}
        chat={{ onGo: go, earlier: resume?.earlier, earlierLabel: resume?.earlierLabel }}
      />
    </main>
  )
}
