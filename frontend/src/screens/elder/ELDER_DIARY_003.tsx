/**
 * ELDER_DIARY_003 — 일기 확인 (FR-DI-004/005, D36). 초안을 보여 주고 읽어 준 뒤 [네, 올려요]를 눌러야만 게시.
 * 사진 없는 일기는 서버가 그림까지 그린 뒤 초안을 주므로 여기서 그림을 보고 올린다. 그림이 실패하면 글만.
 * 같은 화면에서는 같은 request_id → 응답을 못 받아 다시 눌러도 한 번만 올라간다. [다시 말할래요]는 새 대화(사진 유지).
 * 말로 하는 "네"는 받지 않는다(마이크 없음). 기다림·실패 안내도 소리로 읽는다. 디자인 없음 (김승희 교체).
 */
import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { MOOD_LABEL, type DiaryOut, type DraftOut, type SessionOut } from '../../api/types'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { playBase64, speak, stopSpeaking } from '../../lib/audio'

// 초안 = LLM(시도당 15초 × 최대 2번) + 그림(제공자 상한 20초) + TTS. 넘으면 [다시 해 보기] (서버는 같은 초안을 준다)
const DRAFT_MS = 60_000
const SLOW_MS = 8_000 // 이만큼 기다리면 소리로 한 번 안내 (VoiceSession 과 같은 규칙)
const FINAL = ['DIARY_NOT_READY', 'DIARY_POSTED', 'SESSION_NOT_FOUND'] // 다시 해 봐도 안 되는 것
// 서버 diaries._speech 와 같은 문장 (서버 TTS 음성이 없을 때 브라우저가 읽는다)
const readAloud = (d: DraftOut) => `${d.body} 오늘 기분은 ${MOOD_LABEL[d.mood]}. 이대로 올릴까요?`

type Phase = 'WRITING' | 'READY' | 'POSTING' | 'POSTED' | 'FAILED'

