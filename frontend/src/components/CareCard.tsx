/**
 * 가족 홈 돌봄 일지 (11/18 멘토링 — 돌봄 루프). 꼬마심심이가 무엇을 들었고, 무엇을 했고, 어르신이 어떻게 답하셨는지.
 * 최근 7일 가운데 살핀 것이 있는 날만 온다 — 없으면 카드를 그리지 않는다.
 * 문장은 서버가 만든다(backend/app/services/care.py). 어르신 말 원문·점수는 오지 않는다.
 */
import { useState } from 'react'
import type { CareOut } from '../api/types'
import { useFetch } from '../hooks/useFetch'
import './CareCard.css'

const label = (iso: string) =>
  new Date(`${iso}T00:00:00+09:00`).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' })

export default function CareCard({ roomId }: { roomId: number }) {
  const { data } = useFetch<CareOut>(`/api/rooms/${roomId}/care`)
  const [open, setOpen] = useState(false)
  const days = data?.days ?? []
  if (!days.length) return null
  return (
    <section className="fam-card care" aria-label="돌봄 일지">
      <h2>
        돌봄 일지 <small>꼬마심심이가 살핀 것</small>
      </h2>
      {(open ? days : days.slice(0, 1)).map((d) => (
        <article key={d.date} className={d.level === 'CARE' ? 'care-day care-day--care' : 'care-day'}>
          <small>
            {label(d.date)} · {d.level === 'CARE' ? '며칠째 이어져요' : '지켜보고 있어요'}
          </small>
          <ul>
            {d.heard && (
              <li>
                <b>들은 것</b>
                {d.heard}
              </li>
            )}
            {d.notes.map((note) => (
              <li key={note}>
                <b>달라진 점</b>
                {note}
              </li>
            ))}
            {d.did && (
              <li>
                <b>한 일</b>
                {d.did}
              </li>
            )}
            {d.reaction && (
              <li>
                <b>답</b>
                {d.reaction}
              </li>
            )}
          </ul>
        </article>
      ))}
      {days.length > 1 && (
        <button type="button" className="fam-text-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? '접기' : `지난 ${days.length - 1}일 더 보기`}
        </button>
      )}
    </section>
  )
}
