/**
 * 가족 화면 공통 틀 (D70 — 목업 설계자료/목업_1115_가족, 11/14 사용자 '실제 상용화되는 서비스 앱처럼'):
 * 위 막대(지금 보는 어르신 + 바꾸기 · 알림 종) · 본문 · 아래 탭 5개. 탭 첫 화면(App.tsx 의 TAB_SCREENS)만 이 안에 들어온다.
 * 가족방이 여럿이면 위 막대 이름을 눌러 바꾸고, 모든 탭이 그분 기준이다. 고른 분은 폰에 적어 둔다(다시 열어도 같은 분).
 * 로그아웃은 바꾸기 판 맨 아래(목업에 자리가 없어 11/14 사용자가 고름).
 */
import { useEffect, useState } from 'react'
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { NotificationListOut, RoomOut, UserOut } from '../api/types'
import type { FamilyCtx } from '../hooks/useFamily'
import { useFetch } from '../hooks/useFetch'
import { clearUploadDraft } from '../lib/uploadDraft'
import FamIcon, { type FamIconName } from './FamIcon'
import './FamilyFrame.css'

const ROOM_KEY = 'haru.fam.room'
function savedRoom(): number | null {
  try {
    return Number(localStorage.getItem(ROOM_KEY)) || null
  } catch {
    return null
  }
}
function saveRoom(roomId: number) {
  try {
    localStorage.setItem(ROOM_KEY, String(roomId))
  } catch {
    /* 저장을 막아 둔 폰은 다시 열면 첫 가족방 */
  }
}

const TONES = ['a', 'b', 'c', 'd'] as const
/** 얼굴 동그라미(이름 첫 글자, 11/14 사용자) — 색은 이름으로 4색 중 하나라 같은 사람은 늘 같은 색 */
export function Avatar({ name, small }: { name: string; small?: boolean }) {
  const tone = TONES[[...name].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % TONES.length]
  return (
    <span className={`fam-av fam-tone-${tone}${small ? ' fam-av--s' : ''}`} aria-hidden="true">
      {[...name][0]}
    </span>
  )
}

// 주간 이야기·가족방 탭은 지금 보는 분의 방. 가족방 탭은 월요일 팀이 구성원·설정 한 화면으로 바꾼다(목업 ⑥)
function tabs(roomId: number | null): [string, string, FamIconName][] {
  const inRoom = (path: string) => (roomId ? path.replace(':id', String(roomId)) : '/groups/new')
  return [
    ['/', '홈', 'home'],
    ['/upload', '추억 올리기', 'imagePlus'],
    ['/fdiary', '오늘 한 장', 'pencil'],
    [inRoom('/weekly/:id'), '주간 이야기', 'calendar'],
    [inRoom('/groups/:id/members'), '가족방', 'family'],
  ]
}
/**
 * 하위 화면 틀 (D70, 목업 '하위 화면에만 위 ←') — 탭 밖 가족 화면(App.tsx 의 SUB_SCREENS). 제목은 각 화면의 것을 그대로 쓴다.
 * 아이폰 앱 화면에는 브라우저 뒤로 버튼이 없어 이 ← 가 돌아가는 길이다. 앱 안에서 온 곳이 있으면 거기로, 바로 열었으면 홈으로.
 */
export function SubFrame() {
  const nav = useNavigate()
  // react-router 가 history.state.idx 에 앱 안 순번을 적는다 — 0 이면 이 화면으로 바로 들어온 것
  const back = () => ((window.history.state?.idx ?? 0) > 0 ? nav(-1) : nav('/', { replace: true }))
  return (
    <div className="fam">
      <header className="fam-bar fam-bar--sub">
        <button type="button" className="fam-icon-btn" onClick={back} aria-label="뒤로">
          <FamIcon name="arrowLeft" />
        </button>
      </header>
      <div className="fam-body">
        <Outlet />
      </div>
    </div>
  )
}

// 주소에 가족방 번호가 있으면(주간 이야기·가족방 — 알림에서 바로 온 경우도) 그 방이 지금 보는 분이다
const ROOM_IN_PATH = /^\/(weekly|groups)\/(\d+)/

