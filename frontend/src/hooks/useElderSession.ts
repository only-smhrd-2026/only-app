import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { ElderHomeOut, SessionGetOut, SessionOut } from '../api/types'

/** 앞 화면이 navigate(…, { state }) 로 넘기는 것 */
export type ElderNavState = { session?: SessionOut; photoUrl?: string; home?: ElderHomeOut }

/**
 * 화면이 아직 떠 있는지. 요청을 기다리는 동안 [처음으로]·뒤로 가기로 떠났으면 응답이 와도 이동·낭독하지 않는다.
 * (react-router 의 navigate 는 화면이 사라진 뒤에도 이동시킨다.) StrictMode 의 가짜 언마운트 뒤에도 다시 true.
 */
export function useLive() {
  const live = useRef(true)
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])
  return live
}

/**
 * 어르신 대화 화면(회상 ELDER_MEMORY_001 · 일기 ELDER_DIARY_002) 공통.
 * 앞 화면이 넘긴 세션·홈 정보를 쓰고, 새로고침 등으로 없으면 서버에서 다시 읽는다 (30분 안 복귀).
 * 세션을 찾을 수 없으면 홈으로 보낸다.
 */
export function useElderSession(sessionId: string) {
  const nav = useNavigate()
  const loc = useLocation()
  const live = useLive()
  const state = (loc.state ?? {}) as ElderNavState
  const [session, setSession] = useState<SessionOut | undefined>(state.session)
  const [home, setHome] = useState<ElderHomeOut | undefined>(state.home)
  const [photoUrl] = useState<string | undefined>(state.photoUrl)

  // 넘겨받은 state 는 위 state 로 옮겼으니 주소에서 지운다 → 새로고침하면 서버에서 다시 읽는다(30분 복귀 경로)
  useEffect(() => {
    if (loc.state) nav(loc.pathname, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (session && home) return
    // 없는 것만 읽는다. 넘겨받은 세션을 다시 읽어 덮으면 첫 질문의 서버 음성(audio_b64)을 잃는다
    Promise.all([
      session ? null : api<SessionGetOut>(`/api/elder/sessions/${sessionId}`),
      home ?? api<ElderHomeOut>('/api/elder/home'),
    ])
      .then(([s, h]) => {
        if (!live.current) return
        if (s) {
          if (!s.last_ai) return nav('/elder', { replace: true }) // 질문이 없는 세션은 이어 갈 수 없다
          setSession({
            session_id: s.session_id,
            kind: s.kind,
            photo_url: s.photo_url,
            ai: s.last_ai,
            state: s.state,
            end_reason: s.end_reason,
            turn_no: s.turn_no,
            input_locked: s.input_locked,
          })
        }
        setHome(h)
      })
      .catch(() => live.current && nav('/elder', { replace: true }))
  }, [sessionId, session, home, nav, live])

  return { session, home, photoUrl }
}
