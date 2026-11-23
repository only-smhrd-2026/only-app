/**
 * 가족 홈 돌봄 일지 (11/18 멘토링 — 돌봄 루프). 꼬마심심이가 여쭌 안부: 요즘 말씀 · 여쭌 것 · 답.
 * 11/23 시안: 홈 맨 위 한 줄 요약 카드를 펼치면 7일 칸 아래에 붙는다(그래서 카드 틀 없이 내용만 그린다).
 * '지켜보고 있어요'·'며칠째 이어져요'는 감시처럼 읽혀서 빼고 '내일 또 여쭤볼게요' 꼬리표로.
 * 최근 7일 가운데 살핀 것이 있는 날만 온다 — 없으면 아무것도 그리지 않는다.
 * 문장은 서버가 만든다(backend/app/services/care.py). 어르신 말 원문·점수는 오지 않는다.
 */
import { useState } from 'react'
import type { CareDayOut, CareOut } from '../api/types'
import { useFetch } from '../hooks/useFetch'
import Sim from './Sim'
import './CareCard.css'

const label = (iso: string) =>
  new Date(`${iso}T00:00:00+09:00`).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' })

function Day({ d }: { d: CareDayOut }) {
  return (
    <dl className="care-kv">
      {d.heard && (
        <>
          <dt>요즘 말씀</dt>
          <dd>{d.heard}</dd>
        </>
      )}
      {d.notes.map((note) => (
        <div key={note} className="care-kv-row">
          <dt>달라진 점</dt>
          <dd>{note}</dd>
        </div>
      ))}
      {d.did && (
        <>
          <dt>여쭌 것</dt>
          <dd>{d.did}</dd>
        </>
      )}
      {d.reaction && (
        <>
          <dt>답</dt>
          <dd>{d.reaction}</dd>
        </>
      )}
    </dl>
  )
}

export default function CareCard({ roomId }: { roomId: number }) {
  const { data } = useFetch<CareOut>(`/api/rooms/${roomId}/care`)
  const [open, setOpen] = useState(false)
  const days = data?.days ?? []
  if (!days.length) return null
  const [first, ...rest] = days
  return (
    <section className="care" aria-label="돌봄 일지">
      <div className="care-head">
        <span className="fam-av fam-tone-a" aria-hidden="true">
          <Sim face="hello" size={40} />
        </span>
        <div>
          <div className="care-title">
            <h2>돌봄 일지</h2>
            <i className="fam-tag">내일 또 여쭤볼게요</i>
          </div>
          <p className="fam-mini">꼬마심심이(AI 말동무)가 여쭌 안부 · {label(first.date)}</p>
        </div>
      </div>
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
      <p className="fam-mini">잠·식사·기운 같은 안부만 요약해 전해요. 대화 내용은 그대로 보여 드리지 않아요.</p>
    </section>
  )
}
