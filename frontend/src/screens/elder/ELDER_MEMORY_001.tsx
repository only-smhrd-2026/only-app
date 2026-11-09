/**
 * ELDER_MEMORY_001 — 회상 대화 (사진 + VoiceSession). ELDER_HOME_001 이 세션을 만들어 state 로 넘긴다.
 * 새로고침 등으로 state 가 없으면 서버에서 세션을 다시 읽는다 (30분 안 복귀, useElderSession).
 */
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { SessionOut } from '../../api/types'
import VoiceSession from '../../components/VoiceSession/VoiceSession'
import { useElderSession } from '../../hooks/useElderSession'

export default function ELDER_MEMORY_001() {
  const { sessionId = '' } = useParams()
  const nav = useNavigate()
  const { session, home, photoUrl } = useElderSession(sessionId)
  const [ended, setEnded] = useState<SessionOut>()

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
