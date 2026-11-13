/**
 * VoiceSession — 말하기 왕복 상태기계 + 말풍선 대화 화면 (설계안 3절, D5/D6/D48 → 11/12 새 모양 D52). 홍진성 담당.
 *
 *   WAITING ─[말하기]→ (IDLE: 마이크 준비) → RECORDING(≤60초, 진동·삐·남은 시간) ─[다 말했어요]→ TRANSCRIBING(/api/stt)
 *     → HEARD(들은 말이 내 말풍선으로 뜨고 옆에 작은 [다시] 2초 — 안 누르면 보냄)
 *     → THINKING(/turns, 4초 안내·8초 '조금만요'·15초 포기 → '잠깐 문제가 있네요' 낭독 + /end ERROR) → SPEAKING → WAITING …
 *   신뢰도가 낮으면 서버가 확인 질문('제가 ○○ 라고 들었어요…', 칩 [맞아요]/[다시 말할게요])을 AI 말풍선으로 준다.
 *   '맞아요'는 말로 해도 칩으로 눌러도 서버가 들은 문장을 답으로 저장한다(D52 ③, D33 을 바꿈). [다시 말할게요] 칩은 바로 녹음.
 *   글로 쓰기(D52 ⑤): 자판 단추 → 입력 칸(500자) → [보내기]. 쓴 글은 [다시] 없이 TEXT 로 보낸다. 쓰는 동안은 20초 무응답 대신 2분.
 *   다시 듣기 = AI 말풍선 누르기. [다시 듣기]·[그만할래요] 버튼은 없다 — "그만할래" 라고 말하거나 뒤로 키 (D51 ⑥).
 *   회상 6번(일기 3번)이면 서버가 ENDED 를 주고 onEnded 로 올린다. WAITING 에서 20초 무조작이면 event=NO_RESPONSE (서버 3단계).
 *   추천 답변은 늘 2개(모자라면 기본 칩으로 채움, D52 ④). 일기 기분 날씨만 4개.
 *   버튼만(칩) 모드: 가족 설정 BUTTON·마이크 못 씀·STT 실패 2번 연속·[다시] 2번 연속·STT 하루 상한 (FR-VS-006, D48).
 *   끝까지 못 들려주면(자동 재생 막힘·전화벨) TAP: [눌러서 들어 보세요] (D48).
 *   화면이 숨으면(전화·홈 버튼·화면 끔) 녹음·소리·타이머를 멈추고, 돌아오면 지금 질문부터 다시 읽는다. 30분이 넘었으면 끝낸다.
 *   뒤로 키(D52 ⑥): 화면을 떠나도 서버 대화는 마지막 턴 뒤 30분 살아 있다. 대화 번호를 기기에 적어 두고(lib/pausedSession),
 *   다시 열면(새로고침·홈의 '이어서') 서버가 준 지난 말(history)을 말풍선으로 보이고 그 질문부터 다시 읽는다. 끝나면 지운다.
 * 화면을 벗어나면(언마운트) alive=false 로 모든 후속 동작(타이머·재생·요청 뒤 처리)을 멈춘다.
 * 서버 STT/TTS 가 mock 이면 전사는 고정 문장, 읽기는 speechSynthesis — 흐름 확인용.
 */
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { api, ApiError } from '../../api/client'
import type { AiOut, EndReason, SessionOut, SttOut, TurnIn, TurnOut } from '../../api/types'
import { cue, PROMPT, say, startRecording, stopSpeaking, type Recorder } from '../../lib/audio'
import { clearPaused, savePaused } from '../../lib/pausedSession'
import './VoiceSession.css'

type Phase = 'IDLE' | 'RECORDING' | 'TRANSCRIBING' | 'HEARD' | 'THINKING' | 'SPEAKING' | 'WAITING' | 'TAP' | 'ENDED'
type Bubble = { id: number; who: 'AI' | 'ME'; text: string; b64?: string | null }

