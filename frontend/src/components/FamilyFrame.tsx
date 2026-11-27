/**
 * 가족 화면 공통 틀 (D70 — 목업 설계자료/목업_1115_가족, 11/14 사용자 '실제 상용화되는 서비스 앱처럼'):
 * 위 막대(지금 보는 어르신 + 바꾸기 · 알림 종) · 본문 · 아래 탭(11/23 사용자: 홈·사진첩·[+]·주간 이야기·가족방 —
 * 가운데 노란 [+] 는 화면이 아니라 '오늘 소식 보내기·추억 사진 올리기' 판을 연다).
 * 탭 첫 화면(App.tsx 의 TAB_SCREENS)만 이 안에 들어온다.
 * 가족방이 여럿이면 위 막대 이름을 눌러 바꾸고, 모든 탭이 그분 기준이다. 고른 분은 폰에 적어 둔다(다시 열어도 같은 분).
 * 로그아웃은 바꾸기 판 맨 아래 큰 글자 버튼(11/23 시안). 가족방 탭 아래·가족방 없는 홈에도 있다(11/24, lib/logout).
 */
import { useEffect, useState } from 'react'
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import type { NotificationListOut, RoomOut, UserOut } from '../api/types'
import type { FamilyCtx } from '../hooks/useFamily'
import { useFetch } from '../hooks/useFetch'
import { logout } from '../lib/logout'
import { FAMILY_PUSH, syncPush } from '../lib/push'
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
export function Avatar({ name, small, src }: { name: string; small?: boolean; src?: string | null }) {
  const tone = TONES[[...name].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % TONES.length]
  return (
    <span className={`fam-av fam-tone-${tone}${small ? ' fam-av--s' : ''}`} aria-hidden="true">
      {src ? <img className="fam-av-pic" src={src} alt="" /> : [...name][0]}
    </span>
  )
}

// 주간 이야기·가족방 탭은 지금 보는 분의 방. 가운데는 탭이 아니라 [+] — 오늘 소식·추억 사진 올리기 판 (11/23 사용자)
function tabs(roomId: number | null): [string, string, FamIconName][] {
  const inRoom = (path: string) => (roomId ? path.replace(':id', String(roomId)) : '/groups/new')
  return [
    ['/', '홈', 'home'],
    ['/photos', '사진첩', 'image'],
    [inRoom('/weekly/:id'), '주간 이야기', 'calendar'],
    [inRoom('/groups/:id/members'), '가족방', 'family'],
  ]
}
function Tab([to, label, icon]: [string, string, FamIconName]) {
  return (
    <NavLink key={label} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'fam-tab on' : 'fam-tab')}>
      <span className="fam-pill">
        <FamIcon name={icon} />
      </span>
      {label}
    </NavLink>
  )
}
/**
 * 아이폰 키보드 (11/27 가족 일기 쓰기 피드백): 사파리는 키보드가 떠도 화면 높이(100dvh)를 줄이지 않고 페이지를 위로 밀어
 * 위쪽을 다시 볼 수 없었다. 보이는 칸(visualViewport)의 높이·위치를 틀(.fam)에 그대로 준다 — 갤럭시 크롬은 이미
 * 줄어들어(index.html interactive-widget) 값이 같으니 그대로다.
 */
function useKeyboardFit() {
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const root = document.documentElement.style
    const fit = () => {
      root.setProperty('--fam-h', `${vv.height}px`)
      root.setProperty('--fam-top', `${vv.offsetTop}px`)
    }
    fit()
    vv.addEventListener('resize', fit)
    vv.addEventListener('scroll', fit)
    return () => {
      vv.removeEventListener('resize', fit)
      vv.removeEventListener('scroll', fit)
      root.removeProperty('--fam-h')
      root.removeProperty('--fam-top')
    }
  }, [])
}

/**
 * 하위 화면 틀 (D70, 목업 '하위 화면에만 위 ←') — 탭 밖 가족 화면(App.tsx 의 SUB_SCREENS). 제목은 각 화면의 것을 그대로 쓴다.
 * 아이폰 앱 화면에는 브라우저 뒤로 버튼이 없어 이 ← 가 돌아가는 길이다. 앱 안에서 온 곳이 있으면 거기로, 바로 열었으면 홈으로.
 */
