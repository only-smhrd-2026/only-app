/**
 * ELDER_MEMORY_001 — 회상 대화 (사진 + VoiceSession 말풍선). ELDER_HOME_001(오늘의 한 장)·ELDER_ALBUM_001(사진첩)이 세션을 만들어 state 로 넘긴다.
 * 새로고침·뒤로 키 뒤 '이어서'로 state 가 없으면 서버에서 세션과 지난 말을 다시 읽는다 (30분 안 복귀, useElderSession, D52 ⑥).
 */
import { useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { SessionOut } from '../../api/types'
import VoiceSession from '../../components/VoiceSession/VoiceSession'
import { useElderSession } from '../../hooks/useElderSession'

export default function ELDER_MEMORY_001() {
  const { sessionId = '' } = useParams()
  const nav = useNavigate()
  const { session, home, photoUrl, history } = useElderSession(sessionId)
  const [ended, setEnded] = useState<SessionOut>()

  async function finish() {
    // 오류로 끝났으면 오늘의 한 장은 PENDING 그대로라(D27) '다 들었어요' 기록을 남기지 않는다. 사진첩 대화는 오늘의 한 장이 아니다
    if (session?.kind === 'MEMORY' && ended?.end_reason !== 'ERROR') {
      await api('/api/elder/picks/today/listened', { method: 'POST' }).catch(() => {})
    }
    nav('/elder', { replace: true })
  }

  if (!session || !home) return <main className="elder"><p className="elder-text">잠시만요…</p></main>
  // 이어서 하려고 열었는데 이미 끝난 대화(30분 지남·다른 곳에서 끝냄)면 질문을 다시 띄우지 않고 홈으로
  if (session.state === 'ENDED' && !ended) return <Navigate replace to="/elder" />
  // 앞 화면이 넘긴 사진 → 세션의 사진(새로고침) → 오늘의 한 장 (사진첩 대화는 오늘 사진으로 바꾸지 않는다)
  const shownPhoto = photoUrl ?? session.photo_url ?? (session.kind === 'MEMORY' ? home.today_pick?.photo_url : undefined)
  // 스크롤 없이 한 화면(D51 ⑤): 보이는 화면 높이(100dvh, 주소창 뺀 높이)에 맞추고 말풍선 칸만 움직인다
  return (
    <main className="elder" style={{ height: '100dvh', minHeight: 0, overflow: 'hidden', gap: 12 }}>
      {shownPhoto && (
        <img
          className="elder-photo vs-photo"
          src={shownPhoto}
          alt={session.kind === 'ALBUM' ? '사진첩 사진' : '오늘의 사진'}
        />
      )}
      <VoiceSession
        sessionId={sessionId}
        initial={session}
        history={history}
        speed={Number(home.settings.tts_speed) || 0.85}
        inputMode={home.settings.input_mode}
        onEnded={setEnded}
        endAction={ended ? { label: '다 들었어요', onClick: finish } : undefined}
      />
    </main>
  )
}
