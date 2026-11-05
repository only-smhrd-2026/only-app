/** HOME_001 — 가족 홈 (가족방 목록 + 초대 링크 발급). 디자인 없음 (김승희 교체). */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { InviteCreatedOut, InviteKind, RoomOut, UserOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'

export default function HOME_001() {
  const nav = useNavigate()
  const me = useFetch<UserOut>('/api/auth/me')
  const rooms = useFetch<RoomOut[]>(me.data ? '/api/rooms' : null)
  const [links, setLinks] = useState<Record<string, InviteCreatedOut | string>>({})

  if (me.error?.status === 401) {
    nav('/login', { replace: true })
    return null
  }

  async function invite(room: RoomOut, kind: InviteKind) {
    const key = `${room.room_id}-${kind}`
    try {
      const created = await api<InviteCreatedOut>(`/api/rooms/${room.room_id}/invites`, { body: { kind } })
      setLinks((l) => ({ ...l, [key]: created }))
    } catch (e) {
      setLinks((l) => ({ ...l, [key]: (e as ApiError).message }))
    }
  }

  async function logout() {
    await api('/api/auth/logout', { method: 'POST' }).catch(() => {})
    nav('/login', { replace: true })
  }

  return (
    <main className="page">
      <h1>가족 홈</h1>
      <p className="muted">{me.data?.name} 님 · <button className="btn secondary" onClick={logout}>로그아웃</button></p>
      {rooms.data?.length === 0 && <p>아직 가족방이 없어요.</p>}
      {rooms.data?.map((room) => (
        <section className="card" key={room.room_id}>
          <h2 style={{ margin: '0 0 8px', fontSize: 18 }}>
            {room.elder_name} {room.elder_honorific} {room.is_owner && <span className="muted">(방장)</span>}
          </h2>
          <div className="row">
            <Link to={`/groups/${room.room_id}/members`}>구성원</Link>
            <Link to={`/groups/${room.room_id}/settings`}>설정</Link>
            <Link to={`/weekly/${room.room_id}`}>주간 이야기</Link>
            <Link to="/upload">사진 올리기</Link>
          </div>
          {room.is_owner && (
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn secondary" onClick={() => invite(room, 'FAMILY')}>가족 초대 링크</button>
              <button className="btn secondary" onClick={() => invite(room, 'ELDER_DEVICE')}>어르신 기기 링크</button>
            </div>
          )}
          {(['FAMILY', 'ELDER_DEVICE'] as InviteKind[]).map((kind) => {
            const v = links[`${room.room_id}-${kind}`]
            if (!v) return null
            return typeof v === 'string' ? (
              <p className="error" key={kind}>{v}</p>
            ) : (
              <p className="mono" key={kind}>
                {kind === 'FAMILY' ? '가족' : '어르신 기기'} 링크 (만료 {new Date(v.expires_at).toLocaleString('ko-KR')}):<br />
                <a href={v.url}>{v.url}</a>
              </p>
            )
          })}
        </section>
      ))}
      <p><Link className="btn" to="/groups/new">가족방 만들기</Link></p>
    </main>
  )
}