const RECORD_MS = 60_000
const REDO_MS = 2_000 // 들은 말 옆 [다시] (D52 ③)
const WAIT_MS = 20_000
const TYPE_MS = 120_000 // 글을 쓰는 동안은 무응답을 늦게 센다 (마지막으로 글자를 바꾼 뒤 2분)
const SLOW_MS = 4_000
const VERY_SLOW_MS = 8_000
const GIVE_UP_MS = 15_000
const RESUME_MS = 30 * 60_000 // 서버 SESSION_RESUME_MIN — 넘으면 서버가 이미 끝낸 대화
const MAX_RETRY = 2 // [다시] 연속 (FR-VS-006 '2회 연속' — 답을 보내면 0)
const MAX_STT_FAIL = 2 // /api/stt 실패 연속 (장애·말소리 없음·시간 초과·망 오류 — 전사되면 0)
const MAX_TEXT = 500 // 서버 TurnIn.text 상한
const REDO_CHIP = '다시 말할게요' // 서버 확인 질문의 칩(coach.CONFIRM_SUGGESTIONS) — 말할 수 있으면 보내지 않고 바로 녹음
const DEFAULT_CHIPS = ['네', '잘 모르겠어요'] // 모델 칩이 모자랄 때 (FR-VS-003)
const MAX_CHIPS = 2 // 추천 답변은 늘 2개 (11/12 사용자, D52 ④). 서버는 그대로 3개까지 줄 수 있다

const ERROR_AI: AiOut = {
  text: PROMPT.error,
  audio_b64: null,
  suggestions: [],
  choice_mode: 'TWO_BUTTONS',
  question_type: 'CLOSING',
}

/** 목업 아이콘 (24 격자 선 그림) */
const ICONS = {
  mic: (
    <>
      <rect x="9" y="2.5" width="6" height="11.5" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3.5" />
    </>
  ),
  stop: <rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor" />,
  keyboard: (
    <>
      <rect x="2.5" y="6" width="19" height="12" rx="2.5" />
      <path d="M6.5 10h.01M10 10h.01M13.5 10h.01M17 10h.01M8 14h8" />
    </>
  ),
  redo: (
    <>
      <path d="M4.5 12a7.5 7.5 0 1 0 2.6-5.7" />
      <path d="M4 4.5V9h4.5" />
    </>
  ),
  spk: (
    <>
      <path d="M4 9.5v5h3.2L12 18.5v-13L7.2 9.5z" />
      <path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.3 6.3a8 8 0 0 1 0 11.4" />
    </>
  ),
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
} satisfies Record<string, ReactNode>

function Icon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg
      className="vs-ic"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ICONS[name]}
    </svg>
  )
}

/** 보일 추천 답변. 마무리 인사에는 없고, 일기 기분 날씨(4개)는 그대로, 나머지는 2개로 맞춘다 (D52 ④) */
function chipsFor(a: AiOut): string[] {
  if (a.question_type === 'CLOSING') return []
  const given = [...new Set(a.suggestions)]
  if (given.length > 3) return given
  const two = given.slice(0, MAX_CHIPS)
  for (const d of DEFAULT_CHIPS) if (two.length < MAX_CHIPS && !two.includes(d)) two.push(d)
  return two
}