export default function ELDER_DIARY_003() {
  const { sessionId = '' } = useParams()
  const nav = useNavigate()
  const loc = useLocation()
  const live = useLive()
  const [home] = useState((loc.state as ElderNavState | null)?.home)
  const speed = Number(home?.settings.tts_speed) || 0.85
  const [requestId] = useState(() => crypto.randomUUID()) // '네, 올려요' 멱등 키
  const [againId] = useState(() => crypto.randomUUID()) // '다시 말할래요' 새 대화 (두 번 눌러도 하나)
  const [draft, setDraft] = useState<DraftOut>()
  const [phase, setPhase] = useState<Phase>('WRITING')
  const [note, setNote] = useState<string>()
  const [retryable, setRetryable] = useState(false)
  const [posted, setPosted] = useState(false) // 이미 올린 대화 (새로고침 등) → [처음으로]만
  const [leaving, setLeaving] = useState(false) // [다시 말할래요] 처리 중 → 다른 버튼 막기
  const [attempt, setAttempt] = useState(0)

  // 초안 받기. 새로고침·[다시 해 보기]에도 서버가 30분 동안 같은 초안을 준다 (그림을 두 번 그리지 않음)
  useEffect(() => {
    let alive = true
    const ctrl = new AbortController()
    const timer = window.setTimeout(() => ctrl.abort(), DRAFT_MS)
    api<DraftOut>(`/api/elder/sessions/${sessionId}/draft`, { method: 'POST', signal: ctrl.signal })
      .then((d) => {
        if (!alive) return
        setDraft(d)
        setPhase('READY')
      })
      .catch((e) => {
        if (!alive) return
        const final = e instanceof ApiError && FINAL.includes(e.code)
        setRetryable(!final)
        setPosted(e instanceof ApiError && e.code === 'DIARY_POSTED')
        setNote(final ? (e as ApiError).message : '일기를 쓰지 못했어요. 다시 해 볼까요?')
        setPhase('FAILED')
      })
      .finally(() => window.clearTimeout(timer))
    return () => {
      alive = false
      ctrl.abort()
      window.clearTimeout(timer)
    }
  }, [sessionId, attempt])

  // 오래 걸리면 소리로 한 번 안내. 화면이 바뀌면 끊는다
  useEffect(() => {
    if (phase !== 'WRITING') return
    const t = window.setTimeout(() => speak('일기를 쓰고 있어요. 조금만 기다려 주세요.', speed), SLOW_MS)
    return () => {
      window.clearTimeout(t)
      stopSpeaking()
    }
  }, [phase, speed])

  // 본문·기분을 읽어 주고 "이대로 올릴까요?" (서버 TTS 음성이 있으면 그것, 없으면 브라우저 TTS)
  useEffect(() => {
    if (!draft) return
    if (draft.audio_b64) playBase64(draft.audio_b64, speed).catch(() => speak(readAloud(draft), speed))
    else speak(readAloud(draft), speed)
    return () => stopSpeaking()
  }, [draft, speed])

  // 실패 안내도 읽어 준다 (성공 "가족들한테 보냈어요"처럼)
  useEffect(() => {
    if (!note) return
    stopSpeaking() // 아직 읽던 본문과 겹치지 않게
    speak(note, speed)
  }, [note, speed])

  function retry() {
    setPhase('WRITING')
    setNote(undefined)
    setAttempt((a) => a + 1)
  }

  async function post() {
    if (!draft || phase === 'POSTING' || leaving) return
    setPhase('POSTING')
    setNote(undefined)
    try {
      await api<DiaryOut>('/api/elder/diaries', { body: { request_id: requestId, session_id: sessionId } })
    } catch (e) {
      if (e instanceof ApiError && e.code === 'DRAFT_EXPIRED') {
        // 30분이 지나 초안이 사라짐 → [다시 해 보기]가 같은 대화로 초안을 다시 쓴다
        setRetryable(true)
        setNote('시간이 지나서 일기를 다시 써야 해요. 다시 해 볼까요?')
        setPhase('FAILED')
      } else {
        setNote('보내지 못했어요. 다시 눌러 주세요.') // 같은 request_id 라 다시 눌러도 한 번만 올라간다
        setPhase('READY')
      }
      return
    }
    stopSpeaking()
    setPhase('POSTED')
    if (live.current) speak('가족들한테 보냈어요.', speed)
  }

  async function again() {
    if (leaving || phase === 'POSTING') return
    setLeaving(true)
    stopSpeaking()
    const photoUrl = draft?.illustration_type === 'PHOTO' ? draft.illustration_url : undefined
    try {
      const s = await api<SessionOut>('/api/elder/sessions', {
        body: { session_id: againId, kind: 'DIARY', photo_id: draft?.photo_id ?? undefined },
      })
      if (!live.current) return // 기다리다 [처음으로]·뒤로 가기로 떠났으면 끌고 가지 않는다
      nav(`/elder/diary/${againId}`, { replace: true, state: { session: s, home, photoUrl } })
    } catch (e) {
      setNote((e as Error).message)
      setLeaving(false)
    }
  }

  const goHome = () => nav('/elder', { replace: true })

  if (phase === 'WRITING')
    return (
      <main className="elder">
        <p className="elder-text elder-text--lg">일기를 쓰고 있어요.</p>
        <p className="elder-text">조금만 기다려 주세요.</p>
      </main>
    )

  if (phase === 'POSTED')
    return (
      <main className="elder">
        <p className="elder-text elder-text--lg">가족들한테 보냈어요.</p>
        <button className="elder-btn" onClick={goHome}>처음으로</button>
      </main>
    )

  if (phase === 'FAILED' || !draft)
    return (
      <main className="elder">
        <p className="elder-text">{note}</p>
        {retryable && <button className="elder-btn" onClick={retry} disabled={leaving}>다시 해 보기</button>}
        {!posted && (
          <button className="elder-btn elder-btn--secondary" onClick={again} disabled={leaving}>
            {leaving ? '잠시만요…' : '다시 말할래요'}
          </button>
        )}
        <button className="elder-btn elder-btn--secondary" onClick={goHome}>처음으로</button>
      </main>
    )

  return (
    <main className="elder">
      {draft.illustration_type === 'PHOTO' && draft.illustration_url && (
        <img className="elder-photo" src={draft.illustration_url} alt="오늘 찍은 사진" />
      )}
      {draft.illustration_type === 'AI_DRAWING' && draft.illustration_b64 && (
        <figure style={{ margin: 0 }}>
          <img
            className="elder-photo"
            style={{ objectFit: 'contain' }}
            src={`data:image/jpeg;base64,${draft.illustration_b64}`}
            alt="그림일기 그림"
          />
          <figcaption className="elder-text">그림일기 · AI 그림</figcaption>
        </figure>
      )}
      <p className="elder-text">{draft.body}</p>
      <p className="elder-text">오늘 기분: {MOOD_LABEL[draft.mood]}</p>
      <p className="elder-text elder-text--lg">이대로 올릴까요?</p>
      {note && <p className="elder-text">{note}</p>}
      <button className="elder-btn" onClick={post} disabled={phase === 'POSTING' || leaving}>
        {phase === 'POSTING' ? '보내는 중…' : '네, 올려요'}
      </button>
      <button className="elder-btn elder-btn--secondary" onClick={again} disabled={phase === 'POSTING' || leaving}>
        {leaving ? '잠시만요…' : '다시 말할래요'}
      </button>
    </main>
  )
}
