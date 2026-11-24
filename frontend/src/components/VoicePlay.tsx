/** 가족 목소리 답장 듣기 단추 (D99) — 가족 화면(홈 카드·일기 상세·녹음 들어 보기)이 같이 쓴다. 다시 누르면 멈춘다 */
import { useState } from 'react'
import { playVoice, stopSpeaking } from '../lib/audio'

export default function VoicePlay({ url, sec, label = '목소리' }: { url: string; sec?: number; label?: string }) {
  const [on, setOn] = useState(false)
  async function toggle() {
    if (on) {
      stopSpeaking()
      return setOn(false)
    }
    setOn(true)
    await playVoice(url)
    setOn(false)
  }
  return (
    <button type="button" className="fam-voice" onClick={() => void toggle()} aria-pressed={on}>
      <span aria-hidden="true">{on ? '■' : '▶'}</span>
      {label}
      {sec ? ` ${sec}초` : ''}
    </button>
  )
}
