/**
 * ELDER_MEMORY_001 — 회상 대화 (사진 + 지금 질문 카드, VoiceSession 11/23 모양). ELDER_HOME_001(오늘의 한 장)·ELDER_ALBUM_001(사진첩)이
 * 세션을 만들어 state 로 넘긴다. 새로고침·뒤로 키 뒤 '이어서'로 state 가 없으면 서버에서 세션을 다시 읽는다 (30분 안 복귀, D52 ⑥).
 * 끝나면 [다 들었어요](위로 중이면 [조금 쉴게요]) · [더 이야기할래요] — 같은 사진으로 사진첩 대화를 새로 연다(11/23 시안 talk-more).
 * 서버에 '대화 늘리기'가 없어서 새 대화로 잇는다: 사진첩 대화 하루 3번(ALBUM_PER_DAY)에 들어가고, 다 쓰면 서버 문장을 읽어 준다.
 */
import { useState } from 'react'
import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { SessionOut } from '../../api/types'
import VoiceSession from '../../components/VoiceSession/VoiceSession'
import { useElderSession } from '../../hooks/useElderSession'
import { say } from '../../lib/audio'

/** 대화가 바뀌면([더 이야기할래요]) 화면을 새로 만든다 — 같은 경로라 그대로 두면 앞 대화의 상태가 남는다 */
export default function ELDER_MEMORY_001() {
  const { sessionId = '' } = useParams()
  return <Talk key={sessionId} sessionId={sessionId} />
}

function Talk({ sessionId }: { sessionId: string }) {
  const nav = useNavigate()
  const loc = useLocation()
  // 사진첩이 넘긴 사진 번호(있으면) — useElderSession 이 주소의 state 를 지우기 전에 받아 둔다
  const [statePhotoId] = useState<number | undefined>(() => (loc.state as { photoId?: number } | null)?.photoId)
  const { session, home, photoUrl, history } = useElderSession(sessionId)
  const [ended, setEnded] = useState<SessionOut>()
  const [noMore, setNoMore] = useState(false)
  const [busy, setBusy] = useState(false)

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
  // 이어서 하려고 열었는데 이미 끝난 대화(30분 지남·다른 곳에서 끝냄)면 질문을 다시 띄우지 않고 홈으로
  if (session.state === 'ENDED' && !ended) return <Navigate replace to="/elder" />
  // 앞 화면이 넘긴 사진 → 세션의 사진(새로고침) → 오늘의 한 장 (사진첩 대화는 오늘 사진으로 바꾸지 않는다)
  const shownPhoto = photoUrl ?? session.photo_url ?? (session.kind === 'MEMORY' ? home.today_pick?.photo_url : undefined)
  const photoId = statePhotoId ?? (session.kind === 'MEMORY' ? home.today_pick?.photo_id : undefined)
  // 그만할래·무응답·오류로 끝난 대화에는 권하지 않는다
  const canMore = !noMore && photoId !== undefined && (ended?.end_reason === 'COMPLETED' || ended?.end_reason === 'LIMIT')

  async function more() {
    if (busy || photoId === undefined) return
    setBusy(true)
    await listened()
    const id = crypto.randomUUID()
    try {
      const s = await api<SessionOut>('/api/elder/sessions', { body: { session_id: id, kind: 'ALBUM', photo_id: photoId } })
      nav(`/elder/memory/${id}`, { replace: true, state: { session: s, photoUrl: shownPhoto, home, photoId } })
    } catch (e) {
      setBusy(false)
      setNoMore(true) // 하루 상한 등 — 버튼을 거두고 까닭을 읽어 준다
      void say(e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다음에 또 이야기해요.', Number(home?.settings.tts_speed) || 0.9)
    }
  }

  return (
    <main className="elder elder--fit">
      <VoiceSession
        sessionId={sessionId}
        initial={session}
        history={history}
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
