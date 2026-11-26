/**
 * ELDER_CHAT_001 — 심심이랑 이야기 (D106, 11/25 멘토 아이디어). 홈의 큰 꼬마심심이를 누르면 온다.
 * 심심할 때 아무 이야기나·궁금한 것 무엇이든(날씨·요리·날짜). 말하기는 회상·일기와 같은 버튼 방식(VoiceSession 잡담 모양).
 * 왼쪽 위 [뒤로](ElderBackFrame), 오른쪽 위 [지난 이야기](ELDER_CHAT_002). 어르신이 일기·사진첩·가족 소식·마음 체크로
 * 가자고 하시면 그 화면으로 데려간다.
 * 잇기(D107, 11/25 사용자 '30분 이어서'): 잡담 번호를 기기에 적어 두고(lib/pausedSession) 마지막 말 뒤 30분 안에 다시 오면
 * — 사진첩 등에 갔다 와도·지난 이야기·홈에 갔다 와도 — 같은 잡담을 말풍선째 잇는다. 첫마디는 정해진 돌아온 인사(AI 를 부르지 않음).
 * 끝나는 때: 30분 조용함(서버 SESSION_RESUME_MIN) · '그만할래'(STOP) · 심심이 말 20번 · 대화 20분 · 이 화면에서 1분 무응답.
 * '지난 이야기'에서 [이어서 하기]로 오면 state 에 그 잡담 번호·말이 있다 → 서버가 그 이야기로 첫 말을 연다(resume_of).
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { ChatGo, ElderHomeOut, ElderWeatherOut, SessionGetOut, SessionOut, TurnOut } from '../../api/types'
import { ElderStop, IC } from '../../components/ElderUi'
import VoiceSession from '../../components/VoiceSession/VoiceSession'
import { useLive } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { setVoice } from '../../lib/audio'
import { setElderFont } from '../../lib/elderFont'
import { clearPaused, readChat, savePaused, type Paused } from '../../lib/pausedSession'
import './ELDER_CHAT.css'

/** 이어서 할 때 ELDER_CHAT_002 가 넘기는 것 */
export type ChatNavState = { home?: ElderHomeOut; resumeOf?: string; earlier?: TurnOut[]; earlierLabel?: string }

const GO_PATH: Record<ChatGo, string> = {
  DIARY: '/elder/diary',
  ALBUM: '/elder/album',
  NEWS: '/elder/family-news',
  MIND: '/elder/mind',
}

/** 잡담으로 돌아왔을 때 심심이 첫마디 (D107) — 데려다 드린 화면에 맞춰서, 아니면(지난 이야기·홈) BACK_AGAIN */
const BACK_LINE: Record<ChatGo, string> = {
  DIARY: '일기 잘 쓰셨어요? 이야기 더 해요.',
  ALBUM: '사진첩 잘 보셨어요? 이야기 더 해요.',
  NEWS: '가족 소식 잘 보셨어요? 이야기 더 해요.',
  MIND: '마음 체크 잘 하셨어요? 이야기 더 해요.',
}
const BACK_AGAIN = '아까 하던 이야기 이어서 해요.'

type Opened = { s: SessionOut; turns?: TurnOut[] } | null

/** 30분 안에 하던 잡담을 서버에서 다시 읽는다. 끝났거나 없으면 null → 새 잡담 */
async function reopen(p: Paused): Promise<Opened> {
  const s = await api<SessionGetOut>(`/api/elder/sessions/${p.id}`).catch((e: unknown) => {
    if (e instanceof ApiError && e.status === 404) return null // 지워진 잡담 — 새로 연다
    throw e
  })
  if (!s || s.state === 'ENDED' || !s.last_ai) {
    clearPaused(p.id)
    return null
  }
  // 지금 말풍선 = 돌아온 인사. 서버의 마지막 말은 지난 말풍선으로 올라간다(VoiceSession 잡담 log)
  const ai = { ...s.last_ai, text: p.went ? BACK_LINE[p.went] : BACK_AGAIN, audio_b64: null, face: 'smile' as const, go: null }
  const { session_id, kind, photo_url, state, end_reason, turn_no, input_locked } = s
  return { s: { session_id, kind, photo_url, ai, state, end_reason, turn_no, input_locked }, turns: s.turns }
}

