/** ELDER_TODAY_001 — 홈 위에 뜨는 오늘의 한 장 시트. */
import { useEffect } from 'react'
import type { ElderHomeOut } from '../../api/types'
import todayHandle from '../../assets/today-handle.svg'
import { speak, stopSpeaking } from '../../lib/audio'
import './ELDER_TODAY_001.css'

type Props = {
  home: ElderHomeOut
  busy: boolean
  error?: string
  onTalk: () => void
  onSkip: () => void
}

export default function ELDER_TODAY_001({ home, busy, error, onTalk, onSkip }: Props) {
  const photo = home.today_pick
  const prompt = `${home.elder_name} ${home.elder_honorific}, 같이 이야기해 볼까요?`
  const speed = Number(home.settings.tts_speed) || 0.85

  useEffect(() => {
    if (!photo) return
    const retryAfterGesture = () => {
      window.removeEventListener('pointerup', retryAfterGesture)
      window.removeEventListener('keydown', retryAfterGesture)
      void speak(prompt, speed)
    }
    void speak(prompt, speed)
    // 자동 읽기가 막혔을 때만(크롬은 막히면 대기 줄에 안 넣어 speaking=false) 첫 터치·키에 다시 읽는다.
    // 터치는 손을 뗄 때(pointerup)부터 소리가 허용된다 — pointerdown 이면 폰에서 또 막힌다.
    if (!('speechSynthesis' in window) || !window.speechSynthesis.speaking) {
      window.addEventListener('pointerup', retryAfterGesture, { once: true })
      window.addEventListener('keydown', retryAfterGesture, { once: true })
    }
    return () => {
      window.removeEventListener('pointerup', retryAfterGesture)
      window.removeEventListener('keydown', retryAfterGesture)
      stopSpeaking()
    }
  }, [photo, prompt, speed])
  if (!photo) return null

  return (
    <div className="elder-today-overlay">
      <section className="elder-today-sheet" role="dialog" aria-modal="true" aria-labelledby="elder-today-title">
        <img className="elder-today-handle" src={todayHandle} alt="" />
        <h1 id="elder-today-title">오늘의 한 장이 왔어요</h1>
        <div className="elder-today-photo-wrap">
          <img className="elder-today-photo" src={photo.photo_url} alt="가족이 올린 오늘의 사진" />
          <span className="elder-today-caption">가족이 올린 사진</span>
        </div>
        <p className="elder-today-prompt">{prompt}</p>
        {error && <p className="elder-text" role="alert">{error}</p>}
        <div className="elder-today-actions">
          <button className="elder-btn" onClick={onTalk} disabled={busy} autoFocus>
            {busy ? '잠시만요' : <>이야기<wbr />하기</>}
          </button>
          <button className="elder-btn elder-btn--secondary" onClick={onSkip} disabled={busy}>건너<wbr />뛰기</button>
        </div>
      </section>
    </div>
  )
}
