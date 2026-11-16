/** 기분 얼굴 이모지 (D75 — 날씨 그림을 바꿈). 일기 확인·지난 일기·가족 홈·주간 이야기가 같이 쓴다.
 * svg 안의 글자라 부르는 쪽 CSS(.elder-ic 의 너비·높이)대로 커지고 작아진다. 색은 이모지 그대로. */
import type { Mood } from '../api/types'

const FACE: Record<Mood, string> = { GOOD: '😊', SO_SO: '😐', UPSET: '😢', LONELY: '😔' }

export default function MoodIcon({ mood }: { mood: Mood }) {
  return (
    <svg className="elder-ic" viewBox="0 0 24 24" aria-hidden="true">
      <text x="12" y="12" textAnchor="middle" dominantBaseline="central" fontSize="20">
        {FACE[mood]}
      </text>
    </svg>
  )
}
