/** 가족 목소리 답장 듣기 단추 (D99) — 가족 화면(홈 카드·일기 상세·녹음 들어 보기)이 같이 쓴다. 다시 누르면 멈춘다 */
import { useEffect, useRef, useState } from 'react'
import { playVoice, stopSpeaking } from '../lib/audio'

export default function VoicePlay({ url, sec, label = '목소리' }: { url: string; sec?: number; label?: string }) {
  const [playing, setPlaying] = useState<string>() // 지금 트는 주소 — 새 답장으로 주소가 바뀌면 멈춘 것으로 본다
  const active = useRef(false)
  // 주소가 바뀌거나(새 답장) 화면을 떠나면 이 단추가 틀던 소리를 멈춘다
  useEffect(
    () => () => {
      if (active.current) stopSpeaking()
    },
    [url],
  )
  const on = playing === url
  async function toggle() {
    if (on) {
      stopSpeaking()
      return setPlaying(undefined)
    }
    setPlaying(url)
    active.current = true
    await playVoice(url)
    active.current = false
    setPlaying((p) => (p === url ? undefined : p))
  }
  return (
    <button type="button" className="fam-voice" onClick={() => void toggle()} aria-pressed={on}>
      <span aria-hidden="true">{on ? '■' : '▶'}</span>
      {label}
      {sec ? ` ${sec}초` : ''}
    </button>
  )
}
