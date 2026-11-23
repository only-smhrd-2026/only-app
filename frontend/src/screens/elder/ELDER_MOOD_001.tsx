/**
 * ELDER_MOOD_001 — 홈 위에 뜨는 마음 체크 초대 (D56·D66, 11/23 시안 e-mood-invite). 2주에 한 번, [할게요]/[다음에].
 * 가족에게 어떻게 알리는지 먼저 말한다(동의). 아래에서 올라오는 판(elder.css .elder-sheet).
 */
import { useEffect } from 'react'
import { IC } from '../../components/ElderUi'
import Sim from '../../components/Sim'
import { say, stopSpeaking } from '../../lib/audio'
import { MOOD_PROMPT } from '../../lib/moodCheck'

type Props = { speed: number; onYes: () => void; onLater: () => void }

export default function ELDER_MOOD_001({ speed, onYes, onLater }: Props) {
  useEffect(() => {
    let alive = true
    let retry: (() => void) | undefined
    void say(MOOD_PROMPT.moodInvite, speed).then((heard) => {
      if (heard || !alive) return
      // 자동 재생이 막혔으면 첫 터치(손을 뗄 때)에 다시 읽는다
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
    <>
      <div className="elder-scrim" />
      <section className="elder-sheet" role="dialog" aria-modal="true" aria-labelledby="elder-mood-title">
        <div className="elder-greet">
          <Sim face="curious" size={84} className="elder-sim" />
          <h1 id="elder-mood-title" style={{ flex: 1 }}>요즘 마음이<br />어떠세요?</h1>
        </div>
        <p>여덟 가지만 여쭤볼게요. 2~3분이면 돼요.</p>
        <div className="elder-info">{IC.people}<span>잠·입맛처럼 불편하신 점은 가족에게 쉬운 말로 알려요.</span></div>
        <div className="elder-two">
          <button type="button" className="elder-btn" onClick={onYes} autoFocus>할게요</button>
          <button type="button" className="elder-btn elder-btn--secondary" onClick={onLater}>다음에</button>
        </div>
      </section>
    </>
  )
}
