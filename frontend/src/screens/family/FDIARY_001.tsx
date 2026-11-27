/**
 * FDIARY_001 — 오늘 소식 보내기 (이슈 #41, 11/23 시안 f-today: 옛 3단계 '오늘 한 장' FDIARY_001~003 을 한 화면으로, D70).
 * 사진첩 탭(PHOTO_001)의 하위 화면(위 ←). 가족이 쓴 소식은 어르신 홈 '가족 소식'에서 읽어 드린다.
 * 오늘 사진 1장(안 골라도 됨) · 글(200자) · 기분 → [○○께 보내기] = 지금 보는 가족방 하나에 (사진이 있으면) 사진 올리기 → 일기 올리기.
 * 일기 동무(AI 질문 하나 → 답 → 다듬기)는 고를 때만 — 바쁜 날은 쓰고 바로 보낸다. 내 PC(AI 키 없음)는 고정 질문·쓴 말을 이은 초안.
 * 쓰던 것은 lib/familyDiaryDraft 에 바로 담아 ← 로 나갔다 와도 남는다.
 */
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import {
  MOOD_LABEL,
  type DiaryOut,
  type FamilyAskOut,
  type FamilyDraftOut,
  type MemberOut,
  type Mood,
  type PhotoBatchOut,
  type RoomOut,
  type UserOut,
} from '../../api/types'
import FamIcon from '../../components/FamIcon'
import MoodIcon from '../../components/MoodIcon'
import Sim from '../../components/Sim'
import { useFetch } from '../../hooks/useFetch'
import { clearFamilyDiaryDraft, familyDiaryDraft as d, restoreFamilyDiaryText, saveFamilyDiaryText } from '../../lib/familyDiaryDraft'
import { fitPhoto, MAX_BYTES } from '../../lib/fitPhoto' // 상한 넘는 사진 줄이기·10MB(서버와 같은 값)
import { Thumb } from './UPLOAD_001' // 미리보기 그림
import './steps.css'
import './FDIARY_001.css'

const MAX = 200 // 서버 config.py FAMILY_TEXT_MAX·FAMILY_DRAFT_MAX (글·답·초안, D61)
const MOODS: Mood[] = ['GOOD', 'SO_SO', 'UPSET', 'LONELY'] // D75 — 날씨 그림 대신 말·얼굴
// 서버가 받는 사진 종류(D17). accept 는 부탁일 뿐이라 '파일' 앱 등에서 HEIC·PDF 가 올 수 있어 고를 때 바로 막는다
const TYPES = ['image/jpeg', 'image/png']
// 틀(components/FamilyFrame)이 '지금 보는 분'을 적어 두는 칸 — 하위 화면이라 틀이 방을 주지 않아 같은 칸을 읽는다
const ROOM_KEY = 'haru.fam.room'

const msgOf = (e: unknown) => (e instanceof ApiError ? e.message : '연결이 잠깐 끊겼어요. 다시 해 주세요.')
/** 받침이 있으면 앞의 조사, 없으면 뒤의 조사 — 어르신 화면 ELDER_FAMILY_001 의 josa 와 같은 식 */
function josa(word: string, withFinal: string, without: string) {
  const code = word.charCodeAt(word.length - 1)
  return code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 !== 0 ? withFinal : without
}
/** 지금 보는 분의 가족방 — 틀과 같은 규칙(적어 둔 방, 없으면 첫 방) */
function pickedRoom(list: RoomOut[]) {
  let id: number | null = null
  try {
    id = Number(localStorage.getItem(ROOM_KEY)) || null
  } catch {
    /* 저장을 막아 둔 폰 — 첫 가족방 */
  }
  return list.find((r) => r.room_id === id) ?? list[0] ?? null
}

/** 폰 사진 창을 여는 칸. HEIC 는 서버가 받지 않는다(D17) — 이 accept 면 아이폰 Safari 가 보관함 사진을 JPEG 로 바꿔 준다 */
// camera = 바로 카메라로 찍기 (11/23 사용자)
function FileInput(props: { onPick: (e: ChangeEvent<HTMLInputElement>) => void; disabled: boolean; camera?: boolean }) {
  const { onPick, disabled, camera } = props
  return (
    <input
      className="st-file"
      type="file"
      capture={camera ? 'environment' : undefined}
      accept="image/jpeg,image/png"
      onChange={onPick}
      disabled={disabled}
    />
  )
}

