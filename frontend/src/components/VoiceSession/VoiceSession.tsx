/**
 * VoiceSession — 말하기 왕복 상태기계 (설계안 3절, D5/D6/D48). 홍진성 담당.
 *
 *   WAITING ─[말하기]→ (IDLE: 마이크 준비) → RECORDING(≤60초, 진동·삐·남은 초) ─[다 말했어요]→ TRANSCRIBING(/api/stt)
 *     → CONFIRMING(전사 표시, [맞아요]/[다시 말할게요])
 *         신뢰도 ≥0.7: 3초 무조작이면 확정 / <0.7: 소리로도 확인을 부탁하고, 어르신이 [맞아요]를 눌러야 보냄(20초 무조작이면 무응답)
 *     → THINKING(/turns, 4초 안내·8초 '조금만요'·15초 포기 → '잠깐 문제가 있네요' 낭독 + /end ERROR) → SPEAKING → WAITING …
 *   8턴(일기는 3턴)이면 서버가 ENDED 를 주고 onEnded 로 올린다. WAITING 에서 20초 무조작이면 event=NO_RESPONSE (서버가 3단계 처리).
 *   버튼만(칩) 모드: 가족 설정 BUTTON·마이크 못 씀·STT 실패 2번 연속·[다시 말할게요] 2번 연속·STT 하루 상한 (FR-VS-006, D5-a 를 화면에서 지킴).
 *   저신뢰 확인도 화면이 하므로 서버 확인 질문·INPUT_LOCKED 는 이 화면에선 나오지 않는다 (D33).
 *   끝까지 못 들려주면(사용자 터치 전이라 자동 재생 막힘, 전화벨이 소리를 멈춤) TAP: [눌러서 들어 보세요]를 누르면 읽고 나서 기다린다 (D48).
 *   화면이 숨으면(전화·홈 버튼·화면 끔) 녹음·소리·타이머를 멈추고, 돌아오면 지금 질문부터 다시 읽는다. 30분이 넘었으면 끝낸다 (FR-VS-004).
 *   어르신 차례를 기다리는 동안은 화면을 켜 둔다(Wake Lock).
 * 화면을 벗어나면(언마운트) alive=false 로 모든 후속 동작(타이머·재생·요청 뒤 처리)을 멈춘다.
 * 서버 STT/TTS 가 mock 이면 전사는 고정 문장, 읽기는 speechSynthesis — 흐름 확인용.
 */
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { AiOut, EndReason, SessionOut, SttOut, TurnIn } from '../../api/types'
import { cue, PROMPT, say, startRecording, stopSpeaking, type Recorder } from '../../lib/audio'

type Phase = 'IDLE' | 'RECORDING' | 'TRANSCRIBING' | 'CONFIRMING' | 'THINKING' | 'SPEAKING' | 'WAITING' | 'TAP' | 'ENDED'

const RECORD_MS = 60_000
const CONFIRM_MS = 3_000
const WAIT_MS = 20_000
const SLOW_MS = 4_000
const VERY_SLOW_MS = 8_000
const GIVE_UP_MS = 15_000
const RESUME_MS = 30 * 60_000 // 서버 SESSION_RESUME_MIN — 넘으면 서버가 이미 끝낸 대화
const LOW_CONF = 0.7
const MAX_RETRY = 2 // [다시 말할게요] 연속 (FR-VS-006 '2회 연속' — 답을 보내면 0)
const MAX_STT_FAIL = 2 // /api/stt 실패 연속 (장애·말소리 없음·시간 초과·망 오류 — 전사되면 0)
const DEFAULT_CHIPS = ['네', '잘 모르겠어요'] // 모델이 칩을 안 줬을 때 (FR-VS-003)
// 칩은 2개까지만 보인다(11/12 사용자: 버튼이 너무 많음, FR-VS-003 '2~3개' 안). 서버는 그대로 3개까지 줄 수 있다.
// 그대로 다 보이는 것: 문제(답 2개 + '다음에 할게요' — 버튼만 쓰는 어르신이 넘길 칩), 일기 기분(날씨 4개 — 서버 칩 상한 3을 넘는 고르기)
const MAX_CHIPS = 2
const QUIZ_TYPES: AiOut['question_type'][] = ['REMEMBER', 'KNOWHOW', 'THEN_NOW', 'COMMON']

