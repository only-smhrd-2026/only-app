/**
 * ELDER_DIARY_003 — 일기 확인·그림일기 (FR-DI-004/005, D36·D53 — 11/23 시안 e-diary-check).
 * '가족에게 보낼까요?' → [네, 보내요]를 눌러야만 게시 → '가족에게 보냈어요'. 보낸 뒤 뒤로 키는 홈(이 주소를 '보냄'으로 바꿔 둔다 —
 * 대화는 앞 화면들이 replace 로 와서 기록에 남지 않는다). 사진 없는 일기는 서버가 그림까지 그린 뒤 초안을 준다. 그림이 실패하면 기분 얼굴.
 * 같은 화면에서는 같은 request_id → 응답을 못 받아 다시 눌러도 한 번만 올라간다. [다시 말할게요]는 새 대화(사진 유지).
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { MOOD_LABEL, type DiaryOut, type DraftOut, type SessionOut } from '../../api/types'
import ElderPhoto from '../../components/ElderPhoto'
import { Dots, IC } from '../../components/ElderUi'
import MoodIcon from '../../components/MoodIcon'
import Sim from '../../components/Sim'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { playBase64, say, speak, stopSpeaking } from '../../lib/audio'
import './ELDER_DIARY_003.css'

// 긴 일기는 글자 크기를 유지하고 가로 쪽으로 나눈다. 지난 일기 상세도 같은 읽기 영역을 쓴다.
export function DiaryPaper({ body, onRead, saying = false }: { body: string; onRead: () => void; saying?: boolean }) {
  const text = useRef<HTMLSpanElement>(null)
  const [page, setPage] = useState(0)
  const [count, setCount] = useState(1)

  useEffect(() => {
    const element = text.current
    if (!element) return
    const measure = () => {
      if (!element.clientWidth) return
      const pages = Math.max(1, Math.round(element.scrollWidth / element.clientWidth))
      setCount(pages)
      setPage((current) => Math.min(current, pages - 1))
    }
    const size = new ResizeObserver(measure)
    size.observe(element)
    const font = new MutationObserver(measure)
    font.observe(document.documentElement, { attributes: true, attributeFilter: ['data-font'] })
    void document.fonts.ready.then(measure)
    return () => {
      size.disconnect()
      font.disconnect()
    }
  }, [body])

  return (
    <div className="diary-reading">
      <button type="button" className={`elder-paper diary-paper${saying ? ' elder-saying' : ''}`} onClick={onRead}>
        <span className="diary-paper-window">
          <span ref={text} className="diary-paper-pages" style={{ transform: `translateX(-${page * 100}%)` }}>{body}</span>
        </span>
        <span className="elder-spk-dot" aria-hidden="true">{IC.spk}</span>
      </button>
      {count > 1 && (
        <div className="diary-pages" aria-label="일기 글 넘기기">
          <button type="button" className="elder-chip" disabled={page === 0} onClick={() => setPage((current) => current - 1)}>이전 글</button>
          <span role="status" aria-label={`전체 ${count}쪽 중 ${page + 1}쪽`}>{page + 1} / {count}</span>
          <button type="button" className="elder-chip" disabled={page === count - 1} onClick={() => setPage((current) => current + 1)}>다음 글</button>
        </div>
      )}
    </div>
  )
}

// 초안 = LLM(시도당 15초 × 최대 2번) + 그림(제공자 상한 20초) + TTS. 넘으면 [다시 해 보기] (서버는 같은 초안을 준다)
const DRAFT_MS = 60_000
const SLOW_MS = 8_000 // 이만큼 기다리면 소리로 한 번 안내 (VoiceSession 과 같은 규칙)
const FINAL = ['DIARY_NOT_READY', 'DIARY_POSTED', 'SESSION_NOT_FOUND'] // 다시 해 봐도 안 되는 것
// 서버 TTS 음성(audio_b64)이 없을 때 읽는 문장 — 서버 diaries._speech 와 같게 둔다
const readAloud = (d: DraftOut) => `${d.body} 오늘 기분은 ${MOOD_LABEL[d.mood]}. 가족에게 보낼까요?`
const SENT = '가족에게 보냈어요.'

type Phase = 'WRITING' | 'READY' | 'POSTING' | 'POSTED' | 'FAILED'

export default function ELDER_DIARY_003() {
  const { sessionId = '' } = useParams()
  const nav = useNavigate()
  const loc = useLocation()
  const live = useLive()
  const [home] = useState((loc.state as ElderNavState | null)?.home)
  const sentBefore = !!(loc.state as { posted?: boolean } | null)?.posted // 보낸 뒤 새로고침
  const speed = Number(home?.settings.tts_speed) || 0.9
  const [requestId] = useState(() => crypto.randomUUID()) // '네, 보내요' 멱등 키
  const [againId] = useState(() => crypto.randomUUID()) // '다시 말할게요' 새 대화 (두 번 눌러도 하나)
  const [draft, setDraft] = useState<DraftOut>()
  const [phase, setPhase] = useState<Phase>(sentBefore ? 'POSTED' : 'WRITING')
  const [note, setNote] = useState<string>()
  const [retryable, setRetryable] = useState(false)
  const [posted, setPosted] = useState(false) // 이미 올린 대화 (새로고침 등) → [홈으로]만
  const [leaving, setLeaving] = useState(false) // [다시 말할게요] 처리 중 → 다른 버튼 막기
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
    if (sentBefore) return
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
  }, [sessionId, attempt, sentBefore])

  // 쓰는 동안 안내를 읽고, 오래 걸리면 한 번 더. 화면이 바뀌면 끊는다
  useEffect(() => {
    if (phase !== 'WRITING') return
    void speak('일기를 쓰고 있어요. 조금만 기다려 주세요.', speed)
    const t = window.setTimeout(() => speak('조금만 기다려 주세요.', speed), SLOW_MS)
    return () => {
      window.clearTimeout(t)
      stopSpeaking()
    }
  }, [phase, speed])

  // 본문·기분을 읽어 주고 "가족에게 보낼까요?" (서버 TTS 음성이 있으면 그것, 없으면 고른 목소리)
  useEffect(() => {
    if (!draft) return
    if (draft.audio_b64) playBase64(draft.audio_b64, speed).catch(() => speak(readAloud(draft), speed))
    else speak(readAloud(draft), speed)
    return () => stopSpeaking()
  }, [draft, speed])

  // 실패 안내도 읽어 준다
  useEffect(() => {
    if (!note) return
    stopSpeaking() // 아직 읽던 본문과 겹치지 않게
    speak(note, speed)
  }, [note, speed])

  useEffect(() => {
    if (phase !== 'POSTED') return
    void speak(SENT, speed)
    return () => stopSpeaking()
  }, [phase, speed])

  function retry() {
    setPhase('WRITING')
    setNote(undefined)
    setAttempt((a) => a + 1)
  }

  async function post() {
    if (!draft || phase === 'POSTING' || leaving) return
    stopSpeaking()
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
    if (!live.current) return
    setPhase('POSTED')
    // 이 주소를 '보냄'으로 바꿔 둔다 — 새로고침해도 보낸 화면, 뒤로 키는 그 앞(홈)으로. 같은 일기를 또 쓰지 않게
    nav(loc.pathname, { replace: true, state: { home, posted: true } })
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
      if (!live.current) return // 기다리다 뒤로 가기로 떠났으면 끌고 가지 않는다
      nav(`/elder/diary/${againId}`, { replace: true, state: { session: s, home, photoUrl } })
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 눌러 주세요.')
      setLeaving(false)
    }
  }

  const goHome = () => nav('/elder', { replace: true })

  if (phase === 'WRITING')
    return (
      <main className="elder elder--fit elder-center">
        <div className="elder-halo elder-wait"><Sim face="smile" size={150} className="elder-sim" /></div>
        <h1>일기를 쓰고 있어요<Dots /></h1>
        <p className="elder-sub">조금만 기다려 주세요.</p>
      </main>
    )

  if (phase === 'POSTED')
    return (
      <main className="elder elder--fit">
        <div className="elder-grow elder-center">
          <div className="elder-halo elder-pop"><Sim face="joy" size={170} className="elder-sim" /></div>
          <h1>가족에게 보냈어요</h1>
          <p className="elder-sub">가족이 읽으면 알려 드릴게요.</p>
        </div>
        <button type="button" className="elder-btn" onClick={goHome}>홈으로</button>
      </main>
    )

  if (phase === 'FAILED' || !draft)
    return (
      <main className="elder elder--fit">
        <div className="elder-grow elder-center">
          <Sim face="ask" size={150} className="elder-sim" />
          <p className="elder-text" role="alert">{note}</p>
        </div>
        {retryable && <button type="button" className="elder-btn" onClick={retry} disabled={leaving}>다시 해 보기</button>}
        {!posted && (
          <button type="button" className="elder-btn elder-btn--secondary" onClick={again} disabled={leaving}>
            {leaving ? '잠시만요…' : '다시 말할게요'}
          </button>
        )}
        <button type="button" className="elder-btn elder-btn--secondary" onClick={goHome}>홈으로</button>
      </main>
    )

  const busy = phase === 'POSTING' || leaving
  return (
    <main className="elder elder--fit diary-confirm">
      <h1>가족에게 보낼까요?</h1>
      {draft.illustration_type === 'PHOTO' && draft.illustration_url && (
        <ElderPhoto src={draft.illustration_url} alt="오늘 찍은 사진" />
      )}
      {draft.illustration_type === 'AI_DRAWING' && draft.illustration_b64 && (
        <ElderPhoto src={`data:image/jpeg;base64,${draft.illustration_b64}`} alt="그림일기 그림" />
      )}
      {draft.illustration_type === 'AI_DRAWING' && draft.illustration_b64 && <span className="elder-tag">{IC.pen}그림일기 · AI 그림</span>}
      {(draft.illustration_type === 'NONE' || (draft.illustration_type === 'AI_DRAWING' && !draft.illustration_b64)) && (
        <div className="elder-photo-box elder-photo-box--grow elder-mood-pic">
          <MoodIcon mood={draft.mood} />
        </div>
      )}
      <DiaryPaper key={draft.body} body={draft.body} onRead={readDraft} saying={saying} />
      <p className="elder-moodline">
        <MoodIcon mood={draft.mood} />
        오늘 기분 · {MOOD_LABEL[draft.mood]}
      </p>
      {note && <p className="elder-text" role="alert">{note}</p>}
      <div className="elder-two">
        <button type="button" className="elder-btn" onClick={post} disabled={busy}>
          {phase === 'POSTING' ? '보내는 중…' : '네, 보내요'}
        </button>
        <button type="button" className="elder-btn elder-btn--secondary" onClick={again} disabled={busy}>
          {leaving ? '잠시만요…' : <>다시<wbr /> 말할게요</>}
        </button>
      </div>
    </main>
  )
}
