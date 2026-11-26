/**
 * ELDER_MEMORY_001 — 회상 대화 (사진 + 지금 질문 카드, VoiceSession 11/23 모양). ELDER_HOME_001(오늘의 한 장)·ELDER_ALBUM_001(사진첩)이
 * 세션을 만들어 state 로 넘긴다. 새로고침·뒤로 키 뒤 '이어서'로 state 가 없으면 서버에서 세션을 다시 읽는다 (30분 안 복귀, D52 ⑥).
 * 끝나면 [다 들었어요](위로 중이면 [조금 쉴게요]) · [더 이야기할래요] — 끝난 그 대화를 다시 열어 질문 3개를 더 한다(D110,
 * 11/26 사용자 '끝난 시점에서 이어서'). AI 는 앞 대화를 다 본 채 잇는다. 한 대화에 2번까지(서버 MORE_ROUNDS) — 넘으면 서버 문장을 읽어 준다.
 */
import { useState } from 'react'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { SessionGetOut, SessionOut, TurnOut } from '../../api/types'
import VoiceSession from '../../components/VoiceSession/VoiceSession'
import { useElderSession } from '../../hooks/useElderSession'
import { say } from '../../lib/audio'

const MORE_ROUNDS = 2 // 서버 config.MORE_ROUNDS — 다 쓰면 버튼을 거둔다(새로고침 뒤에는 서버가 MORE_LIMIT 로 막는다)

/** 다른 대화로 오면 화면을 새로 만든다 — 같은 경로라 그대로 두면 앞 대화의 상태가 남는다 */
export default function ELDER_MEMORY_001() {
  const { sessionId = '' } = useParams()
  return <Talk key={sessionId} sessionId={sessionId} />
}

function Talk({ sessionId }: { sessionId: string }) {
  const nav = useNavigate()
  const { session, home, photoUrl, history } = useElderSession(sessionId)
  const [ended, setEnded] = useState<SessionOut>()
  const [noMore, setNoMore] = useState(false)
  const [busy, setBusy] = useState(false)
  // [더 이야기할래요]로 다시 연 대화 · 몇 번째인지 · 지난 말(말풍선 그대로 두고 '아까 하던 이야기를 이어서 할게요'로 시작)
  const [again, setAgain] = useState<{ s: SessionOut; n: number; turns?: TurnOut[] }>()

  async function listened() {
    // 오류로 끝났으면 오늘의 한 장은 PENDING 그대로라(D27) '다 들었어요' 기록을 남기지 않는다. 사진첩 대화는 오늘의 한 장이 아니다
    if (session?.kind === 'MEMORY' && ended?.end_reason !== 'ERROR') {
      // 대화 번호를 보내면 서버가 그 대화의 사진에 기록한다 — 자정을 넘겨 끝나도 새 날 사진에 남지 않게 (D65)
      await api('/api/elder/picks/today/listened', { body: { session_id: sessionId } }).catch(() => {})
    }
  }

  async function finish() {
    await listened()
    nav('/elder', { replace: true })
  }

  if (!session || !home) return <main className="elder"><p className="elder-text">잠시만요…</p></main>
  const current = again?.s ?? session
  // 이어서 하려고 열었는데 이미 끝난 대화(30분 지남·다른 곳에서 끝냄)면 질문을 다시 띄우지 않고 홈으로
  if (current.state === 'ENDED' && !ended) return <Navigate replace to="/elder" />
  // 앞 화면이 넘긴 사진 → 세션의 사진(새로고침) → 오늘의 한 장 (사진첩 대화는 오늘 사진으로 바꾸지 않는다)
  const shownPhoto = photoUrl ?? session.photo_url ?? (session.kind === 'MEMORY' ? home.today_pick?.photo_url : undefined)
  // 그만할래·무응답·오류로 끝난 대화에는 권하지 않는다
  const canMore =
    !noMore && (again?.n ?? 0) < MORE_ROUNDS && (ended?.end_reason === 'COMPLETED' || ended?.end_reason === 'LIMIT')

  async function more() {
    if (busy) return
    setBusy(true)
    await listened()
    try {
      // 같은 대화를 다시 연다 — 서버가 앞 대화를 다 본 AI 의 다음 질문을 돌려준다
      const s = await api<SessionOut>(`/api/elder/sessions/${sessionId}/more`, { method: 'POST' })
      const got = await api<SessionGetOut>(`/api/elder/sessions/${sessionId}`).catch(() => undefined)
      setEnded(undefined)
      setAgain({ s, n: (again?.n ?? 0) + 1, turns: got?.turns })
      setBusy(false)
    } catch (e) {
      setBusy(false)
      setNoMore(true) // 2번 다 씀·30분 지남 등 — 버튼을 거두고 까닭을 읽어 준다
      void say(e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다음에 또 이야기해요.', Number(home?.settings.tts_speed) || 0.9)
    }
  }

  return (
    <main className="elder elder--fit">
      <VoiceSession
        key={again?.n ?? 0}
        sessionId={sessionId}
        initial={current}
        history={again ? again.turns : history}
        speed={Number(home.settings.tts_speed) || 0.9}
        inputMode={home.settings.input_mode}
        who={home.elder_honorific}
        title="회상 대화"
        photo={shownPhoto ? { src: shownPhoto, alt: session.kind === 'ALBUM' ? '사진첩 사진' : '오늘의 사진' } : undefined}
        onEnded={setEnded}
        onDone={() => void finish()}
        onMore={canMore ? () => void more() : undefined}
      />
    </main>
  )
}
