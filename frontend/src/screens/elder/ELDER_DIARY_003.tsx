/**
 * ELDER_DIARY_003 — 일기 확인·그림일기 (FR-DI-004/005, D36·D51·D53). [네, 올려요]를 눌러야만 게시.
 * 사진 없는 일기는 서버가 그림까지 그린 뒤 초안을 주므로 여기서 그림을 보고 올린다. 그림이 실패하면 글만.
 * 같은 화면에서는 같은 request_id → 응답을 못 받아 다시 눌러도 한 번만 올라간다. [다시 말할래요]는 새 대화(사진 유지).
 * 그림·누르면 다시 읽는 글 상자·기분·하단 버튼을 공통 클래스로 한 화면에 배치한다. 기다림·실패 안내도 읽는다.
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { MOOD_LABEL, type DiaryOut, type DraftOut, type SessionOut } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import MoodIcon from '../../components/MoodIcon'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { playBase64, say, speak, stopSpeaking } from '../../lib/audio'

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
  const [posted, setPosted] = useState(false) // 이미 올린 대화 (새로고침 등) → [홈으로]만
  const [leaving, setLeaving] = useState(false) // [다시 말할래요] 처리 중 → 다른 버튼 막기
  const [attempt, setAttempt] = useState(0)
  const [saying, setSaying] = useState(false)
  const sayingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => () => clearTimeout(sayingTimer.current), [])

  function readDraft() {
    if (!draft) return
    void say(readAloud(draft), speed, draft.audio_b64)
    setSaying(true)
    clearTimeout(sayingTimer.current)
    sayingTimer.current = setTimeout(() => setSaying(false), 1400)
  }

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
      if (!live.current) return // 기다리다 [홈으로]·뒤로 가기로 떠났으면 끌고 가지 않는다
      nav(`/elder/diary/${againId}`, { replace: true, state: { session: s, home, photoUrl } })
    } catch (e) {
      setNote((e as Error).message)
      setLeaving(false)
    }
  }

  const goHome = () => nav('/elder', { replace: true })

  if (phase === 'WRITING')
    return (
      <main className="elder elder--fit">
        <p className="elder-text elder-text--lg">일기를 쓰고 있어요.</p>
        <p className="elder-text">조금만 기다려 주세요.</p>
      </main>
    )

  if (phase === 'POSTED')
    return (
      <main className="elder elder--fit">
        <p className="elder-text elder-text--lg">가족들한테 보냈어요.</p>
        <button className="elder-btn" onClick={goHome}>홈으로</button>
      </main>
    )

  if (phase === 'FAILED' || !draft)
    return (
      <main className="elder elder--fit">
        <p className="elder-text">{note}</p>
        {retryable && <button className="elder-btn" onClick={retry} disabled={leaving}>다시 해 보기</button>}
        {!posted && (
          <button className="elder-btn elder-btn--secondary" onClick={again} disabled={leaving}>
            {leaving ? '잠시만요…' : '다시 말할래요'}
          </button>
        )}
        <button className="elder-btn elder-btn--secondary" onClick={goHome}>홈으로</button>
      </main>
    )

  return (
    <main className="elder elder--fit">
      {draft.illustration_type === 'PHOTO' && draft.illustration_url && (
        <ElderPhoto src={draft.illustration_url} alt="오늘 찍은 사진" />
      )}
      {draft.illustration_type === 'AI_DRAWING' && draft.illustration_b64 && (
        <div className="elder-photo-box elder-photo-box--grow">
          <img
            style={{ objectFit: 'contain' }}
            src={`data:image/jpeg;base64,${draft.illustration_b64}`}
            alt="그림일기 그림"
          />
          <span className="elder-tag">그림일기 · AI 그림</span>
        </div>
      )}
      <button type="button" className={`elder-paper${saying ? ' elder-saying' : ''}`} onClick={readDraft}>
        <span>{draft.body}</span>
        <svg className="elder-spk" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 9.5v5h3.2L12 18.5v-13L7.2 9.5z" />
          <path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.3 6.3a8 8 0 0 1 0 11.4" />
        </svg>
      </button>
      <div className="elder-mood">
        <MoodIcon mood={draft.mood} />
        오늘 기분 · {MOOD_LABEL[draft.mood]}
      </div>
      {note && <p className="elder-text" role="alert">{note}</p>}
      <div className="elder-two elder-bottom">
        <button className="elder-btn" onClick={post} disabled={phase === 'POSTING' || leaving}>
          {phase === 'POSTING' ? '보내는 중…' : '네, 올려요'}
        </button>
        <button className="elder-btn elder-btn--secondary" onClick={again} disabled={phase === 'POSTING' || leaving}>
          {leaving ? '잠시만요…' : '다시 말할래요'}
        </button>
      </div>
    </main>
  )
}