export default function ELDER_CHAT_001() {
  const nav = useNavigate()
  const loc = useLocation()
  const live = useLive()
  const [start] = useState<ChatNavState>(() => (loc.state ?? {}) as ChatNavState)
  const [home, setHome] = useState<ElderHomeOut | undefined>(start.home)
  const weather = useFetch<ElderWeatherOut>('/api/elder/weather') // 날씨 심심이 (11/26) — 서버가 30분 기억
  const [resume, setResume] = useState(start.resumeOf ? start : undefined) // [새로 이야기하기]면 지난 이야기를 뗀다
  // 30분 안에 하던 잡담 (D107). '지난 이야기'의 [이어서 하기]로 왔으면 그 이야기로 새 잡담을 연다
  const [kept] = useState(() => (start.resumeOf ? null : readChat()))
  const [sessionId, setSessionId] = useState(() => kept?.id ?? crypto.randomUUID())
  const [session, setSession] = useState<SessionOut>()
  const [history, setHistory] = useState<TurnOut[]>() // 이어서 연 잡담의 지난 말
  const [error, setError] = useState<string>()

  // 넘겨받은 state 는 위로 옮겼으니 주소에서 지운다 — 새로고침하면 하던 잡담을 잇는다(30분 안)
  useEffect(() => {
    if (loc.state) nav(loc.pathname, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 잡담을 연다(또는 잇는다). 같은 번호의 요청은 한 번만 보낸다 — 개발 모드(StrictMode)는 이 effect 를 곧바로 두 번 돌리는데,
  // 두 요청이 동시에 가면 서버의 '같은 번호면 그대로' 검사를 둘 다 지나 두 번째가 저장 충돌(500)이 난다
  const opening = useRef(new Map<string, Promise<Opened>>())
  useEffect(() => {
    let alive = true
    setError(undefined)
    let open = opening.current.get(sessionId)
    if (!open) {
      open =
        sessionId === kept?.id
          ? reopen(kept)
          : api<SessionOut>('/api/elder/sessions', {
              body: { session_id: sessionId, kind: 'CHAT', ...(resume?.resumeOf ? { resume_of: resume.resumeOf } : {}) },
            }).then((s) => ({ s }))
      opening.current.set(sessionId, open)
    }
    Promise.all([open, home ?? api<ElderHomeOut>('/api/elder/home')])
      .then(([o, h]) => {
        if (!alive) return
        setVoice(h.settings.tts_voice)
        setElderFont(h.settings.font_size)
        setHome(h)
        if (!o) return setSessionId(crypto.randomUUID()) // 이을 잡담이 끝났다(30분 지남·마무리) → 새 잡담
        setHistory(o.turns)
        setSession(o.s)
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

  /** 가자고 하신 화면으로 — 잡담은 끝내지 않는다. 30분 안에 돌아오면 '사진첩 잘 보셨어요?'로 잇는다 (D107) */
  function go(to: ChatGo) {
    const p = readChat()
    if (p?.id === sessionId) savePaused({ ...p, went: to })
    if (live.current) nav(GO_PATH[to], { state: { home } })
  }

  function again() {
    setResume(undefined)
    setHistory(undefined)
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
        history={history}
        speed={Number(home.settings.tts_speed) || 0.9}
        inputMode={home.settings.input_mode}
        who={home.elder_honorific}
        title="심심이랑 이야기"
        onEnded={() => {}}
        onDone={() => nav('/elder', { replace: true })}
        onMore={again}
        chat={{ onGo: go, earlier: resume?.earlier, earlierLabel: resume?.earlierLabel, weather: weather.data?.look }}
      />
    </main>
  )
}
