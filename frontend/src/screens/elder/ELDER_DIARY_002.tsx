/**
 * ELDER_DIARY_002 — 일기 대화. 질문 3개(뭐 하셨어요 → 누구랑 → 기분은, 기분은 칩 4개 좋았어요·그저 그랬어요·속상했어요·쓸쓸했어요, D75)를 VoiceSession 말풍선으로 (D53 ①).
 * 다 답하면(COMPLETED·5분 LIMIT) ELDER_DIARY_003 확인으로. "그만할래"·무응답·오류로 끝나면 저장하지 않는다 (FR-DI-003).
 */
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import type { EndReason, SessionOut } from '../../api/types'
import VoiceSession from '../../components/VoiceSession/VoiceSession'
import { useElderSession } from '../../hooks/useElderSession'

const DIARY_TURNS = 5 // 서버 config.DIARY_TURNS (D97)
const saved = (r: EndReason | null) => r === 'COMPLETED' || r === 'LIMIT' // 서버 sessions.DIARY_SAVED

export default function ELDER_DIARY_002() {
  const { sessionId = '' } = useParams()
  const nav = useNavigate()
  const { session, home, photoUrl, history } = useElderSession(sessionId)
  // 남길 것은 확인 화면으로 바로. 나머지(그만할래·무응답·오류)는 마무리 인사 뒤 [다 들었어요]로 홈
  function onEnded(r: SessionOut) {
    if (saved(r.end_reason)) nav(`/elder/diary/${sessionId}/confirm`, { replace: true, state: { home } })
  }

  if (!session || !home) return <main className="elder"><p className="elder-text">잠시만요…</p></main>
  // 새로고침·다시 열기로 이미 끝난 대화를 받으면 질문을 다시 띄우지 않는다:
  // 일기로 남길 것은 확인 화면, 나머지(그만할래·오류·30분 지남)는 홈
  if (session.state === 'ENDED')
    return <Navigate replace to={saved(session.end_reason) ? `/elder/diary/${sessionId}/confirm` : '/elder'} state={{ home }} />
  const shownPhoto = photoUrl ?? session.photo_url ?? undefined // 이어서 열면 넘겨받은 사진이 없어 세션의 사진
  // 회상 대화와 같은 모양(D53 ①, 11/23 VoiceSession 이 사진·질문 카드를 함께 그린다). 스크롤 없음
  return (
    <main className="elder elder--fit">
      <VoiceSession
        sessionId={sessionId}
        initial={session}
        history={history}
        maxTurns={DIARY_TURNS}
        speed={Number(home.settings.tts_speed) || 0.9}
        inputMode={home.settings.input_mode}
        who={home.elder_honorific}
        title="일기 대화"
        photo={shownPhoto ? { src: shownPhoto, alt: '오늘 찍은 사진' } : undefined}
        onEnded={onEnded}
        onDone={() => nav('/elder', { replace: true })}
      />
    </main>
  )
}
