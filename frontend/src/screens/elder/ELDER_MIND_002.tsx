/**
 * ELDER_MIND_002 — 기억력 놀이 (11/23 시안 e-memgame). 검사처럼 보이지 않게 '놀이'.
 * 낱말 세 개 보기 → 잠깐 다른 이야기(답은 저장 안 함) → 여섯 개 중 세 개 고르기 → 몇 개 기억하셨는지(놀이라 늘 웃는 얼굴).
 * 낱말은 하루마다 바뀐다(lib/moodCheck memSetFor). 맞힌 수는 서버에 MEMGAME 으로 남긴다(같은 날 두 번 = 1줄).
 * 저장이 안 돼도 결과는 그대로 보여 준다 — 놀이라서 다시 하라고 하지 않는다.
 */
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { MoodCheckIn } from '../../api/types'
import { Bub } from '../../components/ElderUi'
import Sim from '../../components/Sim'
import type { ElderNavState } from '../../hooks/useElderSession'
import { say, stopSpeaking } from '../../lib/audio'
import { memSetFor } from '../../lib/moodCheck'
import './ELDER_MIND_002.css'

const ASIDE = '잠깐 다른 이야기예요. 오늘 아침에는 뭘 드셨어요?'

export default function ELDER_MIND_002() {
  const nav = useNavigate()
  const { home } = (useLocation().state ?? {}) as ElderNavState
  const speed = Number(home?.settings.tts_speed) || 0.9
  const [set] = useState(() => memSetFor())
  const [stage, setStage] = useState<0 | 1 | 2 | 3>(0)
  const [picks, setPicks] = useState<string[]>([])
  const words = set.words.map((w) => w[1])
  const ok = picks.filter((w) => words.includes(w)).length
  const title = ok === 3 ? '세 개 다 기억하셨어요!' : `세 개 중 ${ok}개 기억하셨어요`

  useEffect(() => {
    const text = [`이 낱말 세 개를 기억해 주세요. ${words.join(', ')}.`, ASIDE, '아까 본 낱말을 골라 주세요.', `${title}. 내일 또 해 봐요.`][stage]
    void say(text, speed)
    return () => stopSpeaking()
    // 단계가 바뀔 때만 읽는다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage])

  function pick(w: string) {
    setPicks((p) => (p.includes(w) ? p.filter((x) => x !== w) : p.length < 3 ? [...p, w] : p))
  }

  function finish() {
    const body: MoodCheckIn = { kind: 'MEMGAME', answers: [ok] }
    void api('/api/elder/mood-check', { body }).catch(() => {})
    setStage(3)
  }

  const toMind = () => nav('/elder/mind', { replace: true, state: { home } })

  if (stage === 0)
    return (
      <main className="elder elder--fit">
        <h1>
          이 낱말 세 개를
          <br />
          기억해 주세요
        </h1>
        <div className="elder-grow mem-words">
          {set.words.map(([e, w]) => (
            <span key={w}>
              <i className="elder-face" aria-hidden="true">{e}</i>
              {w}
            </span>
          ))}
        </div>
        <button type="button" className="elder-btn" onClick={() => setStage(1)}>다 외웠어요</button>
      </main>
    )

  if (stage === 1)
    return (
      <main className="elder elder--fit">
        <h1 className="elder-sr">기억력 놀이</h1>
        <Sim face="ask" size={150} className="elder-simflex" />
        <Bub text={ASIDE} speed={speed} className="elder-bub--long elder-bub--up" />
        <div className="elder-row elder-bottom">
          <button type="button" className="elder-chip mem-grow" onClick={() => setStage(2)}>밥이랑 국이요</button>
          <button type="button" className="elder-chip mem-grow" onClick={() => setStage(2)}>잘 모르겠어요</button>
        </div>
      </main>
    )

  if (stage === 2)
    return (
      <main className="elder elder--fit">
        <h1>
          아까 본 낱말을
          <br />
          골라 주세요
        </h1>
        <p className="elder-sub">세 개를 눌러 주세요.</p>
        <div className="elder-grow mem-choices">
          {set.choices.map(([e, w]) => {
            const on = picks.includes(w)
            return (
              <button key={w} type="button" className={`elder-btn elder-btn--secondary${on ? ' elder-btn--on' : ''}`} aria-pressed={on} onClick={() => pick(w)}>
                <i className="elder-face" aria-hidden="true">{e}</i>
                {w}
              </button>
            )
          })}
        </div>
        <button type="button" className="elder-btn" disabled={picks.length !== 3} onClick={finish}>다 골랐어요</button>
      </main>
    )

  return (
    <main className="elder elder--fit">
      <div className="elder-grow elder-center">
        <div className="elder-halo elder-pop">
          {/* elder-sim 이 없으면 빛 번짐(.elder-halo::before)이 그림 위에 그려져 가운데가 뿌옇다 (11/24 실사용) */}
          <Sim face="thumbs" size={150} className="elder-sim" />
        </div>
        <h1>{title}</h1>
        <p className="elder-sub">{words.join(' · ')}였어요. 내일 또 해 봐요.</p>
      </div>
      <button type="button" className="elder-btn" onClick={toMind}>내 마음으로</button>
    </main>
  )
}
