/**
 * ELDER_HOME_001 — 어르신 홈. 인사 + 버튼 2개 (오늘 사진 보기 / 사진첩). 디자인 없음 (김승희 교체).
 * 오늘의 한 장 팝업(ELDER_TODAY_001)은 김승희 첫 PR — 지금은 버튼이 바로 회상 대화를 시작한다.
 */
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { ElderHomeOut, SessionOut } from '../../api/types'
import { useFetch } from '../../hooks/useFetch'

export default function ELDER_HOME_001() {
  const nav = useNavigate()
  const { data: home, error, loading } = useFetch<ElderHomeOut>('/api/elder/home')

  useEffect(() => {
    if (home) document.documentElement.dataset.font = home.settings.font_size
  }, [home])

  async function startMemory() {
    if (!home?.today_pick) return
    const session_id = crypto.randomUUID()
    const s = await api<SessionOut>('/api/elder/sessions', {
      body: { session_id, kind: 'MEMORY', pick_id: home.today_pick.pick_id, photo_id: home.today_pick.photo_id },
    })
    nav(`/elder/memory/${session_id}`, { state: { session: s, photoUrl: home.today_pick.photo_url, home } })
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
      {pick?.status === 'PENDING' ? (
        <button className="elder-btn" onClick={startMemory}>오늘 사진 보기</button>
      ) : (
        <p className="elder-text">{pick ? '오늘 이야기는 다 나눴어요.' : '오늘은 아직 사진이 없어요.'}</p>
      )}
      <button className="elder-btn elder-btn--secondary" onClick={() => nav('/elder/album')}>사진첩</button>
    </main>
  )
}