export default function FamilyFrame() {
  const nav = useNavigate()
  const { pathname } = useLocation()
  const me = useFetch<UserOut>('/api/auth/me')
  const rooms = useFetch<RoomOut[]>(me.data ? '/api/rooms' : null)
  const noti = useFetch<NotificationListOut>(me.data ? '/api/notifications' : null)
  const [picked, setPicked] = useState(savedRoom)
  const [sheet, setSheet] = useState(false)

  // 설치형 앱은 다시 열어도 화면이 새로 뜨지 않는다 → 돌아올 때마다 가족방(폰 연결·사진 수)·알림 수를 다시 읽는다
  const reloadRooms = rooms.reload
  const reloadNoti = noti.reload
  useEffect(() => {
    const onShow = () => {
      if (document.visibilityState !== 'visible') return
      reloadRooms()
      reloadNoti()
    }
    document.addEventListener('visibilitychange', onShow)
    return () => document.removeEventListener('visibilitychange', onShow)
  }, [reloadRooms, reloadNoti])

  if (me.error?.status === 401) return <Navigate to="/login" replace />

  const list = rooms.data ?? []
  const inPath = Number(pathname.match(ROOM_IN_PATH)?.[2]) || null
  const room = list.find((r) => r.room_id === (inPath ?? picked)) ?? list[0] ?? null
  const unread = noti.data?.unread ?? 0

  function pick(roomId: number) {
    setPicked(roomId)
    saveRoom(roomId)
    setSheet(false)
    const m = pathname.match(ROOM_IN_PATH)
    if (m) nav(pathname.replace(m[0], `/${m[1]}/${roomId}`), { replace: true })
  }

  async function logout() {
    await api('/api/auth/logout', { method: 'POST' }).catch(() => {})
    clearUploadDraft() // 고르다 만 사진을 다음 사람에게 남기지 않는다
    nav('/login', { replace: true })
  }

  return (
    <div className="fam">
      <header className="fam-bar">
        {room ? (
          <button type="button" className="fam-switch" onClick={() => setSheet(true)} aria-haspopup="dialog">
            <Avatar name={room.elder_name} small />
            <span>
              {room.elder_name} {room.elder_honorific}네
            </span>
            <FamIcon name="chevDown" className="fam-chev" />
          </button>
        ) : (
          <b className="fam-brand">하루한장</b>
        )}
        <span className="fam-grow" />
        <button
          type="button"
          className="fam-icon-btn"
          onClick={() => nav('/notifications')}
          aria-label={unread ? `알림 ${unread}개` : '알림'}
        >
          <FamIcon name="bell" />
          {unread > 0 && <i className="fam-badge">{unread > 99 ? '99+' : unread}</i>}
        </button>
      </header>

      <div className="fam-body">
        {me.error ? (
          <p className="fam-error">{me.error.message}</p>
        ) : me.data && rooms.data ? (
          <Outlet context={{ me: me.data, rooms: list, room, reloadRooms } satisfies FamilyCtx} />
        ) : null}
      </div>

      <nav className="fam-tabs" aria-label="메뉴">
        {tabs(room?.room_id ?? null).map(([to, label, icon]) => (
          <NavLink key={label} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'fam-tab on' : 'fam-tab')}>
            <span className="fam-pill">
              <FamIcon name={icon} />
            </span>
            {label}
          </NavLink>
        ))}
      </nav>

      {sheet && room && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={() => setSheet(false)} />
          <div className="fam-sheet" role="dialog" aria-label="누구 소식을 볼까요?">
            <span className="fam-grab" />
            <h2>누구 소식을 볼까요?</h2>
            {list.map((r) => {
              const on = r.room_id === room.room_id
              return (
                <button type="button" key={r.room_id} className={on ? 'fam-opt on' : 'fam-opt'} onClick={() => pick(r.room_id)}>
                  <Avatar name={r.elder_name} />
                  <span>
                    <b>
                      {r.elder_name} {r.elder_honorific}
                    </b>
                    <small>
                      구성원 {r.member_count}명 · {r.device_connected ? '기기 연결됨' : '기기 연결 전'}
                    </small>
                  </span>
                  {on && <FamIcon name="check" className="fam-ok" />}
                </button>
              )
            })}
            <button type="button" className="fam-opt" onClick={() => nav('/groups/new')}>
              <span className="fam-add">
                <FamIcon name="plus" />
              </span>
              <span>
                <b>새 가족방 만들기</b>
              </span>
            </button>
            <p className="fam-me">
              {me.data?.name} 님 ·
              <button type="button" className="fam-text-btn" onClick={logout}>
                로그아웃
              </button>
            </p>
          </div>
        </>
      )}
    </div>
  )
}
