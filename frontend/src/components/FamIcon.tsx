/** 가족 화면 그림 (D70) — 목업 설계자료/목업_1115_가족 의 const I 도형 그대로(24 칸, 선 굵기 2). 기분 날씨는 MoodIcon. */
import type { ReactNode } from 'react'

const ICONS = {
  home: <path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z" />,
  imagePlus: (
    <>
      <rect x="3" y="6" width="14" height="14" rx="2.5" />
      <circle cx="8" cy="11" r="1.5" />
      <path d="M17 16.5l-3.5-3.5L6 20" />
      <path d="M20 3v6M17 6h6" />
    </>
  ),
  pencil: (
    <>
      <path d="M4 20h4L19 9l-4-4L4 16z" />
      <path d="M13.5 6.5l4 4" />
    </>
  ),
  calendar: (
    <>
      <rect x="4" y="5" width="16" height="15" rx="2.5" />
      <path d="M4 10h16M8.5 3v4M15.5 3v4" />
      <path d="M8 14h.01M12 14h.01M16 14h.01" />
    </>
  ),
  family: (
    <>
      <circle cx="8.5" cy="8" r="3" />
      <path d="M2.5 20a6 6 0 0 1 12 0" />
      <circle cx="17" cy="9.5" r="2.4" />
      <path d="M16 14.3a5 5 0 0 1 5.5 5.2" />
    </>
  ),
  bell: (
    <>
      <path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </>
  ),
  chevDown: <path d="M6 9l6 6 6-6" />,
  chevRight: <path d="M9 6l6 6-6 6" />,
  arrowLeft: <path d="M19 12H5M11 6l-6 6 6 6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  lock: (
    <>
      <rect x="5" y="11" width="14" height="9" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </>
  ),
  sparkle: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  heart: <path d="M12 20s-7-4.6-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.4-7 10-7 10z" />,
  phone: <path d="M6 3h4l1.5 5L9 9.5a11 11 0 0 0 5.5 5.5L16 12.5l5 1.5v4a2 2 0 0 1-2 2A16 16 0 0 1 4 5a2 2 0 0 1 2-2z" />,
} satisfies Record<string, ReactNode>

export type FamIconName = keyof typeof ICONS

export default function FamIcon({ name, className }: { name: FamIconName; className?: string }) {
  return (
    <svg
      className={className ? `fam-ic ${className}` : 'fam-ic'}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ICONS[name]}
    </svg>
  )
}
