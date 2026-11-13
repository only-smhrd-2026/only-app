/** ELDER_FAMILY_001 — 아직 듣지 않은 가족 일기를 한 장씩 읽는다 (FR-FD-003·004, D53). */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { DiaryListOut } from '../../api/types'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { useFetch } from '../../hooks/useFetch'
import { speak, stopSpeaking } from '../../lib/audio'

export default function ELDER_FAMILY_001() {
  const nav = useNavigate()
  const { home } = (useLocation().state ?? {}) as ElderNavState
  const speed = Number(home?.settings.tts_speed) || 0.85
  const { data, error, loading, reload } = useFetch<DiaryListOut>('/api/elder/family-news')
  const live = useLive()
  const [index, setIndex] = useState(0)
  const [busy, setBusy] = useState(false)
  const [readError, setReadError] = useState<string>()
  const [saying, setSaying] = useState(false)
  const reading = useRef(false)
  const sayingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const diary = data?.diaries[index]
  const sender = [diary?.author_nickname, diary?.author_name].filter(Boolean).join(' ') || '가족'
  const lastChar = sender.charCodeAt(sender.length - 1)
  const particle = lastChar >= 0xac00 && lastChar <= 0xd7a3 && (lastChar - 0xac00) % 28 !== 0 ? '이' : '가'
  const message = loading ? undefined : error
    ? error.code === 'DEVICE_REQUIRED' ? '가족이 보낸 연결 링크를 먼저 열어 주세요.' : error.message
    : diary ? `${sender}${particle} 사진 일기를 보냈어요. 읽어 드릴게요. ${diary.body}`
      : data ? '오늘은 새 소식이 없어요.' : undefined

  useEffect(() => {
    if (message) void speak(message, speed)
    return () => stopSpeaking()
  }, [message, diary?.diary_id, speed])

  useEffect(() => () => clearTimeout(sayingTimer.current), [])

  function replay() {
    if (!diary) return
    void speak(diary.body, speed)
    setSaying(true)
    clearTimeout(sayingTimer.current)
    sayingTimer.current = setTimeout(() => setSaying(false), 1_400)
  }

  async function markRead() {
    if (!diary || reading.current) return
    reading.current = true
    setBusy(true)
    setReadError(undefined)
    try {
      await api(`/api/elder/diaries/${diary.diary_id}/read`, { method: 'POST' })
      if (!live.current) return
      // 목록을 다시 읽으면 읽은 일기가 빠져 번호가 밀린다. 받은 목록에서 번호만 바꾼다.
      if (index === data!.diaries.length - 1) {
        nav('/elder', { replace: true })
      } else {
        clearTimeout(sayingTimer.current)
        setSaying(false)
        setIndex((value) => value + 1)
      }
    } catch (e) {
      if (!live.current) return
      const text = e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 해 주세요.'
      setReadError(text)
      void speak(text, speed)
    } finally {
      reading.current = false
      if (live.current) setBusy(false)
    }
  }

  return (
    <main className="elder elder--fit">
      {loading ? (
        <p className="elder-text" role="status">잠시만요…</p>
      ) : error ? (
        <>
          <p className="elder-text" role="alert">{message}</p>
          {error.code !== 'DEVICE_REQUIRED' && <button className="elder-btn" onClick={reload}>다시 보기</button>}
        </>
      ) : diary ? (
        <>
          <div className="elder-who"><span>{sender}</span><small>{index + 1} / {data!.diaries.length}</small></div>
          {diary.illustration_url && (
            <div className="elder-photo-box elder-photo-box--grow">
              <img src={diary.illustration_url} alt="가족이 보낸 사진" />
            </div>
          )}
          <button type="button" className={`elder-paper${saying ? ' elder-saying' : ''}`} onClick={replay}>
            <span>{diary.body}</span>
            <svg className="elder-spk" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 9.5v5h3.2L12 18.5v-13L7.2 9.5z" />
              <path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.3 6.3a8 8 0 0 1 0 11.4" />
            </svg>
          </button>
          {readError && <p className="elder-text" role="alert">{readError}</p>}
          <button className="elder-btn elder-bottom" disabled={busy} onClick={() => void markRead()}>
            {busy ? '잠시만요…' : index === data!.diaries.length - 1 ? '다 들었어요' : '다음 소식'}
          </button>
        </>
      ) : data && (
        <>
          <p className="elder-text">오늘은 새 소식이 없어요.</p>
          <button className="elder-btn" onClick={() => nav('/elder', { replace: true })}>홈으로</button>
        </>
      )}
    </main>
  )
}
