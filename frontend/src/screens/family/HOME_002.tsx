/**
 * HOME_002 — 일기 상세 (11/23 시안 f-detail). 하위 화면 틀의 ←를 쓰고, 열람 기록은 이 화면을 열 때만 남긴다(D36).
 * 한마디는 인스타 댓글창처럼 — 목록(사람·글·시각) 아래 입력 줄 하나, 추천 문구 없음(11/25 사용자, D91 의 추천 칩을 뺌).
 * 가족 일기에 어르신이 말로 답하신 한 줄(reactions 의 by ELDER·kind REPLY)을 보여 준다. 녹음이 있으면 [듣기]를 눌러야 튼다(11/25).
 * 한마디는 가족 일기에도 남긴다(D98, 쓴 사람은 빼고) — 가족끼리만 보이고 어르신께는 읽어 드리지 않는다.
 * 어르신 일기에는 [🎤 목소리로 답장] (D99, 11/24) — 녹음해 들어 보고 보내면 어르신 가족 소식에서 그 목소리를 틀어 드린다
 * (30초까지, 받아 적은 자막이 같이 붙는다). 녹음한 뒤 [보내기]·[다시 녹음]·[취소](11/25).
 * 한마디·목소리 답장은 한 사람이 여러 개 남긴다(11/25 사용자 — 인스타 댓글처럼). 내 것마다 [지우기].
 * 가족 일기의 [🎤 말로 쓰기]는 그대로 말을 글자로 바꿔 칸에 넣기만 한다(D98, 녹음은 저장하지 않음).
 */
import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { MOOD_LABEL, type DiaryOut, type Reaction, type RoomOut, type SttOut, type UserOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { Avatar } from '../../components/FamilyFrame'
import MoodIcon from '../../components/MoodIcon'
import Sim from '../../components/Sim'
import { useFetch } from '../../hooks/useFetch'
import VoicePlay from '../../components/VoicePlay'
import { micBlockedTip, startRecording, type Recorder } from '../../lib/audio'
import './HOME_002.css'

const REACTS = [
  ['HEART', '❤️', '하트'],
  ['SMILE', '😊', '웃음'],
  ['CLAP', '👏', '박수'],
] as const
// 댓글(한마디, 11/19): 한 사람이 여러 개(11/25). 추천 문구는 뺐다(11/25 사용자 — 인스타 댓글창처럼). 글자 수는 서버 config.REPLY_MAX 와 같은 값
const REPLY_MAX = 40
const VOICE_MS = 20_000 // 말로 한마디 녹음 상한 — 40자면 몇 초
const VOICE_REPLY_SEC = 30 // 목소리 답장 상한 — 서버 config.VOICE_REPLY_MAX_SEC 와 같은 값 (D99)

const postedAt = (iso: string) =>
  new Date(iso).toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: 'long', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
const iga = (word: string) => ((word.charCodeAt(word.length - 1) - 0xac00) % 28 ? '이' : '가')
/** 댓글 시각 — '방금'·'5분'·'3시간'·'2일', 일주일 넘으면 '11월 3일' (인스타 댓글처럼) */
function ago(iso: string) {
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000)
  if (min < 1) return '방금'
  if (min < 60) return `${min}분`
  if (min < 1440) return `${Math.floor(min / 60)}시간`
  if (min < 10080) return `${Math.floor(min / 1440)}일`
  return new Date(iso).toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric' })
}

