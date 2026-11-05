/**
 * 화면 25개 ↔ 경로 표 (설계안 v1 4절). 파일 이름 = 화면설계서 화면 ID (D11).
 * 아직 없는 화면은 NotYet 이 "준비 중" 을 보여 준다. 화면을 만들면 Screen 칸에 컴포넌트를 넣는다.
 */
import type { ComponentType } from 'react'
import { Route, Routes } from 'react-router-dom'
import NotYet from './screens/NotYet'
import ELDER_CONNECT_001 from './screens/elder/ELDER_CONNECT_001'
import ELDER_DIARY_001 from './screens/elder/ELDER_DIARY_001'
import ELDER_DIARY_002 from './screens/elder/ELDER_DIARY_002'
import ELDER_DIARY_003 from './screens/elder/ELDER_DIARY_003'
import ELDER_HOME_001 from './screens/elder/ELDER_HOME_001'
import ELDER_MEMORY_001 from './screens/elder/ELDER_MEMORY_001'
import GROUP_001 from './screens/family/GROUP_001'
import HOME_001 from './screens/family/HOME_001'
import LOGIN_001 from './screens/family/LOGIN_001'

export type ScreenDef = { id: string; path: string; title: string; Screen?: ComponentType }

export const SCREENS: ScreenDef[] = [
  // ---- 어르신 (10)
  { id: 'ELDER_CONNECT_001', path: '/elder/connect', title: '어르신 기기 연결', Screen: ELDER_CONNECT_001 },
  { id: 'ELDER_HOME_001', path: '/elder', title: '어르신 홈', Screen: ELDER_HOME_001 },
  { id: 'ELDER_TODAY_001', path: '/elder/today', title: '오늘의 한 장' },
  { id: 'ELDER_MEMORY_001', path: '/elder/memory/:sessionId', title: '회상 대화', Screen: ELDER_MEMORY_001 },
  { id: 'ELDER_MEMORY_002', path: '/elder/memory/:sessionId/done', title: '회상 마무리' },
  { id: 'ELDER_ALBUM_001', path: '/elder/album', title: '사진첩' },
  { id: 'ELDER_DIARY_001', path: '/elder/diary', title: '오늘 일기', Screen: ELDER_DIARY_001 },
  { id: 'ELDER_DIARY_002', path: '/elder/diary/:sessionId', title: '일기 대화', Screen: ELDER_DIARY_002 },
  { id: 'ELDER_DIARY_003', path: '/elder/diary/:sessionId/confirm', title: '일기 확인', Screen: ELDER_DIARY_003 },
  { id: 'ELDER_FAMILY_001', path: '/elder/family-news', title: '가족 소식' },
  // ---- 가족 (15)
  { id: 'LOGIN_001', path: '/login', title: '로그인', Screen: LOGIN_001 },
  { id: 'JOIN_001', path: '/join', title: '가족방 참여' },
  { id: 'GROUP_001', path: '/groups/new', title: '가족방 만들기', Screen: GROUP_001 },
  { id: 'GROUP_002', path: '/groups/:roomId/members', title: '구성원' },
  { id: 'GROUP_003', path: '/groups/:roomId/settings', title: '가족방 설정' },
  { id: 'HOME_001', path: '/', title: '가족 홈', Screen: HOME_001 },
  { id: 'HOME_002', path: '/diaries/:diaryId', title: '일기 상세' },
  { id: 'UPLOAD_001', path: '/upload', title: '사진 올리기' },
  { id: 'UPLOAD_002', path: '/upload/target', title: '올릴 가족방 고르기' },
  { id: 'UPLOAD_003', path: '/upload/result', title: '올린 결과' },
  { id: 'FDIARY_001', path: '/fdiary', title: '가족 일기' },
  { id: 'FDIARY_002', path: '/fdiary/write', title: '가족 일기 쓰기' },
  { id: 'FDIARY_003', path: '/fdiary/confirm', title: '가족 일기 확인' },
  { id: 'WEEKLY_001', path: '/weekly/:roomId', title: '주간 이야기' },
  { id: 'NOTI_001', path: '/notifications', title: '알림' },
]

export default function App() {
  return (
    <Routes>
      {SCREENS.map(({ id, path, title, Screen }) => (
        <Route key={id} path={path} element={Screen ? <Screen /> : <NotYet id={id} title={title} />} />
      ))}
      <Route path="*" element={<NotYet id="404" title="없는 주소" />} />
    </Routes>
  )
}
