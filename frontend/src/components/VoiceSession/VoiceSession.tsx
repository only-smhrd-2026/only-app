/**
 * VoiceSession — 말하기 왕복 상태기계 (설계안 3절, D5/D6). 홍진성 담당.
 *
 *   WAITING ─[말하기]→ (IDLE: 마이크 준비) → RECORDING(≤60초) ─[다 말했어요]→ TRANSCRIBING(/api/stt)
 *     → CONFIRMING(전사 표시, [맞아요]/[다시 말할게요])
 *         신뢰도 ≥0.7: 3초 무조작이면 확정 / <0.7: 어르신이 [맞아요]를 눌러야 보냄(20초 무조작이면 무응답)
 *     → THINKING(/turns, 4초 안내·8초 음성 안내·15초 포기 → 고정 문구 낭독 + /end ERROR) → SPEAKING → WAITING …
 *   8턴(일기는 3턴)이면 서버가 ENDED 를 주고 onEnded 로 올린다. WAITING 에서 20초 무조작이면 event=NO_RESPONSE (서버가 3단계 처리).
 *   [다시 말할게요] 2회면 이 세션은 버튼만 (D5-a 를 화면에서 지킴. 저신뢰 확인도 화면이 하므로 서버 확인 질문은 이 화면에선 안 씀).
 * 화면을 벗어나면(언마운트) alive=false 로 모든 후속 동작(타이머·재생·요청 뒤 처리)을 멈춘다.
 * 서버 STT/TTS 가 mock 이면 전사는 고정 문장, 읽기는 speechSynthesis — 흐름 확인용.
 */
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { AiOut, EndReason, SessionOut, SttOut, TurnIn } from '../../api/types'
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
  maxTurns?: number // 회상 8 (서버 MAX_TURNS), 일기 3 (서버 DIARY_TURNS)
}