export function SubFrame() {
  useKeyboardFit()
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
  useKeyboardFit()
  const nav = useNavigate()
  const { pathname } = useLocation()
  const me = useFetch<UserOut>('/api/auth/me')
  const rooms = useFetch<RoomOut[]>(me.data ? '/api/rooms' : null)
  const noti = useFetch<NotificationListOut>(me.data ? '/api/notifications' : null)
  const [picked, setPicked] = useState(savedRoom)
  const [sheet, setSheet] = useState(false)
  const [add, setAdd] = useState(false) // 가운데 [+] 판

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

  // 폰 알림을 켜 둔 브라우저면 지금 로그인한 사람 것으로 서버에 맞춘다(화면 변화 없음, lib/push)
  const myId = me.data?.user_id
  useEffect(() => {
    if (myId) void syncPush(FAMILY_PUSH, false, myId)
  }, [myId])

  if (me.error?.status === 401) return <Navigate to="/login" replace />

  const list = rooms.data ?? []
  const inPath = Number(pathname.match(ROOM_IN_PATH)?.[2]) || null
  const room = list.find((r) => r.room_id === (inPath ?? picked)) ?? list[0] ?? null
  const unread = noti.data?.unread ?? 0
  const hon = room ? `${room.elder_name} ${room.elder_honorific}` : '어르신'
  const go = (to: string) => {
    setAdd(false)
    nav(to)
  }

  function pick(roomId: number) {
    setPicked(roomId)
    saveRoom(roomId)
    setSheet(false)
    const m = pathname.match(ROOM_IN_PATH)
    if (m) nav(pathname.replace(m[0], `/${m[1]}/${roomId}`), { replace: true })
  }

  return (
    <div className="fam">
      <header className="fam-bar">
        {room ? (
          <button type="button" className="fam-switch" onClick={() => setSheet(true)} aria-haspopup="dialog">
            <Avatar name={room.elder_name} />
            <span>
              {room.elder_name} {room.elder_honorific}네
            </span>
            <FamIcon name="chevDown" className="fam-chev" />
          </button>
        ) : (
          <b className="fam-brand">하루한장</b>
        )}
        {/* 11/25 사용자 — 가족 홈에만 [일기 달력](HOME_003, 인스타 스토리 보관함처럼) */}
        {room && pathname === '/' && (
          <button type="button" className="fam-icon-btn" onClick={() => nav(`/calendar/${room.room_id}`)} aria-label="일기 달력">
            <FamIcon name="calendar" />
          </button>
        )}
        <button
          type="button"
          className="fam-icon-btn"
          onClick={() => nav('/notifications')}
          aria-label={unread ? `알림, 안 읽은 것 ${unread}개` : '알림'}
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
        {tabs(room?.room_id ?? null).slice(0, 2).map(Tab)}
        <button type="button" className="fam-plus" onClick={() => setAdd(true)} aria-haspopup="dialog" aria-label="올리기 — 내 일기·추억 사진">
          <span>
            <FamIcon name="plus" />
          </span>
        </button>
        {tabs(room?.room_id ?? null).slice(2).map(Tab)}
      </nav>

      {add && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={() => setAdd(false)} />
          <div className="fam-sheet" role="dialog" aria-modal="true" aria-label="무엇을 올릴까요?" onKeyDown={(e) => e.key === 'Escape' && setAdd(false)}>
            <span className="fam-grab" />
            <h2>무엇을 올릴까요?</h2>
            <button type="button" className="fam-opt" onClick={() => go('/fdiary')} autoFocus>
              <span className="fam-add">
                <FamIcon name="pencil" />
              </span>
              <span>
                <b>내 일기 보내기</b>
                <small>오늘 사진 1장과 일기 · {hon}께 읽어 드려요</small>
              </span>
              <FamIcon name="chevRight" />
            </button>
            <button type="button" className="fam-opt" onClick={() => go('/upload')}>
              <span className="fam-add">
                <FamIcon name="imagePlus" />
              </span>
              <span>
                <b>추억 사진 올리기</b>
                <small>옛 사진 여러 장 · 하루 1장씩 '오늘의 한 장'으로 보여 드려요</small>
              </span>
              <FamIcon name="chevRight" />
            </button>
          </div>
        </>
      )}

      {sheet && room && (
        <>
          <button type="button" className="fam-scrim" aria-label="닫기" onClick={() => setSheet(false)} />
          <div className="fam-sheet" role="dialog" aria-modal="true" aria-label="누구 소식을 볼까요?" onKeyDown={(e) => e.key === 'Escape' && setSheet(false)}>
            <span className="fam-grab" />
            <h2>누구 소식을 볼까요?</h2>
            {list.map((r) => {
              const on = r.room_id === room.room_id
              return (
                <button type="button" key={r.room_id} className={on ? 'fam-opt on' : 'fam-opt'} onClick={() => pick(r.room_id)} autoFocus={on}>
                  <Avatar name={r.elder_name} />
                  <span>
                    <b>
                      {r.elder_name} {r.elder_honorific}
                    </b>
                    <small>
                      구성원 {r.member_count}명 · {r.device_connected ? '폰 연결됨' : '폰 연결 전'}
                    </small>
                  </span>
                  {on && <FamIcon name="check" className="fam-ok" />}
                </button>
              )
            })}
            <button type="button" className="fam-btn" onClick={() => nav('/groups/new')}>
              <FamIcon name="plus" />새 가족방 만들기
            </button>
            <button type="button" className="fam-btn fam-btn--text fam-logout" onClick={() => logout(nav)}>
              로그아웃
            </button>
            {me.data && <p className="fam-me">{me.data.name} 님으로 로그인했어요</p>}
          </div>
        </>
      )}
    </div>
  )
}
