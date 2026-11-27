/**
 * MEMORY_001 — 회상 상세·댓글 (/memories/:sessionId, 11/27 가족화면 설정 개선안: 회상 💬 도 일기처럼 새 화면으로).
 * 일기 상세(HOME_002)와 같은 모양 — 사진 · AI 가 만든 가족용 한두 줄 요약(대화 원문은 없다, R18) · ♡ · 댓글 목록(내 것은
 * 고치기·지우기) · 이모지 한 줄 · 쓰기 200자. 가족 홈 💬 로 오면(state.reply) 쓰기 칸에 바로 커서.
 */
import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useLocation, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { MemoryCardOut, Reaction, RoomOut, UserOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { Avatar } from '../../components/FamilyFrame'
import Sim from '../../components/Sim'
import { useFetch } from '../../hooks/useFetch'
import './HOME_002.css'

const EMOJIS = ['❤️', '😊', '👏', '😂', '🥰', '🙏'] // 일기 상세와 같은 줄
const REPLY_MAX = 200 // 서버 config.REPLY_MAX 와 같은 값
const likeCount = (rs: Reaction[]) => rs.filter((r) => r.by === 'FAMILY' && r.kind !== 'REPLY').length
const repliesOf = (rs: Reaction[]) => rs.filter((r) => r.kind === 'REPLY' && r.text)
/** 댓글 시각 — '방금'·'5분'·'3시간'·'2일', 일주일 넘으면 '11월 3일' (일기 상세와 같은 규칙) */
function ago(iso: string) {
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000)
  if (min < 1) return '방금'
  if (min < 60) return `${min}분`
  if (min < 1440) return `${Math.floor(min / 60)}시간`
  if (min < 10080) return `${Math.floor(min / 1440)}일`
  return new Date(iso).toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric' })
}
const when = (iso: string) =>
  new Date(iso).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })

