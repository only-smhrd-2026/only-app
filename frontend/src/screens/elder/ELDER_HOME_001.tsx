/**
 * ELDER_HOME_001 — 어르신 홈. 인사 + 버튼 (오늘 사진 보기 / 오늘 이야기하기 / 사진첩). 디자인 없음 (김승희 교체).
 * 오늘의 한 장 팝업(ELDER_TODAY_001)은 김승희 첫 PR — 지금은 버튼이 바로 회상 대화를 시작한다.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { ElderHomeOut, SessionOut } from '../../api/types'
import { useLive } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'

export default function ELDER_HOME_001() {
  const nav = useNavigate()
  const { data: home, error, loading } = useFetch<ElderHomeOut>('/api/elder/home')
  // 같은 화면에서는 같은 session_id 를 쓴다 → 두 번 눌러도 서버가 멱등으로 세션 하나만 만든다
  const [sessionId] = useState(() => crypto.randomUUID())
  const [busy, setBusy] = useState(false)
  const [startError, setStartError] = useState<string>()
  const live = useLive()

  useEffect(() => {
    if (home) document.documentElement.dataset.font = home.settings.font_size
  }, [home])

  async function startMemory() {
    if (!home?.today_pick || busy) return
    setBusy(true)
    setStartError(undefined)
    try {
      const s = await api<SessionOut>('/api/elder/sessions', {
        body: {
          session_id: sessionId,
          kind: 'MEMORY',
          pick_id: home.today_pick.pick_id,
          photo_id: home.today_pick.photo_id,
        },
      })
      if (!live.current) return // 기다리는 동안 [오늘 이야기하기]·[사진첩]으로 떠났으면 끌고 가지 않는다
      nav(`/elder/memory/${sessionId}`, { state: { session: s, photoUrl: home.today_pick.photo_url, home } })
    } catch (e) {
      setStartError((e as ApiError).message)
      setBusy(false)
    }
  }

  if (loading) return <main className="elder"><p className="elder-text">잠시만요…</p></main>
  if (error)
    return (
      <main className="elder">
        <p className="elder-text">
          {error.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : (error as ApiError).message}
        </p>
      </main>
    )
  if (!home) return null

  const pick = home.today_pick
  return (
    <main className="elder">
      <p className="elder-text elder-text--lg">{home.greeting}</p>
      {home.unread_family_news > 0 && <p className="elder-text">새로운 가족 소식이 {home.unread_family_news}개 있어요.</p>}
      {startError && <p className="elder-text">{startError}</p>}
      {pick?.status === 'PENDING' ? (
        <button className="elder-btn" onClick={startMemory} disabled={busy}>
          {busy ? '잠시만요…' : '오늘 사진 보기'}
        </button>
      ) : (
        <p className="elder-text">{pick ? '오늘 이야기는 다 나눴어요.' : '오늘은 아직 사진이 없어요.'}</p>
      )}
      <button className="elder-btn" onClick={() => nav('/elder/diary', { state: { home } })}>오늘 이야기하기</button>
      <button className="elder-btn elder-btn--secondary" onClick={() => nav('/elder/album')}>사진첩</button>
    </main>
  )
}
