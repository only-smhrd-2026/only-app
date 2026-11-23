/**
 * ELDER_DIARY_001 — 일기 시작 (11/23 시안 e-diary). 꼬마심심이 + 질문 말풍선 + 큰 버튼 3개
 * [지금 사진 찍기](카메라) [사진 고르기](폰 사진첩) [말로만 하기] + 아래 작게 [지난 일기 보기](ELDER_DIARY_004, D60).
 * 고른 사진도 찍은 사진과 같은 길로 올린다(1280px — 옛 사진이면 그때 이야기, FR-DI-002).
 * 업로드 응답이 끊겨도 같은 사진·요청 번호로 재시도해 사진이 중복 저장되지 않게 한다.
 */
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { PhotoOut, SessionOut } from '../../api/types'
import { Bub, IC } from '../../components/ElderUi'
import Sim from '../../components/Sim'
import { useLive, type ElderNavState } from '../../hooks/useElderSession'
import { speak, stopSpeaking } from '../../lib/audio'
import { resizeImage } from '../../lib/resizeImage'

const ASK = '오늘은 뭐 하셨어요? 사진을 찍을까요, 고를까요, 말로만 할까요?'
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
  // 사진 대화는 대화 번호를 따로 쓴다 — [말로만 하기]의 응답만 끊겨 서버에 사진 없는 대화가 이미 있으면,
  // 같은 번호로는 서버가 그 대화를 돌려줘 사진이 일기에 안 붙는다
  const pendingPhoto = useRef<{ file: File; batchId: string; sessionId: string; from: From } | undefined>(undefined)
  const [error, setError] = useState<string>()
  const speed = Number(home?.settings.tts_speed) || 0.9
  const locked = busy || resizing

  useEffect(() => {
    void speak(ASK, speed)
    return () => stopSpeaking()
  }, [speed])

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
    if (locked) return
    // 끊겼던 사진은 같은 버튼을 다시 누를 때만 같은 사진·번호로 다시 — 다른 버튼이면 그 사진은 버리고 새로 찍기·고르기
    // ponytail: 올리기는 됐는데 대화 열기만 끊긴 사진은 서버에 한 장 남는다(어르신 일기에는 안 붙음)
    if (pendingPhoto.current?.from === from) return void start(true)
    pendingPhoto.current = undefined
    ;(from === 'photo' ? photoInput : pickInput).current?.click()
  }

  async function onPhoto(e: ChangeEvent<HTMLInputElement>, from: From) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || locked || !live.current) return
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

  const label = (from: From | 'talk', text: string) => (locked && starting === from ? '잠시만요…' : text)

  return (
    <main className="elder elder--fit">
      <h1 className="elder-sr">일기 쓰기</h1>
      <Sim face="ask" size={168} className="elder-sim elder-simflex" />
      <Bub text={ASK} speed={speed} className="elder-bub--up" />
      {/* capture 있음 = 바로 카메라 · 없음 = 폰 사진첩(갤러리)에서 고르기 */}
      <input type="file" accept="image/*" capture="environment" hidden ref={photoInput} onChange={(e) => void onPhoto(e, 'photo')} />
      <input type="file" accept="image/*" hidden ref={pickInput} onChange={(e) => void onPhoto(e, 'pick')} />
      <div className="elder-col">
        <button type="button" className="elder-btn elder-btn--wide" onClick={() => choosePhoto('photo')} disabled={locked}>
          <span className="elder-lead">{IC.cam}</span>{label('photo', '지금 사진 찍기')}<span className="elder-go">{IC.next}</span>
        </button>
        <button type="button" className="elder-btn elder-btn--secondary elder-btn--wide" onClick={() => choosePhoto('pick')} disabled={locked}>
          <span className="elder-lead">{IC.pic}</span>{label('pick', '사진 고르기')}<span className="elder-go">{IC.next}</span>
        </button>
        <button type="button" className="elder-btn elder-btn--secondary elder-btn--wide" onClick={() => void start()} disabled={locked}>
          <span className="elder-lead">{IC.chat}</span>{label('talk', '말로만 하기')}<span className="elder-go">{IC.next}</span>
        </button>
        {error && <p className="elder-text" role="alert">{error}</p>}
        <button
          type="button"
          className="elder-btn elder-btn--secondary elder-btn--sm"
          style={{ alignSelf: 'center' }}
          onClick={() => nav('/elder/diaries', { state: { home } })}
          disabled={locked}
        >
          {IC.book}지난 일기 보기
        </button>
      </div>
    </main>
  )
}
