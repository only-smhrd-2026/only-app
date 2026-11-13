/**
 * GROUP_001 — 가족방: 내 가족방 목록 + 새 가족방 만들기 (FR-AD-002, 이슈 #24).
 * 구성원 수·기기 연결 상태는 서버(RoomOut)가 주지 않아 넣지 않는다.
 */
import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { RelationTag, RoomOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'
import './GROUP_001.css'

const RELATIONS: [RelationTag, string][] = [
  ['CHILD', '자녀'],
  ['GRANDCHILD', '손주'],
  ['OTHER', '기타'],
]

/** 어르신과의 관계 칩 3개 — JOIN_001 도 같이 쓴다. value 가 없으면 아무것도 안 고른 상태 */
export function RelationChips({ value, onChange }: { value?: RelationTag; onChange: (v: RelationTag) => void }) {
  return (
    <fieldset className="chips">
      <legend>어르신과의 관계</legend>
      <div className="row">
        {RELATIONS.map(([tag, label]) => (
          <label key={tag} className="chip">
            <input type="radio" name="relation_tag" value={tag} checked={value === tag} onChange={() => onChange(tag)} />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

export default function GROUP_001() {
  const nav = useNavigate()
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  const [open, setOpen] = useState(false)
  const [relation, setRelation] = useState<RelationTag>('CHILD')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (busy) return // 두 번 눌러 가족방이 2개 생기지 않게
    const f = new FormData(e.currentTarget)
    setBusy(true)
    setError(undefined)
    try {
      await api<RoomOut>('/api/rooms', {
        body: {
          elder_name: f.get('elder_name'),
          elder_honorific: f.get('elder_honorific'),
          relation_tag: relation,
          nickname: f.get('nickname') || null,
        },
      })
      // 어르신 기기 링크는 사진 3장부터 만들 수 있어서 사진 올리기로 (화면설계서 GROUP_001 ⑥)
      nav('/upload')
    } catch (err) {
      setError((err as ApiError).message)
      setBusy(false)
      rooms.reload() // 응답만 끊겼으면 서버에는 만들어졌다 — 목록에 보여 다시 만들지 않게
    }
  }

  if (rooms.error?.status === 401) return <Navigate to="/login" replace />
  if (rooms.error) {
    return (
      <main className="page fam-skin">
        <p className="error">{rooms.error.message}</p>
        <button className="btn" onClick={rooms.reload}>다시 시도</button>
      </main>
    )
  }
  if (!rooms.data) return <main className="page fam-skin"><p className="muted">불러오는 중…</p></main>

  return (
    <main className="page fam-skin">
      <h1>가족방</h1>
      {rooms.data.map((r) => (
        <section key={r.room_id} className="card">
          <p><strong>{r.elder_name} {r.elder_honorific}</strong>{r.is_owner && ' (방장)'}</p>
          <p className="muted">추억 {r.memory_time.slice(0, 5)} · 일기 {r.diary_time.slice(0, 5)}</p>
          <Link className="btn secondary" to={`/groups/${r.room_id}/members`}>구성원·초대</Link>
        </section>
      ))}
      {open || rooms.data.length === 0 ? (
        <form className="form card" onSubmit={submit}>
          <label>어르신 성함<input name="elder_name" required maxLength={10} /></label>
          <label>호칭<input name="elder_honorific" defaultValue="할머니" maxLength={20} /></label>
          <RelationChips value={relation} onChange={setRelation} />
          <label>어르신이 부르는 내 이름 (선택)<input name="nickname" maxLength={12} /></label>
          {error && <p className="error">{error}</p>}
          <button className="btn" disabled={busy}>{busy ? '만드는 중…' : '만들기'}</button>
        </form>
      ) : (
        <button className="btn" onClick={() => setOpen(true)}>+ 새 가족방</button>
      )}
    </main>
  )
}
