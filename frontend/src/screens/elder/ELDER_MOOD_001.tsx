/**
 * ELDER_MOOD_001 — 홈 위에 뜨는 마음 체크 초대 (D56·D66). 2주에 한 번, [할게요]/[다음에].
 * 가족에게 어떻게 알리는지 먼저 말한다(동의). 모양은 오늘의 한 장 시트(ELDER_TODAY_001)와 같다.
 */
import { useEffect } from 'react'
import { say, stopSpeaking } from '../../lib/audio'
import { MOOD_PROMPT } from '../../lib/moodCheck'
import './ELDER_TODAY_001.css'

type Props = { speed: number; onYes: () => void; onLater: () => void }

export default function ELDER_MOOD_001({ speed, onYes, onLater }: Props) {
  useEffect(() => {
    let alive = true
    let retry: (() => void) | undefined
    void say(MOOD_PROMPT.moodInvite, speed).then((heard) => {
      if (heard || !alive) return
      // 자동 재생이 막혔으면 첫 터치(손을 뗄 때)에 다시 읽는다 — ELDER_TODAY_001 과 같은 방법
      retry = () => void say(MOOD_PROMPT.moodInvite, speed)
      window.addEventListener('pointerup', retry, { once: true })
    })
    return () => {
      alive = false
      if (retry) window.removeEventListener('pointerup', retry)
      stopSpeaking()
    }
  }, [speed])

  return (
    <div className="elder-today-overlay">
      <section className="elder-today-sheet" role="dialog" aria-modal="true" aria-labelledby="elder-mood-title">
        <span className="elder-today-handle" aria-hidden="true" />
        <svg className="elder-mood-heart" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 20.5s-7.5-4.6-7.5-10.2a4.3 4.3 0 0 1 7.5-2.8 4.3 4.3 0 0 1 7.5 2.8c0 5.6-7.5 10.2-7.5 10.2z" />
        </svg>
        <h1 id="elder-mood-title">요즘 마음이 어떠세요?</h1>
        <p>여덟 가지만 여쭤볼게요.<br />2~3분이면 돼요.</p>
        <p className="elder-today-cap">답하신 내용은 가족에게 “요즘 어떠신지” 한 줄로만 알려요.</p>
        <div className="elder-two">
          <button className="elder-btn" onClick={onYes} autoFocus>할게요</button>
          <button className="elder-btn elder-btn--secondary" onClick={onLater}>다음에</button>
        </div>
      </section>
    </div>
  )
}
