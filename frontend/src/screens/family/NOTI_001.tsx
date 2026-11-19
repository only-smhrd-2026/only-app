/** NOTI_001 — 어르신별 알림 (FR-NT-003). 맨 위 카드에서 폰 알림(웹 푸시)을 켜고 끈다. */
import { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { NotificationListOut, NotificationOut, RoomOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'
import { getInstallState } from '../../lib/installPrompt'
import { disablePush, enablePush, FAMILY_PUSH, pushKey, pushState, type PushState } from '../../lib/push'
import './NOTI_001.css'

const LINKS: Record<string, (roomId: number) => string> = {
  HOME_001: () => '/',
  GROUP_002: (id) => '/groups/' + id + '/members',
  WEEKLY_001: (id) => '/weekly/' + id,
}
function savedRoom() {
  try { return Number(localStorage.getItem('haru.fam.room')) || null } catch { return null }
}
function kstDay(value: string | Date) {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' }).format(new Date(value))
}
function period(sentAt: string, today: string) {
  const day = kstDay(sentAt)
  if (day === today) return '오늘'
  const monday = new Date(today + 'T00:00:00Z')
  monday.setUTCDate(monday.getUTCDate() - (monday.getUTCDay() + 6) % 7)
  return day >= monday.toISOString().slice(0, 10) && day < today ? '이번 주' : '이전'
}

/**
 * 폰 알림(웹 푸시) 카드 — 일기·주간 이야기·위급 알림을 앱을 안 열어도 받게 이 브라우저를 켜고 끈다 (lib/push).
 * 서버에 푸시 키가 없거나, 아이폰이 아닌데 푸시를 못 쓰는 브라우저면 아무것도 그리지 않는다.
 */
function PushCard() {
  const [state, setState] = useState<PushState>()
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let alive = true
    void pushKey()
      .then((key) => (key ? pushState() : undefined))
      .then((s) => alive && setState(s), () => {})
    return () => {
      alive = false
    }
  }, [])
  async function toggle() {
    setBusy(true)
    setFailed(false)
    try {
      if (state === 'on') {
        await disablePush()
        setState('off')
      } else setState(await enablePush(FAMILY_PUSH))
    } catch {
      setFailed(true)
    }
    setBusy(false)
  }
  if (!state) return null
  // 푸시를 못 쓰는 브라우저 중 안내할 것은 아이폰 탭뿐 — 아이폰은 홈 화면에 추가한 앱에서만 웹 푸시가 된다
  if (state === 'unsupported' && (!/iPhone/i.test(navigator.userAgent) || getInstallState() === 'installed')) return null
  const guide =
    state === 'unsupported' ? '아이폰은 홈 화면에 추가한 앱에서만 알림을 받을 수 있어요'
    : state === 'denied' ? '알림이 막혀 있어요. 폰 설정의 알림에서 하루한장을 허용해 주세요.'
    : failed ? '알림 설정을 바꾸지 못했어요. 다시 눌러 주세요.'
    : state === 'on' ? '폰 알림 켜짐'
    : '일기가 도착하면 폰으로 알려 드려요'
  return (
    <section className="fam-card noti-push" aria-label="폰 알림">
      <p role={failed ? 'alert' : undefined}>{guide}</p>
      {(state === 'on' || state === 'off') && (
        <button type="button" className={`fam-btn fam-btn--sm ${state === 'on' ? 'fam-btn--tonal' : 'fam-btn--primary'}`} onClick={toggle} disabled={busy}>
          {state === 'on' ? '끄기' : '알림 켜기'}
        </button>
      )}
    </section>
  )
}

export default function NOTI_001() {
  const nav = useNavigate()
  const noti = useFetch<NotificationListOut>('/api/notifications')
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  const [picked, setPicked] = useState<number | null>(savedRoom)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [today] = useState(() => kstDay(new Date()))
  const error = noti.error ?? rooms.error
  if (error?.status === 401) return <Navigate to="/login" replace />
  if (error) return <main className="page"><p className="error">{error.message}</p><button type="button" className="btn secondary" onClick={() => { noti.reload(); rooms.reload() }}>다시 시도</button></main>
  if (!noti.data || !rooms.data) return <main className="page"><p>불러오는 중…</p></main>
  const data = noti.data
  const roomId = rooms.data.find((r) => r.room_id === picked)?.room_id ?? rooms.data[0]?.room_id
  const visible = data.notifications.filter((n) => n.room_id === roomId)
  const fresh = visible.filter((n) => n.read_at === null)

  async function open(n: NotificationOut) {
    setActionError('')
    if (n.read_at === null) {
      try { await api('/api/notifications/' + n.notification_id + '/read', { method: 'POST' }) }
      catch { setActionError('읽음 처리하지 못했어요. 다시 시도해 주세요.'); return }
    }
    try { localStorage.setItem('haru.fam.room', String(n.room_id)) } catch { /* 저장이 막힌 브라우저 */ }
    const link = n.link_screen && Object.hasOwn(LINKS, n.link_screen) ? LINKS[n.link_screen] : undefined
    if (link) nav(link(n.room_id))
    else noti.reload()
  }
  async function markAllRead() {
    setBusy(true)
    setActionError('')
    const results = await Promise.allSettled(fresh.map((n) => api('/api/notifications/' + n.notification_id + '/read', { method: 'POST' })))
    if (results.some((r) => r.status === 'rejected')) setActionError('일부 알림을 읽음 처리하지 못했어요. 다시 시도해 주세요.')
    setBusy(false)
    noti.reload()
  }
  return (
    <main className="page noti-page">
      <div className="noti-heading"><h1>알림</h1><span className="muted">전체 안 읽음 {data.unread}개</span></div>
      <PushCard />
      <div className="noti-chips" role="group" aria-label="알림을 볼 어르신">
        {rooms.data.map((room) => {
          const count = data.notifications.filter((n) => n.room_id === room.room_id && n.read_at === null).length
          return <button key={room.room_id} type="button" className="noti-chip" aria-pressed={room.room_id === roomId} onClick={() => setPicked(room.room_id)}>{room.elder_name} <span aria-label={`안 읽음 ${count}개`}>{count}</span></button>
        })}
      </div>
      {actionError && <p role="alert" className="error">{actionError}</p>}
      <div className="noti-toolbar"><span>안 읽은 알림 {fresh.length}개</span>{fresh.length > 0 && <button type="button" onClick={markAllRead} disabled={busy}>{busy ? '처리 중…' : '모두 읽음'}</button>}</div>
      {visible.length === 0 && <p className="muted">아직 알림이 없어요.</p>}
      {['오늘', '이번 주', '이전'].map((label) => {
        const entries = visible.filter((n) => period(n.sent_at, today) === label)
        if (!entries.length) return null
        return <section key={label} aria-label={label}><h2 className="noti-period">{label}</h2><ul className="noti-list">{entries.map((n) => (
          <li key={n.notification_id} className={`noti-card${n.read_at === null ? ' noti-unread' : ''}${n.kind === 'MOOD_URGENT' ? ' noti-urgent' : ''}`}>
            <button type="button" className="noti-open" onClick={() => open(n)} disabled={busy}>
              <strong>{n.read_at === null && <span className="noti-dot" aria-label="안 읽음" />}{n.title}</strong>
              {n.body && <span>{n.body}</span>}
              <time dateTime={n.sent_at}>{new Date(n.sent_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time>
            </button>
            {n.kind === 'MOOD_URGENT' && <a className="noti-phone" href="tel:">전화</a>}
          </li>
        ))}</ul></section>
      })}
    </main>
  )
}