export default function FDIARY_001() {
  // 하위 화면 틀이라 useFamily() 가 없다 → 로그인한 사람·가족방을 직접 읽는다
  const me = useFetch<UserOut>('/api/auth/me')
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  if (me.error?.status === 401 || rooms.error?.status === 401) return <Navigate to="/login" replace />
  const failed = me.error ?? rooms.error
  if (failed) {
    return (
      <main className="st">
        <div className="st-body">
          <p className="fam-error">{failed.message}</p>
          <button type="button" className="fam-btn fam-btn--tonal" onClick={() => (me.reload(), rooms.reload())}>
            다시 시도
          </button>
        </div>
      </main>
    )
  }
  if (!me.data || !rooms.data) return <main className="st" aria-busy="true" />
  const room = pickedRoom(rooms.data)
  if (!room) {
    return (
      <main className="st">
        <div className="st-body">
          <p className="st-hint">
            먼저 가족방을 만들어 주세요 ·{' '}
            <Link className="st-link" to="/groups/new">
              가족방 만들기
            </Link>
          </p>
        </div>
      </main>
    )
  }
  // 계정이 바뀌면 처음부터(key) — 앞 사람이 쓰던 것이 남지 않게
  return <Write key={me.data.user_id} me={me.data} room={room} />
}

