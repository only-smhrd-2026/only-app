/** ELDER_ALBUM_001 — 사진첩. 사진을 고르면 그 사진으로 회상 대화를 시작한다 (FR-ME-008). */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { AlbumOut, SessionOut } from '../../api/types'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { speak, stopSpeaking } from '../../lib/audio'
import './ELDER_ALBUM_001.css'

export default function ELDER_ALBUM_001() {
  const nav = useNavigate()
  const loc = useLocation()
  // 홈이 넘긴 정보를 회상 화면까지 넘긴다 → 회상 화면이 세션·홈을 다시 읽지 않아 첫 질문을 서버 음성으로 읽는다
  const { home } = (loc.state ?? {}) as ElderNavState
  const speed = Number(home?.settings.tts_speed) || 0.9
  const { data, error, loading, reload } = useFetch<AlbumOut>('/api/elder/album')
  const live = useLive()
  const [busy, setBusy] = useState(false)
  const [startError, setStartError] = useState<string>()
  const [limitMessage, setLimitMessage] = useState<string>() // 오늘 사진첩 이야기를 다 했으면 사진을 잠근다
  const starting = useRef(false)
  // 응답을 못 받아 같은 사진을 다시 누르더라도 서버에서 대화를 중복으로 만들지 않는다.
  const sessionIds = useRef(new Map<number, string>())

  useEffect(() => () => stopSpeaking(), []) // 떠나면 안내 소리를 멈춘다 — 다음 화면 첫 질문과 겹치지 않게

  async function startMemory(photo: AlbumOut['photos'][number]) {
    if (starting.current) return
    starting.current = true
    setBusy(true)
    setStartError(undefined)
    try {
      const sessionId = sessionIds.current.get(photo.photo_id) ?? crypto.randomUUID()
      sessionIds.current.set(photo.photo_id, sessionId)
      const session = await api<SessionOut>('/api/elder/sessions', {
        body: { session_id: sessionId, kind: 'ALBUM', photo_id: photo.photo_id },
      })
      if (!live.current) return // 기다리는 중 [처음으로]·뒤로 가기로 떠났으면 다시 끌고 가지 않는다.
      nav(`/elder/memory/${sessionId}`, { state: { session, photoUrl: photo.url, home } })
    } catch (e) {
      if (live.current) {
        const message = e instanceof ApiError ? e.message : '대화를 시작하지 못했어요. 다시 눌러 주세요.'
        if (e instanceof ApiError && e.code === 'ALBUM_LIMIT') {
          setLimitMessage(message)
          window.scrollTo(0, 0) // 아래 사진을 눌렀어도 맨 위 안내가 보이게
        } else {
          setStartError(message)
        }
        void speak(message, speed)
      }
    } finally {
      starting.current = false
      if (live.current) setBusy(false)
    }
  }

  return (
    <main className="elder elder-album">
      <h1 className="elder-text elder-text--lg">사진첩</h1>
      <button className="elder-btn elder-btn--secondary" onClick={() => nav('/elder')}>처음으로</button>
      {loading ? (
        <p className="elder-text" role="status">잠시만요…</p>
      ) : error ? (
        <>
          <p className="elder-text" role="alert">
            {error.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : error.message}
          </p>
          {error.code !== 'DEVICE_REQUIRED' && <button className="elder-btn" onClick={reload}>다시 보기</button>}
        </>
      ) : data && (
        <>
          {data.photos.length > 0 && (
            <p className="elder-text" role="status">
              {limitMessage ?? (busy ? '잠시만요…' : '이야기할 사진을 눌러 주세요.')}
            </p>
          )}
          {startError && <p className="elder-text" role="alert">{startError}</p>}
          {data.photos.length === 0 ? (
            <p className="elder-text">아직 사진이 없어요.</p>
          ) : (
            <div className="elder-album-grid" role="group" aria-label="사진 목록" aria-busy={busy}>
              {data.photos.map((photo, i) => (
                <button
                  key={photo.photo_id}
                  className="elder-btn elder-album-photo"
                  onClick={() => void startMemory(photo)}
                  disabled={busy || !!limitMessage}
                >
                  <img src={photo.url} alt={`사진 ${i + 1}`} loading="lazy" decoding="async" />
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </main>
  )
}