function DiaryDetail({ diaryId }: { diaryId: string }) {
  const nav = useNavigate()
  const location = useLocation()
  const [diaryOrder] = useState<number[]>(() => {
    // 알림·직접 주소로 연 일기는 예전 홈 목록이 남아 있어도 넘기지 않는다.
    if (location.state?.familyDiaryOrder !== true) return []
    try {
      const order: unknown = JSON.parse(sessionStorage.getItem('haru.fam.diary-order') ?? 'null')
      return Array.isArray(order) && order.every((id) => Number.isSafeInteger(id) && id > 0) ? order : []
    } catch {
      return []
    }
  })
  const diary = useFetch<DiaryOut>(`/api/diaries/${encodeURIComponent(diaryId)}`)
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  const me = useFetch<UserOut>('/api/auth/me')
  const readRequest = useRef<Promise<unknown> | null>(null)
  const photoZoom = useRef<HTMLDialogElement>(null)
  const [readError, setReadError] = useState(false)
  const [edit, setEdit] = useState<{ base: DiaryOut; data: DiaryOut } | null>(null)
  const [busy, setBusy] = useState(false)
  const [reactionError, setReactionError] = useState(false)
  const [draft, setDraft] = useState('')
  const [replySent, setReplySent] = useState(false)
  const [replyError, setReplyError] = useState<string>()
  const [fixing, setFixing] = useState<Reaction>() // 고치는 중인 내 한마디 (11/25 멘토링 '댓글 수정도')
  const replyInput = useRef<HTMLInputElement>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string>()
  const deleteRequest = useRef(false)
  const recorder = useRef<Recorder | undefined>(undefined)
  const live = useRef(true)
  const [voice, setVoice] = useState<'start' | 'rec' | 'stt'>()
  const [voiceError, setVoiceError] = useState<string>()
  // 목소리 답장 (D99): 녹음 중 초 · 녹음을 마친 소리(들어 보기·보내기) · 초 세기와 30초 저절로 멈춤
  const [recSec, setRecSec] = useState(0)
  const [take, setTake] = useState<{ blob: Blob; url: string; sec: number }>()
  const recTimers = useRef<number[]>([])
  const deleteSheet = useRef<HTMLDialogElement>(null)
  const cancelDelete = useRef<HTMLButtonElement>(null)
  const d = edit?.base === diary.data ? edit?.data : diary.data
  const room = rooms.data?.find((r) => r.room_id === d?.room_id)
  // 내 이모지 칸 — 내 한마디(REPLY) 칸은 따로라 여기서 뺀다
  const mine = d?.reactions.find((r) => r.by === 'FAMILY' && r.kind !== 'REPLY' && r.user_id === me.data?.user_id)?.kind
  const replies = d?.reactions.filter((r) => r.by === 'FAMILY' && r.kind === 'REPLY') ?? []
  const elderReply = d?.reactions.find((r) => r.by === 'ELDER' && r.kind === 'REPLY')
  const isMine = (r: Reaction) => r.user_id === me.data?.user_id
  const myLast = replies.findLast(isMine) // 내 마지막 한마디 — 두 번 누름 막기·보냈다는 안내

  // 화면을 떠나면 마이크를 끈다
  useEffect(() => {
    const rec = recorder
    const timers = recTimers
    live.current = true
    return () => {
      live.current = false
      void rec.current?.stop()
      timers.current.forEach((t) => clearTimeout(t))
    }
  }, [])
  // 들어 보기용 주소는 새로 녹음하거나 떠날 때 버린다
  useEffect(() => () => take && URL.revokeObjectURL(take.url), [take])

  useEffect(() => {
    if (deleteOpen) {
      deleteSheet.current?.showModal()
      cancelDelete.current?.focus()
    } else {
      deleteSheet.current?.close()
    }
  }, [deleteOpen])

  async function removeDiary() {
    if (!d?.is_mine || d.author_type !== 'FAMILY' || deleteRequest.current) return
    deleteRequest.current = true
    setDeleting(true)
    setDeleteError(undefined)
    try {
      await api<void>(`/api/diaries/${d.diary_id}`, { method: 'DELETE' })
      nav('/', { replace: true })
    } catch (e) {
      setDeleteError(e instanceof ApiError ? e.message : '일기를 지우지 못했어요. 다시 해 주세요.')
    } finally {
      deleteRequest.current = false
      setDeleting(false)
    }
  }

  // 홈과 같은 API(D54). 응답 일기로 갱신하고 실패하면 기존 선택을 유지한다.
  async function react(kind: Reaction['kind']) {
    if (!d || !diary.data || !me.data || d.author_type !== 'ELDER' || busy) return
    const base = diary.data
    setBusy(true)
    setReactionError(false)
    try {
      const data = await api<DiaryOut>(`/api/diaries/${d.diary_id}/reaction`, { body: { kind, on: mine !== kind } })
      setEdit({ base, data })
    } catch {
      setReactionError(true)
    } finally {
      setBusy(false)
    }
  }

  // 말로 한마디 (D98): 한 번 누르면 녹음, 다시 누르면 /api/stt 로 글자를 받아 칸에 넣는다. 보내기는 사람이 한다
  async function toggleVoice() {
    if (voice === 'start' || voice === 'stt') return
    const r = recorder.current
    if (!r) {
      setVoice('start')
      setVoiceError(undefined)
      try {
        const started = await startRecording(VOICE_MS)
        if (!live.current) return void started.stop()
        recorder.current = started
        setVoice('rec')
      } catch {
        setVoice(undefined)
        setVoiceError('마이크를 쓸 수 없어요. 마이크 허락을 확인해 주세요.')
      }
      return
    }
    recorder.current = undefined
    setVoice('stt')
    try {
      const form = new FormData()
      form.append('audio', await r.stop(), 'speech.webm')
      const { transcript } = await api<SttOut>('/api/stt', { form })
      if (live.current) setDraft(transcript.trim().slice(0, REPLY_MAX))
    } catch (e) {
      if (live.current) setVoiceError(e instanceof ApiError ? e.message : '잘 못 들었어요. 다시 말해 주세요.')
    } finally {
      if (live.current) setVoice(undefined)
    }
  }

  // 목소리 답장 (D99): [목소리로 답장] → 녹음(30초면 저절로 멈춤) → [다 녹음했어요] → 들어 보기 · [보내기] · [다시 녹음]
  const recCount = useRef(0) // 녹음한 초 — 1초마다 센다
  async function startVoiceReply() {
    if (voice || busy) return
    setVoice('start')
    setVoiceError(undefined)
    setReplyError(undefined)
    setReplySent(false)
    setTake(undefined)
    try {
      const started = await startRecording(VOICE_REPLY_SEC * 1000)
      if (!live.current) return void started.stop()
      recorder.current = started
      recCount.current = 0
      setRecSec(0)
      setVoice('rec')
      recTimers.current = [
        window.setInterval(() => setRecSec(++recCount.current), 1000),
        window.setTimeout(() => void stopVoiceReply(), VOICE_REPLY_SEC * 1000),
      ]
    } catch (e) {
      setVoice(undefined)
      setVoiceError(`마이크를 쓸 수 없어요.${micBlockedTip(e) || ' 마이크 허락을 확인해 주세요.'}`)
    }
  }

  async function stopVoiceReply() {
    const r = recorder.current
    recorder.current = undefined
    recTimers.current.forEach((t) => clearTimeout(t))
    recTimers.current = []
    if (!r) return
    const sec = Math.min(VOICE_REPLY_SEC, Math.max(1, recCount.current))
    const blob = await r.stop()
    if (!live.current) return
    setVoice(undefined)
    setTake({ blob, url: URL.createObjectURL(blob), sec })
  }

  async function sendVoiceReply() {
    if (!d || !diary.data || !take || busy) return
    const base = diary.data
    setBusy(true)
    setReplyError(undefined)
    try {
      const form = new FormData()
      form.append('audio', take.blob, take.blob.type.includes('mp4') ? 'voice.mp4' : 'voice.webm') // 아이폰 mp4·갤럭시 webm
      const data = await api<DiaryOut>(`/api/diaries/${d.diary_id}/voice-reply`, { form })
      setEdit({ base, data })
      setTake(undefined)
      setReplySent(true)
    } catch (e) {
      setReplyError(e instanceof ApiError ? e.message : '목소리를 보내지 못했어요. 다시 해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  // 한마디 남기기 (11/19). 보낼 때마다 새 칸이 붙고(11/25) 어르신 일기면 어르신께 읽어 드린다
  async function sendReply(text: string) {
    const clean = text.trim()
    if (!d || !diary.data || d.is_mine || busy || !clean) return
    if (!fixing && clean === myLast?.text && !myLast.audio_url) {
      setDraft('') // 바로 앞에 남긴 글 그대로(두 번 누름) — 서버도 새 칸을 붙이지 않으니 보내지 않는다
      return
    }
    const base = diary.data
    setBusy(true)
    setReplySent(false)
    setReplyError(undefined)
    try {
      const data = fixing // 고치기는 그 칸(at)의 글만 바꾼다 — 자리·시각은 그대로
        ? await api<DiaryOut>(`/api/diaries/${d.diary_id}/reply`, { method: 'PATCH', body: { at: fixing.at, text: clean } })
        : await api<DiaryOut>(`/api/diaries/${d.diary_id}/reply`, { body: { text: clean } })
      setEdit({ base, data })
      setDraft('')
      setReplySent(!fixing)
      setFixing(undefined)
    } catch (e) {
      const what = fixing ? '고치지' : '보내지'
      setReplyError(e instanceof ApiError ? e.message : `한마디를 ${what} 못했어요. 다시 해 주세요.`)
    } finally {
      setBusy(false)
    }
  }

  function startFixing(cell: Reaction) {
    setFixing(cell)
    setDraft(cell.text ?? '')
    setReplySent(false)
    setReplyError(undefined)
    replyInput.current?.focus()
  }

  function stopFixing() {
    setFixing(undefined)
    setDraft('')
  }

  async function removeReply(cell: Reaction) {
    if (!d || !diary.data || busy) return
    const base = diary.data
    setBusy(true)
    setReplySent(false)
    setReplyError(undefined)
    try {
      await api<void>(`/api/diaries/${d.diary_id}/reply?at=${encodeURIComponent(cell.at)}`, { method: 'DELETE' })
      setEdit({ base, data: { ...d, reactions: d.reactions.filter((r) => r !== cell) } })
      if (fixing?.at === cell.at) stopFixing() // 고치던 한마디를 지웠다
    } catch (e) {
      setReplyError(e instanceof ApiError ? e.message : '한마디를 지우지 못했어요. 다시 해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!d || !room) return
    // StrictMode의 effect 재실행·다시 불러오기에도 같은 화면에서는 POST를 한 번만 보낸다.
    readRequest.current ??= api(`/api/diaries/${d.diary_id}/read`, { method: 'POST' })
    const view = new AbortController()
    readRequest.current.catch(() => {
      if (!view.signal.aborted) setReadError(true)
    })
    return () => view.abort()
  }, [d, room])

  if (diary.error?.status === 401 || rooms.error?.status === 401 || me.error?.status === 401) return <Navigate to="/login" replace />
  if (diary.error?.status === 404) {
    return (
      <main className="fam-stack diary-detail">
        <section className="fam-card diary-detail-state">
          <Sim face="ask" size={96} />
          <h1>일기를 찾을 수 없어요</h1>
          <Link className="fam-btn fam-btn--primary" to="/">가족 홈으로</Link>
        </section>
      </main>
    )
  }
  const failed = diary.error ?? rooms.error ?? me.error
  if (failed) {
    return (
      <main className="fam-stack diary-detail">
        <section className="fam-card diary-detail-state">
          <p role="alert">{failed.message}</p>
          <button type="button" className="fam-btn fam-btn--tonal" onClick={() => { diary.reload(); rooms.reload(); me.reload() }}>
            다시 시도
          </button>
          <Link className="fam-text-btn" to="/">가족 홈으로</Link>
        </section>
      </main>
    )
  }
  if (!d || !rooms.data || !me.data) {
    return (
      <main className="fam-stack diary-detail" aria-busy="true">
        <p className="diary-detail-note" role="status">일기를 불러오고 있어요</p>
      </main>
    )
  }
  if (!room) {
    return (
      <main className="fam-stack diary-detail">
        <section className="fam-card diary-detail-state">
          <p>가족방을 찾을 수 없어요</p>
          <Link className="fam-btn fam-btn--primary" to="/">가족 홈으로</Link>
        </section>
      </main>
    )
  }

  const elder = d.author_type === 'ELDER'
  const name = elder ? `${room.elder_name} ${room.elder_honorific}` : (d.author_name ?? '가족')
  const hasPicture = d.illustration_type !== 'NONE' && !!d.illustration_url
  const liked = d.reactions.some((r) => r.by === 'ELDER' && r.kind === 'LIKE')
  const index = diaryOrder.indexOf(d.diary_id)
  const recent = index > 0 ? diaryOrder[index - 1] : undefined
  const past = index >= 0 ? diaryOrder[index + 1] : undefined

  function openDiary(id: number) {
    nav(`/diaries/${id}`, { replace: true, state: { familyDiaryOrder: true } })
  }

  return (
    <main className="fam-stack diary-detail">
      <h1 className="diary-detail-title">일기 상세</h1>
      <article className="diary-detail-card">
        <header className="diary-detail-head">
          <Avatar name={elder ? room.elder_name : name} />
          <div className="diary-detail-who">
            <b>{name}</b>
            <small>
              <time dateTime={d.posted_at}>{postedAt(d.posted_at)}</time>
              {!elder && d.author_nickname ? ` · ${d.author_nickname}` : ''} · {elder ? '일기' : '오늘 소식'}
            </small>
          </div>
        </header>
        {hasPicture ? (
          <button
            type="button"
            className="diary-detail-photo"
            aria-label={d.illustration_type === 'AI_DRAWING' ? '그림일기 그림 크게 보기' : '일기 사진 크게 보기'}
            onClick={() => photoZoom.current?.showModal()}
          >
            <img src={d.illustration_url!} alt={d.illustration_type === 'AI_DRAWING' ? '그림일기 그림' : '일기 사진'} />
            {d.illustration_type === 'AI_DRAWING' && (
              <span className="diary-detail-tag"><FamIcon name="sparkle" />그림일기</span>
            )}
          </button>
        ) : (
          <div className="diary-detail-mood-pic" role="img" aria-label={`일기 기분 · ${MOOD_LABEL[d.mood]}`}>
            <MoodIcon mood={d.mood} />
          </div>
        )}
        <p className="diary-detail-text">{d.body}</p>
        <p className="diary-detail-mood"><MoodIcon mood={d.mood} />일기 기분 · {MOOD_LABEL[d.mood]}</p>
        {elder && (
          <div className="diary-detail-reactions" role="group" aria-label="가족 이모지" aria-busy={busy}>
            {REACTS.map(([kind, emoji, label]) => {
              const n = d.reactions.filter((r) => r.by === 'FAMILY' && r.kind === kind).length
              const on = mine === kind
              return (
                <button
                  type="button"
                  key={kind}
                  className="diary-detail-react"
                  onClick={() => react(kind)}
                  disabled={busy}
                  aria-pressed={on}
                  aria-label={n ? `${label} ${n} 개` : label}
                >
                  <span aria-hidden="true">{emoji}</span>
                  {n > 0 && <span>{n}</span>}
                </button>
              )
            })}
          </div>
        )}
        {elder && reactionError && (
          <p className="diary-detail-note" role="alert">이모지를 보내지 못했어요. 연결을 확인하고 다시 눌러 주세요.</p>
        )}
        {(!d.is_mine || replies.length > 0) && (
          <section className="fam-card diary-detail-reply" aria-labelledby="diary-reply-title" aria-busy={busy}>
            <h2 id="diary-reply-title">
              댓글{replies.length > 0 && <small> {replies.length}</small>}
            </h2>
            {replies.length > 0 && (
              <ul className="diary-detail-replies">
                {replies.map((r) => (
                  <li key={`${r.user_id}-${r.at}`}>
                    <Avatar name={r.name ?? '가족'} small />
                    <span>
                      <span className="cm-text">
                        <b>{isMine(r) ? '나' : (r.name ?? '가족')}</b>
                        {r.text && !r.audio_url && ` ${r.text}`}
                      </span>
                      {r.audio_url && <VoicePlay url={r.audio_url} sec={r.audio_sec} />}
                      {r.audio_url && r.text && <span className="cm-sub">{r.text}</span>}
                      <small>
                        {ago(r.at)}
                        {/* 글 한마디만 고친다 — 목소리 답장은 지우고 다시 */}
                        {isMine(r) && !r.audio_url && (
                          <button type="button" className="cm-del" disabled={busy} onClick={() => startFixing(r)} aria-pressed={fixing?.at === r.at}>
                            고치기
                          </button>
                        )}
                        {isMine(r) && (
                          <button type="button" className="cm-del" disabled={busy} onClick={() => void removeReply(r)}>지우기</button>
                        )}
                      </small>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {!d.is_mine && (
              <>
                {/* 어르신 일기 — 진짜 목소리 답장 (D99). 녹음을 마치면 들어 보고 보낸다 */}
                {elder && take && (
                  <div className="diary-detail-take" role="group" aria-label="녹음한 목소리">
                    <VoicePlay url={take.url} sec={take.sec} label="들어 보기" />
                    <button type="button" className="fam-btn fam-btn--primary fam-btn--sm" disabled={busy} onClick={() => void sendVoiceReply()}>
                      {busy ? '보내는 중…' : '보내기'}
                    </button>
                    <button type="button" className="fam-btn fam-btn--sm" disabled={busy} onClick={() => void startVoiceReply()}>
                      다시 녹음
                    </button>
                    {/* 11/25 피드백: 녹음한 뒤 안 보내고 그만둘 곳이 없었다 */}
                    <button type="button" className="fam-btn fam-btn--sm" disabled={busy} onClick={() => setTake(undefined)}>
                      취소
                    </button>
                  </div>
                )}
                {/* 댓글 입력 줄 (11/25 사용자: 추천 문구 없이 인스타 댓글창처럼). 🎤 = 어르신 일기는 목소리 답장, 가족 일기는 말로 쓰기 */}
                <form className="cm-bar" onSubmit={(e) => { e.preventDefault(); void sendReply(draft) }}>
                  <Avatar name={me.data?.name ?? '나'} small />
                  <input
                    ref={replyInput}
                    className="cm-input"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    maxLength={REPLY_MAX}
                    placeholder="댓글 달기…"
                    aria-label={`댓글 쓰기, ${REPLY_MAX}자까지`}
                    enterKeyHint="send"
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    className="cm-mic"
                    onClick={() => void (elder ? (voice === 'rec' ? stopVoiceReply() : startVoiceReply()) : toggleVoice())}
                    disabled={busy || voice === 'start' || voice === 'stt' || !!fixing}
                    aria-pressed={voice === 'rec'}
                    aria-label={voice === 'rec' ? (elder ? '다 녹음했어요' : '다 말했어요') : elder ? '목소리로 답장' : '말로 쓰기'}
                  >
                    {voice === 'rec' ? <span className="cm-stop">■ {elder ? `${recSec}초` : ''}</span> : <FamIcon name="mic" />}
                  </button>
                  <button type="submit" className="cm-post" disabled={busy || !!voice || !draft.trim()}>{fixing ? '고치기' : '보내기'}</button>
                </form>
                {voice === 'rec' && (
                  <p className="cm-hint" role="status">
                    {elder ? `녹음하고 있어요. ${room.elder_honorific}께 이 목소리 그대로 들려 드려요 (${VOICE_REPLY_SEC}초까지).` : '듣고 있어요. 다 말하면 한 번 더 눌러 주세요.'}
                  </p>
                )}
                {voiceError && <p className="diary-detail-reply-note" role="alert">{voiceError}</p>}
                {replyError && <p className="diary-detail-reply-note" role="alert">{replyError}</p>}
                {fixing && (
                  <p className="cm-hint" role="status">
                    한마디를 고치고 있어요{elder ? ` · 고치면 ${room.elder_honorific}께 다시 읽어 드려요` : ''}{' '}
                    <button type="button" className="cm-del" onClick={stopFixing}>취소</button>
                  </p>
                )}
                {voice !== 'rec' && !fixing && (
                  <p className="cm-hint" role={replySent ? 'status' : undefined}>
                    {replySent
                      ? elder
                        ? `보냈어요 · ${name}께 ${myLast?.audio_url ? '목소리를 들려' : '읽어'} 드릴게요.`
                        : '보냈어요 · 가족 모두에게 보여요.'
                      : elder
                        ? `${room.elder_honorific}께 읽어 드려요 · 🎤 누르면 목소리로`
                        : '가족 모두에게 보여요'}
                  </p>
                )}
                {replySent && <Link className="fam-btn fam-btn--tonal fam-btn--sm" to="/">홈으로</Link>}
              </>
            )}
          </section>
        )}
        {!elder && elderReply && (
          <section className="diary-detail-elder-reply" aria-label="어르신 답장">
            <p className="fam-note">
              <FamIcon name="speaker" />
              <span>
                {room.elder_honorific}
                {iga(room.elder_honorific)} 말로 답하셨어요
              </span>
            </p>
            <p className="diary-detail-quote">“{elderReply.text}”</p>
            {/* 어르신 목소리 (11/25 사용자) — 저절로 틀지 않고 눌러야 나온다 */}
            {elderReply.audio_url && <VoicePlay url={elderReply.audio_url} sec={elderReply.audio_sec} label="목소리 듣기" />}
          </section>
        )}
        {!elder && (
          <p className={`diary-detail-heard${d.read_by_elder ? '' : ' not'}`}>
            {d.read_by_elder ? (
              <>
                <FamIcon name="check" />
                {room.elder_honorific}{iga(room.elder_honorific)} 들으셨어요{liked ? ' · 좋아요를 보내셨어요' : ''}
              </>
            ) : '아직 안 들으셨어요'}
          </p>
        )}
      </article>
      {(recent !== undefined || past !== undefined) && (
        <nav className="diary-detail-nav" aria-label="일기 넘기기">
          <button type="button" className="fam-btn fam-btn--sm" disabled={past === undefined} onClick={() => past !== undefined && openDiary(past)}>
            ‹ 지난 일기
          </button>
          <button type="button" className="fam-btn fam-btn--sm" disabled={recent === undefined} onClick={() => recent !== undefined && openDiary(recent)}>
            최근 일기 ›
          </button>
        </nav>
      )}
      {hasPicture && (
        <dialog
          ref={photoZoom}
          className="diary-detail-zoom"
          aria-label={d.illustration_type === 'AI_DRAWING' ? '그림일기 그림 크게 보기' : '일기 사진 크게 보기'}
          onClick={() => photoZoom.current?.close()}
        >
          <img src={d.illustration_url!} alt={d.illustration_type === 'AI_DRAWING' ? '그림일기 그림' : '일기 사진'} />
          <a
            className="diary-detail-save"
            href={d.illustration_url!}
            download={`하루한장_${new Date(d.posted_at).toLocaleDateString('en-CA', { timeZone: 'Asia/Seoul' })}.jpg`}
            onClick={(e) => e.stopPropagation()}
          >
            사진 저장
          </a>
          <p>화면을 누르면 닫혀요</p>
        </dialog>
      )}
      {readError && (
        <p className="diary-detail-note" role="alert">
          읽음 표시를 남기지 못했어요. 연결을 확인하고 일기를 다시 열어 주세요.
        </p>
      )}
      {!elder && d.is_mine && (
        <>
          <button
            type="button"
            className="fam-text-btn diary-detail-delete"
            onClick={() => { setDeleteError(undefined); setDeleteOpen(true) }}
          >
            이 일기 지우기
          </button>
          <dialog
            ref={deleteSheet}
            className="fam-sheet diary-detail-delete-sheet"
            aria-labelledby="diary-delete-title"
            aria-describedby="diary-delete-description"
            aria-busy={deleting}
            onCancel={(e) => { e.preventDefault(); if (!deleteRequest.current) setDeleteOpen(false) }}
          >
            <span className="fam-grab" />
            <h2 id="diary-delete-title">지울까요?</h2>
            <p id="diary-delete-description">{room.elder_honorific} 가족 소식에서도 사라져요</p>
            {deleteError && <p className="fam-error" role="alert">{deleteError}</p>}
            <div className="diary-detail-delete-actions">
              <button
                ref={cancelDelete}
                type="button"
                className="fam-btn fam-btn--tonal"
                disabled={deleting}
                onClick={() => setDeleteOpen(false)}
              >
                취소
              </button>
              <button
                type="button"
                className="fam-btn diary-detail-delete-confirm"
                disabled={deleting}
                onClick={removeDiary}
              >
                {deleting ? '지우는 중…' : '지우기'}
              </button>
            </div>
          </dialog>
        </>
      )}
    </main>
  )
}

export default function HOME_002() {
  const { diaryId = '' } = useParams()
  // 주소의 번호가 바뀌면 이전 일기와 열람 요청을 버리고 새 화면으로 연다.
  return <DiaryDetail key={diaryId} diaryId={diaryId} />
}
