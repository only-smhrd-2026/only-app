/**
 * ELDER_DIARY_001 — 일기 시작. 질문 글 상자를 누르면 다시 읽고, [그냥 이야기]로 대화를 연다 (D51·D53).
 * 사진 없이 말로 쓰는 일기 → 확인 화면에서 그림일기 (D36). [사진 찍기]는 다음 작업에서 추가한다.
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { SessionOut } from '../../api/types'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { speak, stopSpeaking } from '../../lib/audio'

const ASK = '오늘은 뭐 하셨어요? 그냥 이야기하실래요?'

export default function ELDER_DIARY_001() {
  const nav = useNavigate()
  const loc = useLocation()
  const { home } = (loc.state ?? {}) as ElderNavState
  const live = useLive()
  // 같은 화면에서는 같은 session_id → 두 번 눌러도 서버가 멱등으로 세션 하나만 만든다
  const [sessionId] = useState(() => crypto.randomUUID())
  const [busy, setBusy] = useState(false)
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

  async function start() {
    if (busy) return
    setBusy(true)
    setError(undefined)
    try {
      const s = await api<SessionOut>('/api/elder/sessions', { body: { session_id: sessionId, kind: 'DIARY' } })
      if (!live.current) return // 기다리다 뒤로 가기로 떠났으면 끌고 가지 않는다
      nav(`/elder/diary/${sessionId}`, { state: { session: s, home } })
    } catch (e) {
      if (!live.current) return
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
      <div className="elder-tiles elder-tiles--one">
        <button type="button" className="elder-tile elder-tile--4" onClick={start} disabled={busy}>
          <svg
            className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
          >
            <path d="M5 5h14v10h-9l-4 4v-4H5z" />
          </svg>
          <span>{busy ? '잠시만요…' : '그냥 이야기'}</span>
        </button>
      </div>
      {error && <p className="elder-text" role="alert">{error}</p>}
    </main>
  )
}