const ERROR_AI: AiOut = {
  text: PROMPT.error,
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
  maxTurns?: number // 회상 8 (서버 MAX_TURNS), 일기 3 (서버 DIARY_TURNS). 진행 숫자는 11/12 뺐다(설계서에 없음) — 받기만 함
}

export default function VoiceSession({ sessionId, initial, speed, inputMode, onEnded }: Props) {
  const [phase, setPhase] = useState<Phase>('IDLE')
  const [ai, setAi] = useState<AiOut>(initial.ai)
  const [locked, setLocked] = useState(initial.input_locked || inputMode === 'BUTTON')
  const [heard, setHeard] = useState<SttOut>()
  const [note, setNote] = useState<string>()
  const [left, setLeft] = useState(0) // 녹음 남은 초
  const recorder = useRef<Recorder | null>(null)
  const retries = useRef(0)
  const sttFails = useRef(0)
  const timers = useRef<number[]>([])
  const alive = useRef(false)
  const last = useRef(initial) // 지금 질문 — 다시 듣기·자동 재생 막힘·돌아왔을 때 다시 읽는다
  const seq = useRef(0) // 읽기·녹음 차례 번호: 화면이 숨거나 다시 읽으면 앞 차례의 뒤 처리를 버린다
  const away = useRef(document.hidden) // 화면이 숨은 동안 (전화·홈 버튼·화면 끔)
  const awayAt = useRef(0)
  const sending = useRef(false) // /turns 응답을 기다리는 중 (두 번 보내지 않게)
  const over = useRef(false) // 끝내는 중·끝남 — 뒤늦은 응답·복귀를 무시
  const lock = useRef<WakeLockSentinel | null>(null)
  const wantLock = useRef(false)

  function later(ms: number, fn: () => void) {
    if (!alive.current) return
    timers.current.push(window.setTimeout(() => alive.current && fn(), ms))
  }
  function clearTimers() {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }

  /** 화면 켜 두기. 숨으면 브라우저가 풀고, 다시 기다릴 때 또 잡는다. 아무도 안 누르는 TAP·끝 화면에서는 놓는다 */
  function wake(on: boolean) {
    wantLock.current = on
    if (!on) {
      lock.current?.release().catch(() => {})
      lock.current = null
      return
    }
    if (lock.current && !lock.current.released) return
    navigator.wakeLock?.request('screen').then(
      (l) => (wantLock.current && alive.current ? (lock.current = l) : void l.release()),
      () => {}, // 지원 안 하는 기기·거절 — 그냥 둔다
    )
  }

  function endWith(result: SessionOut) {
    over.current = true
    clearTimers()
    stopSpeaking()
    wake(false)
    setPhase('ENDED')
    if (alive.current) onEnded(result)
  }

  function ended(aiOut: AiOut, end_reason: EndReason | null): SessionOut {
    return { ...initial, ai: aiOut, state: 'ENDED', end_reason, turn_no: last.current.turn_no }
  }

  /** 화면이 정한 끝인사를 자막과 소리로 알리고 끝낸다 (FR-VS-004 'AI 말은 TTS 와 자막을 동시에'). */
  async function sayBye(a: AiOut, reason: EndReason | null) {
    over.current = true
    clearTimers()
    setAi(a)
    setNote(undefined)
    setPhase('ENDED')
    if (alive.current && !away.current) await say(a.text, speed) // 늘 끝난다: mp3 가 3초 안에 안 나오면 기기 목소리(상한 15초)
    if (alive.current) endWith(ended(a, reason))
  }

  function speakAi(a: AiOut) {
    setPhase('SPEAKING')
    return say(a.text, speed, a.audio_b64)
  }

  async function present(r: SessionOut) {
    if (!alive.current || over.current) return
    const my = ++seq.current
    clearTimers() // 다시 듣기: 기다리던 20초 무응답을 멈추고 다 읽은 뒤 새로 센다
    last.current = r
    setAi(r.ai)
    setNote(undefined) // 4초 '조금만 기다려 주세요'·실패 안내는 새 질문에서 지운다 (남으면 어르신이 기다리기만 함)
    if (r.input_locked) setLocked(true)
    if (away.current) return // 숨어 있으면 돌아와서 이 질문부터 읽는다
    const heardIt = await speakAi(r.ai)
    if (!alive.current || over.current || my !== seq.current) return
    if (!heardIt) {
      wake(false) // 아무도 안 누르면 화면이 꺼지게
      return setPhase('TAP') // 버튼을 누르면 그 터치로 다시 읽는다 (D48)
    }
    if (r.state === 'ENDED') return endWith(r)
    startWaiting()
  }

  function startWaiting() {
    if (!alive.current || over.current || away.current) return // 숨어 있으면 돌아와서 다시 읽은 뒤 센다
    clearTimers()
    setPhase('WAITING')
    wake(true)
    later(WAIT_MS, () => sendTurn({ input_type: 'BUTTON', event: 'NO_RESPONSE' }))
  }

  /** 이 대화는 버튼(칩)만 — 까닭을 글·소리로 알리고 기다린다 (FR-VS-006). */
  function buttonsOnly(msg: string) {
    setLocked(true)
    setNote(msg)
    void say(msg, speed) // 기다리지 않는다: 칩을 누르면 바로 보낸다
    startWaiting()
  }

  async function sendTurn(body: TurnIn) {
    if (!alive.current || over.current || sending.current) return // 타이머와 터치가 겹쳐도 한 번만
    sending.current = true
    clearTimers()
    stopSpeaking() // 확인 부탁·실패 안내를 읽는 중에 답했으면 끊는다
    setNote(undefined)
    setHeard(undefined)
    setPhase('THINKING')
    if (body.text) retries.current = 0 // 답을 보냈으면 [다시 말할게요] 연속이 끊긴다
    later(SLOW_MS, () => setNote('조금만 기다려 주세요.'))
    later(VERY_SLOW_MS, () => void say(PROMPT.slow, speed)) // 고정 안내도 서버와 같은 목소리 mp3 (D48)
    const ctrl = new AbortController()
    const giveUp = window.setTimeout(() => ctrl.abort(), GIVE_UP_MS) // 화면이 숨어도 포기는 하도록 timers 와 따로
    let r: SessionOut | undefined
    let err: unknown
    try {
      r = await api<SessionOut>(`/api/elder/sessions/${sessionId}/turns`, { body, signal: ctrl.signal })
    } catch (e) {
      err = e
    }
    clearTimeout(giveUp)
    sending.current = false
    clearTimers()
    if (!alive.current || over.current) return
    if (r) {
      stopSpeaking() // 8초 안내 낭독 중이었으면 끊고 답을 읽는다
      return present(r)
    }
    if (err instanceof ApiError && err.code === 'INPUT_LOCKED') return buttonsOnly(PROMPT.buttons)
    // 이미 끝난 대화(30분 지남·다른 곳에서 끝냄)는 오류가 아니다: 서버에 남은 종료 사유로 인사하고 끝낸다
    if (err instanceof ApiError && err.code === 'SESSION_ENDED') return finish('NO_RESPONSE', PROMPT.thanks)
    // 15초 초과·네트워크 오류: 서버에 ERROR 로 끝내 달라고 한다 (하루 3회면 서버가 가족에게 알림).
    // 응답만 잃고 서버는 이미 끝냈을 수 있다(마지막 답 → COMPLETED·LIMIT). 그때는 서버가 돌려준 종료 사유를 따른다
    // — 일기는 COMPLETED 여야 확인 화면으로 가서 남는다.
    over.current = true
    stopSpeaking()
    setAi(ERROR_AI)
    setNote(undefined)
    setPhase('ENDED')
    const end = await api<{ end_reason: EndReason | null }>(`/api/elder/sessions/${sessionId}/end`, {
      body: { reason: 'ERROR' },
      signal: AbortSignal.timeout(5_000), // 망이 죽었으면 오래 매달리지 않는다
    }).catch(() => null)
    if (!alive.current) return
    if (end?.end_reason === 'COMPLETED' || end?.end_reason === 'LIMIT') {
      return sayBye({ ...ERROR_AI, text: PROMPT.thanks }, end.end_reason)
    }
    return sayBye(ERROR_AI, 'ERROR')
  }

  async function beginRecording() {
    clearTimers()
    stopSpeaking()
    setNote(undefined) // '잘 못 들었어요' 안내가 녹음 중에 남지 않게
    setPhase('IDLE') // 마이크 준비 동안 [말하기]를 꺼서 녹음 두 번 시작·칩 동시 전송을 막는다
    const my = ++seq.current
    let rec: Recorder
    try {
      rec = await startRecording(RECORD_MS)
    } catch {
      if (!alive.current || my !== seq.current) return
      return buttonsOnly(PROMPT.micOff)
    }
    if (!alive.current || my !== seq.current) {
      rec.stop().catch(() => {})
      return
    }
    recorder.current = rec
    cue() // 지금부터 듣는다는 신호 — 준비 중에 한 말은 녹음되지 않는다 (FR-VS-001)
    setPhase('RECORDING')
    const endAt = Date.now() + RECORD_MS
    const tick = () => {
      setLeft(Math.max(0, Math.ceil((endAt - Date.now()) / 1000)))
      later(1_000, tick)
    }
    tick()
    later(RECORD_MS, finishRecording)
  }

  async function finishRecording() {
    clearTimers()
    const rec = recorder.current
    recorder.current = null
    if (!rec) return
    const my = seq.current
    setPhase('TRANSCRIBING')
    const blob = await rec.stop()
    if (!alive.current || my !== seq.current) return
    const form = new FormData()
    form.append('audio', blob, 'speech.webm')
    try {
      const r = await api<SttOut>('/api/stt', { form, signal: AbortSignal.timeout(GIVE_UP_MS) }) // 망이 멈춰도 15초면 다시 말하기로
      if (!alive.current || my !== seq.current) return
      sttFails.current = 0
      setHeard(r)
      setPhase('CONFIRMING')
      if (r.confidence >= LOW_CONF) later(CONFIRM_MS, () => confirmHeard(r))
      else {
        void say(PROMPT.check, speed) // 저신뢰는 소리로도 확인을 부탁한다 (FR-VS-002)
        later(WAIT_MS, () => sendTurn({ input_type: 'BUTTON', event: 'NO_RESPONSE' }))
      }
    } catch (e) {
      if (!alive.current || my !== seq.current) return
      // 429(분당·하루 상한)는 서버 문장을 읽는다. 하루 상한이면 이 대화는 버튼만 (D46)
      // 그 밖의 실패(장애·말소리 없음·시간 초과·망 오류)도 2번 연속이면 버튼만 (FR-VS-006, D48)
      sttFails.current += 1
      if (e instanceof ApiError && e.code === 'STT_DAILY_LIMIT') return buttonsOnly(e.message)
      if (sttFails.current >= MAX_STT_FAIL) return buttonsOnly(PROMPT.buttons)
      const msg = e instanceof ApiError && e.status === 429 ? e.message : PROMPT.notHeard
      setNote(msg)
      void say(msg, speed) // 기다리지 않는다: [말하기]를 누르면 녹음 전에 stopSpeaking 이 끊는다
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
    if (retries.current >= MAX_RETRY) return buttonsOnly(PROMPT.buttons)
    beginRecording()
  }

  /** 화면이 대화를 끝낸다: 서버에 알리고(5초까지) 끝인사. [그만할래요] · 30분 넘게 떠났다 돌아옴 */
  async function finish(reason: 'USER_STOP' | 'NO_RESPONSE', text: string) {
    over.current = true // 이 뒤로 오는 응답·타이머·복귀는 무시
    clearTimers()
    stopSpeaking()
    setNote(undefined)
    setPhase('ENDED') // 응답을 기다리는 동안 다른 버튼이 눌리지 않게
    const rec = recorder.current
    recorder.current = null
    if (rec) await rec.stop().catch(() => {})
    const r = await api<{ end_reason: EndReason | null }>(`/api/elder/sessions/${sessionId}/end`, {
      body: { reason },
      signal: AbortSignal.timeout(5_000), // 망이 느려도 화면이 멈춰 있지 않게
    }).catch(() => null)
    if (!alive.current) return
    return sayBye({ ...ERROR_AI, text }, r?.end_reason ?? reason)
  }

  /** 화면이 숨으면(전화·홈 버튼·화면 끔) 녹음·소리·타이머를 멈춘다. 하던 녹음은 버린다 (FR-VS-004). */
  function leave() {
    if (away.current) return
    away.current = true
    awayAt.current = Date.now()
    stopSpeaking() // 끝인사 중이었어도 숨은 화면에서 울리지 않게
    if (over.current) return
    seq.current += 1 // 읽던 낭독·녹음·STT 응답의 뒤 처리를 버린다
    clearTimers()
    recorder.current?.stop().catch(() => {})
    recorder.current = null
    setHeard(undefined)
  }

  /** 돌아오면 지금 질문부터 다시 읽는다. 답을 보내는 중이었으면 응답이 와서 읽는다. 30분이 넘었으면 끝낸다(공통 기준: 넘으면 홈). */
  function comeBack() {
    if (!away.current) return
    away.current = false
    if (over.current || sending.current) return
    if (Date.now() - awayAt.current > RESUME_MS) return void finish('NO_RESPONSE', PROMPT.thanks)
    present(last.current)
  }

  useEffect(() => {
    alive.current = true
    awayAt.current = Date.now() // 숨은 채로 열렸으면 이때부터 센다 (0 이면 돌아오자마자 '30분 지남'으로 끝남)
    // 한 틱 미뤄 시작: StrictMode 의 가짜 언마운트가 이 타이머를 지워서 첫 질문은 한 번만 읽힌다
    const start = window.setTimeout(() => present(initial), 0)
    const onShow = () => (document.hidden ? leave() : comeBack())
    document.addEventListener('visibilitychange', onShow)
    return () => {
      window.clearTimeout(start)
      document.removeEventListener('visibilitychange', onShow)
      alive.current = false
      wake(false)
      clearTimers()
      stopSpeaking()
      recorder.current?.stop().catch(() => {})
      recorder.current = null
    }
    // 세션 하나에 한 번만 시작한다 (sessionId 가 바뀌면 화면이 새로 마운트됨)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 칩이 없으면 기본 칩. 마무리 인사에는 칩이 없다
  const given = ai.suggestions
  const chips =
    given.length === 0
      ? ai.question_type === 'CLOSING' ? [] : DEFAULT_CHIPS
      : QUIZ_TYPES.includes(ai.question_type) || given.length > 3 ? given : given.slice(0, MAX_CHIPS)
  const confirming = phase === 'CONFIRMING' && heard
  const canStop = phase === 'WAITING' || phase === 'CONFIRMING' || phase === 'TAP'
  const bold = { fontWeight: 700 } // 자막은 32px 굵게 — 40px 이면 긴 질문(40자 넘음)이 6줄이라 한 화면을 넘는다 (11/12 갤럭시)
  // 아래 버튼 높이 (11/12 사용자: 갤럭시에서 아래가 너무 큼 → 칩 56·결정 64·보조 48, D48). 요구사항(결정 88·칩 64px)보다 작다
  const main = { minHeight: 64 }
  const chip = { minHeight: 56, flex: '1 1 40%' }
  const aid = { minHeight: 48, fontSize: 28 }
  const row = { display: 'flex', gap: 12 }
  return (
    <section className="elder-stack" aria-live="polite">
      <div className="elder-stack">
        {confirming ? (
          <>
            <p className="elder-text" style={bold}>“{heard.transcript}”</p>
            {heard.confidence < LOW_CONF && <p className="elder-text">잘 들었는지 확인해 주세요. 맞으면 [맞아요]를 눌러 주세요.</p>}
          </>
        ) : (
          <>
            <p className="elder-text" style={bold}>{ai.text}</p>
            {note && <p className="elder-text">{note}</p>}
            {phase === 'THINKING' && <p className="elder-text">생각하고 있어요…</p>}
            {phase === 'RECORDING' && <p className="elder-text">듣고 있어요…</p>}
          </>
        )}
      </div>

      {/* 버튼은 글 아래 순서대로, 스크롤 없음(화면 높이는 부르는 화면이 맞춘다 — ELDER_MEMORY_001 은 사진이 줄어듦, 11/12).
          대화 중에는 단계가 바뀌어도 같은 자리에 같은 버튼: 손 밑에 다른 버튼이 오지 않게 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {confirming ? (
          <>
            <button className="elder-btn" style={main} onClick={() => confirmHeard(heard)}>맞아요</button>
            <button className="elder-btn elder-btn--secondary" style={main} onClick={retryHeard}>다시 말할게요</button>
          </>
        ) : (
          phase !== 'ENDED' && (
            <>
              {chips.length > 0 && (
                // 칩은 한 줄에 둘씩. 기다릴 때만 보이고, 그 밖에는 자리만 남긴다 (visibility)
                <div style={{ ...row, flexWrap: 'wrap', visibility: phase === 'WAITING' ? 'visible' : 'hidden' }}>
                  {chips.map((s) => (
                    <button
                      key={s}
                      className="elder-chip"
                      style={chip}
                      onClick={() => sendTurn({ text: s, input_type: ai.choice_mode === 'TWO_BUTTONS' ? 'BUTTON' : 'CHIP' })}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
              {phase === 'TAP' ? (
                <button className="elder-btn" style={main} onClick={() => present(last.current)}>
                  눌러서 들어 보세요
                </button>
              ) : phase === 'RECORDING' ? (
                // 처음 1초는 끔: [말하기]를 두 번 톡톡 누르면 빈 녹음이 STT 실패로 세어진다
                <button className="elder-btn" style={main} onClick={finishRecording} disabled={left >= RECORD_MS / 1000}>
                  다 말했어요 ({left}초)
                </button>
              ) : (
                !locked && (
                  <button className="elder-btn" style={main} onClick={beginRecording} disabled={phase !== 'WAITING'}>
                    {phase === 'WAITING' ? '말하기' : phase === 'SPEAKING' ? '말하는 중…' : '잠깐만요…'}
                  </button>
                )
              )}
            </>
          )
        )}

        {/* 보조 버튼은 늘 맨 아래 같은 자리, 한 줄에 반씩 (화면설계서: 왼쪽 아래 다시 듣기, 오른쪽 아래 그만) */}
        <div style={row}>
          <button
            className="elder-btn elder-btn--secondary"
            style={aid}
            onClick={() => present(last.current)}
            disabled={phase !== 'WAITING' && phase !== 'TAP'}
          >
            다시 듣기
          </button>
          <button
            className="elder-btn elder-btn--secondary"
            style={aid}
            onClick={() => void finish('USER_STOP', PROMPT.bye)}
            disabled={!canStop}
          >
            그만할래요
          </button>
        </div>
      </div>
    </section>
  )
}
