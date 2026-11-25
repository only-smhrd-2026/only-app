/**
 * NOTI_001 — 어르신별 알림 (FR-NT-003, 11/23 시안 f-noti). 맨 위 카드에서 폰 알림(웹 푸시)을 켜고 끄고,
 * 일기·주간·돌봄 알림을 묶음별로 끈다(GET/PUT /api/push/prefs — 급한 알림은 끌 수 없다).
 * 알림을 누르면 그 화면으로 — 일기 알림은 그 일기(link_id), 급한 알림은 빨간 테두리 + '급한 알림' 꼬리표.
 */
import { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { NotificationListOut, NotificationOut, PushGroup, PushPrefs, RoomOut } from '../../api/types'
import FamIcon, { type FamIconName } from '../../components/FamIcon'
import Sim from '../../components/Sim'
import { useFetch } from '../../hooks/useFetch'
import { getInstallState } from '../../lib/installPrompt'
import { disablePush, enablePush, FAMILY_PUSH, pushKey, pushState, type PushState } from '../../lib/push'
import './NOTI_001.css'

const LINKS: Record<string, (n: NotificationOut) => string | null> = {
  HOME_001: () => '/',
  HOME_002: (n) => (n.link_id ? `/diaries/${n.link_id}` : '/'),
  GROUP_002: (n) => `/groups/${n.room_id}/members`,
  WEEKLY_001: (n) => `/weekly/${n.room_id}`,
}
const HOT = new Set(['MOOD_URGENT', 'URGENT_MISSED'])
const ICON: Record<string, FamIconName> = {
  DIARY_POSTED: 'book',
  ELDER_REPLY: 'book',
  WEEKLY_READY: 'calendar',
  MOOD_LOW_2D: 'phone',
  MOOD_URGENT: 'phone',
  URGENT_MISSED: 'phone',
}
const GROUPS: [PushGroup, string][] = [
  ['DIARY', '일기 알림'],
  ['WEEKLY', '주간 이야기 알림'],
  ['CARE', '돌봄 알림'],
]

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
 * 폰 알림(웹 푸시) 카드 — 이 브라우저로 폰 알림을 켜고 끈다 (lib/push). 그 아래 묶음별 끄기.
 * 서버에 푸시 키가 없거나, 아이폰이 아닌데 푸시를 못 쓰는 브라우저면 켜기 줄은 그리지 않는다.
 */
function PushCard() {
  const [state, setState] = useState<PushState>()
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const prefs = useFetch<PushPrefs>('/api/push/prefs')
  const [muted, setMuted] = useState<PushGroup[]>()
  const [prefBusy, setPrefBusy] = useState(false)
  const [prefFailed, setPrefFailed] = useState(false)
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
  const now = muted ?? prefs.data?.muted ?? []
  async function mute(g: PushGroup) {
    const next = now.includes(g) ? now.filter((x) => x !== g) : [...now, g]
    setPrefBusy(true)
    setPrefFailed(false)
    try {
      const out = await api<PushPrefs>('/api/push/prefs', { method: 'PUT', body: { muted: next } })
      setMuted(out.muted)
    } catch {
      setPrefFailed(true)
    }
    setPrefBusy(false)
  }
  // 푸시를 못 쓰는 브라우저 중 안내할 것은 아이폰 탭뿐 — 아이폰은 홈 화면에 추가한 앱에서만 웹 푸시가 된다
  const hidePush = !state || (state === 'unsupported' && (!/iPhone/i.test(navigator.userAgent) || getInstallState() === 'installed'))
  const guide =
    state === 'unsupported' ? '아이폰은 홈 화면에 추가한 앱에서만 알림을 받을 수 있어요'
    : state === 'denied' ? '알림이 막혀 있어요. 폰 설정의 알림에서 하루한장을 허용해 주세요.'
    : failed ? '알림 설정을 바꾸지 못했어요. 다시 눌러 주세요.'
    : state === 'on' ? '이 폰으로 알려 드려요'
    : '일기가 도착하면 폰으로 알려 드려요'
  if (hidePush && !prefs.data) return null
  return (
    <section className="fam-card noti-push" aria-label="알림 설정">
      {!hidePush && (
        <div className="noti-push-row">
          <span className="noti-sq" aria-hidden="true">
            <FamIcon name="bell" />
          </span>
          <div>
            <b>폰 알림 {state === 'on' ? '켜짐' : '꺼짐'}</b>
            <p className="fam-mini" role={failed ? 'alert' : undefined}>{guide}</p>
          </div>
          {(state === 'on' || state === 'off') && (
            <button type="button" className={`fam-btn fam-btn--sm${state === 'on' ? '' : ' fam-btn--primary'}`} onClick={toggle} disabled={busy}>
              {state === 'on' ? '끄기' : '켜기'}
            </button>
          )}
        </div>
      )}
      {prefs.data &&
        GROUPS.map(([g, label]) => {
          const on = !now.includes(g)
          return (
            // 줄 전체가 스위치 — 누르는 곳이 48px 줄 전체 (11/23 점검)
            <button key={g} type="button" role="switch" aria-checked={on} className="noti-set" disabled={prefBusy} onClick={() => mute(g)}>
              <span>{label}</span>
              <span className="noti-switch" aria-hidden="true">
                <i />
              </span>
            </button>
          )
        })}
      {prefFailed && <p className="fam-error" role="alert">알림 설정을 바꾸지 못했어요. 다시 눌러 주세요.</p>}
      <p className="fam-mini">급한 알림은 끌 수 없어요 — 늘 폰으로 알려 드려요</p>
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
  if (error)
    return (
      <main className="fam-stack noti">
        <p className="fam-error">{error.message}</p>
        <button type="button" className="fam-text-btn" onClick={() => { noti.reload(); rooms.reload() }}>다시 시도</button>
      </main>
    )
  if (!noti.data || !rooms.data) return <main className="fam-stack noti" aria-busy="true"><p className="noti-empty" role="status">불러오는 중…</p></main>
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
    const link = n.link_screen && Object.hasOwn(LINKS, n.link_screen) ? LINKS[n.link_screen](n) : HOT.has(n.kind) ? '/' : null
    if (link) nav(link)
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
    <main className="fam-stack noti">
      <h1 className="noti-title">알림</h1>
      <PushCard />
      {rooms.data.length > 1 && (
        <div className="fam-seg noti-rooms" role="group" aria-label="알림을 볼 어르신">
          {rooms.data.map((room) => {
            const count = data.notifications.filter((n) => n.room_id === room.room_id && n.read_at === null).length
            return (
              <button key={room.room_id} type="button" className="fam-chip" aria-pressed={room.room_id === roomId} onClick={() => setPicked(room.room_id)}>
                {room.elder_name} {room.elder_honorific}
                {count > 0 && <span aria-label={`안 읽음 ${count}개`}> {count}</span>}
              </button>
            )
          })}
        </div>
      )}
      {actionError && <p role="alert" className="fam-error">{actionError}</p>}
      <div className="noti-toolbar">
        <span>안 읽은 알림 {fresh.length}개</span>
        <button type="button" className="fam-btn fam-btn--text fam-btn--sm" onClick={markAllRead} disabled={busy || fresh.length === 0}>
          {busy ? '처리 중…' : '모두 읽음'}
        </button>
      </div>
      {visible.length === 0 && (
        <div className="noti-empty">
          <Sim face="smile" size={96} />
          <p>아직 알림이 없어요.</p>
        </div>
      )}
      {['오늘', '이번 주', '이전'].map((label) => {
        const entries = visible.filter((n) => period(n.sent_at, today) === label)
        if (!entries.length) return null
        return (
          <section key={label} aria-label={label} className="noti-group">
            <h2 className="noti-period">{label}</h2>
            {entries.map((n) => {
              const hot = HOT.has(n.kind)
              return (
                <button
                  key={n.notification_id}
                  type="button"
                  className={`fam-card noti-item${hot ? ' hot' : ''}`}
                  onClick={() => open(n)}
                  disabled={busy}
                >
                  <span className="noti-sq" aria-hidden="true">
                    <FamIcon name={ICON[n.kind] ?? 'bell'} />
                  </span>
                  <span className="noti-text">
                    <b>
                      {hot && <span className="noti-hot">급한 알림</span>}
                      {n.title}
                    </b>
                    {n.body && <span className="noti-body">{n.body}</span>}
                    <time className="fam-mini" dateTime={n.sent_at}>
                      {new Date(n.sent_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
                    </time>
                  </span>
                  {n.read_at === null && <span className="noti-unread" role="img" aria-label="안 읽음" />}
                </button>
              )
            })}
          </section>
        )
      })}
    </main>
  )
}
