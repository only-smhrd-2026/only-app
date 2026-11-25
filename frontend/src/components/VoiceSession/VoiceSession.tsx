/**
 * VoiceSession — 말하기 왕복 상태기계 + 대화 화면 (설계안 3절, D5/D6/D48 → 11/23 시안 e-talk·e-diary-talk·e-care). 홍진성 담당.
 *
 * 모양(11/23): 위에 사진(흰 종이, 자르지 않음, 누르면 크게 — ElderPhoto. 사진이 없으면 큰 심심이) · 가운데 '지금 질문 카드' 하나
 * (심심이 표정이 단계마다 바뀜, 상태 글에 주어 — '심심이가 말하는 중'·'할머니 말씀 듣는 중', 카드를 누르면 다시 들음) ·
 * 아래 받침(답 칩 2개 · [눌러서 말하기] · [글자로]). 첫 질문은 스크롤 없이 한 화면 — 사진이 남는 자리를 쓴다.
 * 지난 대화 쌓기(11/25 실사용 a안, D102): 두 번째 질문부터 사진이 위에 작게 붙고(띠), 그 아래로 지난 대화가 말풍선으로 쌓인다.
 * 맨 아래가 지금 질문 카드, 위로 밀면 처음 대화까지 보인다. 받침은 늘 아래에 고정. 지난 대화는 서버 대화를 턴마다 다시 읽는다.
 *
 *   SPEAKING ─(끝까지 읽음)→ WAITING ─[눌러서 말하기]→ IDLE(마이크 준비) → RECORDING(≤60초) ─[다 말했어요]→ TRANSCRIBING(/api/stt)
 *     → THINKING(/turns, 8초 '조금만요' 소리) → SPEAKING …
 *   끼어들기: SPEAKING 중에도 답 칩·말하기·글자로가 눌린다 — 말을 멈추고 바로 받는다 (11/23 시안).
 *   [다 말했어요]: 첫 0.9초 누름은 무시(손 떨림 두 번 누름), 녹음이 1.5초보다 짧으면 보내지 않고 '잘 못 들었어요'.
 *   들은 말 확인: 신뢰도가 낮으면 서버가 확인 질문(칩 [맞아요]/[다시 말할게요], coach.CONFIRM_SUGGESTIONS)을 준다 →
 *   들은 말을 크게 + 큰 [맞아요]/[다시 말할게요] (시안 check). '맞아요'는 서버가 들은 문장을 답으로 저장한다(D52 ③).
 *   말할 차례: 10초 뒤 소리로 다시 안내(NUDGE). 20초 무응답이면 지금처럼 서버에 NO_RESPONSE(서버 3단계 — 다시 묻기 → 칩만 → 끝).
 *   서버가 다시 물은 뒤 10초에 또 안내하므로 시안의 '10초·30초 안내'와 같아지고, 무응답으로 끝나는 시간(3×20초)은 그대로다.
 *   [글자로](D52 ⑤): 화면 위쪽 판에 입력 칸 + [보내기], [말로 할게요]로 닫음. 쓰는 동안은 무응답을 2분으로 센다.
 *   연결 끊김(/turns 15초 넘김·망 오류): 대화를 끝내지 않는다 → '하신 말씀은 그대로 있어요' + [다시 연결하기]/[나중에 할게요].
 *   다시 연결하면 서버 대화를 먼저 읽어, 답이 이미 들어갔으면 그 다음 질문을, 아니면 같은 답을 다시 보낸다(두 번 저장 안 되게).
 *   [나중에 할게요]는 대화를 끝내지 않고(lib/pausedSession 에 남은 채) 홈으로 — 홈의 '이어서'로 30분 안에 잇는다.
 *   위로(D94 바꿈, 11/23): 힘든 말씀 뒤에도 서버가 대화를 끝내지 않고 위로 턴(AiOut.care)을 준다 → 심심이 웃는 얼굴(엄지·인사 없음),
 *   전화 버튼 없음, 끝 단추는 [조금 쉴게요]. 몸 위급이면 서버가 urgent='BODY' 로 [119 전화하기]를 띄우게 한다(11/19, 그대로).
 *   일기 기분 칩 4개(D75): 얼굴과 함께 2×2. 속상했어요·쓸쓸했어요는 한마디 알아 드린 뒤 보낸다(11/23 시안 MOOD_ACK).
 *   버튼만(칩) 모드: 가족 설정 BUTTON·마이크 못 씀·STT 실패 2번 연속·[다시 말할게요] 2번 연속·STT 하루 상한 (FR-VS-006, D48).
 *   끝까지 못 들려주면(자동 재생 막힘·전화벨) TAP: 카드에 '눌러서 들어 보세요' (D48).
 *   화면이 숨으면(전화·홈 버튼·화면 끔) 녹음·소리·타이머를 멈추고, 돌아오면 지금 질문부터 다시 읽는다. 30분이 넘었으면 끝낸다.
 *   이어서(D52 ⑥): 화면을 떠나도 서버 대화는 마지막 턴 뒤 30분 살아 있다. 대화 번호를 기기에 적어 두고(lib/pausedSession),
 *   다시 열면(새로고침·홈의 '이어서') '아까 하던 이야기를 이어서 할게요.' 뒤에 그 질문부터 다시 읽는다. 끝나면 지운다.
 * 화면을 벗어나면(언마운트) alive=false 로 모든 후속 동작(타이머·재생·요청 뒤 처리)을 멈춘다.
 *
 * 잡담 모양(chat, D106 — 11/25 멘토 아이디어 '심심이랑 이야기'): 말하기 길(녹음·STT·끼어들기·끊김·위로·119)은 위와 같고
 * 모양만 다르다 — 위에 심심이 무대(말할 때 통통·들을 때 갸웃·생각할 때 흔들 + 말 따라 표정), 아래로 ChatGPT 처럼 말풍선
 * (심심이 말은 글자가 하나씩), 답 버튼 없음(말하기·글자로만). 어르신이 일기·사진첩·가족 소식·마음 체크로 가자고 하시면
 * 서버가 go 를 주고 → 말을 다 들려준 뒤 '바로 열어 드릴게요' 판(GO_MS 뒤 저절로, [지금 가기]·[더 이야기할래요]).
 */
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { AiOut, ChatGo, EndReason, SessionGetOut, SessionOut, SttOut, TurnIn, TurnOut } from '../../api/types'
import { cue, micBlockedTip, PROMPT, say, startRecording, stopSpeaking, type Recorder } from '../../lib/audio'
import { clearPaused, RESUME_LEAD, savePaused } from '../../lib/pausedSession'
import ElderPhoto from '../ElderPhoto'
import Sim, { type SimFace } from '../Sim'
import './VoiceSession.css'

