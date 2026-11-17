/** HOME_002 — 일기 상세. 하위 화면 틀의 ←를 쓰고, 열람 기록은 이 화면을 열 때만 남긴다(D36). */
import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { MOOD_LABEL, type DiaryOut, type Reaction, type RoomOut, type UserOut } from '../../api/types'
import FamIcon from '../../components/FamIcon'
import { Avatar } from '../../components/FamilyFrame'
import MoodIcon from '../../components/MoodIcon'
import { useFetch } from '../../hooks/useFetch'
import './HOME_002.css'

const REACTS = [
  ['HEART', '❤️', '하트'],
  ['SMILE', '😊', '웃음'],
  ['CLAP', '👏', '박수'],
] as const

const postedAt = (iso: string) =>
  new Date(iso).toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: 'long', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
const iga = (word: string) => ((word.charCodeAt(word.length - 1) - 0xac00) % 28 ? '이' : '가')

function DiaryDetail({ diaryId }: { diaryId: string }) {
  const nav = useNavigate()
  const diary = useFetch<DiaryOut>(`/api/diaries/${encodeURIComponent(diaryId)}`)
  const rooms = useFetch<RoomOut[]>('/api/rooms')
  const me = useFetch<UserOut>('/api/auth/me')
  const readRequest = useRef<Promise<unknown> | null>(null)
  const photoZoom = useRef<HTMLDialogElement>(null)
  const [readError, setReadError] = useState(false)
  const [edit, setEdit] = useState<{ base: DiaryOut; data: DiaryOut } | null>(null)
  const [busy, setBusy] = useState(false)
  const [reactionError, setReactionError] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string>()
  const deleteRequest = useRef(false)
  const deleteSheet = useRef<HTMLDialogElement>(null)
  const cancelDelete = useRef<HTMLButtonElement>(null)
  const d = edit?.base === diary.data ? edit?.data : diary.data
  const room = rooms.data?.find((r) => r.room_id === d?.room_id)
  const mine = d?.reactions.find((r) => r.by === 'FAMILY' && r.user_id === me.data?.user_id)?.kind

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

  return (
    <main className="fam-stack diary-detail">
      <h1 className="diary-detail-title">일기 상세</h1>
      <article className="fam-card diary-detail-card">
        <header className="diary-detail-head">
          <Avatar name={elder ? room.elder_name : name} />
          <div className="diary-detail-who">
            <b>{name}</b>
            <small>
              <time dateTime={d.posted_at}>{postedAt(d.posted_at)}</time>
              {!elder && d.author_nickname ? ` · ${d.author_nickname}` : ''} · {elder ? '일기' : '오늘 한 장'}
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
        <div className="diary-detail-chips">
          <span className="diary-detail-chip"><MoodIcon mood={d.mood} />기분 · {MOOD_LABEL[d.mood]}</span>
        </div>
        {elder && (
          <div className="diary-detail-reactions" role="group" aria-label="가족 이모지" aria-busy={busy}>
            {REACTS.map(([kind, emoji, label]) => {
              const n = d.reactions.filter((r) => r.by === 'FAMILY' && r.kind === kind).length
              const on = mine === kind
              return (
                <button
                  type="button"
                  key={kind}
                  className={`diary-detail-react${on ? ' on' : ''}`}
                  onClick={() => react(kind)}
                  disabled={busy}
                  aria-pressed={on}
                  aria-label={n ? `${label} ${n}개` : label}
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
