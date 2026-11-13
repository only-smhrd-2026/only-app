/** 기분 날씨 그림 (맑음·구름·비·달). 일기 확인·지난 일기가 같이 쓴다. 크기·색은 부르는 쪽 CSS(.elder-ic). */
import type { Mood } from '../api/types'

export default function MoodIcon({ mood }: { mood: Mood }) {
  return (
    <svg className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {mood === 'SUNNY' && <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" />
      </>}
      {mood === 'CLOUDY' && <path d="M7 18a4 4 0 0 1 0-8 5 5 0 0 1 9.6 1.5A3.3 3.3 0 0 1 17 18z" />}
      {mood === 'RAINY' && <>
        <path d="M7 14a4 4 0 0 1 0-8 5 5 0 0 1 9.6 1.5A3.3 3.3 0 0 1 17 14z" />
        <path d="M9 17l-1 3M13 17l-1 3M17 17l-1 3" />
      </>}
      {mood === 'MOON' && <path d="M19 14.5A7.5 7.5 0 0 1 9.5 5 7.5 7.5 0 1 0 19 14.5z" />}
    </svg>
  )
}