function Write({ me, room }: { me: UserOut; room: RoomOut }) {
  const nav = useNavigate()
  // 열 때 한 번 — 다른 사람이 쓰던 것이면 비우고, 페이지를 새로 연 뒤면 같은 사람이 쓰던 글을 되살린다
  const [start] = useState(() => (restoreFamilyDiaryText(me.user_id), { ...d }))
  const [photo, setPhoto] = useState<File | null>(start.photo)
  const [text, setText] = useState(start.text)
  const [before, setBefore] = useState(start.before)
  const [question, setQuestion] = useState(start.question)
  const [answer, setAnswer] = useState(start.answer)
  const [mood, setMood] = useState<Mood>(start.mood)
  // 일기 동무 판: 닫힘 · 열림(질문·답) · 다듬음
  const [buddy, setBuddy] = useState<'off' | 'open' | 'done'>(start.before ? 'done' : 'off')
  const [busy, setBusy] = useState<'ask' | 'draft' | 'post' | null>(null)
  const [preparing, setPreparing] = useState(false) // 큰 사진 줄이는 중 — 그동안 고르기·보내기 막기
  const [error, setError] = useState('')
  const [nick, setNick] = useState<string | null>(null) // 이 방에서 내 호칭 — 읽어 드리는 첫 문장이 어르신 화면과 같게
  const sending = useRef(false)
  // 화면을 떠나면(← 등) 기다리던 질문·초안·보내기를 멈춘다. 안 멈추면 늦게 온 답이 떠난 사람을 홈으로 끌고 간다
  const leaving = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    leaving.current = controller
    return () => controller.abort()
  }, [])

  useEffect(() => {
    let alive = true
    api<MemberOut[]>(`/api/rooms/${room.room_id}/members`)
      .then((list) => alive && setNick(list.find((m) => m.user_id === me.user_id)?.nickname ?? null))
      .catch(() => {}) // 못 읽으면 이름만으로 보여 준다
    return () => {
      alive = false
    }
  }, [room.room_id, me.user_id])

  const hon = room.elder_honorific
  const elder = `${room.elder_name} ${hon}`
  const sender = [nick, me.name].filter(Boolean).join(' ') || '가족'

  function editText(v: string) {
    setText(v)
    d.text = v
    saveFamilyDiaryText()
  }

  function choosePhoto(f: File | null) {
    setPhoto(f)
    d.photo = f
  }

  async function onPick(e: ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0]
    e.target.value = '' // 같은 사진을 다시 골라도 onChange 가 오게
    if (!picked) return // 고르다 취소 — 앞 사진 그대로
    if (!TYPES.includes(picked.type)) return setError('jpg·png 사진만 고를 수 있어요')
    setError('')
    setPreparing(true)
    let file: File
    try {
      file = await fitPhoto(picked) // 상한 넘는 사진만 줄인다(UPLOAD_001 과 같은 규칙)
    } finally {
      setPreparing(false)
    }
    if (file.size > MAX_BYTES) return setError(`${MAX_BYTES / 1024 / 1024}MB보다 작은 사진을 골라 주세요`)
    choosePhoto(file)
  }

  /** 실패 처리 — 떠나서 멈춘 요청은 조용히 끝, 쓰는 사이 로그인이 풀렸으면(401) 로그인 화면으로(쓴 글은 메모리에 남음) */
  function fail(e: unknown, signal?: AbortSignal) {
    if (signal?.aborted) return
    if (e instanceof ApiError && e.status === 401) return nav('/login', { replace: true })
    setError(msgOf(e))
    sending.current = false
    setBusy(null)
  }

  /** [일기 동무에게 다듬어 달라기] — 질문은 한 편에 한 번만 받는다(글을 고쳐도 다시 받지 않음) */
  async function openBuddy() {
    setBuddy('open')
    if (question || busy) return
    const signal = leaving.current?.signal
    setBusy('ask')
    setError('')
    try {
      const out = await api<FamilyAskOut>(`/api/rooms/${room.room_id}/family-diary/ask`, { body: { text }, signal })
      if (signal?.aborted) return
      setQuestion(out.question)
      d.question = out.question
      saveFamilyDiaryText()
      setBusy(null)
    } catch (e) {
      fail(e, signal)
    }
  }

  async function makeDraft() {
    if (busy || !text.trim()) return
    const signal = leaving.current?.signal
    setBusy('draft')
    setError('')
    try {
      const out = await api<FamilyDraftOut>(`/api/rooms/${room.room_id}/family-diary/draft`, {
        body: { text, question, answer },
        signal,
      })
      if (signal?.aborted) return
      setBefore(text)
      d.before = text
      editText(out.body)
      setBuddy('done')
      setBusy(null)
    } catch (e) {
      fail(e, signal)
    }
  }

  function undoDraft() {
    editText(before)
    setBefore('')
    d.before = ''
    setBuddy('off')
  }

  async function post() {
    // busy(state)는 다시 그린 뒤에야 바뀌어 아주 빠른 두 번 누르기를 못 막는다 → ref 로 한 번 더 (서버도 같은 번호면 1개만)
    const body = text.trim()
    if (busy || sending.current || !body) return
    sending.current = true
    const signal = leaving.current?.signal
    setBusy('post')
    setError('')
    // 앞서 보냈는데 답을 못 받은 것과 똑같으면 같은 번호로 — 서버가 한 번만 저장한다(D17). 사진만 같으면 사진 번호만 그대로
    const p = d.sent
    const s =
      p && p.body === body && p.mood === mood && p.photo === photo
        ? p
        : { postId: crypto.randomUUID(), batchId: p && p.photo === photo ? p.batchId : crypto.randomUUID(), body, mood, photo }
    d.sent = s
    try {
      let photoId: number | null = null
      if (s.photo) {
        const form = new FormData()
        form.append('files', s.photo)
        form.append('upload_batch_id', s.batchId)
        form.append('source', 'FAMILY_DIARY') // 오늘의 한 장 후보에 섞이지 않게 (#142)
        const up = await api<PhotoBatchOut>(`/api/rooms/${room.room_id}/photos`, { form, signal })
        photoId = up.photos[0].photo_id
      }
      await api<DiaryOut>(`/api/rooms/${room.room_id}/diaries`, {
        body: { request_id: s.postId, body: s.body, mood: s.mood, photo_id: photoId, illustration_type: photoId ? 'PHOTO' : 'NONE' },
        signal,
      })
      clearFamilyDiaryDraft()
      nav('/', { replace: true }) // 가족 홈 맨 위에 방금 쓴 소식. replace — 뒤로 가기로 돌아와 또 보내지 않게
    } catch (e) {
      fail(e, signal)
    }
  }

  const locked = !!busy || preparing

  return (
    <main className="st">
      <div className="st-body">
        <div className="st-head">
          <h1>내 일기 보내기</h1>
        </div>

        {photo ? (
          <div className="fd-pic">
            <div className="fd-photo">
              <Thumb file={photo} alt="고른 사진" />
            </div>
            <div className="fd-row">
              <label className="fam-btn fam-btn--tonal fam-btn--sm st-again">
                <FileInput onPick={onPick} disabled={locked} />
                <FamIcon name="imagePlus" />
                다른 사진
              </label>
              <label className="fam-btn fam-btn--tonal fam-btn--sm st-again">
                <FileInput onPick={onPick} disabled={locked} camera />
                <FamIcon name="camera" />
                다시 찍기
              </label>
              <button type="button" className="fam-text-btn" disabled={locked} onClick={() => choosePhoto(null)}>
                사진 빼기
              </button>
            </div>
          </div>
        ) : (
          <div className="st-pickers st-pickers--slim">
            <label className="st-picker st-picker--slim">
              <FileInput onPick={onPick} disabled={locked} />
              <FamIcon name="imagePlus" />
              사진 고르기
            </label>
            <label className="st-picker st-picker--slim st-picker--cam">
              <FileInput onPick={onPick} disabled={locked} camera />
              <FamIcon name="camera" />
              사진 찍기
            </label>
            <small className="st-pickers-note">오늘 사진 1장 · 안 넣어도 돼요</small>
          </div>
        )}
        {preparing && (
          <p className="st-hint" role="status">
            사진을 준비하는 중…
          </p>
        )}

        {/* 글자 수는 이름(label) 밖에 둔다 — 안에 두면 칠 때마다 칸 이름이 바뀌어 화면 읽기 기능이 다시 읽는다 */}
        <label className="st-label" htmlFor="fd-text">
          오늘 어떤 하루였어요?
        </label>
        <textarea
          id="fd-text"
          className="st-input"
          rows={3}
          maxLength={MAX}
          value={text}
          disabled={busy === 'draft' || busy === 'post'}
          placeholder="예) 점심에 엄마가 좋아하는 칼국수 먹었어요"
          onChange={(e) => editText(e.target.value)}
        />
        <span className="st-count">
          {text.length}/{MAX}
        </span>

        {buddy === 'open' ? (
          <section className="fd-buddy" aria-label="일기 동무">
            <div className="fd-row">
              <span className="fd-av" aria-hidden="true">
                <Sim face="ask" size={32} />
              </span>
              <b className="fd-grow">일기 동무</b>
              <button type="button" className="fam-text-btn" onClick={() => setBuddy('off')}>
                닫기
              </button>
            </div>
            {/* 늘 그려 두는 aria-live 칸 — 안의 글이 바뀌어야 화면 읽기 기능이 새 질문을 읽어 준다 */}
            <p aria-live="polite">{busy === 'ask' ? '질문을 생각하는 중…' : question}</p>
            {question && (
              <>
                <input
                  className="st-input"
                  type="text"
                  maxLength={MAX}
                  value={answer}
                  placeholder="답 (안 적어도 돼요)"
                  aria-label="일기 동무에게 답하기"
                  autoComplete="off"
                  disabled={!!busy}
                  onChange={(e) => (setAnswer(e.target.value), (d.answer = e.target.value), saveFamilyDiaryText())}
                />
                <button type="button" className="fam-btn fam-btn--primary" disabled={!!busy || !text.trim()} onClick={makeDraft}>
                  {busy === 'draft' ? '일기 동무가 다듬는 중…' : '이 답까지 넣어 다듬기'}
                </button>
              </>
            )}
          </section>
        ) : buddy === 'done' ? (
          <p className="st-note">
            <FamIcon name="check" />
            <span>
              일기 동무가 다듬었어요. 고쳐도 돼요 ·{' '}
              <button type="button" className="st-link fd-inline" onClick={undoDraft}>
                처음 글로
              </button>
            </span>
          </p>
        ) : (
          // 질문은 쓴 글을 보고 만든다 — 글이 있어야 누를 수 있다
          <button type="button" className="fam-text-btn fd-buddy-on" disabled={!text.trim() || !!busy} onClick={openBuddy}>
            <FamIcon name="pencil" />
            일기 동무에게 다듬어 달라기 <small>(선택)</small>
          </button>
        )}

        <p className="st-label" id="fd-mood">
          오늘 기분
        </p>
        <div className="st-chips" role="group" aria-labelledby="fd-mood">
          {MOODS.map((m) => (
            <button
              key={m}
              type="button"
              className="st-chip"
              aria-pressed={mood === m}
              onClick={() => (setMood(m), (d.mood = m))}
            >
              <MoodIcon mood={m} />
              {MOOD_LABEL[m]}
            </button>
          ))}
        </div>

        <p className="st-note">
          <FamIcon name="sparkle" />
          <span>
            {hon}께는 “{sender}
            {josa(sender, '이', '가')} 소식을 보냈어요” 다음에 이 글을 읽어 드려요
          </span>
        </p>
        {error && (
          <p className="fam-error" role="alert">
            {error}
          </p>
        )}
      </div>

      <div className="st-cta">
        <button type="button" className="fam-btn fam-btn--primary" disabled={!text.trim() || locked} onClick={post}>
          {busy === 'post' ? '보내는 중…' : `${elder}께 보내기`}
        </button>
      </div>
    </main>
  )
}
