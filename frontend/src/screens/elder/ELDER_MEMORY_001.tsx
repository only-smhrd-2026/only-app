/**
 * ELDER_MEMORY_001 — 회상 대화 (사진 + VoiceSession). ELDER_HOME_001 이 세션을 만들어 state 로 넘긴다.
 * 새로고침 등으로 state 가 없으면 서버에서 세션을 다시 읽는다 (30분 안 복귀).
 */
import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { ElderHomeOut, SessionGetOut, SessionOut } from '../../api/types'
import VoiceSession from '../../components/VoiceSession/VoiceSession'

type NavState = { session?: SessionOut; photoUrl?: string; home?: ElderHomeOut }

export default function ELDER_MEMORY_001() {
  const { sessionId = '' } = useParams()
  const nav = useNavigate()
  const state = (useLocation().state ?? {}) as NavState
  const [session, setSession] = useState<SessionOut | undefined>(state.session)
  const [home, setHome] = useState<ElderHomeOut | undefined>(state.home)
  const [ended, setEnded] = useState<SessionOut>()

  useEffect(() => {
    if (session && home) return
    Promise.all([api<SessionGetOut>(`/api/elder/sessions/${sessionId}`), api<ElderHomeOut>('/api/elder/home')])
      .then(([s, h]) => {
        setHome(h)
        if (s.last_ai)
          setSession({
            session_id: s.session_id,
            ai: s.last_ai,
            state: s.state,
            end_reason: s.end_reason,
            turn_no: s.turn_no,
            input_locked: s.input_locked,
          })
      })
      .catch(() => nav('/elder', { replace: true }))
  }, [sessionId, session, home, nav])

  async function finish() {
    await api('/api/elder/picks/today/listened').catch(() => {})
    nav('/elder', { replace: true })
  }

  if (!session || !home) return <main className="elder"><p className="elder-text">잠시만요…</p></main>
  const photoUrl = state.photoUrl ?? home.today_pick?.photo_url
  return (
    <main className="elder">
      {photoUrl && <img className="elder-photo" src={photoUrl} alt="오늘의 사진" />}
      {ended ? (
        <>
          <p className="elder-text">{ended.ai.text}</p>
          <button className="elder-btn" onClick={finish}>다 들었어요</button>
        </>
      ) : (
        <VoiceSession
          sessionId={sessionId}
          initial={session}
          speed={Number(home.settings.tts_speed) || 0.85}
          inputMode={home.settings.input_mode}
          onEnded={setEnded}
        />
      )}
    </main>
  )
}
