/** NOTI_001 — 가족 알림 목록 (FR-NT-003). 최신 순, 누르면 읽음 + 해당 화면으로. 디자인 없음 (김승희 교체). */
import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { NotificationListOut, NotificationOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'

const LINKS: Record<string, (roomId: number) => string> = {
  HOME_001: () => '/',
  GROUP_002: (roomId) => '/groups/' + roomId + '/members',
  WEEKLY_001: (roomId) => '/weekly/' + roomId,
}

export default function NOTI_001() {
  const nav = useNavigate()
  const { data, error, reload } = useFetch<NotificationListOut>('/api/notifications')
  const [busy, setBusy] = useState(false)

  if (error?.status === 401) return <Navigate to="/login" replace />
  if (error) return (
    <main className="page">
      <p className="error">{error.message}</p>
      <button type="button" className="btn secondary" onClick={reload}>다시 시도</button>
    </main>
  )
  if (!data) return <main className="page"><p>불러오는 중…</p></main>
  const fresh = data.notifications.filter((n) => n.read_at === null)

  async function open(n: NotificationOut) {
    if (n.read_at === null) {
      await api('/api/notifications/' + n.notification_id + '/read', { method: 'POST' }).catch(() => {})
    }
    const link = n.link_screen && Object.hasOwn(LINKS, n.link_screen) ? LINKS[n.link_screen] : undefined
    if (link) nav(link(n.room_id))
    else reload()
  }

  async function markAllRead() {
    setBusy(true)
    await Promise.all(fresh.map((n) => (
      api('/api/notifications/' + n.notification_id + '/read', { method: 'POST' }).catch(() => {})
    )))
    setBusy(false)
    reload()
  }

  return (
    <main className="page">
      <h1>알림</h1>
      <p className="muted">안 읽은 알림 {data.unread}개</p>
      {fresh.length > 0 && (
        <p><button type="button" className="btn secondary" onClick={markAllRead} disabled={busy}>모두 읽음</button></p>
      )}
      {data.notifications.length === 0 && <p>아직 알림이 없어요.</p>}
      {data.notifications.map((n) => (
        <button
          key={n.notification_id}
          type="button"
          className="card"
          onClick={() => open(n)}
          style={{ display: 'block', width: '100%', textAlign: 'left', border: 0, font: 'inherit', cursor: 'pointer', overflowWrap: 'anywhere' }}
        >
          <span style={{ display: 'block' }}>{n.read_at === null && <strong>새 · </strong>}{n.title}</span>
          {n.body && <span className="muted" style={{ display: 'block' }}>{n.body}</span>}
          <span className="muted" style={{ display: 'block' }}>{new Date(n.sent_at).toLocaleString('ko-KR')}</span>
        </button>
      ))}
    </main>
  )
}
