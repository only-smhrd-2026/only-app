/**
 * ELDER_MOOD_002 — 마음 체크 8문항 (D56·D66). 한 번에 하나씩 읽어 주고 보기 4개로 답한다.
 * 끝에는 고맙다는 말만 — 결과·점수는 어르신께 보이지 않는다(가족 홈 마음 카드에 3단계 문장으로만).
 * 답은 8개를 다 골라야 서버에 간다. 도중에 나가면 저장하지 않는다(다음 날 홈에서 다시 권한다).
 * 문항·보기 글은 lib/moodCheck.ts 한 곳 — 바꾸면 mp3 도 다시 만든다.
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { MoodCheckIn } from '../../api/types'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { say, stopSpeaking } from '../../lib/audio'
import { MOOD_ANSWERS, MOOD_ITEMS, MOOD_PROMPT } from '../../lib/moodCheck'

const TAP_GAP_MS = 600 // 보기 버튼이 같은 자리에 있어서, 두 번 눌림이 다음 문항의 답이 되지 않게

export default function ELDER_MOOD_002() {
  const nav = useNavigate()
  const { home } = (useLocation().state ?? {}) as ElderNavState
  const speed = Number(home?.settings.tts_speed) || 0.85
  const live = useLive()
  const [answers, setAnswers] = useState<number[]>([])
  const [step, setStep] = useState<'asking' | 'saving' | 'failed' | 'done'>('asking')
  const [error, setError] = useState<string>()
  const [saying, setSaying] = useState(false)
  const sayingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const tappedAt = useRef(0)
  const k = answers.length
  const item = MOOD_ITEMS[k] as string | undefined // 8개를 다 답하면 undefined

  useEffect(() => {
    if (step === 'done') void say(MOOD_PROMPT.moodThanks, speed)
    else if (step === 'asking' && item) void say(item, speed) // 읽는 중에 답하면 끊기고 다음 문항을 읽는다
    return () => stopSpeaking()
  }, [item, step, speed])

  useEffect(() => () => clearTimeout(sayingTimer.current), [])

  function replay(text: string) {
    void say(text, speed)
    setSaying(true)
    clearTimeout(sayingTimer.current)
    sayingTimer.current = setTimeout(() => setSaying(false), 1_400)
  }

  async function save(all: number[]) {
    setStep('saving')
    setError(undefined)
    try {
      const body: MoodCheckIn = { answers: all }
      await api('/api/elder/mood-check', { body })
      if (live.current) setStep('done')
    } catch (e) {
      if (!live.current) return
      const text = e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 해 주세요.'
      setError(text)
      setStep('failed')
      void say(text, speed)
    }
  }

  function answer(value: number) {
    if (step !== 'asking' || !item || Date.now() - tappedAt.current < TAP_GAP_MS) return
    tappedAt.current = Date.now()
    const next = [...answers, value]
    setAnswers(next)
    if (next.length === MOOD_ITEMS.length) void save(next)
  }

  const speaker = (
    <svg className="elder-spk" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 9.5v5h3.2L12 18.5v-13L7.2 9.5z" />
      <path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.3 6.3a8 8 0 0 1 0 11.4" />
    </svg>
  )
  const paper = (text: string) => (
    <button type="button" className={`elder-paper${saying ? ' elder-saying' : ''}`} onClick={() => replay(text)}>
      <span>{text}</span>
      {speaker}
    </button>
  )

  return (
    <main className="elder elder--fit">
      {step === 'done' ? (
        <>
          {paper(MOOD_PROMPT.moodThanks)}
          <button className="elder-btn elder-bottom" onClick={() => nav('/elder', { replace: true })}>홈으로</button>
        </>
      ) : step === 'asking' && item ? (
        <>
          <div className="elder-steps" role="img" aria-label={`${MOOD_ITEMS.length}개 중 ${k + 1}번째`}>
            {MOOD_ITEMS.map((_, n) => <i key={n} className={n <= k ? 'on' : undefined} />)}
          </div>
          {paper(item)}
          <div className="elder-answers">
            {MOOD_ANSWERS.map((label, value) => (
              <button key={label} type="button" className="elder-chip" onClick={() => answer(value)}>{label}</button>
            ))}
          </div>
        </>
      ) : (
        <>
          <p className="elder-text" role={error ? 'alert' : 'status'}>{error ?? '잠시만요…'}</p>
          {step === 'failed' && <button className="elder-btn elder-bottom" onClick={() => void save(answers)}>다시 보내기</button>}
        </>
      )}
    </main>
  )
}