type Phase = 'IDLE' | 'RECORDING' | 'TRANSCRIBING' | 'THINKING' | 'SPEAKING' | 'WAITING' | 'TAP' | 'OFFLINE' | 'ENDED'

const RECORD_MS = 60_000
const READY_MS = 900 // [다 말했어요] 첫 0.9초는 무시 — [눌러서 말하기]를 두 번 톡톡 누르면 바로 끝나지 않게 (시안)
// 이보다 짧은 녹음은 STT 에 보내지 않고 '잘 못 들었어요'. 시안은 2초 — '네' 한마디(누르고 말하고 누르기 약 1.5초)는 받으려고 줄였다
const SHORT_MS = 1_500
const NUDGE_MS = 10_000 // 말할 차례에 아무것도 안 누르면 소리로 다시 안내 (시안 10초·30초, 위 머리말)
const WAIT_MS = 20_000 // 무응답 → 서버 NO_RESPONSE (그대로)
const TYPE_MS = 120_000 // 글을 쓰는 동안은 무응답을 늦게 센다 (마지막으로 글자를 바꾼 뒤 2분)
const VERY_SLOW_MS = 8_000
const GIVE_UP_MS = 15_000
const RESUME_MS = 30 * 60_000 // 서버 SESSION_RESUME_MIN — 넘으면 서버가 이미 끝낸 대화
const MAX_RETRY = 2 // [다시 말할게요] 연속 (FR-VS-006 '2회 연속' — 답을 보내면 0)
const MAX_STT_FAIL = 2 // /api/stt 실패 연속 (장애·말소리 없음·시간 초과·망 오류 — 전사되면 0)
const MAX_TEXT = 500 // 서버 TurnIn.text 상한
const YES_CHIP = '맞아요'
const REDO_CHIP = '다시 말할게요' // 서버 확인 질문의 칩(coach.CONFIRM_SUGGESTIONS) — 말할 수 있으면 보내지 않고 바로 녹음
const DEFAULT_CHIPS = ['네', '잘 모르겠어요'] // 모델 칩이 모자랄 때 (FR-VS-003)
const MAX_CHIPS = 2 // 추천 답변은 늘 2개 (11/12 사용자, D52 ④). 서버는 그대로 3개까지 줄 수 있다
const NUDGE = "말씀하시려면 아래 큰 '눌러서 말하기' 버튼을 눌러 주세요." // 11/23 시안 — 색 이름은 안 씀
const OFFLINE = '연결이 잠깐 끊겼어요. 하신 말씀은 그대로 있어요.' // 11/23 시안
// 일기 기분 칩 (D75, 서버 coach 의 기분 질문 칩) → 얼굴 · 속상·쓸쓸은 보내기 전에 한마디 (11/23 시안)
const MOODS: Record<string, { face: string; ack?: string }> = {
  좋았어요: { face: '😊' },
  '그저 그랬어요': { face: '😐' },
  속상했어요: { face: '😢', ack: '속상하셨군요. 말씀해 주셔서 고마워요.' },
  쓸쓸했어요: { face: '😔', ack: '쓸쓸하셨군요. 말씀해 주셔서 고마워요.' },
}

