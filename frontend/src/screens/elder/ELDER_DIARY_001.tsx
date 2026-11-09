/**
 * ELDER_DIARY_001 — 오늘 이야기하기 시작. 지금은 사진 없이 말로 쓰는 일기만 (→ 확인 화면에서 그림일기, D36).
 * [사진 찍기](FR-DI-001 카메라 업로드)·옛 사진 분기(FR-DI-002)는 천주웅 업로드 API + 김승희 화면에서 붙인다. 디자인 없음.
 */
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { SessionOut } from '../../api/types'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'

export default function ELDER_DIARY_001() {
  const nav = useNavigate()
  const loc = useLocation()
  const { home } = (loc.state ?? {}) as ElderNavState
  const live = useLive()
  // 같은 화면에서는 같은 session_id → 두 번 눌러도 서버가 멱등으로 세션 하나만 만든다
  const [sessionId] = useState(() => crypto.randomUUID())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  async function start() {
    if (busy) return
    setBusy(true)
    setError(undefined)
    try {
      const s = await api<SessionOut>('/api/elder/sessions', { body: { session_id: sessionId, kind: 'DIARY' } })
      if (!live.current) return // 기다리다 [처음으로]·뒤로 가기로 떠났으면 끌고 가지 않는다
      nav(`/elder/diary/${sessionId}`, { state: { session: s, home } })
    } catch (e) {
      setError(e instanceof ApiError && e.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : (e as Error).message)
      setBusy(false)
    }
  }

  return (
    <main className="elder">
      <p className="elder-text elder-text--lg">오늘 하루 이야기를 들려주세요. 제가 일기로 써 드릴게요.</p>
      {error && <p className="elder-text">{error}</p>}
      <button className="elder-btn" onClick={start} disabled={busy}>
        {busy ? '잠시만요…' : '이야기할래요'}
      </button>
      <button className="elder-btn elder-btn--secondary" onClick={() => nav('/elder')}>처음으로</button>
    </main>
  )
}
