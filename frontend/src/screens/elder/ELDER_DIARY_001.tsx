/**
 * ELDER_DIARY_001 — 일기 시작. 사진을 찍거나 그냥 이야기로 대화를 연다 (D51·D53, FR-DI-001).
 * 업로드 응답이 끊겨도 같은 사진·요청 번호로 재시도해 사진이 중복 저장되지 않게 한다.
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { PhotoOut, SessionOut } from '../../api/types'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { speak, stopSpeaking } from '../../lib/audio'

const ASK = '오늘은 뭐 하셨어요? 사진을 찍으실래요, 그냥 이야기하실래요?'

export default function ELDER_DIARY_001() {
  const nav = useNavigate()
  const loc = useLocation()
  const { home } = (loc.state ?? {}) as ElderNavState
  const live = useLive()
  // 같은 화면에서는 같은 session_id → 두 번 눌러도 서버가 멱등으로 세션 하나만 만든다
  const [sessionId] = useState(() => crypto.randomUUID())
  const [busy, setBusy] = useState(false)
  const [starting, setStarting] = useState<'photo' | 'talk'>()
  const photoInput = useRef<HTMLInputElement>(null)
  const pendingPhoto = useRef<{ file: File; batchId: string } | undefined>(undefined)
  const [error, setError] = useState<string>()
  const speed = Number(home?.settings.tts_speed) || 0.85
  const [saying, setSaying] = useState(false)
  const sayingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    void speak(ASK, speed)
    return () => {
      stopSpeaking()
      clearTimeout(sayingTimer.current)
    }
  }, [speed])

  function readQuestion() {
    void speak(ASK, speed)
    setSaying(true)
    clearTimeout(sayingTimer.current)
    sayingTimer.current = setTimeout(() => setSaying(false), 1400)
  }

  async function start(withPhoto = false) {
    if (busy) return
    const pending = withPhoto ? pendingPhoto.current : undefined
    if (withPhoto && !pending) return
    setBusy(true)
    setStarting(withPhoto ? 'photo' : 'talk')
    setError(undefined)
    try {
      let photo: PhotoOut | undefined
      if (pending) {
        const form = new FormData()
        form.append('files', pending.file)
        form.append('upload_batch_id', pending.batchId)
        photo = await api<PhotoOut>('/api/elder/photos', { form })
        if (!live.current) return // 사진을 올리는 중 떠났으면 대화를 열지 않는다
      }
      const s = await api<SessionOut>('/api/elder/sessions', {
        body: { session_id: sessionId, kind: 'DIARY', photo_id: photo?.photo_id },
      })
      if (!live.current) return // 기다리다 뒤로 가기로 떠났으면 끌고 가지 않는다
      nav(`/elder/diary/${sessionId}`, { state: { session: s, home, photoUrl: s.photo_url ?? undefined } })
    } catch (e) {
      if (!live.current) return
      // 거절된 사진은 다시 고르고, 연결·서버 오류는 같은 사진과 번호를 남겨 재시도한다.
      if (withPhoto && e instanceof ApiError && e.status >= 400 && e.status < 500) {
        pendingPhoto.current = undefined
      }
      const message = e instanceof ApiError
        ? e.code === 'DEVICE_REQUIRED'
          ? '가족이 보낸 연결 링크를 먼저 열어 주세요.'
          : e.message
        : '대화를 시작하지 못했어요. 다시 눌러 주세요.'
      setError(message)
      void speak(message, speed)
      setBusy(false)
    }
  }

  function takePhoto() {
    if (busy) return
    if (pendingPhoto.current) void start(true)
    else photoInput.current?.click()
  }

  return (
    <main className="elder elder--fit">
      <button type="button" className={`elder-ask${saying ? ' elder-saying' : ''}`} onClick={readQuestion}>
        <span>{ASK}</span>
        <svg
          className="elder-spk" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
        >
          <path d="M4 9.5v5h3.2L12 18.5v-13L7.2 9.5z" />
          <path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.3 6.3a8 8 0 0 1 0 11.4" />
        </svg>
      </button>
      <input
        type="file" accept="image/*" capture="environment" hidden ref={photoInput}
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (!file || busy || !live.current) return
          pendingPhoto.current = { file, batchId: crypto.randomUUID() }
          void start(true)
        }}
      />
      <div className="elder-tiles elder-tiles--one">
        <button type="button" className="elder-tile elder-tile--2" onClick={takePhoto} disabled={busy}>
          <svg
            className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
          >
            <path d="M4 8h3l1.5-2h7L17 8h3v11H4z" />
            <circle cx="12" cy="13.5" r="3.2" />
          </svg>
          <span>{busy && starting === 'photo' ? '잠시만요…' : '사진 찍기'}</span>
        </button>
        <button type="button" className="elder-tile elder-tile--4" onClick={() => void start()} disabled={busy}>
          <svg
            className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
          >
            <path d="M5 5h14v10h-9l-4 4v-4H5z" />
          </svg>
          <span>{busy && starting === 'talk' ? '잠시만요…' : '그냥 이야기'}</span>
        </button>
      </div>
      {error && <p className="elder-text" role="alert">{error}</p>}
    </main>
  )
}
