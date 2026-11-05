/**
 * VoiceSession — 말하기 왕복 상태기계 (설계안 3절, D5/D6). 홍진성 담당.
 *
 *   WAITING ─[말하기]→ RECORDING(≤60초) ─[다 말했어요]→ TRANSCRIBING(/api/stt)
 *     → CONFIRMING(전사 표시, [맞아요]/[다시 말할게요], 신뢰도≥0.7 이면 3초 무조작 확정)
 *     → THINKING(/turns, 4초 안내·8초 음성 안내·15초 포기→/end ERROR) → SPEAKING(서버 mp3 또는 브라우저 TTS) → WAITING …
 *   8턴이면 서버가 ENDED 를 주고 onEnded 로 올린다. WAITING 에서 20초 무조작이면 event=NO_RESPONSE 를 보낸다 (서버가 3단계 처리).
 *   [다시 말할게요] 2회면 이 세션은 버튼만 (D5-a 를 화면 쪽에서도 지킴).
 * 서버 STT/TTS 가 mock 이면 전사는 고정 문장, 읽기는 speechSynthesis — 흐름 확인용.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { AiOut, SessionOut, SttOut, TurnIn } from '../../api/types'
import { playBase64, speak, startRecording, stopSpeaking, type Recorder } from '../../lib/audio'

type Phase = 'IDLE' | 'RECORDING' | 'TRANSCRIBING' | 'CONFIRMING' | 'THINKING' | 'SPEAKING' | 'WAITING' | 'ENDED'

const RECORD_MS = 60_000
const CONFIRM_MS = 3_000
const WAIT_MS = 20_000
const SLOW_MS = 4_000
const VERY_SLOW_MS = 8_000
const GIVE_UP_MS = 15_000
const LOW_CONF = 0.7
const MAX_RETRY = 2

const ERROR_AI: AiOut = {
  text: '지금은 대화를 이어가기 어려워요. 다음에 다시 이야기해요.',
  audio_b64: null,
  suggestions: [],
  choice_mode: 'TWO_BUTTONS',
  question_type: 'CLOSING',
}

type Props = {
  sessionId: string
  initial: SessionOut
  speed: number
  inputMode: 'VOICE' | 'BUTTON'
  onEnded: (result: SessionOut) => void
}

export default function VoiceSession({ sessionId, initial, speed, inputMode, onEnded }: Props) {
  const [phase, setPhase] = useState<Phase>('IDLE')
  const [ai, setAi] = useState<AiOut>(initial.ai)
  const [turnNo, setTurnNo] = useState(initial.turn_no)
  const [locked, setLocked] = useState(initial.input_locked || inputMode === 'BUTTON')
  const [heard, setHeard] = useState<SttOut>()
  const [note, setNote] = useState<string>()
  const recorder = useRef<Recorder | null>(null)
  const retries = useRef(0)
  const timers = useRef<number[]>([])
  const started = useRef(false)

  const later = (ms: number, fn: () => void) => {
    timers.current.push(window.setTimeout(fn, ms))
  }
  const clearTimers = () => {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }

  const endWith = useCallback(
    (result: SessionOut) => {
      clearTimers()
      stopSpeaking()
      setPhase('ENDED')
      onEnded(result)
    },
    [onEnded],
  )

  const sendTurn = useCallback(
    async (body: TurnIn) => {
      clearTimers()
      setNote(undefined)
      setHeard(undefined)
      setPhase('THINKING')
      later(SLOW_MS, () => setNote('조금만 기다려 주세요.'))
      later(VERY_SLOW_MS, () => speak('생각하는 중이에요. 잠깐만요.', speed)) // 키 없는 동안 mp3 대신 브라우저 TTS
      const ctrl = new AbortController()
      later(GIVE_UP_MS, () => ctrl.abort())
      try {
        const r = await api<SessionOut>(`/api/elder/sessions/${sessionId}/turns`, { body, signal: ctrl.signal })
        clearTimers()
        present(r)
      } catch (e) {
        clearTimers()
        if (e instanceof ApiError && e.code === 'INPUT_LOCKED') {
          setLocked(true)
          setNote('버튼으로 답해 주세요.')
          startWaiting()
          return
        }
        if (e instanceof ApiError && e.code === 'SESSION_ENDED') {
          endWith({ ...initial, ai: ERROR_AI, state: 'ENDED', end_reason: 'LIMIT' })
          return
        }
        // 15초 초과·네트워크 오류: 반드시 ERROR 로 끝낸다 (하루 3회면 서버가 가족에게 알림)
        await api(`/api/elder/sessions/${sessionId}/end`, { body: { reason: 'ERROR' } }).catch(() => {})
        endWith({ ...initial, ai: ERROR_AI, state: 'ENDED', end_reason: 'ERROR' })
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sessionId, speed, initial, endWith],
  )

  function startWaiting() {
    clearTimers()
    setPhase('WAITING')
    later(WAIT_MS, () => sendTurn({ input_type: 'BUTTON', event: 'NO_RESPONSE' }))
  }

  async function speakAi(a: AiOut) {
    setPhase('SPEAKING')
    if (a.audio_b64) {
      await playBase64(a.audio_b64).catch(() => speak(a.text, speed))
    } else {
      await speak(a.text, speed)
    }
  }

  async function present(r: SessionOut) {
    setAi(r.ai)
    setTurnNo(r.turn_no)
    if (r.input_locked) setLocked(true)
    if (r.state === 'ENDED') {
      setPhase('SPEAKING')
      await speakAi(r.ai)
      endWith(r)
      return
    }
    await speakAi(r.ai)
    startWaiting()
  }

  async function beginRecording() {
    clearTimers()
    stopSpeaking()
    try {
      recorder.current = await startRecording(RECORD_MS)
    } catch {
      setLocked(true)
      setNote('마이크를 쓸 수 없어요. 버튼으로 답해 주세요.')
      startWaiting()
      return
    }
    setPhase('RECORDING')
    later(RECORD_MS, finishRecording)
  }

  async function finishRecording() {
    clearTimers()
    const rec = recorder.current
    recorder.current = null
    if (!rec) return
    setPhase('TRANSCRIBING')
    const blob = await rec.stop()
    const form = new FormData()
    form.append('audio', blob, 'speech.webm')
    try {
      const r = await api<SttOut>('/api/stt', { form })
      setHeard(r)
      setPhase('CONFIRMING')
      if (r.confidence >= LOW_CONF) later(CONFIRM_MS, () => confirmHeard(r))
    } catch {
      setNote('잘 못 들었어요. 다시 말씀해 주세요.')
      startWaiting()
    }
  }

  function confirmHeard(r: SttOut) {
    // 신뢰도가 낮아도 어르신이 "맞아요" 했으면 retried=true 로 보내 서버가 다시 묻지 않게 한다
    sendTurn({ text: r.transcript, input_type: 'VOICE', stt_confidence: r.confidence, retried: r.confidence < LOW_CONF })
  }

  function retryHeard() {
    clearTimers()
    setHeard(undefined)
    retries.current += 1
    if (retries.current >= MAX_RETRY) {
      setLocked(true)
      setNote('이번에는 버튼으로 답해 주세요.')
      startWaiting()
      return
    }
    beginRecording()
  }

  async function stopSession() {
    clearTimers()
    stopSpeaking()
    if (recorder.current) await recorder.current.stop().catch(() => {})
    const r = await api<SessionOut>(`/api/elder/sessions/${sessionId}/end`, { body: { reason: 'USER_STOP' } }).catch(
      () => null,
    )
    endWith({
      ...initial,
      ai: { ...ERROR_AI, text: '그래요, 오늘은 여기까지 할게요. 고마워요.' },
      state: 'ENDED',
      end_reason: r?.end_reason ?? 'USER_STOP',
      turn_no: turnNo,
    })
  }

  useEffect(() => {
    if (started.current) return
    started.current = true
    present(initial)
    return () => {
      clearTimers()
      stopSpeaking()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const busy = phase === 'THINKING' || phase === 'SPEAKING' || phase === 'TRANSCRIBING'
  return (
    <section className="elder-stack" aria-live="polite">
      <p className="muted" style={{ margin: 0 }}>{turnNo} / 8</p>

      {phase === 'CONFIRMING' && heard ? (
        <>
          <p className="elder-text elder-text--lg">“{heard.transcript}”</p>
          {heard.confidence < LOW_CONF && <p className="elder-text">잘 들었는지 확인해 주세요.</p>}
          <button className="elder-btn" onClick={() => confirmHeard(heard)}>맞아요</button>
          <button className="elder-btn elder-btn--secondary" onClick={retryHeard}>다시 말할게요</button>
        </>
      ) : (
        <>
          <p className="elder-text elder-text--lg">{ai.text}</p>
          {note && <p className="elder-text">{note}</p>}
          {phase === 'RECORDING' && <p className="elder-text">듣고 있어요…</p>}
          {phase === 'THINKING' && <p className="elder-text">생각하고 있어요…</p>}

          {phase === 'WAITING' && ai.suggestions.length > 0 && (
            <div className="elder-stack">
              {ai.suggestions.map((s) => (
                <button
                  key={s}
                  className="elder-chip"
                  onClick={() => sendTurn({ text: s, input_type: ai.choice_mode === 'TWO_BUTTONS' ? 'BUTTON' : 'CHIP' })}
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {!locked && phase === 'WAITING' && (
            <button className="elder-btn" onClick={beginRecording}>말하기</button>
          )}
          {phase === 'RECORDING' && (
            <button className="elder-btn" onClick={finishRecording}>다 말했어요</button>
          )}
        </>
      )}

      <button className="elder-btn elder-btn--secondary" onClick={stopSession} disabled={busy}>
        그만할래요
      </button>
    </section>
  )
}
