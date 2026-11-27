/**
 * 가족 홈 돌봄 일지 (11/18 멘토링 — 돌봄 루프). 꼬마심심이가 여쭌 안부를 짧은 줄로.
 * 11/23 시안: 홈 맨 위 요약 카드를 펼치면 7일 칸 아래에 붙는다(그래서 카드 틀 없이 내용만 그린다).
 * 11/27 팀 회의 'AI 티가 많이 나고 글이 많다' → '요즘 말씀/여쭌 것/답' 표와 'AI 말동무' 설명을 빼고
 * 날마다 아이콘 + 한 줄(들은 말씀 · 달라진 점 · 답)만. '여쭌 것'(AI 가 한 일)은 가족에게 필요 없는 말이라 뺐다.
 * 최근 7일 가운데 살핀 것이 있는 날만 온다 — 없으면 아무것도 그리지 않는다.
 * 문장은 서버가 만든다(backend/app/services/care.py). 어르신 말 원문·점수는 오지 않는다.
 */
import { useState } from 'react'
import type { CareDayOut, CareOut } from '../api/types'
import { useFetch } from '../hooks/useFetch'
import FamIcon from './FamIcon'
import './CareCard.css'

const label = (iso: string) =>
  new Date(`${iso}T00:00:00+09:00`).toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric', weekday: 'short' })

function Day({ d }: { d: CareDayOut }) {
  return (
    <ul className="care-lines">
      {d.heard && (
        <li>
          <FamIcon name="chat" />
          {d.heard}
        </li>
      )}
      {d.notes.map((note) => (
        <li key={note}>
          <FamIcon name="sparkle" />
          {note}
        </li>
      ))}
      {d.reaction && (
        <li>
          <FamIcon name="heart" />
          {d.reaction}
        </li>
      )}
    </ul>
  )
}

export default function CareCard({ roomId }: { roomId: number }) {
  const { data } = useFetch<CareOut>(`/api/rooms/${roomId}/care`)
  const [open, setOpen] = useState(false)
  const days = data?.days ?? []
  if (!days.length) return null
  const [first, ...rest] = days
  return (
    <section className="care" aria-label="요즘 안부">
      <h2 className="care-title">
        요즘 안부 <small>{label(first.date)}</small>
      </h2>
      <Day d={first} />
      {open &&
        rest.map((d) => (
          <div key={d.date} className="care-more">
            <p className="fam-mini">{label(d.date)}</p>
            <Day d={d} />
          </div>
        ))}
      {rest.length > 0 && (
        <button type="button" className="fam-text-btn care-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? '접기' : `지난 ${rest.length}일 더 보기`}
        </button>
      )}
    </section>
  )
}
