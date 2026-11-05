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
  const loc = useLocation()
  const state = (loc.state ?? {}) as NavState
  const [session, setSession] = useState<SessionOut | undefined>(state.session)
  const [home, setHome] = useState<ElderHomeOut | undefined>(state.home)
  const [photoUrl] = useState<string | undefined>(state.photoUrl)
  const [ended, setEnded] = useState<SessionOut>()

  // 넘겨받은 state 는 위 state 로 옮겼으니 주소에서 지운다 → 새로고침하면 서버에서 다시 읽는다(30분 복귀 경로)
  useEffect(() => {
    if (loc.state) nav(loc.pathname, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
    // 오류로 끝났으면 오늘의 한 장은 PENDING 그대로라(D27) '다 들었어요' 기록을 남기지 않는다
    if (ended?.end_reason !== 'ERROR') {
      await api('/api/elder/picks/today/listened', { method: 'POST' }).catch(() => {})
    }
    nav('/elder', { replace: true })
  }

  if (!session || !home) return <main className="elder"><p className="elder-text">잠시만요…</p></main>
  const shownPhoto = photoUrl ?? home.today_pick?.photo_url
  return (
    <main className="elder">
      {shownPhoto && <img className="elder-photo" src={shownPhoto} alt="오늘의 사진" />}
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
