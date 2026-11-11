/** ELDER_ALBUM_001 — 사진첩. 사진을 고르면 그 사진으로 회상 대화를 시작한다 (FR-ME-008). */
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { AlbumOut, SessionOut } from '../../api/types'
import { useLive } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import './ELDER_ALBUM_001.css'

export default function ELDER_ALBUM_001() {
  const nav = useNavigate()
  const { data, error, loading, reload } = useFetch<AlbumOut>('/api/elder/album')
  const live = useLive()
  const [busy, setBusy] = useState(false)
  const [startError, setStartError] = useState<string>()
  const starting = useRef(false)
  // 응답을 못 받아 같은 사진을 다시 누르더라도 서버에서 대화를 중복으로 만들지 않는다.
  const sessionIds = useRef(new Map<number, string>())

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
      nav(`/elder/memory/${sessionId}`, { state: { session, photoUrl: photo.url } })
    } catch (e) {
      if (live.current) {
        setStartError(e instanceof ApiError ? e.message : '대화를 시작하지 못했어요. 다시 눌러 주세요.')
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
          <p className="elder-text" role="alert">{error.message}</p>
          <button className="elder-btn" onClick={reload}>다시 보기</button>
        </>
      ) : data && (
        <>
          {data.photos.length > 0 && <p className="elder-text" role="status">{busy ? '잠시만요…' : '이야기할 사진을 눌러 주세요.'}</p>}
          {startError && <p className="elder-text" role="alert">{startError}</p>}
          {data.photos.length === 0 ? (
            <p className="elder-text">아직 사진이 없어요.</p>
          ) : (
            <div className="elder-album-grid" aria-label="가족 사진" aria-busy={busy}>
              {data.photos.map((photo) => (
                <button
                  key={photo.photo_id}
                  className="elder-btn elder-album-photo"
                  onClick={() => void startMemory(photo)}
                  disabled={busy}
                >
                  <img src={photo.url} alt="가족이 올린 사진" />
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </main>
  )
}
