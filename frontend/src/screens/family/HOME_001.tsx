/** HOME_001 — 가족 홈 (가족방 목록 + 어르신 '새 일기' 한 줄 + 일기 목록 + 초대 링크 발급). 디자인 없음 (김승희 교체). */
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { MOOD_LABEL, type DiaryListOut, type InviteCreatedOut, type InviteKind, type RoomOut, type UserOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'

/**
 * 가족방 하나의 소식 (D36). 어르신이 일기를 올리면 가족 모두의 홈에 '새 일기 N개' 한 줄이 뜬다.
 * 실시간 반영은 없다 — 가족이 홈을 열 때(앱으로 돌아올 때 포함) 읽는다. 앱 내 알림 DIARY_POSTED 도 1건씩 쌓인다
 * (알림 화면은 천주웅). [다 봤어요] = 열람 기록(diary_reads). 회상 대화 내용은 여기 없다(주간 이야기로만, R18).
 */
function RoomNews({ room }: { room: RoomOut }) {
  const { data, error, reload } = useFetch<DiaryListOut>(`/api/rooms/${room.room_id}/diaries`)
  const [busy, setBusy] = useState(false)

  // 설치형 앱(PWA)은 다시 열어도 화면이 새로 뜨지 않는다 → 앱으로 돌아올 때마다 다시 읽는다
  useEffect(() => {
    const onShow = () => document.visibilityState === 'visible' && reload()
    document.addEventListener('visibilitychange', onShow)
    return () => document.removeEventListener('visibilitychange', onShow)
  }, [reload])

  if (error) return <p className="error">{error.message}</p>
  if (!data) return null
  const fresh = data.diaries.filter((d) => !d.read_by_me)

  async function markAllRead() {
    setBusy(true)
    await Promise.all(fresh.map((d) => api(`/api/diaries/${d.diary_id}/read`, { method: 'POST' }).catch(() => {})))
    setBusy(false)
    reload()
  }

  return (
    <div style={{ marginTop: 12 }}>
      {fresh.length > 0 ? (
        <p className="row" style={{ margin: '0 0 8px' }}>
          <strong>새 일기 {fresh.length}개가 왔어요</strong>
          <button className="btn secondary" onClick={markAllRead} disabled={busy}>다 봤어요</button>
        </p>
      ) : (
        <p className="muted" style={{ margin: '0 0 8px' }}>
          {data.diaries.length ? '새 소식이 없어요' : '아직 일기가 없어요. 추억 사진을 올려 보세요.'}
        </p>
      )}
      {/* 안 본 일기는 전부 + 최근 것 5개까지. [다 봤어요]가 화면에 없는 일기를 읽음 처리하지 않게 */}
      {data.diaries.filter((d, i) => i < 5 || !d.read_by_me).map((d) => (
        <article key={d.diary_id} style={{ borderTop: '1px solid #eee', padding: '8px 0' }}>
          {d.illustration_url && (
            <img
              src={d.illustration_url}
              alt={d.illustration_type === 'AI_DRAWING' ? '그림일기 그림' : '일기 사진'}
              style={{ width: '100%', maxHeight: 240, objectFit: 'contain', borderRadius: 8 }}
            />
          )}
          <p className="muted" style={{ margin: '4px 0' }}>
            {!d.read_by_me && <strong>새 일기 · </strong>}
            {d.author_name} · {MOOD_LABEL[d.mood]} · {new Date(d.posted_at).toLocaleString('ko-KR')}
            {d.illustration_type === 'AI_DRAWING' && ' · 그림일기'}
          </p>
          <p style={{ margin: 0 }}>{d.body}</p>
        </article>
      ))}
    </div>
  )
}

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
          <RoomNews room={room} />
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
