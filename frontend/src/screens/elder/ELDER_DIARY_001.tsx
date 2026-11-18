/**
 * ELDER_DIARY_001 — 일기 시작. 홈처럼 큰 상자 4개: [사진 찍기] [사진 고르기](폰 사진첩) [그냥 이야기] [지난 일기]
 * (D51·D53·D79, FR-DI-001). 고른 사진도 찍은 사진과 같은 길로 올린다(1280px — 옛 사진이면 그때 이야기, FR-DI-002).
 * [지난 일기]는 내가 올린 일기 목록(ELDER_DIARY_004)으로 간다 (D60).
 * 업로드 응답이 끊겨도 같은 사진·요청 번호로 재시도해 사진이 중복 저장되지 않게 한다.
 */
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { PhotoOut, SessionOut } from '../../api/types'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { speak, stopSpeaking } from '../../lib/audio'
import { resizeImage } from '../../lib/resizeImage'

const ASK = '오늘은 뭐 하셨어요? 사진으로 할까요, 그냥 이야기할까요?'
type From = 'photo' | 'pick' // 사진 찍기 / 사진 고르기

export default function ELDER_DIARY_001() {
  const nav = useNavigate()
  const loc = useLocation()
  const { home } = (loc.state ?? {}) as ElderNavState
  const live = useLive()
  // 같은 화면에서는 같은 session_id → 두 번 눌러도 서버가 멱등으로 세션 하나만 만든다
  const [sessionId] = useState(() => crypto.randomUUID())
  const [busy, setBusy] = useState(false)
  const [resizing, setResizing] = useState(false)
  const [starting, setStarting] = useState<From | 'talk'>()
  const photoInput = useRef<HTMLInputElement>(null)
  const pickInput = useRef<HTMLInputElement>(null)
  // 사진 대화는 대화 번호를 따로 쓴다 — [그냥 이야기]의 응답만 끊겨 서버에 사진 없는 대화가 이미 있으면,
  // 같은 번호로는 서버가 그 대화를 돌려줘 사진이 일기에 안 붙는다
  const pendingPhoto = useRef<{ file: File; batchId: string; sessionId: string; from: From } | undefined>(undefined)
  const [error, setError] = useState<string>()
  const speed = Number(home?.settings.tts_speed) || 0.9
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
    setStarting(pending?.from ?? 'talk')
    setError(undefined)
    const id = pending?.sessionId ?? sessionId
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
        body: { session_id: id, kind: 'DIARY', photo_id: photo?.photo_id },
      })
      if (!live.current) return // 기다리다 뒤로 가기로 떠났으면 끌고 가지 않는다
      // replace — 대화 중 뒤로 키는 홈으로 (D52 ⑥). 이 화면으로 돌아오면 질문을 다시 읽고 새 대화가 열린다
      nav(`/elder/diary/${id}`, { replace: true, state: { session: s, home, photoUrl: s.photo_url ?? undefined } })
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

  function choosePhoto(from: From) {
    if (busy || resizing) return
    if (pendingPhoto.current) void start(true) // 끊겼던 사진은 같은 사진·번호로 다시
    else (from === 'photo' ? photoInput : pickInput).current?.click()
  }

  async function onPhoto(e: ChangeEvent<HTMLInputElement>, from: From) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || busy || resizing || !live.current) return
    setResizing(true)
    setStarting(from)
    setError(undefined)
    let photo = file
    try {
      photo = await resizeImage(file, 1280)
    } catch {
      // 읽지 못하는 형식 등으로 축소가 실패해도 원본 사진으로 업로드를 시도한다.
    } finally {
      if (live.current) setResizing(false)
    }
    if (!live.current) return
    pendingPhoto.current = { file: photo, batchId: crypto.randomUUID(), sessionId: crypto.randomUUID(), from }
    void start(true)
  }

  return (
    <main className="elder elder--fit">
      <button type="button" className={`elder-ask${saying ? ' elder-saying' : ''}`} onClick={readQuestion} disabled={busy || resizing}>
        <span>{ASK}</span>
        <svg
          className="elder-spk" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
        >
          <path d="M4 9.5v5h3.2L12 18.5v-13L7.2 9.5z" />
          <path d="M15.5 9a4.2 4.2 0 0 1 0 6M18.3 6.3a8 8 0 0 1 0 11.4" />
        </svg>
      </button>
      {/* capture 있음 = 바로 카메라 · 없음 = 폰 사진첩(갤러리)에서 고르기 */}
      <input type="file" accept="image/*" capture="environment" hidden ref={photoInput} onChange={(e) => void onPhoto(e, 'photo')} />
      <input type="file" accept="image/*" hidden ref={pickInput} onChange={(e) => void onPhoto(e, 'pick')} />
      <div className="elder-tiles">
        <button type="button" className="elder-tile elder-tile--2" onClick={() => choosePhoto('photo')} disabled={busy || resizing}>
          <svg
            className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
          >
            <path d="M4 8h3l1.5-2h7L17 8h3v11H4z" />
            <circle cx="12" cy="13.5" r="3.2" />
          </svg>
          <span>{(busy || resizing) && starting === 'photo' ? '잠시만요…' : '사진 찍기'}</span>
        </button>
        <button type="button" className="elder-tile elder-tile--1" onClick={() => choosePhoto('pick')} disabled={busy || resizing}>
          <svg
            className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
          >
            <rect x="3" y="5" width="18" height="14" rx="2.5" />
            <circle cx="8.5" cy="10" r="1.6" />
            <path d="M21 16l-5-5-7.5 8" />
          </svg>
          <span>{(busy || resizing) && starting === 'pick' ? '잠시만요…' : '사진 고르기'}</span>
        </button>
        <button type="button" className="elder-tile elder-tile--4" onClick={() => void start()} disabled={busy || resizing}>
          <svg
            className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
          >
            <path d="M5 5h14v10h-9l-4 4v-4H5z" />
          </svg>
          <span>{busy && starting === 'talk' ? '잠시만요…' : '그냥 이야기'}</span>
        </button>
        <button
          type="button" className="elder-tile elder-tile--3"
          onClick={() => nav('/elder/diaries', { state: { home } })} disabled={busy || resizing}
        >
          <svg
            className="elder-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
          >
            <path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z" />
            <path d="M5 17a3 3 0 0 1 3-3h11M9 8h6" />
          </svg>
          <span>지난 일기</span>
        </button>
      </div>
      {error && <p className="elder-text" role="alert">{error}</p>}
    </main>
  )
}
