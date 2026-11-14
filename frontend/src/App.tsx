/**
 * 화면 25개 + 지난 일기(11/13, D60) ↔ 경로 표 (설계안 v1 4절). 파일 이름 = 화면설계서 화면 ID (D11).
 * 아직 없는 화면은 NotYet 이 "준비 중" 을 보여 준다. 화면을 만들면 Screen 칸에 컴포넌트를 넣는다.
 */
import { useEffect, type ComponentType } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import type { DeviceOut } from './api/types'
import { useFetch } from './hooks/useFetch'
import NotYet from './screens/NotYet'
import ELDER_ALBUM_001 from './screens/elder/ELDER_ALBUM_001'
import ELDER_CONNECT_001 from './screens/elder/ELDER_CONNECT_001'
import ELDER_DIARY_001 from './screens/elder/ELDER_DIARY_001'
import ELDER_DIARY_002 from './screens/elder/ELDER_DIARY_002'
import ELDER_DIARY_003 from './screens/elder/ELDER_DIARY_003'
import ELDER_DIARY_004 from './screens/elder/ELDER_DIARY_004'
import ELDER_FAMILY_001 from './screens/elder/ELDER_FAMILY_001'
import ELDER_HOME_001 from './screens/elder/ELDER_HOME_001'
import ELDER_MEMORY_001 from './screens/elder/ELDER_MEMORY_001'
import ELDER_MOOD_002 from './screens/elder/ELDER_MOOD_002'
import GROUP_001 from './screens/family/GROUP_001'
import GROUP_002 from './screens/family/GROUP_002'
import HOME_001 from './screens/family/HOME_001'
import JOIN_001 from './screens/family/JOIN_001'
import LOGIN_001 from './screens/family/LOGIN_001'
import NOTI_001 from './screens/family/NOTI_001'
import UPLOAD_001 from './screens/family/UPLOAD_001'
import UPLOAD_002 from './screens/family/UPLOAD_002'
import UPLOAD_003 from './screens/family/UPLOAD_003'
import WEEKLY_001 from './screens/family/WEEKLY_001'

export type ScreenDef = { id: string; path: string; title: string; Screen?: ComponentType }

export const SCREENS: ScreenDef[] = [
  // ---- 어르신 (10 + 지난 일기 + 마음 체크 2)
  { id: 'ELDER_CONNECT_001', path: '/elder/connect', title: '어르신 기기 연결', Screen: ELDER_CONNECT_001 },
  { id: 'ELDER_HOME_001', path: '/elder', title: '어르신 홈', Screen: ELDER_HOME_001 },
  { id: 'ELDER_TODAY_001', path: '/elder/today', title: '오늘의 한 장', Screen: ELDER_HOME_001 },
  { id: 'ELDER_MEMORY_001', path: '/elder/memory/:sessionId', title: '회상 대화', Screen: ELDER_MEMORY_001 },
  { id: 'ELDER_MEMORY_002', path: '/elder/memory/:sessionId/done', title: '회상 마무리' },
  { id: 'ELDER_ALBUM_001', path: '/elder/album', title: '사진첩', Screen: ELDER_ALBUM_001 },
  { id: 'ELDER_DIARY_001', path: '/elder/diary', title: '오늘 일기', Screen: ELDER_DIARY_001 },
  { id: 'ELDER_DIARY_002', path: '/elder/diary/:sessionId', title: '일기 대화', Screen: ELDER_DIARY_002 },
  { id: 'ELDER_DIARY_003', path: '/elder/diary/:sessionId/confirm', title: '일기 확인', Screen: ELDER_DIARY_003 },
  { id: 'ELDER_DIARY_004', path: '/elder/diaries', title: '지난 일기', Screen: ELDER_DIARY_004 }, // 11/13 새 화면 (D60)
  { id: 'ELDER_FAMILY_001', path: '/elder/family-news', title: '가족 소식', Screen: ELDER_FAMILY_001 },
  // 11/14 새 화면 2개 — 마음 체크 (D56·D66). 초대는 오늘의 한 장처럼 홈 위에 뜬다
  { id: 'ELDER_MOOD_001', path: '/elder/mood', title: '마음 체크 초대', Screen: ELDER_HOME_001 },
  { id: 'ELDER_MOOD_002', path: '/elder/mood-check', title: '마음 체크', Screen: ELDER_MOOD_002 },
  // ---- 가족 (15)
  { id: 'LOGIN_001', path: '/login', title: '로그인', Screen: LOGIN_001 },
  { id: 'JOIN_001', path: '/join', title: '가족방 참여', Screen: JOIN_001 },
  { id: 'GROUP_001', path: '/groups/new', title: '가족방 만들기', Screen: GROUP_001 },
  { id: 'GROUP_002', path: '/groups/:roomId/members', title: '구성원', Screen: GROUP_002 },
  { id: 'GROUP_003', path: '/groups/:roomId/settings', title: '가족방 설정' },
  { id: 'HOME_001', path: '/', title: '가족 홈', Screen: HOME_001 },
  { id: 'HOME_002', path: '/diaries/:diaryId', title: '일기 상세' },
  { id: 'UPLOAD_001', path: '/upload', title: '사진 올리기', Screen: UPLOAD_001 },
  { id: 'UPLOAD_002', path: '/upload/target', title: '올릴 가족방 고르기', Screen: UPLOAD_002 },
  { id: 'UPLOAD_003', path: '/upload/result', title: '올린 결과', Screen: UPLOAD_003 },
  { id: 'FDIARY_001', path: '/fdiary', title: '가족 일기' },
  { id: 'FDIARY_002', path: '/fdiary/write', title: '가족 일기 쓰기' },
  { id: 'FDIARY_003', path: '/fdiary/confirm', title: '가족 일기 확인' },
  { id: 'WEEKLY_001', path: '/weekly/:roomId', title: '주간 이야기', Screen: WEEKLY_001 },
  { id: 'NOTI_001', path: '/notifications', title: '알림', Screen: NOTI_001 },
]

/**
 * 홈 화면 아이콘으로 열 때의 첫 주소 (manifest start_url, D68). 어르신 폰이면 어르신 홈, 아니면 가족 홈
 * (가족 홈은 로그인 안 했으면 로그인으로 보낸다). 한 폰이 둘 다면(개발용 폰) 어르신이 먼저다.
 * 401 이 아닌 실패(폰을 켠 직후 망이 아직 안 붙음 등)는 붙을 때까지 다시 묻는다 — 어르신 폰이 가족 화면으로 가지 않게.
 */
function Start() {
  const { data, error, reload } = useFetch<DeviceOut>('/api/devices/me')
  const notElder = error?.status === 401
  useEffect(() => {
    if (!error || notElder) return
    const timer = window.setTimeout(reload, 5_000) // 어르신 홈(ELDER_HOME_001)과 같은 간격
    return () => window.clearTimeout(timer)
  }, [error, notElder, reload])
  if (data) return <Navigate to="/elder" replace />
  if (notElder) return <Navigate to="/" replace />
  if (error)
    return (
      <main className="elder">
        <p className="elder-text">연결이 잠깐 끊겼어요. 잠시 뒤에 다시 열어 볼게요.</p>
      </main>
    )
  return null
}

export default function App() {
  return (
    <Routes>
      {SCREENS.map(({ id, path, title, Screen }) => (
        <Route key={id} path={path} element={Screen ? <Screen /> : <NotYet id={id} title={title} />} />
      ))}
      <Route path="/start" element={<Start />} />
      <Route path="*" element={<NotYet id="404" title="없는 주소" />} />
    </Routes>
  )
}