// 잡담(D106) — 가자고 하신 화면으로 데려가기 전 기다리는 시간 · 판 글 · 심심이 글자가 나오는 빠르기(목소리 0.9배와 비슷하게)
const GO_MS = 2_600
const GO_LABEL: Record<ChatGo, string> = { DIARY: '오늘의 이야기 쓰기', ALBUM: '사진첩', NEWS: '가족 소식', MIND: '마음 체크' }
const TYPE_CHAR_MS = 90

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
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
    </>
  ),
  stop: <rect x="6" y="6" width="12" height="12" rx="3" fill="currentColor" stroke="none" />,
  keyboard: (
    <>
      <rect x="2.5" y="6" width="19" height="12" rx="2.5" />
      <path d="M6.5 10h.01M10 10h.01M13.5 10h.01M17 10h.01M7.5 14h9" />
    </>
  ),
  redo: (
    <>
      <path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3L4.5 9" />
      <path d="M4.5 4.5V9H9" />
    </>
  ),
  spk: (
    <>
      <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" />
      <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />
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

/** 보일 추천 답변. 마무리 인사에는 없고, 일기 기분 칩(4개)은 그대로, 나머지는 2개로 맞춘다 (D52 ④) */
function chipsFor(a: AiOut): string[] {
  if (a.question_type === 'CLOSING') return []
  const given = [...new Set(a.suggestions)]
  if (given.length > 3) return given
  const two = given.slice(0, MAX_CHIPS)
  for (const d of DEFAULT_CHIPS) if (two.length < MAX_CHIPS && !two.includes(d)) two.push(d)
  return two
}
const isMoodAsk = (a: AiOut) => a.suggestions.length > 3 && a.suggestions.every((s) => s in MOODS)
const isConfirm = (a: AiOut) => a.question_type !== 'CLOSING' && a.suggestions.includes(REDO_CHIP)
/** 서버 대화 → 지난 말풍선: 끝의 AI 턴(지금 질문 카드에 있는 말)은 뺀다 */
const pastTurns = (turns?: TurnOut[]) => (turns?.at(-1)?.speaker === 'AI' ? turns.slice(0, -1) : (turns ?? []))

type Props = {
  sessionId: string
  initial: SessionOut
  history?: TurnOut[] // 서버에서 다시 읽은 대화(새로고침·'이어서')면 있다 — 첫 질문 앞에 '아까 하던 이야기를…'
  speed: number
  inputMode: 'VOICE' | 'BUTTON'
  who: string // 어르신 호칭 — '할머니 말씀 듣는 중'
  title: string // 화면 읽기용 제목 ('회상 대화'·'일기 대화')
  photo?: { src: string; alt: string } // 없으면 사진 자리에 큰 심심이
  onEnded: (result: SessionOut) => void
  onDone: () => void // 끝난 뒤 [다 들었어요]·[조금 쉴게요]
  onMore?: () => void // 끝난 뒤 [더 이야기할래요] (회상만)
  maxTurns?: number // 회상 5 (서버 MAX_TURNS, D97), 일기 5 (서버 DIARY_TURNS). 진행 숫자는 11/12 뺐다 — 받기만 함
  chat?: ChatProps // 있으면 잡담 모양 (D106)
}
type ChatProps = {
  onGo: (go: ChatGo) => void // 어르신이 가자고 하신 화면으로
  earlier?: TurnOut[] // '지난 이야기'에서 이어서 한 잡담의 말 — 맨 위에 흐리게
  earlierLabel?: string // 그 밑 구분 글 ('11월 24일 이야기')
}

export default function VoiceSession(props: Props) {
  const { sessionId, initial, history, speed, inputMode, who, title, photo, onEnded, onDone, onMore, chat } = props
  const nav = useNavigate()
  const [phase, setPhase] = useState<Phase>('IDLE')
  const [ai, setAi] = useState<AiOut>(initial.ai)
  const [closing, setClosing] = useState(initial.state === 'ENDED') // 지금 질문이 마무리 인사(서버가 끝낸 대화)
  const [locked, setLocked] = useState(initial.input_locked || inputMode === 'BUTTON')
  const [note, setNote] = useState<string>() // 카드에 질문 대신 잠깐 보이는 말 (잘 못 들었어요·기분 한마디 등)
  const [lead, setLead] = useState<string>() // 이어서 연 대화의 첫마디
  const [me, setMe] = useState<string>() // 방금 보낸(들은) 내 말 — 생각하는 중·끊김·확인 질문에서만 보인다
  const [typing, setTyping] = useState(false)
  const [draft, setDraft] = useState('')
  // 지난 대화 말풍선 (D102, [지난 말 보기] 판 D97 을 바꿈) — 서버 대화에서 지금 질문(마지막 AI 턴)을 뺀 것
  const [log, setLog] = useState<TurnOut[]>(() => pastTurns(history))
  const scroller = useRef<HTMLDivElement>(null)
  const [urgent, setUrgent] = useState(initial.urgent) // 몸 위급 — [119 전화하기] (11/19 응급)
  const recorder = useRef<Recorder | null>(null)
  const recAt = useRef(0) // 녹음 시작 시각 (첫 0.9초·너무 짧은 녹음)
  const lockedRef = useRef(locked) // 타이머 안에서 읽는 버튼만 모드
  const retries = useRef(0)
  const sttFails = useRef(0)
  const timers = useRef<number[]>([])
  const alive = useRef(false)
  const last = useRef(initial) // 지금 질문 — 자동 재생 막힘·돌아왔을 때 다시 읽는다
  const seq = useRef(0) // 읽기·녹음 차례 번호: 끼어들기·화면 숨김·다시 읽기면 앞 차례의 뒤 처리를 버린다
  const away = useRef(document.hidden) // 화면이 숨은 동안 (전화·홈 버튼·화면 끔)
  const awayAt = useRef(0)
  const sending = useRef(false) // /turns 응답을 기다리는 중 (두 번 보내지 않게)
  const pending = useRef<TurnIn | null>(null) // 끊겼을 때 다시 보낼 답
  const offline = useRef(false)
  const over = useRef(false) // 끝내는 중·끝남 — 뒤늦은 응답·복귀를 무시
  const lock = useRef<WakeLockSentinel | null>(null)
  const wantLock = useRef(false)
  const [handoff, setHandoff] = useState<ChatGo>() // 잡담: 가자고 하신 화면 — '바로 열어 드릴게요' 판
  const [typed, setTyped] = useState(Infinity) // 잡담: 심심이 말이 지금까지 나온 글자 수

  function later(ms: number, fn: () => void) {
    if (!alive.current) return
    timers.current.push(window.setTimeout(() => alive.current && fn(), ms))
  }
  function clearTimers() {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }
  function setLock(on: boolean) {
    lockedRef.current = on
    setLocked(on)
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

  /** 화면이 정한 끝인사를 카드와 소리로 알리고 끝낸다 (FR-VS-004 'AI 말은 TTS 와 자막을 동시에'). */
  async function sayBye(a: AiOut, reason: EndReason | null) {
    over.current = true
    clearTimers()
    setAi(a)
    setNote(undefined)
    setLead(undefined)
    setClosing(true)
    setPhase('SPEAKING')
    if (alive.current && !away.current) await say(a.text, speed) // 늘 끝난다: mp3 가 3초 안에 안 나오면 기기 목소리(상한 15초)
    if (alive.current) endWith(ended(a, reason))
  }

  /** 질문을 보이고 읽는다. fresh=false 면 같은 질문을 다시 읽기만 (돌아옴·카드 누르기). first = 이어서 연 대화의 첫마디 */
  async function present(r: SessionOut, fresh = true, first?: string) {
    if (!alive.current || over.current) return
    const my = ++seq.current
    clearTimers() // 다시 듣기: 기다리던 무응답을 멈추고 다 읽은 뒤 새로 센다
    last.current = r
    if (r.urgent) setUrgent(r.urgent) // 마무리 말을 읽는 동안에도 119 버튼이 바로 보이게
    setAi(r.ai)
    setClosing(r.state === 'ENDED')
    setNote(undefined)
    if (fresh) {
      setLead(first)
      if (!isConfirm(r.ai)) setMe(undefined) // 지난 답은 다음 질문 밑에 남기지 않는다. 확인 질문은 들은 말을 크게 보인다
    }
    if (r.input_locked) setLock(true)
    if (away.current) return // 숨어 있으면 돌아와서 이 질문부터 읽는다
    setPhase('SPEAKING')
    let heardIt = first ? await say(first, speed) : true
    if (!alive.current || over.current || my !== seq.current) return
    if (heardIt) heardIt = await say(r.ai.text, speed, r.ai.audio_b64)
    if (!alive.current || over.current || my !== seq.current) return
    if (!heardIt) {
      wake(false) // 아무도 안 누르면 화면이 꺼지게
      return setPhase('TAP') // 카드를 누르면 그 터치로 다시 읽는다 (D48)
    }
    if (r.state === 'ENDED') return endWith(r)
    if (chat && r.ai.go) return goSoon(r.ai.go)
    startWaiting()
  }

  /** 잡담: 가자고 하신 화면 — 판을 띄우고 GO_MS 뒤 저절로. 그사이 말하기·글자로를 누르면 판을 접고 이야기를 잇는다 */
  function goSoon(go: ChatGo) {
    clearTimers()
    setHandoff(go)
    setPhase('WAITING')
    later(GO_MS, () => goNow(go))
  }
  function goNow(go: ChatGo) {
    clearTimers()
    stopSpeaking()
    setHandoff(undefined)
    chat?.onGo(go)
  }
  function stayHere() {
    setHandoff(undefined)
    startWaiting()
  }

  function startWaiting() {
    if (!alive.current || over.current || away.current) return // 숨어 있으면 돌아와서 다시 읽은 뒤 센다
    clearTimers()
    setPhase('WAITING')
    wake(true)
    const a = last.current.ai
    if (!lockedRef.current && !isMoodAsk(a) && !isConfirm(a)) later(NUDGE_MS, () => void say(NUDGE, speed))
    later(WAIT_MS, () => sendTurn({ input_type: 'BUTTON', event: 'NO_RESPONSE' }))
  }

  /** 카드에 잠깐 보이고 읽어 준다. 다 읽으면 카드는 다시 질문으로 */
  function tell(msg: string) {
    setNote(msg)
    void say(msg, speed).then(() => alive.current && setNote((n) => (n === msg ? undefined : n)))
  }

  /** 이 대화는 버튼(칩)만 — 까닭을 글·소리로 알리고 기다린다 (FR-VS-006). */
  function buttonsOnly(msg: string) {
    setLock(true)
    tell(msg) // 기다리지 않는다: 칩을 누르면 바로 보낸다
    startWaiting()
  }

  /** 칩·글로 쓴 답을 바로 보낸다 */
  function answer(text: string, input_type: TurnIn['input_type']) {
    if (!alive.current || over.current || sending.current) return // 두 번 눌러도 전송은 한 번
    setMe(text)
    void sendTurn({ text, input_type })
  }

  async function onChip(c: string) {
    if (!canAnswer) return
    if (c === REDO_CHIP && !locked) return redo() // 확인 질문에 '아니요' — 서버를 거치지 않고 바로 다시 말한다
    const input = ai.choice_mode === 'TWO_BUTTONS' ? 'BUTTON' : 'CHIP'
    const ack = isMoodAsk(ai) ? MOODS[c]?.ack : undefined
    if (!ack) return answer(c, input)
    if (note === ack) return // 같은 기분을 또 누름 — 한마디를 읽는 중
    // 속상·쓸쓸: 한마디 알아 드린 뒤 보낸다. 읽는 동안 다른 기분을 누르면 그것으로 바뀐다
    const my = ++seq.current
    clearTimers()
    setNote(ack)
    setPhase('SPEAKING')
    await say(ack, speed)
    if (!alive.current || over.current || my !== seq.current) return
    answer(c, input)
  }

  async function sendTurn(body: TurnIn) {
    if (!alive.current || over.current || sending.current) return // 타이머와 터치가 겹쳐도 한 번만
    sending.current = true
    seq.current += 1 // 끼어들기: 읽던 질문의 뒤 처리(기다리기 시작)를 버린다
    clearTimers()
    stopSpeaking() // 질문·안내를 읽는 중에 답했으면 끊는다
    setHandoff(undefined)
    setNote(undefined)
    setTyping(false)
    setPhase('THINKING')
    pending.current = body
    if (body.text) retries.current = 0 // 답을 보냈으면 [다시 말할게요] 연속이 끊긴다
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
      pending.current = null
      // 잡담: 서버를 다시 읽기 전에 앞 말·내 말을 먼저 올린다 — 말풍선이 잠깐 사라졌다 나타나지 않게 (아래 loadLog 가 바로잡음)
      const said = body.text
      if (chat && said) setLog((l) => [...l, { speaker: 'AI', text: last.current.ai.text }, { speaker: 'ELDER', text: said }])
      void loadLog() // 방금 한 답과 앞 질문이 말풍선으로 올라간다
      if (r.state !== 'ENDED') savePaused({ id: sessionId, kind: initial.kind, at: Date.now() }) // 30분은 마지막 턴부터
      return present(r)
    }
    if (err instanceof ApiError && err.code === 'INPUT_LOCKED') return buttonsOnly(PROMPT.buttons)
    // 이미 끝난 대화(30분 지남·다른 곳에서 끝냄)는 오류가 아니다: 서버에 남은 종료 사유로 인사하고 끝낸다
    if (err instanceof ApiError && err.code === 'SESSION_ENDED') return finish('NO_RESPONSE', PROMPT.thanks)
    // 15초 초과·망 오류(11/23 바꿈): 예전처럼 /end ERROR 로 끝내지 않는다 — 한 말은 서버에 그대로 있고, 다시 이어 갈 수 있다
    goOffline()
  }

  function goOffline() {
    offline.current = true
    seq.current += 1
    clearTimers()
    stopSpeaking()
    wake(false)
    setNote(undefined)
    setPhase('OFFLINE')
    if (!away.current) void say(OFFLINE, speed)
  }

  /** [다시 연결하기]: 서버 대화를 먼저 읽는다. 답이 이미 들어갔으면(응답만 잃음) 그 뒤 질문을, 아니면 같은 답을 다시 보낸다 */
  async function reconnect() {
    if (!offline.current) return
    offline.current = false
    stopSpeaking()
    setPhase('THINKING')
    let s: SessionGetOut
    try {
      s = await api<SessionGetOut>(`/api/elder/sessions/${sessionId}`, { signal: AbortSignal.timeout(GIVE_UP_MS) })
    } catch {
      if (alive.current && !over.current) goOffline()
      return
    }
    if (!alive.current || over.current) return
    if (!s.last_ai) return goOffline() // 질문이 없는 대화 — 일어나지 않지만, 버튼은 남긴다
    const body = pending.current
    if (s.state === 'ENDED' || s.turn_no !== last.current.turn_no || !body) {
      pending.current = null
      const { session_id, kind, photo_url, state, end_reason, turn_no, input_locked } = s
      return present({ session_id, kind, photo_url, ai: s.last_ai, state, end_reason, turn_no, input_locked })
    }
    void sendTurn(body)
  }

  /** [나중에 할게요]: 대화를 끝내지 않고 홈으로. 대화 번호는 기기에 남아 홈에서 '이어서' (30분 안) */
  function pauseForLater() {
    stopSpeaking()
    nav('/elder', { replace: true })
  }

  async function beginRecording() {
    clearTimers()
    stopSpeaking() // 끼어들기: 읽던 질문을 멈춘다
    setHandoff(undefined) // 잡담: 다른 화면으로 가려던 판을 접고 이야기를 잇는다
    setNote(undefined) // '잘 못 들었어요' 안내가 녹음 중에 남지 않게
    setTyping(false)
    setPhase('IDLE') // 마이크 준비 동안 버튼을 꺼서 녹음 두 번 시작·칩 동시 전송을 막는다
    const my = ++seq.current
    let rec: Recorder
    try {
      rec = await startRecording(RECORD_MS)
    } catch (e) {
      if (!alive.current || my !== seq.current) return
      return buttonsOnly(PROMPT.micOff + micBlockedTip(e)) // 아이폰 [취소] 뒤면 '앱을 다시 열면…'을 덧붙인다
    }
    if (!alive.current || my !== seq.current) {
      rec.stop().catch(() => {})
      return
    }
    recorder.current = rec
    cue() // 지금부터 듣는다는 신호 — 준비 중에 한 말은 녹음되지 않는다 (FR-VS-001)
    recAt.current = Date.now()
    setPhase('RECORDING')
    later(RECORD_MS, finishRecording)
  }

  /** [다 말했어요] — 첫 0.9초는 무시 */
  function stopTap() {
    if (Date.now() - recAt.current < READY_MS) return
    void finishRecording()
  }

  async function finishRecording() {
    clearTimers()
    const rec = recorder.current
    recorder.current = null
    if (!rec) return
    const my = seq.current
    if (Date.now() - recAt.current < SHORT_MS) {
      // 너무 짧음 — 말을 못 담았다. STT 를 부르지 않고(실패로 세지 않음) 같은 질문에 다시 말하게 한다
      rec.stop().catch(() => {})
      tell(PROMPT.notHeard)
      return startWaiting()
    }
    setPhase('TRANSCRIBING')
    let blob: Blob
    try {
      blob = await rec.stop()
    } catch {
      // 녹음기가 멈추다 실패 — '듣는 중'에 멈춰 있지 않게 같은 질문에 다시 말하게 한다
      if (!alive.current || my !== seq.current) return
      tell(PROMPT.notHeard)
      return startWaiting()
    }
    if (!alive.current || my !== seq.current) return
    const form = new FormData()
    form.append('audio', blob, 'speech.webm')
    try {
      const r = await api<SttOut>('/api/stt', { form, signal: AbortSignal.timeout(GIVE_UP_MS) }) // 망이 멈춰도 15초면 다시 말하기로
      if (!alive.current || my !== seq.current) return
      sttFails.current = 0
      // 들은 말을 바로 보낸다. 신뢰도가 낮으면 서버가 확인 질문을 준다 (D52 ③)
      setMe(r.transcript)
      void sendTurn({ text: r.transcript, input_type: 'VOICE', stt_confidence: r.confidence })
    } catch (e) {
      if (!alive.current || my !== seq.current) return
      // 429(분당·하루 상한)는 서버 문장을 읽는다. 하루 상한이면 이 대화는 버튼만 (D46)
      // 그 밖의 실패(장애·말소리 없음·시간 초과·망 오류)도 2번 연속이면 버튼만 (FR-VS-006, D48)
      sttFails.current += 1
      if (e instanceof ApiError && e.code === 'STT_DAILY_LIMIT') return buttonsOnly(e.message)
      if (sttFails.current >= MAX_STT_FAIL) return buttonsOnly(PROMPT.buttons)
      tell(e instanceof ApiError && e.status === 429 ? e.message : PROMPT.notHeard)
      startWaiting()
    }
  }

  /** 확인 질문의 [다시 말할게요]: 들은 말을 버리고 바로 다시 녹음. 2번 연속이면 버튼만 */
  function redo() {
    clearTimers()
    setMe(undefined)
    retries.current += 1
    if (retries.current >= MAX_RETRY) return buttonsOnly(PROMPT.buttons)
    void beginRecording()
  }

  /** 글자로 (D52 ⑤). 쓰는 동안은 20초 대신 마지막으로 고친 뒤 2분이 지나야 무응답 */
  function typeTimer() {
    clearTimers()
    later(TYPE_MS, () => sendTurn({ input_type: 'BUTTON', event: 'NO_RESPONSE' }))
  }
  function openTyping() {
    if (!canAnswer) return
    seq.current += 1 // 읽던 질문의 뒤 처리(20초 무응답 시작)를 버린다
    stopSpeaking()
    setHandoff(undefined)
    setPhase('WAITING')
    setTyping(true)
    typeTimer()
  }
  /** 지난 대화를 서버에서 다시 읽는다 (D102). 실패하면 있던 말풍선 그대로 — 대화는 계속된다 */
  async function loadLog() {
    try {
      const s = await api<SessionGetOut>(`/api/elder/sessions/${sessionId}`)
      if (alive.current) setLog(pastTurns(s.turns))
    } catch {
      /* 다음 턴에 다시 읽는다 */
    }
  }
  function closeTyping() {
    setTyping(false)
    setDraft('')
    startWaiting()
  }
  function submitTyping(e: FormEvent) {
    e.preventDefault()
    const text = draft.trim().slice(0, MAX_TEXT)
    if (!text) return // 쓴 말이 없으면 판을 그대로 둔다
    setDraft('')
    setTyping(false)
    answer(text, 'TEXT') // 직접 쓴 글은 확인 없이 바로 보낸다
  }

  /** 카드 누르기 = 다시 듣기 (D51 ⑥). 듣는 중에는 안 눌린다 */
  function replayCard() {
    if (over.current || phase === 'ENDED') return void say(line, speed, line === ai.text ? ai.audio_b64 : null)
    if (phase === 'WAITING' || phase === 'TAP' || phase === 'SPEAKING') {
      if (typing) return void say(ai.text, speed, ai.audio_b64)
      return void present(last.current, false)
    }
    if (phase === 'THINKING' || phase === 'OFFLINE') void say(line, speed)
  }

  /** 화면이 대화를 끝낸다: 서버에 알리고(5초까지) 끝인사. 30분 넘게 떠났다 돌아옴 · 이미 끝난 대화 */
  async function finish(reason: 'NO_RESPONSE', text: string) {
    over.current = true // 이 뒤로 오는 응답·타이머·복귀는 무시
    clearTimers()
    stopSpeaking()
    setNote(undefined)
    setPhase('THINKING') // 응답을 기다리는 동안 다른 버튼이 눌리지 않게
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
    setTyping(false)
  }

  /** 돌아오면 지금 질문부터 다시 읽는다. 답을 보내는 중·끊김이면 그대로. 30분이 넘었으면 끝낸다(공통 기준: 넘으면 홈). */
  function comeBack() {
    if (!away.current) return
    away.current = false
    if (over.current || sending.current || offline.current) return
    if (Date.now() - awayAt.current > RESUME_MS) return void finish('NO_RESPONSE', PROMPT.thanks)
    void present(last.current, false)
  }

  useEffect(() => {
    alive.current = true
    awayAt.current = Date.now() // 숨은 채로 열렸으면 이때부터 센다 (0 이면 돌아오자마자 '30분 지남'으로 끝남)
    if (initial.state !== 'ENDED') savePaused({ id: sessionId, kind: initial.kind, at: Date.now() })
    // 한 틱 미뤄 시작: StrictMode 의 가짜 언마운트가 이 타이머를 지워서 첫 질문은 한 번만 읽힌다
    const start = window.setTimeout(() => present(initial, true, history ? RESUME_LEAD : undefined), 0)
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

  // 새 말풍선·새 질문이 오면 맨 아래(지금 질문)가 보이게 (D102). 위로 밀어 보던 중이어도 새 질문이 오면 내려온다
  // 잡담은 글자가 나올 때마다·판이 뜰 때도 (typed·handoff·phase)
  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTop = el.scrollHeight
  }, [log.length, ai.text, note, typed, handoff, phase])

  // 잡담: 새 심심이 말은 글자가 하나씩 나온다(ChatGPT 처럼). 움직임 줄이기 설정이면 바로 다 보인다
  const isChat = !!chat
  useEffect(() => {
    if (!isChat) return
    const len = ai.text.length
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    let n = still ? len : 0
    setTyped(n)
    if (still) return
    const id = window.setInterval(() => {
      n += 1
      setTyped(n)
      if (n >= len) window.clearInterval(id)
    }, TYPE_CHAR_MS)
    return () => window.clearInterval(id)
  }, [isChat, ai.text])

  const mood = isMoodAsk(ai)
  const confirm = isConfirm(ai)
  // 확인 질문에서 [다시 말할게요]를 눌러 다시 말하는 중 — 받침은 [다 말했어요]로 (11/25 실사용: 확인 버튼이 남아 녹음을 못 멈췄다)
  const redoing = confirm && (phase === 'IDLE' || phase === 'RECORDING' || phase === 'TRANSCRIBING' || phase === 'THINKING')
  const care = !!ai.care
  // 말하는 중에도 답할 수 있다(끼어들기). 마무리 인사·끊김·생각하는 중에는 안 된다
  const canAnswer = (phase === 'WAITING' || phase === 'SPEAKING' || phase === 'TAP') && !closing
  const line =
    phase === 'OFFLINE'
      ? OFFLINE
      : (note ?? (redoing && (phase === 'IDLE' || phase === 'RECORDING') ? '다시 말씀해 주세요.' : lead ? `${lead} ${ai.text}` : ai.text))

  // 심심이 표정 (시안 talkHtml pose). 위로 중에는 웃는 얼굴만 — 손 흔들기·엄지는 쓰지 않는다
  const face: SimFace =
    phase === 'RECORDING' || phase === 'IDLE'
      ? 'curious'
      : phase === 'THINKING' || phase === 'TRANSCRIBING' || phase === 'OFFLINE'
        ? 'ask'
        : phase === 'SPEAKING' || care
          ? 'smile'
          : phase === 'ENDED'
            ? 'thumbs'
            : confirm
              ? 'curious'
              : 'hello'

  let status: ReactNode
  if (phase === 'RECORDING')
    status = (
      <span className="vs-status vs-status--rec">
        <i className="vs-recdot" />
        {who} 말씀 듣는 중
      </span>
    )
  else if (phase === 'THINKING' || phase === 'TRANSCRIBING')
    status = (
      <span className="vs-status">
        심심이가 생각하는 중
        <span className="vs-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
      </span>
    )
  else if (phase === 'SPEAKING')
    status = (
      <span className="vs-status">
        <span className="vs-bars" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
        </span>
        심심이가 말하는 중
      </span>
    )
  else if (phase === 'OFFLINE')
    status = (
      <span className="vs-status">
        <Icon name="redo" />
        잠깐 끊겼어요
      </span>
    )
  else if (phase === 'TAP')
    status = (
      <span className="vs-status">
        <Icon name="spk" />
        눌러서 들어 보세요
      </span>
    )
  else if (phase === 'IDLE') status = <span className="vs-status">잠깐만요</span>
  else if (phase === 'ENDED' || closing) status = <span className="vs-status">꼬마심심이</span>
  else if (confirm) status = <span className="vs-status">이렇게 들었어요</span>
  else if (mood || locked) status = <span className="vs-status">골라 주세요</span>
  else
    status = (
      <span className="vs-status">
        <Icon name="mic" />
        말씀하실 차례예요
      </span>
    )

  let dock: ReactNode
  if (phase === 'OFFLINE') {
    dock = (
      <div className="vs-row">
        <button type="button" className="vs-key vs-key--p vs-wide" onClick={() => void reconnect()}>
          <span className="vs-dot">
            <Icon name="redo" />
          </span>
          다시 연결하기
        </button>
        <button type="button" className="vs-key" onClick={pauseForLater}>
          나중에 할게요
        </button>
      </div>
    )
  } else if (closing) {
    const done = phase === 'ENDED'
    dock = (
      <>
        <button type="button" className="vs-key vs-key--p" onClick={onDone} disabled={!done}>
          <span className="vs-dot">
            <Icon name="check" />
          </span>
          {care ? '조금 쉴게요' : '다 들었어요'}
        </button>
        {onMore && (
          <button type="button" className="vs-key" onClick={onMore} disabled={!done}>
            더 이야기할래요
          </button>
        )}
      </>
    )
  } else if (confirm && !redoing) {
    dock = (
      <>
        {me && <p className="vs-heard">“{me}”</p>}
        <div className="vs-row">
          <button type="button" className="vs-key vs-key--p vs-wide" onClick={() => void onChip(YES_CHIP)} disabled={!canAnswer}>
            <span className="vs-dot">
              <Icon name="check" />
            </span>
            맞아요
          </button>
          <button type="button" className="vs-key" onClick={() => void onChip(REDO_CHIP)} disabled={!canAnswer}>
            다시 말할게요
          </button>
        </div>
      </>
    )
  } else if (mood) {
    dock = (
      <div className="vs-moods">
        {chipsFor(ai).map((c) => (
          <button key={c} type="button" className="vs-key" onClick={() => void onChip(c)} disabled={!canAnswer}>
            <span className="vs-face" aria-hidden="true">
              {MOODS[c].face}
            </span>
            {c}
          </button>
        ))}
      </div>
    )
  } else {
    // 답 버튼 줄은 늘 그 자리에 — 사진 크기가 들썩이지 않게 (시안). 잡담은 답 버튼이 없다 (D106)
    dock = (
      <>
        {!chat && (
          <div className="vs-row">
            {(redoing ? [] : chipsFor(ai)).map((c) => (
              <button key={c} type="button" className="vs-key vs-chip" onClick={() => void onChip(c)} disabled={!canAnswer}>
                {c}
              </button>
            ))}
          </div>
        )}
        <div className="vs-row">
          {phase === 'RECORDING' ? (
            // 듣는 중: 노랑 그대로 + 빨간 점. 남은 시간 숫자는 없다 (60초면 저절로 끝남)
            <button type="button" className="vs-key vs-key--p vs-rec" onClick={stopTap}>
              <span className="vs-dot">
                <Icon name="stop" />
              </span>
              다 말했어요
              <span className="vs-bars" aria-hidden="true">
                <i />
                <i />
                <i />
                <i />
              </span>
            </button>
          ) : locked ? (
            // 버튼만 모드: 칩이 답이고, 글자로는 남긴다 (말을 못 하는 상황용, D52 ⑤)
            <button type="button" className="vs-key" onClick={openTyping} disabled={!canAnswer}>
              <Icon name="keyboard" />
              글자로
            </button>
          ) : (
            <>
              <button
                type="button"
                className={`vs-key vs-key--p vs-talk${phase === 'WAITING' && !typing ? ' vs-nudge' : ''}`}
                onClick={() => void beginRecording()}
                disabled={!canAnswer}
              >
                <span className="vs-dot">
                  <Icon name="mic" />
                </span>
                눌러서 말하기
              </button>
              <button type="button" className="vs-key vs-sq" onClick={openTyping} disabled={!canAnswer} aria-label="글자로 답하기">
                <Icon name="keyboard" />
                <span aria-hidden="true">글자로</span>
              </button>
            </>
          )}
        </div>
      </>
    )
  }

  const sheet = typing && (
    <>
      <div className="vs-scrim" onClick={closeTyping} />
      {/* 자판이 아래를 가리므로 판은 화면 위쪽에, [보내기]는 칸 바로 옆에 (11/23 시안) */}
      <form className="vs-sheet" role="dialog" aria-modal="true" aria-label="글자로 답하기" onSubmit={submitTyping}>
        <h2>글자로 답하기</h2>
        <div className="vs-row">
          <input
            autoFocus
            className="vs-field"
            type="text"
            enterKeyHint="send"
            autoComplete="off"
            maxLength={MAX_TEXT}
            placeholder="여기에 써 주세요"
            aria-label="글자로 답하기"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
              typeTimer()
            }}
          />
          <button type="submit" className="vs-key vs-key--p vs-send">
            보내기
          </button>
        </div>
        <button type="button" className="vs-key" onClick={closeTyping}>
          말로 할게요
        </button>
      </form>
    </>
  )

  if (chat) {
    // 잡담 모양 (D106): 위 심심이 무대 · 말풍선(지난 이야기 → 이번 잡담 → 지금 심심이 말) · 받침
    const earlier = chat.earlier ?? []
    const chatFace: SimFace =
      phase === 'RECORDING' || phase === 'IDLE'
        ? 'curious'
        : phase === 'THINKING' || phase === 'TRANSCRIBING' || phase === 'OFFLINE'
          ? 'ask'
          : care
            ? 'smile'
            : (ai.face ?? 'smile')
    const shown = phase === 'SPEAKING' && line === ai.text ? line.slice(0, typed) : line
    const small = log.length + earlier.length >= 2 // 말풍선이 쌓이면 심심이가 작아져 자리를 내준다
    const live = phase === 'RECORDING' || phase === 'IDLE' || phase === 'TRANSCRIBING'
    return (
      <section className="vs vs--chat">
        <h1 className="vs-sr">{title}</h1>
        <div className={`vs-stage vs-stage--${phase.toLowerCase()}${small ? ' vs-stage--small' : ''}`}>
          <span className="vs-stage-sim">
            <span className="vs-halo" aria-hidden="true" />
            <Sim key={chatFace} face={chatFace} size={170} />
          </span>
          {status}
        </div>
        <div className="vs-scroll" ref={scroller}>
          {earlier.map((t, i) => (
            <p key={`e${i}`} className={`vs-bub vs-bub--${t.speaker === 'AI' ? 'ai' : 'me'} vs-bub--old`}>
              {t.text}
            </p>
          ))}
          {earlier.length > 0 && <p className="vs-sep">{chat.earlierLabel ?? '지난 이야기'}</p>}
          {log.map((t, i) => (
            <p key={i} className={`vs-bub vs-bub--${t.speaker === 'AI' ? 'ai' : 'me'}`}>
              {t.text}
            </p>
          ))}
          {/* 지금 심심이 말 — 누르면 다시 들음 (D51 ⑥) */}
          <button type="button" className="vs-bub vs-bub--ai vs-bub--now" onClick={replayCard} disabled={phase === 'RECORDING'}>
            <span aria-live="polite">{shown}</span>
          </button>
          {live && <p className="vs-bub vs-bub--me vs-bub--live">{phase === 'TRANSCRIBING' ? '받아 적는 중…' : '듣고 있어요…'}</p>}
          {me && (phase === 'THINKING' || phase === 'OFFLINE') && <p className="vs-bub vs-bub--me">{me}</p>}
          {handoff && (
            <div className="vs-go" role="status">
              <b>{GO_LABEL[handoff]}</b>
              <span>바로 열어 드릴게요</span>
              <span className="vs-go-bar" aria-hidden="true">
                <i />
              </span>
              <span className="vs-row">
                <button type="button" className="vs-key vs-key--p" onClick={() => goNow(handoff)}>
                  지금 가기
                </button>
                <button type="button" className="vs-key" onClick={stayHere}>
                  더 이야기할래요
                </button>
              </span>
            </div>
          )}
        </div>
        <div className="vs-dock">
          {urgent === 'BODY' && (
            <a className="vs-key vs-urgent" href="tel:119">
              119 전화하기
            </a>
          )}
          {dock}
        </div>
        {sheet}
      </section>
    )
  }

  return (
    <section className="vs">
      <h1 className="vs-sr">{title}</h1>
      {/* 사진 띠 + 지난 대화 + 지금 질문 — 이 칸만 스크롤 (D102). 받침은 밖에 고정 */}
      <div className="vs-scroll" ref={scroller}>
        <div className={`vs-band${log.length ? ' vs-band--small' : ''}`}>
          {photo ? (
            <ElderPhoto className="vs-photo" src={photo.src} alt={photo.alt} />
          ) : (
            <div className="vs-hero">
              <Sim face={face} size={150} />
            </div>
          )}
        </div>
        {log.map((t, i) => (
          <p key={i} className={`vs-bub vs-bub--${t.speaker === 'AI' ? 'ai' : 'me'}`}>
            <small>{t.speaker === 'AI' ? '꼬마심심이' : who}</small>
            {t.text}
          </p>
        ))}

        <button type="button" className={`vs-card vs-card--${phase.toLowerCase()}`} onClick={replayCard} disabled={phase === 'RECORDING'}>
          <span className="vs-who">
            {photo && <Sim face={face} size={48} />}
            {status}
          </span>
          <span className="vs-line" aria-live="polite">
            {line}
          </span>
          <span className="vs-again">
            <Icon name="spk" />
            다시 듣기
          </span>
        </button>

        {me && (!confirm || redoing) && (phase === 'THINKING' || phase === 'OFFLINE') && <p className="vs-me">{me}</p>}
      </div>

      <div className="vs-dock">
        {/* 몸이 위급하다는 말 (11/19 응급): 전화 앱이 119 를 채운 채 열린다 — 거는 것은 어르신이 한 번 더 누른다 */}
        {urgent === 'BODY' && (
          <a className="vs-key vs-urgent" href="tel:119">
            119 전화하기
          </a>
        )}
        {dock}
      </div>

      {sheet}
    </section>
  )
}
