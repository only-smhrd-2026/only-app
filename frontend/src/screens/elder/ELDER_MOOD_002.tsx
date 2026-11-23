/**
 * ELDER_MOOD_002 — 마음 체크 (D56·D66 → 11/23 시안 e-mood). 체크 5가지(PHQ-8·PHQ-9·UCLA-3·GAD-7·SMCQ) 공통 화면.
 * 종류는 앞 화면이 넘긴 state.kind(홈 초대·ELDER_MIND_001) 또는 주소 ?kind=, 없으면 PHQ-8. 문항·보기 글은 lib/moodCheck.ts 한 곳.
 *
 * 한 번에 한 문항: 위에 진행 점 + '3 / 8' + [그만할래요], 심심이, 질문 말풍선(누르면 다시 읽음), 아래 보기(원래 칸 수 그대로).
 *   - 문항이 뜬 뒤 첫 0.8초 누름은 무시(두 번 눌림), 고른 답은 0.7초 보여 준 뒤 다음 문항으로(안 눌린 줄 알고 또 누르지 않게) — D51 ⑥.
 *   - 갤럭시 뒤로 키 = 앞 질문: 문항마다 방문 기록(history state 의 q)을 하나씩 쌓아서, 뒤로 키가 앞 문항으로 돌아간다.
 *   - [그만할래요]·도중에 나가면 저장하지 않는다(다음에 홈에서 다시 권한다).
 * 끝: 서버가 준 얼굴·제목·덧붙임만(점수 없음, NFR-DE-003) + [내 마음으로]·[홈으로]. 끝난 뒤 뒤로 키 = 홈(끝난 흐름을 다시 시작하지 않게).
 * PHQ-9 9번이 0 보다 크면 서버가 가족에게 급한 알림을 보내지만, 화면·소리는 알렸다고 말하지 않는다(서버 say = 위로 한마디).
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { MoodCheckIn, MoodCheckSavedOut, MoodKind } from '../../api/types'
import { Bub } from '../../components/ElderUi'
import Sim from '../../components/Sim'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { say, stopSpeaking } from '../../lib/audio'
import { CHECKS, checkKind, ordinal } from '../../lib/moodCheck'
import './ELDER_MOOD_002.css'

const READY_MS = 800 // 문항이 뜬 뒤 이만큼은 답이 안 눌린다
const PICKED_MS = 700 // 고른 답을 보여 주는 시간
const THANKS = '말씀해 주셔서 고마워요.'

type MoodNavState = ElderNavState & { kind?: MoodKind; q?: number }

export default function ELDER_MOOD_002() {
  const nav = useNavigate()
  const loc = useLocation()
  const [params] = useSearchParams()
  const st = (loc.state ?? {}) as MoodNavState
  const [kind] = useState(() => checkKind(st.kind ?? params.get('kind')))
  const [home] = useState(st.home)
  const check = CHECKS[kind]
  const n = check.items.length
  const speed = Number(home?.settings.tts_speed) || 0.9
  const live = useLive()
  const q = st.q ?? 0 // 지금 문항 번호 — 방문 기록에 있어서 뒤로 키가 줄인다
  const [answers, setAnswers] = useState<number[]>([])
  const k = Math.min(q, answers.length, n - 1) // 새로고침으로 답이 비었으면 앞에서부터
  const [picked, setPicked] = useState<{ k: number; v: number }>()
  const [step, setStep] = useState<'asking' | 'saving' | 'failed' | 'done'>('asking')
  const [result, setResult] = useState<MoodCheckSavedOut>()
  const [error, setError] = useState<string>()
  const readyAt = useRef(0)
  const pickTimer = useRef<number | undefined>(undefined)
  const endQ = useRef(-1) // 다 답했을 때의 q — 그 뒤 뒤로 키가 오면 홈으로
  const item = check.items[k]

  // 새로고침으로 답을 잃었는데 기록이 중간 문항이면 첫 문항 기록으로 바꿔 둔다(뒤로 키가 엉뚱한 문항으로 가지 않게)
  useEffect(() => {
    if (q > 0 && answers.length === 0) nav(loc.pathname + loc.search, { replace: true, state: { ...st, q: 0 } })
    // 처음 한 번만
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 문항을 읽는다: '세 번째 질문이에요.' 다음 질문. 읽는 중에 답하면 끊긴다
  useEffect(() => {
    if (step !== 'asking') return
    readyAt.current = Date.now() + READY_MS
    let on = true
    void say(ordinal(k), speed).then((ok) => on && ok && say(item, speed))
    return () => {
      on = false
      stopSpeaking()
    }
  }, [k, item, step, speed])

  // 뒤로 키: 고르는 중이던 답은 버린다. 다 답한 뒤면 홈으로
  useEffect(() => {
    window.clearTimeout(pickTimer.current)
    setPicked(undefined)
    if (step !== 'asking' && endQ.current !== q) nav('/elder', { replace: true })
  }, [q, step, nav])

  useEffect(() => () => window.clearTimeout(pickTimer.current), [])

  useEffect(() => {
    if (step !== 'done' || !result) return
    void say(result.say ?? `${THANKS} ${result.title}. ${result.sub}`.trim(), speed)
    return () => stopSpeaking()
  }, [step, result, speed])

  async function save(all: number[]) {
    setStep('saving')
    setError(undefined)
    try {
      const body: MoodCheckIn = { kind, answers: all }
      const saved = await api<MoodCheckSavedOut>('/api/elder/mood-check', { body })
      if (!live.current) return
      setResult(saved)
      setStep('done')
    } catch (e) {
      if (!live.current) return
      const text = e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 해 주세요.'
      setError(text)
      setStep('failed')
      void say(text, speed)
    }
  }

  function answer(v: number) {
    if (step !== 'asking' || picked || Date.now() < readyAt.current) return
    stopSpeaking()
    setPicked({ k, v })
    const next = [...answers.slice(0, k), v]
    pickTimer.current = window.setTimeout(() => {
      if (!live.current) return
      setPicked(undefined)
      setAnswers(next)
      if (next.length === n) {
        endQ.current = q
        void save(next)
      } else nav(loc.pathname + loc.search, { state: { ...st, q: k + 1 } })
    }, PICKED_MS)
  }

  const toMind = () => nav('/elder/mind', { replace: true, state: { home } })
  const toHome = () => nav('/elder', { replace: true })

  if (step === 'done' && result)
    return (
      <main className="elder elder--fit">
        <div className="elder-grow elder-center">
          <span className="elder-face mood-face" aria-hidden="true">{result.face}</span>
          <h1>{result.title}</h1>
          {result.sub && <p className="elder-sub">{result.sub}</p>}
          <p className="elder-sub">{THANKS} 결과는 내 마음에서 다시 볼 수 있어요.</p>
        </div>
        <button type="button" className="elder-btn" onClick={toMind}>내 마음으로</button>
        <button type="button" className="elder-btn elder-btn--secondary" onClick={toHome}>홈으로</button>
      </main>
    )

  if (step !== 'asking')
    return (
      <main className="elder elder--fit">
        <p className="elder-text" role={error ? 'alert' : 'status'}>{error ?? '잠시만요…'}</p>
        {step === 'failed' && (
          <>
            <button type="button" className="elder-btn elder-bottom" onClick={() => void save(answers)}>다시 보내기</button>
            <button type="button" className="elder-btn elder-btn--secondary" onClick={toHome}>홈으로</button>
          </>
        )}
      </main>
    )

  const shown = picked?.k === k ? picked.v : undefined
  return (
    <main className="elder elder--fit">
      <h1 className="elder-sr">{check.name}</h1>
      <div className="mood-top">
        <div className="elder-steps" role="img" aria-label={`${n}가지 가운데 ${k + 1}번째`}>
          {check.items.map((_, i) => <i key={i} className={i <= k ? 'on' : undefined} />)}
        </div>
        <span className="elder-eyebrow" aria-hidden="true">{k + 1} / {n}</span>
        <button type="button" className="elder-btn elder-btn--secondary elder-btn--sm" onClick={toHome}>그만할래요</button>
      </div>
      <Sim face="hello" size={150} className="elder-simflex" />
      <Bub text={item} speed={speed} className="elder-bub--long elder-bub--up" />
      <div className="elder-answers">
        {check.answers.map((label, v) => (
          <button
            key={label}
            type="button"
            className={`elder-chip${shown === v ? ' elder-btn--on' : ''}`}
            aria-pressed={shown === v}
            onClick={() => answer(v)}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="elder-sr" aria-live="polite">{shown !== undefined ? `${check.answers[shown]}, 골랐어요` : ''}</p>
    </main>
  )
}
