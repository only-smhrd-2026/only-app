/**
 * 어르신 달력 한 달 (11/25 지난 가족 소식 달력을 11/27 팀 회의에서 지난 일기에도 — 둘 다 크게).
 * 일기·소식이 있는 날 = 그날 사진(없으면 심심이)·2개 이상이면 수, 누름. 나머지 날은 글자만(누를 수 없음).
 * 모양은 elder.css 의 .fcal-*. 달 넘기기는 있는 달로만(prev·next 가 없으면 버튼 없음).
 */
import { useState } from 'react'
import type { DiaryOut } from '../api/types'
import Sim from './Sim'

const WD = ['일', '월', '화', '수', '목', '금', '토']
/** ISO 시각 → 한국 날짜 'YYYY-MM-DD' */
export const kstDay = (iso: string) => new Date(iso).toLocaleDateString('en-CA', { timeZone: 'Asia/Seoul' })

export type CalMonth = { month: string; diaries: DiaryOut[]; prev_month: string | null; next_month: string | null }

type Props = {
  title: string
  noun: string // '가족 소식'·'일기' — 날 칸 읽기·아래 개수 줄
  empty: string // 그 달에 하나도 없을 때 아래 줄
  out: CalMonth
  onOpen: (i: number) => void // out.diaries 의 번호
  onMonth: (month: string) => void
}

export default function ElderCalendar({ title, noun, empty, out, onOpen, onMonth }: Props) {
  const [y, m] = out.month.split('-').map(Number)
  const lead = new Date(y, m - 1, 1).getDay()
  const days = new Date(y, m, 0).getDate()
  const [today] = useState(() => kstDay(new Date().toISOString()))
  const byDay = new Map<string, number[]>() // 'YYYY-MM-DD' → 그날 번호들
  out.diaries.forEach((d, i) => byDay.set(kstDay(d.posted_at), [...(byDay.get(kstDay(d.posted_at)) ?? []), i]))
  const go = (to: string | null, label: string) =>
    to ? <button type="button" className="elder-btn elder-btn--secondary elder-btn--sm" onClick={() => onMonth(to)}>{label}</button> : <span />
  return (
    <>
      <h1>{title}</h1>
      <div className="fcal-month">
        {go(out.prev_month, `◀ ${Number(out.prev_month?.slice(5))}월`)}
        <b>{m}월</b>
        {go(out.next_month, `${Number(out.next_month?.slice(5))}월 ▶`)}
      </div>
      <div className="fcal-week" aria-hidden="true">{WD.map((w) => <span key={w}>{w}</span>)}</div>
      <div className="fcal-grid">
        {Array.from({ length: lead }, (_, i) => <span key={`b${i}`} />)}
        {Array.from({ length: days }, (_, i) => {
          const date = `${out.month}-${String(i + 1).padStart(2, '0')}`
          const items = byDay.get(date)
          if (!items) return <span key={date} className={`fcal-day${date === today ? ' today' : ''}${date > today ? ' fut' : ''}`}>{i + 1}</span>
          const pic = items.map((j) => out.diaries[j].illustration_url).find(Boolean)
          return (
            <button key={date} type="button" className={`fcal-day${pic ? '' : ' sim'}`} onClick={() => onOpen(items[0])} aria-label={`${m}월 ${i + 1}일 ${noun} ${items.length}개`}>
              {pic ? <img src={pic} alt="" loading="lazy" /> : <Sim face="smile" size={40} />}
              <span className="fcal-num">{i + 1}</span>
              {items.length > 1 && <span className="fcal-cnt">{items.length}</span>}
            </button>
          )
        })}
      </div>
      <p className="elder-sub fcal-count">{out.diaries.length ? `${m}월 ${noun} ${out.diaries.length}개 · 사진을 누르면 읽어 드려요` : empty}</p>
    </>
  )
}
