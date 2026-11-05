/**
 * ELDER_DIARY_002 — 일기 대화. 질문 3개(뭐 하셨어요 → 누구랑 → 기분은, 기분은 칩 4개)를 VoiceSession 으로.
 * 다 답하면(COMPLETED·5분 LIMIT) ELDER_DIARY_003 확인으로. 그만할래요·무응답·오류로 끝나면 저장하지 않는다 (FR-DI-003).
 */
import { useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import type { EndReason, SessionOut } from '../../api/types'
import VoiceSession from '../../components/VoiceSession/VoiceSession'
import { useElderSession } from '../../hooks/useElderSession'

const DIARY_TURNS = 3 // 서버 config.DIARY_TURNS
const saved = (r: EndReason | null) => r === 'COMPLETED' || r === 'LIMIT' // 서버 sessions.DIARY_SAVED

export default function ELDER_DIARY_002() {
  const { sessionId = '' } = useParams()
  const nav = useNavigate()
  const { session, home, photoUrl } = useElderSession(sessionId)
  const [stopped, setStopped] = useState<SessionOut>()

  function onEnded(r: SessionOut) {
    if (saved(r.end_reason)) nav(`/elder/diary/${sessionId}/confirm`, { replace: true, state: { home } })
    else setStopped(r)
  }

  if (!session || !home) return <main className="elder"><p className="elder-text">잠시만요…</p></main>
  // 새로고침·다시 열기로 이미 끝난 대화를 받으면 질문을 다시 띄우지 않는다:
  // 일기로 남길 것은 확인 화면, 나머지(그만할래요·오류·30분 지남)는 홈
  if (session.state === 'ENDED')
    return <Navigate replace to={saved(session.end_reason) ? `/elder/diary/${sessionId}/confirm` : '/elder'} state={{ home }} />
  return (
    <main className="elder">
      {photoUrl && <img className="elder-photo" src={photoUrl} alt="오늘 찍은 사진" />}
      {stopped ? (
        <>
          <p className="elder-text">{stopped.ai.text}</p>
          <button className="elder-btn" onClick={() => nav('/elder', { replace: true })}>처음으로</button>
        </>
      ) : (
        <VoiceSession
          sessionId={sessionId}
          initial={session}
          maxTurns={DIARY_TURNS}
          speed={Number(home.settings.tts_speed) || 0.85}
          inputMode={home.settings.input_mode}
          onEnded={onEnded}
        />
      )}
    </main>
  )
}