const mmss = (sec: number) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`

type Props = {
  sessionId: string
  initial: SessionOut
  history?: TurnOut[] // 이어서 할 때 서버가 준 지난 말 (마지막 질문 포함)
  speed: number
  inputMode: 'VOICE' | 'BUTTON'
  onEnded: (result: SessionOut) => void
  endAction?: { label: string; onClick: () => void } // 끝난 뒤 아래 단추 (회상 '다 들었어요')
  maxTurns?: number // 회상 6 (서버 MAX_TURNS), 일기 3 (서버 DIARY_TURNS). 진행 숫자는 11/12 뺐다 — 받기만 함
}

export default function VoiceSession({ sessionId, initial, history, speed, inputMode, onEnded, endAction }: Props) {
  const nextId = useRef(0)
  // 지난 말풍선 (이어서). 마지막 질문은 시작할 때 present 가 새로 붙이므로 여기서는 뺀다
  const [bubbles, setBubbles] = useState<Bubble[]>(() => {
    const past = [...(history ?? [])]
    if (past.at(-1)?.speaker === 'AI' && past.at(-1)?.text === initial.ai.text) past.pop()
    return past.map((t) => ({ id: ++nextId.current, who: t.speaker === 'AI' ? 'AI' : 'ME', text: t.text }))
  })
  const [phase, setPhase] = useState<Phase>('IDLE')
  const [ai, setAi] = useState<AiOut>(initial.ai)
  const [locked, setLocked] = useState(initial.input_locked || inputMode === 'BUTTON')
  const [note, setNote] = useState<string>()
  const [left, setLeft] = useState(0) // 녹음 남은 초
  const [typing, setTyping] = useState(false)
  const [draft, setDraft] = useState('')
  const [heardId, setHeardId] = useState<number>() // [다시] 를 보이는 내 말풍선
  const [lastAiId, setLastAiId] = useState<number>()
  const logRef = useRef<HTMLDivElement>(null)
  const recorder = useRef<Recorder | null>(null)
  const heard = useRef<{ id: number; r: SttOut } | null>(null) // [다시] 를 기다리는 들은 말
  const retries = useRef(0)
  const sttFails = useRef(0)
  const timers = useRef<number[]>([])
  const alive = useRef(false)
  const last = useRef(initial) // 지금 질문 — 자동 재생 막힘·돌아왔을 때 다시 읽는다
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

  function add(who: Bubble['who'], text: string, b64?: string | null) {
    const id = ++nextId.current
    setBubbles((xs) => [...xs, { id, who, text, b64 }])
    return id
  }
  /** [다시] 를 기다리던 들은 말을 거둔다 (안 보낸 말이라 말풍선도 지운다) */
  function dropHeard() {
    const id = heard.current?.id
    if (id !== undefined) setBubbles((xs) => xs.filter((x) => x.id !== id))
    heard.current = null
    setHeardId(undefined)
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
    clearPaused(sessionId)
    setTyping(false)
    setPhase('ENDED')
    if (alive.current) onEnded(result)
  }

  function ended(aiOut: AiOut, end_reason: EndReason | null): SessionOut {
    return { ...initial, ai: aiOut, state: 'ENDED', end_reason, turn_no: last.current.turn_no }
  }

  /** 화면이 정한 끝인사를 말풍선과 소리로 알리고 끝낸다 (FR-VS-004 'AI 말은 TTS 와 자막을 동시에'). */
  async function sayBye(a: AiOut, reason: EndReason | null) {
    over.current = true
    clearTimers()
    setAi(a)
    setNote(undefined)
    setPhase('ENDED')
    setLastAiId(add('AI', a.text))
    if (alive.current && !away.current) await say(a.text, speed) // 늘 끝난다: mp3 가 3초 안에 안 나오면 기기 목소리(상한 15초)
    if (alive.current) endWith(ended(a, reason))
  }

  /** 질문을 보이고 읽는다. fresh=false 면 같은 질문을 다시 읽기만 (돌아옴·눌러서 듣기·말풍선 누르기) */
  async function present(r: SessionOut, fresh = true) {
    if (!alive.current || over.current) return
    const my = ++seq.current
    clearTimers() // 다시 듣기: 기다리던 20초 무응답을 멈추고 다 읽은 뒤 새로 센다
    last.current = r
    setAi(r.ai)
    setNote(undefined) // 4초 '조금만 기다려 주세요'·실패 안내는 새 질문에서 지운다 (남으면 어르신이 기다리기만 함)
    if (fresh) setLastAiId(add('AI', r.ai.text, r.ai.audio_b64))
    if (r.input_locked) setLocked(true)
    if (away.current) return // 숨어 있으면 돌아와서 이 질문부터 읽는다
    setPhase('SPEAKING')
    const heardIt = await say(r.ai.text, speed, r.ai.audio_b64)
    if (!alive.current || over.current || my !== seq.current) return
    if (!heardIt) {
      wake(false) // 아무도 안 누르면 화면이 꺼지게
      return setPhase('TAP') // 버튼을 누르면 그 터치로 다시 읽는다 (D48)
    }
    if (r.state === 'ENDED') return endWith(r)
    startWaiting()
  }

  /** AI 말풍선을 누르면 그 말을 다시 읽는다. 지금 질문이면 present 와 같다 (D51 ⑥ 다시 듣기) */
  async function replay(b: Bubble) {
    if (over.current) return void say(b.text, speed, b.b64) // 끝난 뒤에도 다시 들을 수 있다
    if (phase !== 'WAITING' && phase !== 'TAP') return
    if (b.id === lastAiId) return present(last.current, false)
    const my = ++seq.current
    clearTimers()
    setPhase('SPEAKING')
    await say(b.text, speed, b.b64)
    if (alive.current && !over.current && my === seq.current) startWaiting()
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

  /** 칩·글로 쓴 답: 내 말풍선을 붙이고 바로 보낸다 ([다시] 없음) */
  function answer(text: string, input_type: TurnIn['input_type']) {
    if (!alive.current || over.current || sending.current) return // 두 번 눌러도 말풍선·전송은 한 번
    add('ME', text)
    void sendTurn({ text, input_type })
  }

  function onChip(c: string) {
    if (phase !== 'WAITING') return
    if (c === REDO_CHIP && !locked) return redo() // 확인 질문에 '아니요' — 서버를 거치지 않고 바로 다시 말한다
    answer(c, ai.choice_mode === 'TWO_BUTTONS' ? 'BUTTON' : 'CHIP')
  }

  async function sendTurn(body: TurnIn) {
    if (!alive.current || over.current || sending.current) return // 타이머와 터치가 겹쳐도 한 번만
    sending.current = true
    clearTimers()
    stopSpeaking() // 안내를 읽는 중에 답했으면 끊는다
    setNote(undefined)
    setHeardId(undefined)
    heard.current = null
    setTyping(false)
    setPhase('THINKING')
    if (body.text) retries.current = 0 // 답을 보냈으면 [다시] 연속이 끊긴다
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
      if (r.state !== 'ENDED') savePaused({ id: sessionId, kind: initial.kind, at: Date.now() }) // 30분은 마지막 턴부터
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
      // 들은 말 = 내 말풍선 + [다시] 2초. 안 누르면 보낸다. 신뢰도가 낮으면 서버가 확인 질문을 준다 (D52 ③)
      const id = add('ME', r.transcript)
      heard.current = { id, r }
      setHeardId(id)
      setPhase('HEARD')
      later(REDO_MS, () => sendTurn({ text: r.transcript, input_type: 'VOICE', stt_confidence: r.confidence }))
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

  /** [다시] (들은 말 옆) · 확인 질문의 [다시 말할게요]: 들은 말을 버리고 바로 다시 녹음. 2번 연속이면 버튼만 */
  function redo() {
    clearTimers()
    dropHeard()
    retries.current += 1
    if (retries.current >= MAX_RETRY) return buttonsOnly(PROMPT.buttons)
    void beginRecording()
  }

  /** 글로 쓰기 (D52 ⑤). 쓰는 동안은 20초 대신 마지막으로 고친 뒤 2분이 지나야 무응답 */
  function typeTimer() {
    clearTimers()
    later(TYPE_MS, () => sendTurn({ input_type: 'BUTTON', event: 'NO_RESPONSE' }))
  }
  function openTyping() {
    if (phase !== 'WAITING') return
    stopSpeaking()
    setTyping(true)
    typeTimer()
  }
  function submitTyping(e: FormEvent) {
    e.preventDefault()
    const text = draft.trim().slice(0, MAX_TEXT)
    setDraft('')
    setTyping(false)
    if (text) answer(text, 'TEXT') // 직접 쓴 글은 [다시] 없이 바로 보낸다
    else startWaiting()
  }

  /** 화면이 대화를 끝낸다: 서버에 알리고(5초까지) 끝인사. 30분 넘게 떠났다 돌아옴 · 이미 끝난 대화 */
  async function finish(reason: 'NO_RESPONSE', text: string) {
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

  /** 화면이 숨으면(전화·홈 버튼·화면 끔) 녹음·소리·타이머를 멈춘다. 하던 녹음·안 보낸 들은 말은 버린다 (FR-VS-004). */
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
    dropHeard()
  }

  /** 돌아오면 지금 질문부터 다시 읽는다. 답을 보내는 중이었으면 응답이 와서 읽는다. 30분이 넘었으면 끝낸다(공통 기준: 넘으면 홈). */
  function comeBack() {
    if (!away.current) return
    away.current = false
    if (over.current || sending.current) return
    if (Date.now() - awayAt.current > RESUME_MS) return void finish('NO_RESPONSE', PROMPT.thanks)
    void present(last.current, false)
  }

  useEffect(() => {
    alive.current = true
    awayAt.current = Date.now() // 숨은 채로 열렸으면 이때부터 센다 (0 이면 돌아오자마자 '30분 지남'으로 끝남)
    if (initial.state !== 'ENDED') savePaused({ id: sessionId, kind: initial.kind, at: Date.now() })
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

  // 말이 붙으면 말풍선 칸만 맨 아래로 (화면·버튼은 그대로, D52 ①)
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [bubbles, phase, note])

  const chips = phase === 'ENDED' ? [] : chipsFor(ai)
  const canAnswer = phase === 'WAITING' && !typing

  let talk: ReactNode
  if (phase === 'ENDED') {
    talk = endAction && (
      <button className="vs-talk" onClick={endAction.onClick}>
        <Icon name="check" />
        {endAction.label}
      </button>
    )
  } else if (phase === 'TAP') {
    talk = (
      <button className="vs-talk" onClick={() => present(last.current, false)}>
        눌러서 들어 보세요
      </button>
    )
  } else if (phase === 'RECORDING') {
    // 처음 1초는 끔: [말하기]를 두 번 톡톡 누르면 빈 녹음이 STT 실패로 세어진다
    talk = (
      <button className="vs-talk vs-rec" onClick={finishRecording} disabled={left >= RECORD_MS / 1000}>
        <Icon name="stop" />
        다 말했어요 <small>{mmss(left)}</small>
      </button>
    )
  } else if (locked) {
    // 버튼만 모드: 칩이 답이고, 글로 쓰기는 남긴다 (말을 못 하는 상황용, D52 ⑤)
    talk = (
      <button className="vs-talk vs-ghost" onClick={openTyping} disabled={phase !== 'WAITING'}>
        <Icon name="keyboard" />
        글로 쓰기
      </button>
    )
  } else {
    talk = (
      <>
        <button className="vs-talk" onClick={beginRecording} disabled={phase !== 'WAITING'}>
          {phase === 'WAITING' ? (
            <>
              <Icon name="mic" />
              말하기
            </>
          ) : phase === 'SPEAKING' ? (
            '말하는 중…'
          ) : (
            '잠깐만요…'
          )}
        </button>
        <button className="vs-key" onClick={openTyping} disabled={phase !== 'WAITING'} aria-label="글로 쓰기">
          <Icon name="keyboard" />
        </button>
      </>
    )
  }

  return (
    <section className="vs">
      <div className="vs-log" ref={logRef} aria-live="polite">
        {bubbles.map((b) =>
          b.who === 'AI' ? (
            <button
              key={b.id}
              type="button"
              className={`vs-msg vs-ai${b.id === lastAiId && phase === 'SPEAKING' ? ' vs-saying' : ''}`}
              onClick={() => void replay(b)}
            >
              <span>{b.text}</span>
              <Icon name="spk" />
            </button>
          ) : (
            <div key={b.id} className="vs-me-row">
              {b.id === heardId && (
                <button type="button" className="vs-redo" onClick={redo}>
                  <Icon name="redo" />
                  다시
                </button>
              )}
              <p className={`vs-msg vs-me${b.id === heardId ? ' vs-timing' : ''}`}>{b.text}</p>
            </div>
          ),
        )}
        {phase === 'RECORDING' && <p className="vs-note">듣고 있어요…</p>}
        {(phase === 'THINKING' || phase === 'TRANSCRIBING') && (
          <div className="vs-msg vs-ai vs-dots" role="status" aria-label="생각하고 있어요">
            <i />
            <i />
            <i />
          </div>
        )}
        {note && <p className="vs-note">{note}</p>}
      </div>

      {/* 칩은 기다릴 때만 보이고, 그 밖에는 자리만 남긴다 (손 밑에 다른 버튼이 오지 않게) */}
      {chips.length > 0 && (
        <div className="vs-chips" style={{ visibility: canAnswer ? 'visible' : 'hidden' }}>
          {chips.map((c) => (
            <button key={c} type="button" className="vs-chip" onClick={() => onChip(c)} disabled={!canAnswer}>
              {c}
            </button>
          ))}
        </div>
      )}

      {typing ? (
        <form className="vs-type" onSubmit={submitTyping}>
          <input
            autoFocus
            type="text"
            enterKeyHint="send"
            autoComplete="off"
            maxLength={MAX_TEXT}
            placeholder="여기에 써 주세요"
            aria-label="글로 답하기"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
              typeTimer()
            }}
          />
          <button type="submit" className="vs-talk">
            보내기
          </button>
        </form>
      ) : (
        <div className="vs-say">{talk}</div>
      )}
    </section>
  )
}
