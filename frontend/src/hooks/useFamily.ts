/** 가족 공통 틀(components/FamilyFrame, D70)이 탭 화면에 주는 것 — const { me, room } = useFamily() */
import { useOutletContext } from 'react-router-dom'
import type { RoomOut, UserOut } from '../api/types'

// room = 지금 보는 어르신의 가족방(위 막대에서 바꿈). 가족방이 하나도 없으면 null
export type FamilyCtx = { me: UserOut; rooms: RoomOut[]; room: RoomOut | null; reloadRooms: () => void }
export const useFamily = () => useOutletContext<FamilyCtx>()