export default function VoiceSession({ sessionId, initial, speed, inputMode, onEnded, maxTurns = 8 }: Props) {
  const [phase, setPhase] = useState<Phase>('IDLE')
  const [ai, setAi] = useState<AiOut>(initial.ai)
  const [turnNo, setTurnNo] = useState(initial.turn_no)
  const [locked, setLocked] = useState(initial.input_locked || inputMode === 'BUTTON')
  const [heard, setHeard] = useState<SttOut>()
  const [note, setNote] = useState<string>()
  const recorder = useRef<Recorder | null>(null)
  const retries = useRef(0)
  const timers = useRef<number[]>([])
  const alive = useRef(false)

  function later(ms: number, fn: () => void) {
    if (!alive.current) return
    timers.current.push(window.setTimeout(() => alive.current && fn(), ms))
  }
  function clearTimers() {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }

  function endWith(result: SessionOut) {
    clearTimers()
    stopSpeaking()
    setPhase('ENDED')
    if (alive.current) onEnded(result)
  }

  function ended(aiOut: AiOut, end_reason: EndReason | null): SessionOut {
    return { ...initial, ai: aiOut, state: 'ENDED', end_reason, turn_no: turnNo }
  }

  async function speakAi(a: AiOut) {
    setPhase('SPEAKING')
    if (a.audio_b64) await playBase64(a.audio_b64).catch(() => speak(a.text, speed))
    else await speak(a.text, speed)
  }

  async function present(r: SessionOut) {
    if (!alive.current) return
    setAi(r.ai)
    setTurnNo(r.turn_no)
    if (r.input_locked) setLocked(true)
    await speakAi(r.ai)
    if (!alive.current) return
    if (r.state === 'ENDED') return endWith(r)
    startWaiting()
  }

  function startWaiting() {
    if (!alive.current) return
    clearTimers()
    setPhase('WAITING')
    later(WAIT_MS, () => sendTurn({ input_type: 'BUTTON', event: 'NO_RESPONSE' }))
  }

  async function sendTurn(body: TurnIn) {
    if (!alive.current) return
    clearTimers()
    setNote(undefined)
    setHeard(undefined)
    setPhase('THINKING')
    later(SLOW_MS, () => setNote('조금만 기다려 주세요.'))
    later(VERY_SLOW_MS, () => speak('생각하는 중이에요. 잠깐만요.', speed)) // 키 없는 동안 mp3 대신 브라우저 TTS
    const ctrl = new AbortController()
    later(GIVE_UP_MS, () => ctrl.abort())
    let r: SessionOut
    try {
      r = await api<SessionOut>(`/api/elder/sessions/${sessionId}/turns`, { body, signal: ctrl.signal })
    } catch (e) {
      clearTimers()
      if (!alive.current) return
      if (e instanceof ApiError && e.code === 'INPUT_LOCKED') {
        setLocked(true)
        setNote('버튼으로 답해 주세요.')
        return startWaiting()
      }
      if (e instanceof ApiError && e.code === 'SESSION_ENDED') return endWith(ended(ERROR_AI, null))
      // 15초 초과·네트워크 오류: 서버에 ERROR 로 끝내 달라고 한다 (하루 3회면 서버가 가족에게 알림).
      // 응답만 잃고 서버는 이미 끝냈을 수 있다(마지막 답 → COMPLETED·LIMIT). 그때는 서버가 돌려준 종료 사유를 따른다
      // — 일기는 COMPLETED 여야 확인 화면으로 가서 남는다.
      stopSpeaking()
      setAi(ERROR_AI)
      const end = await api<{ end_reason: EndReason | null }>(`/api/elder/sessions/${sessionId}/end`, {
        body: { reason: 'ERROR' },
        signal: AbortSignal.timeout(5_000), // 망이 죽었으면 오래 매달리지 않는다
      }).catch(() => null)
      if (!alive.current) return
      if (end?.end_reason === 'COMPLETED' || end?.end_reason === 'LIMIT') {
        return endWith(ended({ ...ERROR_AI, text: '고마워요. 오늘은 여기까지 할게요.' }, end.end_reason))
      }
      await speakAi(ERROR_AI)
      if (alive.current) endWith(ended(ERROR_AI, 'ERROR'))
      return
    }
    clearTimers()
    stopSpeaking() // 8초 안내 낭독 중이었으면 끊고 답을 읽는다
    await present(r)
  }

  async function beginRecording() {
    clearTimers()
    stopSpeaking()
    setPhase('IDLE') // 마이크 준비 동안 버튼을 숨겨 녹음 두 번 시작·칩 동시 전송을 막는다
    let rec: Recorder
    try {
      rec = await startRecording(RECORD_MS)
    } catch {
      if (!alive.current) return
      setLocked(true)
      setNote('마이크를 쓸 수 없어요. 버튼으로 답해 주세요.')
      return startWaiting()
    }
    if (!alive.current) {
      rec.stop().catch(() => {})
      return
    }
    recorder.current = rec
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
    if (!alive.current) return
    const form = new FormData()
    form.append('audio', blob, 'speech.webm')
    try {
      const r = await api<SttOut>('/api/stt', { form })
      if (!alive.current) return
      setHeard(r)
      setPhase('CONFIRMING')
      if (r.confidence >= LOW_CONF) later(CONFIRM_MS, () => confirmHeard(r))
      else later(WAIT_MS, () => sendTurn({ input_type: 'BUTTON', event: 'NO_RESPONSE' }))
    } catch {
      if (!alive.current) return
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
      return startWaiting()
    }
    beginRecording()
  }

  async function stopSession() {
    clearTimers()
    stopSpeaking()
    const rec = recorder.current
    recorder.current = null
    if (rec) await rec.stop().catch(() => {})
    const r = await api<{ end_reason: EndReason | null }>(`/api/elder/sessions/${sessionId}/end`, {
      body: { reason: 'USER_STOP' },
    }).catch(() => null)
    endWith(ended({ ...ERROR_AI, text: '그래요, 오늘은 여기까지 할게요. 고마워요.' }, r?.end_reason ?? 'USER_STOP'))
  }

  useEffect(() => {
    alive.current = true
    // 한 틱 미뤄 시작: StrictMode 의 가짜 언마운트가 이 타이머를 지워서 첫 질문은 한 번만 읽힌다
    const start = window.setTimeout(() => present(initial), 0)
    return () => {
      window.clearTimeout(start)
      alive.current = false
      clearTimers()
      stopSpeaking()
      recorder.current?.stop().catch(() => {})
      recorder.current = null
    }
    // 세션 하나에 한 번만 시작한다 (sessionId 가 바뀌면 화면이 새로 마운트됨)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const busy = phase === 'THINKING' || phase === 'SPEAKING' || phase === 'TRANSCRIBING'
  return (
    <section className="elder-stack" aria-live="polite">
      <p className="muted" style={{ margin: 0 }}>{turnNo} / {maxTurns}</p>

      {phase === 'CONFIRMING' && heard ? (
        <>
          <p className="elder-text elder-text--lg">“{heard.transcript}”</p>
          {heard.confidence < LOW_CONF && <p className="elder-text">잘 들었는지 확인해 주세요. 맞으면 [맞아요]를 눌러 주세요.</p>}
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

      <button className="elder-btn elder-btn--secondary" onClick={stopSession} disabled={busy || phase === 'ENDED'}>
        그만할래요
      </button>
    </section>
  )
}
