/**
 * 어르신 화면 공통 조각 (11/23 시안 app.js 의 ic·bub 그대로) — 선 그림 아이콘과 '누르면 다시 읽어 주는 말풍선'.
 * 모양은 elder.css(.elder-ic·.elder-bub·.elder-spk-dot). 꾸밈 그림이라 화면 읽기에는 안 읽힌다.
 */
import { useState, type ReactNode } from 'react'
import { speak } from '../lib/audio'
import Sim from './Sim'

const I = (d: ReactNode, w = 2.2) => (
  <svg className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={w} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {d}
  </svg>
)

export const IC = {
  mic: I(<><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" /></>),
  spk: I(<><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" /></>),
  heart: I(<path d="M12 20s-7.5-4.6-7.5-10A4.5 4.5 0 0 1 12 7.2 4.5 4.5 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z" />),
  heartFill: (
    <svg className="elder-ic" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 20s-7.5-4.6-7.5-10A4.5 4.5 0 0 1 12 7.2 4.5 4.5 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z" />
    </svg>
  ),
  next: I(<path d="M9 5l7 7-7 7" />, 2.6),
  cam: I(<><path d="M4 8h3l1.5-2.5h7L17 8h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></>),
  pic: I(<><rect x="3.5" y="5" width="17" height="14" rx="2.5" /><circle cx="9" cy="10" r="1.6" /><path d="M4 17l5-4.5 3.5 3 3-2.5 4.5 4" /></>),
  chat: I(<path d="M5 6h14v10h-7l-4 3.5V16H5z" />),
  book: I(<><path d="M5 4.5h11a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z" /><path d="M5 17a3 3 0 0 1 3-3h11M9 8.5h6" /></>),
  check: I(<path d="M5 12.5l4.5 4.5L19 7.5" />, 2.8),
  stop: (
    <svg className="elder-ic" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="6" y="6" width="12" height="12" rx="3" fill="currentColor" />
    </svg>
  ),
  phone: I(<path d="M6.5 4h3l1.5 4-2 1.5a11 11 0 0 0 5.5 5.5l1.5-2 4 1.5v3a2 2 0 0 1-2 2A15.5 15.5 0 0 1 4.5 6a2 2 0 0 1 2-2z" />),
  plus: I(<path d="M12 5v14M5 12h14" />, 2.6),
  pen: I(<><path d="M4 20l1-4.5L16.5 4a2 2 0 0 1 3 3L8 18.5z" /><path d="M14.5 6l3 3" /></>),
  people: I(<><circle cx="9" cy="9" r="3.2" /><path d="M3.5 19a5.5 5.5 0 0 1 11 0" /><circle cx="17" cy="10" r="2.5" /><path d="M16 14.6a4.5 4.5 0 0 1 4.8 4.4" /></>),
  redo: I(<><path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3L4.5 9" /><path d="M4.5 4.5V9H9" /></>),
}

/** 더 갈 수 없을 때(연결이 풀림·읽기 실패) — 심심이 + 가운데 말 + (다시 해 볼 수 있으면) [다시 보기]. 홈의 연결 안내와 같은 모양 */
export function ElderStop({ text, onRetry }: { text?: string; onRetry?: () => void }) {
  return (
    <div className="elder-stop">
      <Sim face="ask" size={130} className="elder-sim" />
      <p className="elder-text" role="alert">{text}</p>
      {onRetry && <button type="button" className="elder-btn" onClick={onRetry}>다시 보기</button>}
    </div>
  )
}

/** 기다림 점 셋 · 소리 막대 넷 */
export const Dots = () => <span className="elder-dots" aria-hidden="true"><i /><i /><i /></span>
export const Bars = () => <span className="elder-bars" aria-hidden="true"><i /><i /><i /><i /></span>

/**
 * 꼬마심심이의 말 — 누르면 다시 읽는다(읽는 동안 스피커가 뛴다). 스피커 표시가 혼자 다음 줄로 떨어지지 않게 마지막 낱말에 붙인다.
 * className: elder-bub--tail(왼쪽 꼬리)·--up·--down·--long(긴 글 크기)
 */
export function Bub({ text, speed, className = '', disabled }: { text: string; speed: number; className?: string; disabled?: boolean }) {
  const [on, setOn] = useState(false)
  const cut = text.lastIndexOf(' ') + 1
  return (
    <button
      type="button"
      className={`elder-bub ${className}${on ? ' elder-speaking' : ''}`}
      disabled={disabled}
      onClick={() => {
        setOn(true)
        void speak(text, speed).finally(() => setOn(false))
      }}
    >
      {text.slice(0, cut)}
      <span className="elder-nb">
        {text.slice(cut)}
        <span className="elder-spk-dot" aria-hidden="true">{IC.spk}</span>
      </span>
    </button>
  )
}