export default function MEMORY_001() {
  const { sessionId } = useParams()
  const location = useLocation()
  const card = useFetch<MemoryCardOut>(`/api/memories/${sessionId}`)
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  const me = useFetch<UserOut>('/api/auth/me')
  const [edited, setM] = useState<MemoryCardOut>() // 좋아요·댓글로 바뀐 카드 — 없으면 받은 그대로
  const m = edited ?? card.data ?? undefined
  const [draft, setDraft] = useState('')
  const [fixing, setFixing] = useState<Reaction>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const input = useRef<HTMLInputElement>(null)

  // 가족 홈 카드의 💬 로 왔으면 댓글 쓰기 칸으로 한 번
  const focused = useRef(false)
  const toReply = location.state?.reply === true
  useEffect(() => {
    if (!toReply || !m || !me.data || focused.current || !input.current) return
    focused.current = true
    input.current.scrollIntoView({ block: 'center' })
    input.current.focus({ preventScroll: true })
  }, [toReply, m, me.data])

  if (card.error?.status === 401 || rooms.error?.status === 401 || me.error?.status === 401) return <Navigate to="/login" replace />
  if (card.error?.status === 404) {
    return (
      <main className="fam-stack diary-detail">
        <section className="fam-card diary-detail-state">
          <Sim face="ask" size={96} />
          <h1>회상 카드를 찾을 수 없어요</h1>
          <Link className="fam-btn fam-btn--primary" to="/">가족 홈으로</Link>
        </section>
      </main>
    )
  }
  const failed = card.error ?? rooms.error ?? me.error
  if (failed) {
    return (
      <main className="fam-stack diary-detail">
        <section className="fam-card diary-detail-state">
          <p role="alert">{failed.message}</p>
          <button type="button" className="fam-btn fam-btn--tonal" onClick={() => { card.reload(); rooms.reload(); me.reload() }}>
            다시 시도
          </button>
        </section>
      </main>
    )
  }
  const room = rooms.data?.find((r) => r.room_id === m?.room_id)
  const user = me.data
  if (!m || !room || !user) {
    return (
      <main className="fam-stack diary-detail" aria-busy="true">
        <p className="diary-detail-note" role="status">불러오고 있어요</p>
      </main>
    )
  }
  const mine = m.reactions.some((r) => r.by === 'FAMILY' && r.kind !== 'REPLY' && r.user_id === user.user_id)
  const likes = likeCount(m.reactions)
  const replies = repliesOf(m.reactions)
  const base = `/api/memories/${m.session_id}`

  async function call(work: () => Promise<void>, fail: string) {
    setBusy(true)
    setError(undefined)
    try {
      await work()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : fail)
    } finally {
      setBusy(false)
    }
  }
  const like = () =>
    call(async () => setM(await api<MemoryCardOut>(`${base}/reaction`, { body: { kind: 'HEART', on: !mine } })), '좋아요를 보내지 못했어요. 다시 눌러 주세요.')
  function send() {
    const text = draft.trim()
    if (!text || busy) return
    void call(async () => {
      setM(fixing
        ? await api<MemoryCardOut>(`${base}/reply`, { method: 'PATCH', body: { at: fixing.at, text } })
        : await api<MemoryCardOut>(`${base}/reply`, { body: { text } }))
      setDraft('')
      setFixing(undefined)
    }, '댓글을 보내지 못했어요. 다시 해 주세요.')
  }
  const remove = (r: Reaction, card: MemoryCardOut) =>
    call(async () => {
      await api<void>(`${base}/reply?at=${encodeURIComponent(r.at)}`, { method: 'DELETE' })
      setM({ ...card, reactions: card.reactions.filter((x) => x !== r) })
      if (fixing === r) setFixing(undefined)
    }, '댓글을 지우지 못했어요. 다시 해 주세요.')
  function fix(r: Reaction) {
    setFixing(r)
    setDraft(r.text ?? '')
    input.current?.focus()
  }

  return (
    <main className="fam-stack diary-detail">
      <h1 className="diary-detail-title">회상</h1>
      <article className="diary-detail-card">
        <header className="diary-detail-head">
          <Avatar name={room.elder_name} src={room.elder_photo_url} />
          <div className="diary-detail-who">
            <b>{room.elder_name} {room.elder_honorific}</b>
            <small>
              <time dateTime={m.ended_at}>{when(m.ended_at)}</time> · 회상
            </small>
          </div>
        </header>
        {m.photo_url && (
          <div className="diary-detail-photo">
            <img src={m.photo_url} alt="이야기 나눈 사진" />
            <span className="diary-detail-tag"><FamIcon name="chat" />사진 보며 이야기</span>
          </div>
        )}
        <p className="diary-detail-text">{m.summary}</p>
        <div className="diary-detail-reactions" role="group" aria-label="좋아요" aria-busy={busy}>
          <button type="button" className="diary-detail-like" onClick={() => void like()} disabled={busy} aria-pressed={mine} aria-label={mine ? '좋아요 취소' : '좋아요'}>
            <FamIcon name="heart" />
          </button>
          {likes > 0 && <span className="diary-detail-likes">좋아요 {likes}개</span>}
        </div>
        <section className="fam-card diary-detail-reply" aria-labelledby="memory-reply-title" aria-busy={busy}>
          <h2 id="memory-reply-title">댓글{replies.length > 0 && <small> {replies.length}</small>}</h2>
          {replies.length > 0 ? (
            <ul className="diary-detail-replies">
              {replies.map((r) => {
                const my = r.by === 'FAMILY' && r.user_id === user.user_id
                return (
                  <li key={`${r.by}${r.user_id ?? ''}-${r.at}`}>
                    <Avatar name={r.name ?? '가족'} src={r.profile_url} small />
                    <span>
                      <span className="cm-text">
                        <b>{my ? '나' : (r.name ?? '가족')}</b> {r.text}
                      </span>
                      <small>
                        {ago(r.at)}
                        {my && (
                          <button type="button" className="cm-del" disabled={busy} onClick={() => fix(r)} aria-pressed={fixing === r}>고치기</button>
                        )}
                        {my && (
                          <button type="button" className="cm-del" disabled={busy} onClick={() => void remove(r, m)}>지우기</button>
                        )}
                      </small>
                    </span>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="fam-mini">첫 댓글을 남겨 보세요</p>
          )}
          <div className="cm-emojis" role="group" aria-label="이모지 넣기">
            {EMOJIS.map((e) => (
              <button type="button" key={e} onClick={() => { setDraft((t) => (t + e).slice(0, REPLY_MAX)); input.current?.focus() }}>
                {e}
              </button>
            ))}
          </div>
          <form className="cm-bar" onSubmit={(e) => { e.preventDefault(); send() }}>
            <Avatar name={user.name} src={room?.my_profile_url} small />
            <input
              ref={input}
              className="cm-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={REPLY_MAX}
              placeholder="댓글 달기…"
              aria-label={`댓글 쓰기, ${REPLY_MAX}자까지`}
              enterKeyHint="send"
              autoComplete="off"
            />
            <button type="submit" className="cm-post" disabled={busy || !draft.trim()}>{fixing ? '고치기' : '보내기'}</button>
          </form>
          {fixing && (
            <p className="cm-hint" role="status">
              댓글을 고치고 있어요{' '}
              <button type="button" className="cm-del" onClick={() => { setFixing(undefined); setDraft('') }}>취소</button>
            </p>
          )}
          {error && <p className="diary-detail-reply-note" role="alert">{error}</p>}
        </section>
      </article>
    </main>
  )
}
